"""
Tests for modules/cts/workflows/activities/decision.py

synthesise_decision takes signals from all upstream activities and produces
a terminal CTS decision: STP_CONFIRM, STP_RETURN, or HUMAN_REVIEW.

All thresholds come from config_service — never hardcoded.
SHAP values must be present in output (required before NGCH filing).
"""
import pytest
from unittest.mock import AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_signals(
    fraud_score=0.05,
    ocr_confidence=0.97,
    signature_match=0.95,
    cbs_outcome="PROCEED",
    alteration_detected=False,
    pps_outcome="FOUND",
    available_balance=100000.0,
    amount=50000.0,
):
    from modules.cts.workflows.activities.decision import DecisionInput
    return DecisionInput(
        instrument_id="INST001",
        bank_id="test-bank",
        fraud_score=fraud_score,
        ocr_confidence=ocr_confidence,
        signature_match_score=signature_match,
        cbs_outcome=cbs_outcome,
        alteration_detected=alteration_detected,
        pps_outcome=pps_outcome,
        available_balance=available_balance,
        cheque_amount=amount,
        shap_values={"amount_feature": 0.1, "drawer_history": -0.05},
    )


def _make_config(
    stp_threshold=0.92,
    fraud_threshold=0.72,
    ocr_min_confidence=0.85,
    sig_min_match=0.80,
):
    return {
        "stp_auto_confirm_threshold": stp_threshold,
        "human_review_fraud_threshold": fraud_threshold,
        "ocr_min_confidence": ocr_min_confidence,
        "sig_min_match_score": sig_min_match,
    }


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

class TestDecisionInput:
    def test_requires_shap_values(self):
        from modules.cts.workflows.activities.decision import DecisionInput
        with pytest.raises(Exception):
            DecisionInput(
                instrument_id="I", bank_id="b",
                fraud_score=0.1, ocr_confidence=0.9,
                signature_match_score=0.9, cbs_outcome="PROCEED",
                alteration_detected=False, pps_outcome="FOUND",
                available_balance=100.0, cheque_amount=50.0,
                # missing shap_values
            )

    def test_input_is_frozen(self):
        inp = _make_signals()
        with pytest.raises(Exception):
            inp.fraud_score = 0.99


# ---------------------------------------------------------------------------
# STP_CONFIRM path
# ---------------------------------------------------------------------------

class TestSTPConfirm:
    @pytest.mark.asyncio
    async def test_low_fraud_high_confidence_gives_stp_confirm(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(fraud_score=0.05, ocr_confidence=0.98, signature_match=0.97),
            config=_make_config(stp_threshold=0.92, fraud_threshold=0.72),
        )
        assert result.decision == "STP_CONFIRM"

    @pytest.mark.asyncio
    async def test_stp_confirm_has_shap_values(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(fraud_score=0.05),
            config=_make_config(),
        )
        assert result.decision == "STP_CONFIRM"
        assert result.shap_values is not None
        assert len(result.shap_values) > 0

    @pytest.mark.asyncio
    async def test_stp_confirm_has_rationale(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(fraud_score=0.05),
            config=_make_config(),
        )
        assert result.rationale
        assert isinstance(result.rationale, str)


# ---------------------------------------------------------------------------
# STP_RETURN path
# ---------------------------------------------------------------------------

class TestSTPReturn:
    @pytest.mark.asyncio
    async def test_frozen_account_gives_return(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(cbs_outcome="RETURN"),
            config=_make_config(),
        )
        assert result.decision == "STP_RETURN"

    @pytest.mark.asyncio
    async def test_alteration_detected_gives_return(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(alteration_detected=True),
            config=_make_config(),
        )
        assert result.decision == "STP_RETURN"

    @pytest.mark.asyncio
    async def test_return_has_shap_values(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(cbs_outcome="RETURN"),
            config=_make_config(),
        )
        assert result.shap_values is not None


# ---------------------------------------------------------------------------
# HUMAN_REVIEW path
# ---------------------------------------------------------------------------

