"""
Tests for KP + KC backstop in modules/cts/workflows/activities/decision.py

Dual checkpoint — the decision activity is the enforcement backstop:
  - KP active → HUMAN_REVIEW regardless of all upstream AI scores (even STP_CONFIRM quality)
  - KC active → HUMAN_REVIEW (Vision AI skipped upstream, decision honours that)
  - NONE      → normal STP logic applies

This backstop catches the mid-flight race condition:
  kill switch activated AFTER detect_alteration started (120s Qwen2-VL call).
  The alteration result arrives with kill_switch_mode="NONE" but the decision
  activity independently re-checks the kill_switch_status passed to it.
"""
import pytest


# ---------------------------------------------------------------------------
# Helpers (mirror test_decision.py pattern)
# ---------------------------------------------------------------------------

def _make_signals(**kwargs):
    from modules.cts.workflows.activities.decision import DecisionInput
    defaults = dict(
        instrument_id="INST001",
        bank_id="test-bank",
        smb_id=None,
        fraud_score=0.05,
        ocr_confidence=0.97,
        signature_match_score=0.95,
        cbs_outcome="PROCEED",
        alteration_detected=False,
        pps_outcome="FOUND",
        available_balance=100000.0,
        cheque_amount=50000.0,
        shap_values={"amount_feature": 0.1},
        kill_switch_mode="NONE",
        kill_switch_scope=None,
    )
    defaults.update(kwargs)
    return DecisionInput(**defaults)


def _make_config():
    return {
        "stp_auto_confirm_threshold": 0.92,
        "human_review_fraud_threshold": 0.72,
        "ocr_min_confidence": 0.85,
        "sig_min_match_score": 0.80,
    }


def _kill_status(mode: str, scope: str = "GLOBAL", smb_id: str | None = None):
    from modules.cts.kill_switch.vision_ai_kill_switch import KillMode, KillScope, KillSwitchStatus
    if mode == "NONE":
        return KillSwitchStatus(mode=KillMode.NONE)
    return KillSwitchStatus(mode=KillMode(mode), scope=KillScope(scope), smb_id=smb_id)


# ---------------------------------------------------------------------------
# Kill Partial (KP) backstop — STP suppressed regardless of AI scores
# ---------------------------------------------------------------------------

class TestKillPartialBackstop:
    @pytest.mark.asyncio
    async def test_kp_overrides_stp_confirm_quality_to_human_review(self):
        """Perfect scores + KP active = HUMAN_REVIEW. STP must not fire."""
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(fraud_score=0.01, ocr_confidence=0.99, signature_match_score=0.99),
            config=_make_config(),
            kill_switch_status=_kill_status("KP"),
        )
        assert result.decision == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_kp_overrides_stp_return_to_human_review(self):
        """Even a clean STP_RETURN (alteration detected) becomes HUMAN_REVIEW under KP."""
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(alteration_detected=True),
            config=_make_config(),
            kill_switch_status=_kill_status("KP"),
        )
        assert result.decision == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_kp_rationale_mentions_kill_switch(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(), config=_make_config(), kill_switch_status=_kill_status("KP")
        )
        assert "KP" in result.rationale or "kill_switch" in result.rationale.lower()

    @pytest.mark.asyncio
    async def test_kp_result_carries_kill_switch_mode(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(), config=_make_config(), kill_switch_status=_kill_status("KP")
        )
        assert result.kill_switch_mode == "KP"

    @pytest.mark.asyncio
    async def test_kp_result_carries_scope(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(), config=_make_config(),
            kill_switch_status=_kill_status("KP", scope="SB_OWN"),
        )
        assert result.kill_switch_scope == "SB_OWN"


# ---------------------------------------------------------------------------
# Kill Complete (KC) backstop — dual checkpoint catches mid-flight case
# ---------------------------------------------------------------------------

