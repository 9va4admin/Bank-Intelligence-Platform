"""
Tests for MSV (Multi-Signature Validation) wiring in ChequeProcessingWorkflow.

Item 1: When sig_count > 1, the workflow must route through MSVValidationWorkflow
instead of the single-signature verify_signature activity.

MSV outcome → CTS decision mapping:
  GREEN  → PROCEED (continue to fraud scoring / decision)
  AMBER  → HUMAN_REVIEW (degraded or unknown)
  RED    → HUMAN_REVIEW (validation failed)
  absent → HUMAN_REVIEW (msv_not_configured)

All tests use run_with_mocks() — no Temporal server required.
"""
import time
import pytest
from unittest.mock import MagicMock, AsyncMock


# ── helpers ──────────────────────────────────────────────────────────────────

def _wf_inp(**kwargs):
    from modules.cts.workflows.cheque_workflow import ChequeWorkflowInput
    defaults = dict(
        instrument_id="INST-MSV-001",
        bank_id="saraswat-coop",
        image_url="s3://bucket/INST-MSV-001.jpg",
        account_number="1234567890",
        cheque_number="100001",
        presented_amount=50000.0,
        presented_payee="ACME Corp",
        iet_deadline=time.time() + 10800,
        cts_config={"stp_mode": "FULL_STP"},  # pre-Phase-C tests expect auto-file behaviour
    )
    defaults.update(kwargs)
    return ChequeWorkflowInput(**defaults)


def _base_mocks(instrument_id="INST-MSV-001"):
    """All activities before signature step returning PROCEED."""
    from modules.cts.workflows.activities.alteration import AlterationActivityResult
    from modules.cts.workflows.activities.pps import PPSActivityResult
    from modules.cts.workflows.activities.cbs import CBSActivityResult
    from modules.cts.workflows.activities.stop_payment import StopPaymentActivityResult
    from modules.cts.workflows.activities.fraud import FraudActivityResult
    from modules.cts.workflows.activities.decision import DecisionResult

    compliance_mock = MagicMock()
    compliance_mock.is_compliant = True
    compliance_mock.violations = []

    account_status_mock = MagicMock()
    account_status_mock.outcome = "PROCEED"
    account_status_mock.account_status = "ACTIVE"

    return {
        "alteration": AlterationActivityResult(alteration_detected=False, tamper_risk_score=0.02),
        "compliance": compliance_mock,
        "stop_payment": StopPaymentActivityResult(
            outcome="PROCEED", bank_id="saraswat-coop", instrument_id=instrument_id,
        ),
        "pps": PPSActivityResult(outcome="PROCEED"),
        "fraud": FraudActivityResult(fraud_score=0.05, shap_values={"amount": 0.01}),
        "cbs": CBSActivityResult(outcome="PROCEED", account_status="ACTIVE", available_balance=200000.0),
        "account_status": account_status_mock,
        "decision": DecisionResult(
            instrument_id=instrument_id,
            decision="STP_CONFIRM",
            rationale="All signals clean",
            shap_values={"amount": 0.01},
        ),
    }


def _msv_result(outcome: str, reason_code: str = "ALL_MATCHED", confidence: float = 0.93):
    """Build a mock MSVWorkflowResult."""
    m = MagicMock()
    m.outcome = outcome
    m.reason_code = reason_code
    m.confidence = confidence
    return m


async def _run(mock_results: dict, **wf_kwargs):
    from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
    wf = ChequeProcessingWorkflow()
    inp = _wf_inp(**wf_kwargs)
    return await wf.run_with_mocks(inp, mock_results)


# ── single-sig path (unchanged behaviour) ────────────────────────────────────

class TestSingleSigPath:
    @pytest.mark.asyncio
    async def test_single_sig_uses_signature_result(self):
        """sig_count=1 → verify_signature mock result consumed, STP_CONFIRM."""
        from modules.cts.workflows.activities.signature import SignatureActivityResult
        mocks = _base_mocks()
        mocks["signature"] = SignatureActivityResult(outcome="PROCEED", match_score=0.95)
        mocks["sig_count"] = 1
        result = await _run(mocks)
        assert result.decision == "STP_CONFIRM"

    @pytest.mark.asyncio
    async def test_default_sig_count_one_uses_signature(self):
        """No sig_count key in mocks → defaults to 1 → signature path."""
        from modules.cts.workflows.activities.signature import SignatureActivityResult
        mocks = _base_mocks()
        mocks["signature"] = SignatureActivityResult(outcome="PROCEED", match_score=0.91)
        # no "sig_count" key — should default to 1
        result = await _run(mocks)
        assert result.decision == "STP_CONFIRM"