class TestHumanReview:
    @pytest.mark.asyncio
    async def test_high_fraud_score_gives_human_review(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(fraud_score=0.85),
            config=_make_config(fraud_threshold=0.72),
        )
        assert result.decision == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_low_ocr_confidence_gives_human_review(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(ocr_confidence=0.70),
            config=_make_config(),
        )
        assert result.decision == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_low_signature_match_gives_human_review(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(signature_match=0.60),
            config=_make_config(),
        )
        assert result.decision == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_cbs_unavailable_gives_human_review(self):
        """CBS unavailable is not a RETURN — it's an escalation."""
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(cbs_outcome="CBS_UNAVAILABLE"),
            config=_make_config(),
        )
        assert result.decision == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_pps_miss_gives_human_review(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(pps_outcome="HUMAN_REVIEW"),
            config=_make_config(),
        )
        assert result.decision == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_human_review_has_shap_values(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(fraud_score=0.85),
            config=_make_config(),
        )
        assert result.shap_values is not None

    @pytest.mark.asyncio
    async def test_dormant_cbs_gives_human_review(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(cbs_outcome="HUMAN_REVIEW"),
            config=_make_config(),
        )
        assert result.decision == "HUMAN_REVIEW"


# ---------------------------------------------------------------------------
# Thresholds must not be hardcoded
# ---------------------------------------------------------------------------

class TestThresholdsFromConfig:
    @pytest.mark.asyncio
    async def test_different_fraud_threshold_changes_decision(self):
        """Verify threshold is read from config, not hardcoded."""
        from modules.cts.workflows.activities.decision import synthesise_decision
        # With tight threshold (0.50), score 0.60 should trigger human review
        result_tight = await synthesise_decision(
            _make_signals(fraud_score=0.60),
            config=_make_config(fraud_threshold=0.50),
        )
        # With loose threshold (0.90), score 0.60 should proceed
        result_loose = await synthesise_decision(
            _make_signals(fraud_score=0.60),
            config=_make_config(fraud_threshold=0.90, stp_threshold=0.92),
        )
        assert result_tight.decision == "HUMAN_REVIEW"
        assert result_loose.decision != "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_different_stp_threshold_changes_decision(self):
        """STP confirm threshold is configurable per bank."""
        from modules.cts.workflows.activities.decision import synthesise_decision
        # Signals that look good but we set a very high STP threshold
        result = await synthesise_decision(
            _make_signals(fraud_score=0.05, ocr_confidence=0.93, signature_match=0.93),
            config=_make_config(stp_threshold=0.99, fraud_threshold=0.72),
        )
        # Low fraud but STP threshold set impossibly high → human review
        assert result.decision == "HUMAN_REVIEW"


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

