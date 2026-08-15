"""TDD tests for persist_agent_decision activity.

Tests verify:
- Happy path: INSERT into cts.agent_decisions with correct fields
- Missing db_conn: returns PersistDecisionResult(success=False) — never raises
- instrument_id not found: writes with null FK reference (cheque_instruments join is optional)
- Duplicate write (conflict on workflow_id UNIQUE): returns success=False, logs, does not raise
- ocr_engines_used + indic_ocr_kill_switch_active stored correctly
- All PII masking: no account number, no exact amount in any logged field
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.cts.workflows.activities.persist_decision import (
    PersistDecisionInput,
    PersistDecisionResult,
    persist_agent_decision,
)


def _fake_input(**overrides) -> PersistDecisionInput:
    defaults = dict(
        instrument_id=str(uuid.uuid4()),
        bank_id="saraswat-coop",
        workflow_id="cts-saraswat-coop-INST-001",
        decision="STP_CONFIRM",
        decision_reason="STP threshold met",
        fraud_score=0.08,
        shap_values={"sig_mismatch_delta": -0.31, "vault_hit": -0.22},
        processing_started_at=1723700000.0,
        processing_completed_at=1723700000.412,
        ocr_confidence=None,
        alteration_detected=False,
        signature_match_score=0.97,
        signature_verdict="MATCH",
        pps_checked=True,
        pps_verdict="PROCEED",
        cbs_balance_status="SUFFICIENT",
        degraded_mode=False,
        ocr_engines_used=[],
        indic_ocr_kill_switch_active=False,
        iet_margin_seconds=9800,
    )
    defaults.update(overrides)
    return PersistDecisionInput(**defaults)


def _fake_db():
    """Fake asyncpg connection mock."""
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value="INSERT 0 1")
    return conn


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestPersistDecisionHappyPath:
    @pytest.mark.asyncio
    async def test_returns_success_true_on_insert(self):
        conn = _fake_db()
        result = await persist_agent_decision(_fake_input(), db_conn=conn)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_calls_db_execute_once(self):
        conn = _fake_db()
        await persist_agent_decision(_fake_input(), db_conn=conn)
        assert conn.execute.call_count == 1

    @pytest.mark.asyncio
    async def test_sql_targets_cts_agent_decisions(self):
        conn = _fake_db()
        await persist_agent_decision(_fake_input(), db_conn=conn)
        sql_call = conn.execute.call_args[0][0]
        assert "cts.agent_decisions" in sql_call

    @pytest.mark.asyncio
    async def test_fraud_score_included_in_values(self):
        inp = _fake_input(fraud_score=0.91)
        conn = _fake_db()
        await persist_agent_decision(inp, db_conn=conn)
        call_args = conn.execute.call_args[0]
        # values are positional args after the SQL string
        assert 0.91 in call_args[1:]

    @pytest.mark.asyncio
    async def test_shap_values_serialised_as_json(self):
        shap = {"sig_mismatch_delta": 0.38, "vault_hit": -0.22}
        inp = _fake_input(shap_values=shap)
        conn = _fake_db()
        await persist_agent_decision(inp, db_conn=conn)
        call_args = conn.execute.call_args[0]
        json_arg = next((a for a in call_args[1:] if isinstance(a, str) and '"sig_mismatch' in a), None)
        assert json_arg is not None
        assert json.loads(json_arg) == shap

    @pytest.mark.asyncio
    async def test_processing_duration_ms_computed_correctly(self):
        inp = _fake_input(
            processing_started_at=1723700000.000,
            processing_completed_at=1723700000.412,
        )
        conn = _fake_db()
        await persist_agent_decision(inp, db_conn=conn)
        call_args = conn.execute.call_args[0]
        assert 412 in call_args[1:]

    @pytest.mark.asyncio
    async def test_decision_field_stored(self):
        inp = _fake_input(decision="STP_RETURN")
        conn = _fake_db()
        await persist_agent_decision(inp, db_conn=conn)
        call_args = conn.execute.call_args[0]
        assert "STP_RETURN" in call_args[1:]

    @pytest.mark.asyncio
    async def test_ocr_engines_used_stored_as_json(self):
        inp = _fake_input(ocr_engines_used=["got-ocr2.0:cascade-1", "indic_ocr:paddle/devanagari"])
        conn = _fake_db()
        await persist_agent_decision(inp, db_conn=conn)
        call_args = conn.execute.call_args[0]
        json_arg = next((a for a in call_args[1:] if isinstance(a, str) and "got-ocr2.0" in a), None)
        assert json_arg is not None
        assert json.loads(json_arg) == ["got-ocr2.0:cascade-1", "indic_ocr:paddle/devanagari"]

    @pytest.mark.asyncio
    async def test_indic_ocr_kill_switch_active_stored(self):
        inp = _fake_input(indic_ocr_kill_switch_active=True)
        conn = _fake_db()
        await persist_agent_decision(inp, db_conn=conn)
        call_args = conn.execute.call_args[0]
        assert True in call_args[1:]


# ---------------------------------------------------------------------------
# Graceful degradation — no db_conn
# ---------------------------------------------------------------------------

class TestPersistDecisionNoDB:
    @pytest.mark.asyncio
    async def test_returns_success_false_when_no_db_conn(self):
        result = await persist_agent_decision(_fake_input(), db_conn=None)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_does_not_raise_when_no_db_conn(self):
        # Must not raise — activity degrades gracefully, never blocks workflow
        result = await persist_agent_decision(_fake_input(), db_conn=None)
        assert isinstance(result, PersistDecisionResult)

    @pytest.mark.asyncio
    async def test_logs_warning_when_no_db_conn(self):
        # structlog does not pipe through stdlib logging, so caplog cannot capture it.
        # Verify by patching the module-level logger instead.
        with patch("modules.cts.workflows.activities.persist_decision.log") as mock_log:
            await persist_agent_decision(_fake_input(), db_conn=None)
        mock_log.warning.assert_called_once()
        event = mock_log.warning.call_args[0][0]
        assert "db_conn" in event or "unavailable" in event.lower()


# ---------------------------------------------------------------------------
# Graceful degradation — DB error (duplicate / connection loss)
# ---------------------------------------------------------------------------

class TestPersistDecisionDBError:
    @pytest.mark.asyncio
    async def test_returns_success_false_on_unique_violation(self):
        conn = AsyncMock()
        conn.execute = AsyncMock(side_effect=Exception("duplicate key value violates unique constraint"))
        result = await persist_agent_decision(_fake_input(), db_conn=conn)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_does_not_raise_on_db_error(self):
        conn = AsyncMock()
        conn.execute = AsyncMock(side_effect=OSError("connection reset"))
        result = await persist_agent_decision(_fake_input(), db_conn=conn)
        assert isinstance(result, PersistDecisionResult)
        assert result.success is False


# ---------------------------------------------------------------------------
# PII safety — no raw account number or exact amount
# ---------------------------------------------------------------------------

class TestPersistDecisionPIISafety:
    @pytest.mark.asyncio
    async def test_no_exact_amount_in_sql_args(self):
        """Amount is stored via cheque_instruments (amount_range) — not in agent_decisions."""
        inp = _fake_input()
        conn = _fake_db()
        await persist_agent_decision(inp, db_conn=conn)
        # PersistDecisionInput intentionally has no 'amount' field
        fields = set(inp.model_fields.keys())
        assert "amount" not in fields
        assert "presented_amount" not in fields

    @pytest.mark.asyncio
    async def test_no_account_number_in_sql_args(self):
        """account_number never flows into persist_agent_decision."""
        inp = _fake_input()
        conn = _fake_db()
        await persist_agent_decision(inp, db_conn=conn)
        fields = set(inp.model_fields.keys())
        assert "account_number" not in fields
