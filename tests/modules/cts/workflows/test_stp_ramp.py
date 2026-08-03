"""
Phase C — STP Confidence Ramp.

Tests for:
  1. DecisionResult.stp_confidence field (used by SELECTIVE mode)
  2. HumanReviewInput.review_timeout_minutes (HIGH-1 fix)
  3. ChequeWorkflowResult.stp_eligible + ai_recommendation fields
  4. STP mode routing in ChequeProcessingWorkflow.run_with_mocks():
       FULL_MANUAL  — STP_CONFIRM always downgraded to HUMAN_REVIEW (stp_eligible=True)
       SUPERVISED   — STP_CONFIRM downgraded to HUMAN_REVIEW with stp_eligible+stp_mode tag
       SELECTIVE    — above stp_supervised_confirm_threshold → auto-file, else HUMAN_REVIEW
       FULL_STP     — STP_CONFIRM always auto-filed (current behaviour, now explicit)

STP mode routing rules:
  STP_RETURN from AI   → never changed by STP mode (return is a return)
  HUMAN_REVIEW from AI → never changed by STP mode (already flagged)
  STP_CONFIRM from AI  → routed based on stp_mode (see above)
"""
import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _decision_mock(decision="STP_CONFIRM", stp_confidence=0.96):
    m = MagicMock()
    m.decision = decision
    m.rationale = "all_clean" if decision == "STP_CONFIRM" else "flagged"
    m.shap_values = {"amount": -0.1}
    m.stp_confidence = stp_confidence
    return m


def _mocks(decision="STP_CONFIRM", stp_confidence=0.96):
    alt = MagicMock(); alt.alteration_detected = False
    comp = MagicMock(); comp.is_compliant = True; comp.violations = []
    sp = MagicMock(); sp.outcome = "PROCEED"; sp.stop_reason = None
    pps = MagicMock(); pps.outcome = "FOUND"
    sig = MagicMock(); sig.outcome = "MATCH"; sig.match_score = 0.97
    fraud = MagicMock(); fraud.fraud_score = 0.04; fraud.shap_values = {}
    cbs = MagicMock(); cbs.outcome = "PROCEED"; cbs.available_balance = 80000.0
    acct = MagicMock(); acct.outcome = "PROCEED"; acct.account_status = "ACTIVE"
    return {
        "alteration": alt,
        "compliance": comp,
        "stop_payment": sp,
        "pps": pps,
        "signature": sig,
        "fraud": fraud,
        "cbs": cbs,
        "account_status": acct,
        "decision": _decision_mock(decision=decision, stp_confidence=stp_confidence),
    }


def _inp(stp_mode="FULL_MANUAL", stp_supervised_confirm_threshold=0.95):
    from modules.cts.workflows.cheque_workflow import ChequeWorkflowInput
    return ChequeWorkflowInput(
        instrument_id="CHQ-STP-001",
        bank_id="test-bank",
        image_url="minio://cts/CHQ-STP-001.tiff",
        account_number="9876543210",
        cheque_number="456789",
        presented_amount=50000.0,
        presented_payee="Test Payee",
        iet_deadline=9999999999.0,
        cts_config={
            "stp_mode": stp_mode,
            "stp_supervised_confirm_threshold": stp_supervised_confirm_threshold,
            "stp_auto_confirm_threshold": 0.92,
            "human_review_fraud_threshold": 0.72,
            "ocr_min_confidence": 0.90,
            "sig_min_match_score": 0.80,
            "stp_supervised_review_timeout_minutes": 30,
        },
    )


# ---------------------------------------------------------------------------
# 1. DecisionResult.stp_confidence
# ---------------------------------------------------------------------------

