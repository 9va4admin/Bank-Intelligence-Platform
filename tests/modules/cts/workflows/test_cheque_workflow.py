"""
Tests for modules/cts/workflows/cheque_workflow.py

ChequeProcessingWorkflow orchestrates all CTS activities.
IETWatchdogWorkflow must be the first thing spawned — before any activity.
Workflow ID: cts-{bank_id}-{instrument_id} (deterministic, idempotency).

These tests use pure Python (no Temporal SDK) — activities are mocked.
"""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_workflow_input(instrument_id="INST001", bank_id="test-bank"):
    from modules.cts.workflows.cheque_workflow import ChequeWorkflowInput
    import time
    return ChequeWorkflowInput(
        instrument_id=instrument_id,
        bank_id=bank_id,
        image_url="s3://bucket/INST001.jpg",
        account_number="1234567890",
        cheque_number="100001",
        presented_amount=50000.0,
        presented_payee="ACME Corp",
        iet_deadline=time.time() + 10800,  # 3 hours from now
    )


def _make_all_proceed_results():
    """All activities return proceed — happy path."""
    from modules.cts.workflows.activities.ocr import OCRActivityResult
    from modules.cts.workflows.activities.alteration import AlterationActivityResult
    from modules.cts.workflows.activities.signature import SignatureActivityResult
    from modules.cts.workflows.activities.pps import PPSActivityResult
    from modules.cts.workflows.activities.cbs import CBSActivityResult
    from modules.cts.workflows.activities.fraud import FraudActivityResult
    from modules.cts.workflows.activities.decision import DecisionResult

    return {
        "ocr": OCRActivityResult(
            outcome="PROCEED", micr_line="123456789012345",
            amount_figures="50000.00", overall_confidence=0.97,
        ),
        "alteration": AlterationActivityResult(alteration_detected=False, tamper_risk_score=0.02),
        "signature": SignatureActivityResult(outcome="PROCEED", match_score=0.95),
        "pps": PPSActivityResult(outcome="PROCEED"),
        "cbs": CBSActivityResult(outcome="PROCEED", account_status="ACTIVE", available_balance=200000.0),
        "fraud": FraudActivityResult(fraud_score=0.05, shap_values={"amount": 0.01}),
        "decision": DecisionResult(
            instrument_id="INST001",
            decision="STP_CONFIRM",
            rationale="All signals clean",
            shap_values={"amount": 0.01},
        ),
    }


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------

class TestChequeWorkflowInput:
    def test_requires_instrument_id(self):
        from modules.cts.workflows.cheque_workflow import ChequeWorkflowInput
        with pytest.raises(Exception):
            ChequeWorkflowInput(
                bank_id="b", image_url="s3://x", account_number="123",
                cheque_number="1", presented_amount=100.0,
                presented_payee="X", iet_deadline=9999999999.0,
            )

    def test_is_frozen(self):
        inp = _make_workflow_input()
        with pytest.raises(Exception):
            inp.instrument_id = "OTHER"

    def test_workflow_id_is_deterministic(self):
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        wf_id = wf.workflow_id("test-bank", "INST001")
        assert wf_id == "cts-test-bank-INST001"

    def test_workflow_id_never_contains_uuid(self):
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        wf_id = wf.workflow_id("test-bank", "INST001")
        # Must be derived from inputs, not a random UUID
        assert "INST001" in wf_id
        assert "test-bank" in wf_id


# ---------------------------------------------------------------------------
# IET Watchdog — must be spawned first
# ---------------------------------------------------------------------------

class TestIETWatchdogFirst:
    @pytest.mark.asyncio
    async def test_iet_watchdog_id_is_deterministic(self):
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        watchdog_id = wf.iet_watchdog_id("test-bank", "INST001")
        assert watchdog_id == "cts-iet-test-bank-INST001"

    def test_workflow_records_watchdog_spawn_order(self):
        """Workflow must track that watchdog was spawned before activities."""
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        # watchdog_spawned starts False
        assert wf._watchdog_spawned is False


# ---------------------------------------------------------------------------
# Workflow orchestration (mocked activities)
# ---------------------------------------------------------------------------