class TestKillCompleteBackstop:
    @pytest.mark.asyncio
    async def test_kc_forces_human_review(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(), config=_make_config(), kill_switch_status=_kill_status("KC")
        )
        assert result.decision == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_kc_backstop_catches_mid_flight_alteration(self):
        """
        Mid-flight scenario: alteration ran before KC was activated.
        DecisionInput.kill_switch_mode="NONE" (from alteration result),
        but kill_switch_status="KC" (freshly resolved at decision time).
        Decision must return HUMAN_REVIEW.
        """
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(kill_switch_mode="NONE"),  # alteration didn't know about KC
            config=_make_config(),
            kill_switch_status=_kill_status("KC"),   # decision re-checks and finds KC
        )
        assert result.decision == "HUMAN_REVIEW"
        assert result.kill_switch_mode == "KC"

    @pytest.mark.asyncio
    async def test_kc_rationale_mentions_kill_switch(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(), config=_make_config(), kill_switch_status=_kill_status("KC")
        )
        assert "KC" in result.rationale or "kill_switch" in result.rationale.lower()


# ---------------------------------------------------------------------------
# NONE mode — normal STP logic unchanged
# ---------------------------------------------------------------------------

class TestNoneModePreservesNormalLogic:
    @pytest.mark.asyncio
    async def test_none_mode_allows_stp_confirm(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(fraud_score=0.01, ocr_confidence=0.99, signature_match_score=0.99),
            config=_make_config(),
            kill_switch_status=_kill_status("NONE"),
        )
        assert result.decision == "STP_CONFIRM"

    @pytest.mark.asyncio
    async def test_none_mode_allows_stp_return(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(alteration_detected=True),
            config=_make_config(),
            kill_switch_status=_kill_status("NONE"),
        )
        assert result.decision == "STP_RETURN"

    @pytest.mark.asyncio
    async def test_no_kill_switch_status_passed_normal_stp_confirm(self):
        """No kill_switch_status argument = NONE mode = normal logic."""
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(fraud_score=0.01, ocr_confidence=0.99, signature_match_score=0.99),
            config=_make_config(),
        )
        assert result.decision == "STP_CONFIRM"

    @pytest.mark.asyncio
    async def test_none_mode_kill_switch_mode_not_set_on_result(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(), config=_make_config(), kill_switch_status=_kill_status("NONE")
        )
        assert result.kill_switch_mode == "NONE"


# ---------------------------------------------------------------------------
# DecisionInput accepts new kill_switch fields
# ---------------------------------------------------------------------------

class TestDecisionInputSchema:
    def test_decision_input_accepts_kill_switch_mode(self):
        from modules.cts.workflows.activities.decision import DecisionInput
        inp = DecisionInput(
            instrument_id="X", bank_id="b", smb_id="ucb-001",
            fraud_score=0.1, ocr_confidence=0.9, signature_match_score=0.9,
            cbs_outcome="PROCEED", alteration_detected=False, pps_outcome="FOUND",
            available_balance=100.0, cheque_amount=50.0,
            shap_values={"f": 0.1},
            kill_switch_mode="KP",
            kill_switch_scope="SMB",
        )
        assert inp.kill_switch_mode == "KP"
        assert inp.kill_switch_scope == "SMB"
        assert inp.smb_id == "ucb-001"

    def test_decision_result_carries_kill_switch_fields(self):
        from modules.cts.workflows.activities.decision import DecisionResult
        r = DecisionResult(
            instrument_id="X", decision="HUMAN_REVIEW", rationale="KP",
            shap_values={}, kill_switch_mode="KP", kill_switch_scope="GLOBAL",
        )
        assert r.kill_switch_mode == "KP"
        assert r.kill_switch_scope == "GLOBAL"


# ---------------------------------------------------------------------------
# Immudb write on decision backstop — per-instrument CTS_KILL_SWITCH_APPLIED
# ---------------------------------------------------------------------------