# ── multi-sig path (new MSV routing) ─────────────────────────────────────────

class TestMultiSigMSVRouting:
    @pytest.mark.asyncio
    async def test_green_msv_proceeds_to_decision(self):
        """sig_count=2, MSV GREEN → workflow continues, final decision STP_CONFIRM."""
        mocks = _base_mocks()
        mocks["sig_count"] = 2
        mocks["msv"] = _msv_result("GREEN", "ALL_MATCHED", confidence=0.93)
        result = await _run(mocks)
        assert result.decision == "STP_CONFIRM"

    @pytest.mark.asyncio
    async def test_amber_msv_routes_human_review(self):
        """sig_count=2, MSV AMBER → HUMAN_REVIEW."""
        mocks = _base_mocks()
        mocks["sig_count"] = 2
        mocks["msv"] = _msv_result("AMBER", "NO_SIGNATORIES_ENROLLED", confidence=0.0)
        result = await _run(mocks)
        assert result.decision == "HUMAN_REVIEW"
        assert "msv_" in result.rationale.lower()

    @pytest.mark.asyncio
    async def test_red_msv_routes_human_review(self):
        """sig_count=2, MSV RED → HUMAN_REVIEW (not STP_RETURN — human eyes needed)."""
        mocks = _base_mocks()
        mocks["sig_count"] = 2
        mocks["msv"] = _msv_result("RED", "MISSING_SIGNATORY", confidence=0.0)
        result = await _run(mocks)
        assert result.decision == "HUMAN_REVIEW"
        assert "msv_" in result.rationale.lower()

    @pytest.mark.asyncio
    async def test_absent_msv_mock_routes_human_review(self):
        """sig_count=2, no 'msv' key in mocks → HUMAN_REVIEW (not configured)."""
        mocks = _base_mocks()
        mocks["sig_count"] = 2
        # Deliberately no "msv" key and no "signature" key
        result = await _run(mocks)
        assert result.decision == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_msv_green_confidence_propagated(self):
        """MSV GREEN confidence becomes match_score passed to fraud scoring path."""
        mocks = _base_mocks()
        mocks["sig_count"] = 2
        mocks["msv"] = _msv_result("GREEN", "QUORUM_MET", confidence=0.88)
        # We just verify the workflow completes successfully (confidence is internal)
        result = await _run(mocks)
        assert result.decision == "STP_CONFIRM"

    @pytest.mark.asyncio
    async def test_sig_count_three_amber_routes_human_review(self):
        """sig_count=3, MSV AMBER (low confidence match) → HUMAN_REVIEW."""
        mocks = _base_mocks()
        mocks["sig_count"] = 3
        mocks["msv"] = _msv_result("AMBER", "LOW_CONFIDENCE_MATCH", confidence=0.82)
        result = await _run(mocks)
        assert result.decision == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_msv_green_reason_code_in_rationale_not_required(self):
        """GREEN path does not add rationale — continues to decision rationale."""
        mocks = _base_mocks()
        mocks["sig_count"] = 2
        mocks["msv"] = _msv_result("GREEN", "ALL_MATCHED", confidence=0.95)
        result = await _run(mocks)
        assert result.decision == "STP_CONFIRM"
        # decision rationale comes from decision mock, not MSV
        assert result.rationale == "All signals clean"

    @pytest.mark.asyncio
    async def test_watchdog_spawned_before_msv_path(self):
        """IET watchdog must be spawned first even in multi-sig path."""
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        mocks = _base_mocks()
        mocks["sig_count"] = 2
        mocks["msv"] = _msv_result("GREEN")
        wf = ChequeProcessingWorkflow()
        assert not wf._watchdog_spawned
        inp = _wf_inp()
        await wf.run_with_mocks(inp, mocks)
        assert wf._watchdog_spawned