class TestDecisionResultSTPConfidence:
    """stp_confidence must be present on DecisionResult for SELECTIVE mode."""

    def test_stp_confidence_field_accepted(self):
        from modules.cts.workflows.activities.decision import DecisionResult
        r = DecisionResult(
            instrument_id="CHQ001",
            decision="STP_CONFIRM",
            rationale="all_clean",
            shap_values={},
            stp_confidence=0.96,
        )
        assert r.stp_confidence == pytest.approx(0.96)

    def test_stp_confidence_defaults_to_zero(self):
        from modules.cts.workflows.activities.decision import DecisionResult
        r = DecisionResult(
            instrument_id="CHQ001",
            decision="HUMAN_REVIEW",
            rationale="fraud",
            shap_values={},
        )
        assert r.stp_confidence == pytest.approx(0.0)

    def test_stp_confidence_is_immutable(self):
        from modules.cts.workflows.activities.decision import DecisionResult
        r = DecisionResult(
            instrument_id="CHQ001",
            decision="STP_CONFIRM",
            rationale="clean",
            shap_values={},
            stp_confidence=0.95,
        )
        with pytest.raises(Exception):
            r.stp_confidence = 0.5  # frozen model


# ---------------------------------------------------------------------------
# 2. HumanReviewInput.review_timeout_minutes  (HIGH-1 fix)
# ---------------------------------------------------------------------------

class TestHumanReviewInputTimeout:
    """review_timeout_minutes must be configurable — fixing HIGH-1."""

    def test_default_timeout_is_55_minutes(self):
        from modules.cts.workflows.human_review_workflow import HumanReviewInput
        inp = HumanReviewInput(
            instrument_id="CHQ001",
            bank_id="test-bank",
            workflow_id="cts-test-bank-CHQ001",
            context_bundle={},
            iet_deadline=9999999999.0,
        )
        assert inp.review_timeout_minutes == 55

    def test_custom_timeout_accepted(self):
        from modules.cts.workflows.human_review_workflow import HumanReviewInput
        inp = HumanReviewInput(
            instrument_id="CHQ001",
            bank_id="test-bank",
            workflow_id="cts-test-bank-CHQ001",
            context_bundle={},
            iet_deadline=9999999999.0,
            review_timeout_minutes=30,
        )
        assert inp.review_timeout_minutes == 30

    def test_timeout_must_be_positive(self):
        from modules.cts.workflows.human_review_workflow import HumanReviewInput
        with pytest.raises(Exception):
            HumanReviewInput(
                instrument_id="CHQ001",
                bank_id="test-bank",
                workflow_id="w1",
                context_bundle={},
                iet_deadline=9999.0,
                review_timeout_minutes=0,
            )

    def test_timeout_immutable(self):
        from modules.cts.workflows.human_review_workflow import HumanReviewInput
        inp = HumanReviewInput(
            instrument_id="CHQ001",
            bank_id="test-bank",
            workflow_id="w1",
            context_bundle={},
            iet_deadline=9999.0,
            review_timeout_minutes=45,
        )
        with pytest.raises(Exception):
            inp.review_timeout_minutes = 10


# ---------------------------------------------------------------------------
# 3. ChequeWorkflowResult.stp_eligible + ai_recommendation
# ---------------------------------------------------------------------------

class TestChequeWorkflowResultSTPFields:
    """stp_eligible and ai_recommendation must exist on ChequeWorkflowResult."""

    def test_stp_eligible_defaults_false(self):
        from modules.cts.workflows.cheque_workflow import ChequeWorkflowResult
        r = ChequeWorkflowResult(
            instrument_id="CHQ001",
            bank_id="test-bank",
            decision="STP_CONFIRM",
            rationale="clean",
        )
        assert r.stp_eligible is False

    def test_stp_eligible_can_be_true(self):
        from modules.cts.workflows.cheque_workflow import ChequeWorkflowResult
        r = ChequeWorkflowResult(
            instrument_id="CHQ001",
            bank_id="test-bank",
            decision="HUMAN_REVIEW",
            rationale="stp_mode_full_manual",
            stp_eligible=True,
        )
        assert r.stp_eligible is True

    def test_ai_recommendation_defaults_none(self):
        from modules.cts.workflows.cheque_workflow import ChequeWorkflowResult
        r = ChequeWorkflowResult(
            instrument_id="CHQ001",
            bank_id="test-bank",
            decision="STP_CONFIRM",
            rationale="clean",
        )
        assert r.ai_recommendation is None

    def test_ai_recommendation_accepts_confirm(self):
        from modules.cts.workflows.cheque_workflow import ChequeWorkflowResult
        r = ChequeWorkflowResult(
            instrument_id="CHQ001",
            bank_id="test-bank",
            decision="HUMAN_REVIEW",
            rationale="stp_mode_full_manual",
            stp_eligible=True,
            ai_recommendation="CONFIRM",
        )
        assert r.ai_recommendation == "CONFIRM"