class TestDecisionOutput:
    @pytest.mark.asyncio
    async def test_output_has_decision_field(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(_make_signals(), config=_make_config())
        assert hasattr(result, "decision")

    @pytest.mark.asyncio
    async def test_output_has_instrument_id(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(_make_signals(), config=_make_config())
        assert result.instrument_id == "INST001"

    @pytest.mark.asyncio
    async def test_output_is_frozen(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(_make_signals(), config=_make_config())
        with pytest.raises(Exception):
            result.decision = "SOMETHING_ELSE"


# ---------------------------------------------------------------------------
# OPA Layer 4 policy evaluation
# ---------------------------------------------------------------------------

class TestOPAGate:
    def _opa_client(self, decision: str, reason: str):
        """Build a mock OPAClient that returns the given decision."""
        from shared.opa_client import OPAClient, OPAResult
        client = MagicMock(spec=OPAClient)
        client.decide = AsyncMock(return_value=OPAResult(decision=decision, reason=reason))
        return client

    @pytest.mark.asyncio
    async def test_government_cheque_routed_to_human_review(self):
        """OPA HUMAN_REVIEW → synthesise_decision returns HUMAN_REVIEW regardless of clean signals."""
        from modules.cts.workflows.activities.decision import synthesise_decision
        opa = self._opa_client("HUMAN_REVIEW", "government_cheque")
        result = await synthesise_decision(
            _make_signals(fraud_score=0.01, ocr_confidence=0.99, signature_match=0.99),
            config=_make_config(),
            opa_client=opa,
        )
        assert result.decision == "HUMAN_REVIEW"
        assert "OPA policy" in result.rationale
        assert "government_cheque" in result.rationale

    @pytest.mark.asyncio
    async def test_court_order_cheque_routed_to_human_review(self):
        """Court-order cheques flagged by OPA → HUMAN_REVIEW."""
        from modules.cts.workflows.activities.decision import synthesise_decision
        opa = self._opa_client("HUMAN_REVIEW", "court_order")
        result = await synthesise_decision(
            _make_signals(),
            config=_make_config(),
            opa_client=opa,
        )
        assert result.decision == "HUMAN_REVIEW"
        assert "court_order" in result.rationale

    @pytest.mark.asyncio
    async def test_opa_auto_return_maps_to_stp_return(self):
        """OPA AUTO_RETURN → decision is STP_RETURN (not HUMAN_REVIEW)."""
        from modules.cts.workflows.activities.decision import synthesise_decision
        opa = self._opa_client("AUTO_RETURN", "policy_blocked_category")
        result = await synthesise_decision(
            _make_signals(),
            config=_make_config(),
            opa_client=opa,
        )
        assert result.decision == "STP_RETURN"
        assert "OPA policy" in result.rationale

    @pytest.mark.asyncio
    async def test_opa_proceed_falls_through_to_normal_gates_stp_confirm(self):
        """OPA PROCEED + all signals clean → STP_CONFIRM (OPA doesn't short-circuit normal path)."""
        from modules.cts.workflows.activities.decision import synthesise_decision
        opa = self._opa_client("PROCEED", "no_policy_match")
        result = await synthesise_decision(
            _make_signals(fraud_score=0.01, ocr_confidence=0.99, signature_match=0.99),
            config=_make_config(),
            opa_client=opa,
        )
        assert result.decision == "STP_CONFIRM"

    @pytest.mark.asyncio
    async def test_opa_proceed_falls_through_to_normal_gates_human_review(self):
        """OPA PROCEED + high fraud score → HUMAN_REVIEW from existing gate."""
        from modules.cts.workflows.activities.decision import synthesise_decision
        opa = self._opa_client("PROCEED", "no_policy_match")
        result = await synthesise_decision(
            _make_signals(fraud_score=0.90),
            config=_make_config(fraud_threshold=0.72),
            opa_client=opa,
        )
        assert result.decision == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_no_opa_client_standard_behavior_unchanged(self):
        """When opa_client is None, existing behavior is identical to before OPA was added."""
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_signals(fraud_score=0.01, ocr_confidence=0.99, signature_match=0.99),
            config=_make_config(),
            opa_client=None,
        )
        assert result.decision == "STP_CONFIRM"

    @pytest.mark.asyncio
    async def test_opa_shap_values_preserved_on_human_review(self):
        """SHAP values must be present even when OPA short-circuits."""
        from modules.cts.workflows.activities.decision import synthesise_decision
        opa = self._opa_client("HUMAN_REVIEW", "government_cheque")
        result = await synthesise_decision(
            _make_signals(),
            config=_make_config(),
            opa_client=opa,
        )
        assert result.shap_values is not None
        assert len(result.shap_values) > 0

    @pytest.mark.asyncio
    async def test_opa_human_review_overrides_stp_confirm_quality(self):
        """Even with perfect OCR/sig/fraud — government cheque goes to human review."""
        from modules.cts.workflows.activities.decision import synthesise_decision
        opa = self._opa_client("HUMAN_REVIEW", "government_cheque_always_review")
        result = await synthesise_decision(
            _make_signals(
                fraud_score=0.0,
                ocr_confidence=1.0,
                signature_match=1.0,
                cbs_outcome="PROCEED",
                alteration_detected=False,
                pps_outcome="FOUND",
            ),
            config=_make_config(stp_threshold=0.5),  # very low STP bar — still overridden
            opa_client=opa,
        )
        assert result.decision == "HUMAN_REVIEW"