class TestChequeWorkflowOrchestration:
    @pytest.mark.asyncio
    async def test_stp_confirm_path(self):
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow

        results = _make_all_proceed_results()
        wf = ChequeProcessingWorkflow()

        result = await wf.run_with_mocks(
            _make_workflow_input(),
            mock_results=results,
        )
        assert result.decision == "STP_CONFIRM"

    @pytest.mark.asyncio
    async def test_stp_return_on_frozen_account(self):
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        from modules.cts.workflows.activities.cbs import CBSActivityResult
        from modules.cts.workflows.activities.decision import DecisionResult

        results = _make_all_proceed_results()
        results["cbs"] = CBSActivityResult(outcome="RETURN", account_status="FROZEN")
        results["decision"] = DecisionResult(
            instrument_id="INST001", decision="STP_RETURN",
            rationale="CBS frozen", shap_values={},
        )

        wf = ChequeProcessingWorkflow()
        result = await wf.run_with_mocks(_make_workflow_input(), mock_results=results)
        assert result.decision == "STP_RETURN"

    @pytest.mark.asyncio
    async def test_human_review_on_high_fraud_score(self):
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        from modules.cts.workflows.activities.fraud import FraudActivityResult
        from modules.cts.workflows.activities.decision import DecisionResult

        results = _make_all_proceed_results()
        results["fraud"] = FraudActivityResult(fraud_score=0.88, shap_values={"amount": 0.5})
        results["decision"] = DecisionResult(
            instrument_id="INST001", decision="HUMAN_REVIEW",
            rationale="high fraud score", shap_values={"amount": 0.5},
        )

        wf = ChequeProcessingWorkflow()
        result = await wf.run_with_mocks(_make_workflow_input(), mock_results=results)
        assert result.decision == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_result_contains_instrument_id(self):
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow

        wf = ChequeProcessingWorkflow()
        result = await wf.run_with_mocks(
            _make_workflow_input(instrument_id="INST999"),
            mock_results=_make_all_proceed_results(),
        )
        assert result.instrument_id == "INST999"

    @pytest.mark.asyncio
    async def test_result_contains_shap_values(self):
        """SHAP must be in final workflow result — required for NGCH audit."""
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow

        wf = ChequeProcessingWorkflow()
        result = await wf.run_with_mocks(
            _make_workflow_input(),
            mock_results=_make_all_proceed_results(),
        )
        assert result.shap_values is not None

    @pytest.mark.asyncio
    async def test_watchdog_spawned_before_first_activity(self):
        """IET watchdog spawn must happen before any activity call."""
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow

        wf = ChequeProcessingWorkflow()
        call_order = []

        async def track_watchdog(*a, **kw):
            call_order.append("watchdog")

        async def track_ocr(*a, **kw):
            call_order.append("ocr")
            return _make_all_proceed_results()["ocr"]

        await wf.run_with_mocks(
            _make_workflow_input(),
            mock_results=_make_all_proceed_results(),
            on_watchdog_spawn=track_watchdog,
            on_ocr_call=track_ocr,
        )

        watchdog_idx = call_order.index("watchdog") if "watchdog" in call_order else -1
        ocr_idx = call_order.index("ocr") if "ocr" in call_order else 999
        assert watchdog_idx < ocr_idx


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

class TestChequeWorkflowResult:
    @pytest.mark.asyncio
    async def test_result_has_decision(self):
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow

        wf = ChequeProcessingWorkflow()
        result = await wf.run_with_mocks(_make_workflow_input(), mock_results=_make_all_proceed_results())
        assert result.decision in {"STP_CONFIRM", "STP_RETURN", "HUMAN_REVIEW"}

    @pytest.mark.asyncio
    async def test_result_has_bank_id(self):
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow

        wf = ChequeProcessingWorkflow()
        result = await wf.run_with_mocks(
            _make_workflow_input(bank_id="kotak"),
            mock_results=_make_all_proceed_results(),
        )
        assert result.bank_id == "kotak"

    @pytest.mark.asyncio
    async def test_result_is_frozen(self):
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow

        wf = ChequeProcessingWorkflow()
        result = await wf.run_with_mocks(_make_workflow_input(), mock_results=_make_all_proceed_results())
        with pytest.raises(Exception):
            result.decision = "SOMETHING"


class TestChequeWorkflowSubMember:
    @pytest.mark.asyncio
    async def test_sub_member_stp_return_triggers_notification(self):
        """Covers lines 110-129: sub_member_id set + STP_RETURN → notify_sub_member_return called."""
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        from modules.cts.workflows.activities.decision import DecisionResult

        results = _make_all_proceed_results()
        results["decision"] = DecisionResult(
            instrument_id="INST001",
            decision="STP_RETURN",
            rationale="Signature mismatch",
            shap_values={"amount": 0.01},
        )
        results["sub_member_id"] = "vasavi-coop"
        results["amount_range"] = "₹[1L-5L]"
        results["session_date"] = "2026-06-24"
        results["clearing_session"] = "MORNING"

        wf = ChequeProcessingWorkflow()
        result = await wf.run_with_mocks(_make_workflow_input(), mock_results=results)
        assert result.sub_member_notified is True
        assert result.ledger_updated is True

    @pytest.mark.asyncio
    async def test_sub_member_stp_confirm_updates_ledger_not_notified(self):
        """Covers lines 131-139: sub_member_id + STP_CONFIRM → ledger updated, no notification."""
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow

        results = _make_all_proceed_results()
        results["sub_member_id"] = "vasavi-coop"
        results["session_date"] = "2026-06-24"
        results["clearing_session"] = "MORNING"

        wf = ChequeProcessingWorkflow()
        result = await wf.run_with_mocks(_make_workflow_input(), mock_results=results)
        assert result.sub_member_notified is False
        assert result.ledger_updated is True

    @pytest.mark.asyncio
    async def test_run_shield_check_returns_dict(self):
        """Covers line 170: run_shield_check calls check_return_rate_shield."""
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow

        wf = ChequeProcessingWorkflow()
        result = await wf.run_shield_check(
            bank_id="test-bank",
            sub_member_id="vasavi-coop",
            session_date="2026-06-24",
            clearing_session="MORNING",
        )
        assert isinstance(result, dict)
        assert "shield_status" in result