class TestDecisionBackstopImmudb:
    @pytest.mark.asyncio
    async def test_kp_backstop_writes_to_immudb(self):
        """KP backstop must write CTS_KILL_SWITCH_APPLIED to Immudb."""
        from modules.cts.workflows.activities.decision import synthesise_decision
        from unittest.mock import AsyncMock, MagicMock
        immudb = MagicMock()
        immudb.write_event = AsyncMock(return_value={"tx_id": "tx-kp-001"})
        hsm = MagicMock()
        hsm.sign = MagicMock(side_effect=lambda d: b"sig")

        await synthesise_decision(
            _make_signals(),
            config=_make_config(),
            kill_switch_status=_kill_status("KP"),
            immudb_client=immudb,
            hsm=hsm,
        )
        immudb.write_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_kc_backstop_writes_to_immudb(self):
        """KC backstop must write CTS_KILL_SWITCH_APPLIED to Immudb."""
        from modules.cts.workflows.activities.decision import synthesise_decision
        from unittest.mock import AsyncMock, MagicMock
        immudb = MagicMock()
        immudb.write_event = AsyncMock(return_value={"tx_id": "tx-kc-001"})
        hsm = MagicMock()
        hsm.sign = MagicMock(side_effect=lambda d: b"sig")

        await synthesise_decision(
            _make_signals(),
            config=_make_config(),
            kill_switch_status=_kill_status("KC"),
            immudb_client=immudb,
            hsm=hsm,
        )
        immudb.write_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_backstop_immudb_event_type_is_applied(self):
        import json
        from modules.cts.workflows.activities.decision import synthesise_decision
        from shared.audit.audit_event import AuditEventType
        from unittest.mock import AsyncMock, MagicMock
        immudb = MagicMock()
        written_bytes = []
        async def _capture(data):
            written_bytes.append(data)
            return {}
        immudb.write_event = _capture
        hsm = MagicMock()
        hsm.sign = MagicMock(side_effect=lambda d: b"sig")

        await synthesise_decision(
            _make_signals(),
            config=_make_config(),
            kill_switch_status=_kill_status("KP"),
            immudb_client=immudb,
            hsm=hsm,
        )
        assert len(written_bytes) == 1
        data = json.loads(written_bytes[0])
        assert data["event_type"] == AuditEventType.CTS_KILL_SWITCH_APPLIED.value

    @pytest.mark.asyncio
    async def test_backstop_immudb_payload_contains_instrument_id(self):
        import json
        from modules.cts.workflows.activities.decision import synthesise_decision
        from unittest.mock import AsyncMock, MagicMock
        immudb = MagicMock()
        written_bytes = []
        async def _capture(data):
            written_bytes.append(data)
            return {}
        immudb.write_event = _capture
        hsm = MagicMock()
        hsm.sign = MagicMock(side_effect=lambda d: b"sig")

        await synthesise_decision(
            _make_signals(instrument_id="INST-XYZ"),
            config=_make_config(),
            kill_switch_status=_kill_status("KP"),
            immudb_client=immudb,
            hsm=hsm,
        )
        data = json.loads(written_bytes[0])
        assert data["payload"]["instrument_id"] == "INST-XYZ"

    @pytest.mark.asyncio
    async def test_backstop_immudb_payload_contains_mode(self):
        import json
        from modules.cts.workflows.activities.decision import synthesise_decision
        from unittest.mock import AsyncMock, MagicMock
        immudb = MagicMock()
        written_bytes = []
        async def _capture(data):
            written_bytes.append(data)
            return {}
        immudb.write_event = _capture
        hsm = MagicMock()
        hsm.sign = MagicMock(side_effect=lambda d: b"sig")

        await synthesise_decision(
            _make_signals(),
            config=_make_config(),
            kill_switch_status=_kill_status("KP", scope="SB_OWN"),
            immudb_client=immudb,
            hsm=hsm,
        )
        data = json.loads(written_bytes[0])
        assert data["payload"]["kill_switch_mode"] == "KP"
        assert data["payload"]["kill_switch_scope"] == "SB_OWN"

    @pytest.mark.asyncio
    async def test_backstop_without_immudb_does_not_raise(self):
        """Backward compatibility: no immudb_client = no write, no crash."""
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(),
            config=_make_config(),
            kill_switch_status=_kill_status("KP"),
            immudb_client=None,
            hsm=None,
        )
        assert result.decision == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_none_mode_does_not_write_immudb(self):
        """NONE mode = no kill switch active = no Immudb write in decision."""
        from modules.cts.workflows.activities.decision import synthesise_decision
        from unittest.mock import AsyncMock, MagicMock
        immudb = MagicMock()
        immudb.write_event = AsyncMock()
        hsm = MagicMock()
        hsm.sign = MagicMock(side_effect=lambda d: b"sig")

        await synthesise_decision(
            _make_signals(fraud_score=0.01, ocr_confidence=0.99, signature_match_score=0.99),
            config=_make_config(),
            kill_switch_status=_kill_status("NONE"),
            immudb_client=immudb,
            hsm=hsm,
        )
        immudb.write_event.assert_not_called()