# ---------------------------------------------------------------------------
# 4. STP mode routing in run_with_mocks()
# ---------------------------------------------------------------------------

class TestSTPRampRouting:

    # ── FULL_STP ─────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_full_stp_ai_confirm_passes_through(self):
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        result = await wf.run_with_mocks(_inp("FULL_STP"), _mocks())
        assert result.decision == "STP_CONFIRM"
        assert result.stp_eligible is False

    @pytest.mark.asyncio
    async def test_full_stp_ai_return_unchanged(self):
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        result = await wf.run_with_mocks(_inp("FULL_STP"), _mocks(decision="STP_RETURN"))
        assert result.decision == "STP_RETURN"
        assert result.stp_eligible is False

    @pytest.mark.asyncio
    async def test_full_stp_ai_human_review_unchanged(self):
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        result = await wf.run_with_mocks(_inp("FULL_STP"), _mocks(decision="HUMAN_REVIEW"))
        assert result.decision == "HUMAN_REVIEW"
        assert result.stp_eligible is False

    # ── FULL_MANUAL ───────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_full_manual_ai_confirm_downgraded_to_human_review(self):
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        result = await wf.run_with_mocks(_inp("FULL_MANUAL"), _mocks())
        assert result.decision == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_full_manual_sets_stp_eligible(self):
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        result = await wf.run_with_mocks(_inp("FULL_MANUAL"), _mocks())
        assert result.stp_eligible is True

    @pytest.mark.asyncio
    async def test_full_manual_sets_ai_recommendation_confirm(self):
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        result = await wf.run_with_mocks(_inp("FULL_MANUAL"), _mocks())
        assert result.ai_recommendation == "CONFIRM"

    @pytest.mark.asyncio
    async def test_full_manual_stp_return_not_affected(self):
        """STP_RETURN from AI must NEVER be changed by STP mode."""
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        result = await wf.run_with_mocks(_inp("FULL_MANUAL"), _mocks(decision="STP_RETURN"))
        assert result.decision == "STP_RETURN"
        assert result.stp_eligible is False

    @pytest.mark.asyncio
    async def test_full_manual_ai_human_review_not_affected(self):
        """HUMAN_REVIEW from AI must not get spurious stp_eligible flag."""
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        result = await wf.run_with_mocks(_inp("FULL_MANUAL"), _mocks(decision="HUMAN_REVIEW"))
        assert result.decision == "HUMAN_REVIEW"
        assert result.stp_eligible is False

    # ── SUPERVISED ────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_supervised_ai_confirm_downgraded(self):
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        result = await wf.run_with_mocks(_inp("SUPERVISED"), _mocks())
        assert result.decision == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_supervised_sets_stp_eligible(self):
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        result = await wf.run_with_mocks(_inp("SUPERVISED"), _mocks())
        assert result.stp_eligible is True

    @pytest.mark.asyncio
    async def test_supervised_sets_ai_recommendation_confirm(self):
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        result = await wf.run_with_mocks(_inp("SUPERVISED"), _mocks())
        assert result.ai_recommendation == "CONFIRM"

    @pytest.mark.asyncio
    async def test_supervised_rationale_indicates_mode(self):
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        result = await wf.run_with_mocks(_inp("SUPERVISED"), _mocks())
        assert "supervised" in result.rationale.lower()

    @pytest.mark.asyncio
    async def test_supervised_stp_return_not_affected(self):
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        result = await wf.run_with_mocks(_inp("SUPERVISED"), _mocks(decision="STP_RETURN"))
        assert result.decision == "STP_RETURN"
        assert result.stp_eligible is False

    # ── SELECTIVE ─────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_selective_high_confidence_auto_files(self):
        """confidence=0.97 > threshold=0.95 → STP_CONFIRM auto-files."""
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        result = await wf.run_with_mocks(
            _inp("SELECTIVE", stp_supervised_confirm_threshold=0.95),
            _mocks(stp_confidence=0.97),
        )
        assert result.decision == "STP_CONFIRM"
        assert result.stp_eligible is False

    @pytest.mark.asyncio
    async def test_selective_exact_threshold_auto_files(self):
        """confidence=0.95 == threshold=0.95 → auto-file (boundary inclusive)."""
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        result = await wf.run_with_mocks(
            _inp("SELECTIVE", stp_supervised_confirm_threshold=0.95),
            _mocks(stp_confidence=0.95),
        )
        assert result.decision == "STP_CONFIRM"

    @pytest.mark.asyncio
    async def test_selective_below_threshold_routes_to_human(self):
        """confidence=0.93 < threshold=0.95 → HUMAN_REVIEW with stp_eligible."""
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        result = await wf.run_with_mocks(
            _inp("SELECTIVE", stp_supervised_confirm_threshold=0.95),
            _mocks(stp_confidence=0.93),
        )
        assert result.decision == "HUMAN_REVIEW"
        assert result.stp_eligible is True
        assert result.ai_recommendation == "CONFIRM"

    @pytest.mark.asyncio
    async def test_selective_stp_return_not_affected(self):
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        result = await wf.run_with_mocks(
            _inp("SELECTIVE", stp_supervised_confirm_threshold=0.95),
            _mocks(decision="STP_RETURN"),
        )
        assert result.decision == "STP_RETURN"
        assert result.stp_eligible is False

    # ── Default (missing stp_mode) ────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_missing_stp_mode_defaults_to_full_manual(self):
        """No stp_mode in cts_config → conservative default = FULL_MANUAL."""
        from modules.cts.workflows.cheque_workflow import (
            ChequeProcessingWorkflow, ChequeWorkflowInput,
        )
        inp = ChequeWorkflowInput(
            instrument_id="CHQ-DEFAULT",
            bank_id="test-bank",
            image_url="minio://cts/CHQ-DEFAULT.tiff",
            account_number="1234567890",
            cheque_number="000001",
            presented_amount=10000.0,
            presented_payee="Default Payee",
            iet_deadline=9999999999.0,
            cts_config={
                # no stp_mode key — should default to FULL_MANUAL
                "stp_auto_confirm_threshold": 0.92,
                "human_review_fraud_threshold": 0.72,
                "ocr_min_confidence": 0.90,
                "sig_min_match_score": 0.80,
            },
        )
        wf = ChequeProcessingWorkflow()
        result = await wf.run_with_mocks(inp, _mocks())
        assert result.decision == "HUMAN_REVIEW"
        assert result.stp_eligible is True

    # ── STP mode does not change HUMAN_REVIEW from AI ─────────────────────────

    @pytest.mark.asyncio
    async def test_supervised_ai_human_review_not_affected(self):
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        result = await wf.run_with_mocks(_inp("SUPERVISED"), _mocks(decision="HUMAN_REVIEW"))
        assert result.decision == "HUMAN_REVIEW"
        assert result.stp_eligible is False

    @pytest.mark.asyncio
    async def test_selective_ai_human_review_not_affected(self):
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        result = await wf.run_with_mocks(_inp("SELECTIVE"), _mocks(decision="HUMAN_REVIEW"))
        assert result.decision == "HUMAN_REVIEW"
        assert result.stp_eligible is False
