"""
CCP-compliance tests for decision.py — Phase 2 enhancements.

Tests cheque validity gates (stale/post-dated/undated) and CTS alteration
specificity (non-date fields = code 85 auto-return; date-only = human review).

All gates are new additions; existing decision tests remain unchanged.
"""
import pytest
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock


def _make_config():
    return {
        "stp_auto_confirm_threshold": 0.92,
        "human_review_fraud_threshold": 0.72,
        "ocr_min_confidence": 0.85,
        "sig_min_match_score": 0.80,
        "cheque_validity_days": 90,   # Layer 3 — 3-month validity per RBI
    }


_DEFAULT_DATE = object()  # sentinel: "use today"


def _make_clean_signals(
    cheque_date=_DEFAULT_DATE,
    altered_fields=None,
    alteration_detected=False,
):
    from modules.cts.workflows.activities.decision import DecisionInput
    resolved_date = date.today() if cheque_date is _DEFAULT_DATE else cheque_date
    return DecisionInput(
        instrument_id="INST001",
        bank_id="test-bank",
        fraud_score=0.05,
        ocr_confidence=0.97,
        signature_match_score=0.95,
        cbs_outcome="PROCEED",
        alteration_detected=alteration_detected,
        altered_fields=altered_fields or [],
        pps_outcome="FOUND",
        available_balance=200000.0,
        cheque_amount=50000.0,
        shap_values={"amount_feature": 0.1},
        cheque_date=resolved_date,
    )


# ── Cheque validity gate ────────────────────────────────────────────────────

class TestStaleChequeGate:
    @pytest.mark.asyncio
    async def test_stale_cheque_gives_stp_return(self):
        """Cheque older than 90 days = stale → auto-return, code 31."""
        from modules.cts.workflows.activities.decision import synthesise_decision
        stale_date = date.today() - timedelta(days=91)
        result = await synthesise_decision(
            _make_clean_signals(cheque_date=stale_date),
            config=_make_config(),
        )
        assert result.decision == "STP_RETURN"
        assert result.return_reason_code == "31"

    @pytest.mark.asyncio
    async def test_stale_cheque_is_not_customer_fault(self):
        """Bank presented stale cheque — not customer's clearing fault."""
        from modules.cts.workflows.activities.decision import synthesise_decision
        stale_date = date.today() - timedelta(days=91)
        result = await synthesise_decision(
            _make_clean_signals(cheque_date=stale_date),
            config=_make_config(),
        )
        assert result.is_customer_fault is False

    @pytest.mark.asyncio
    async def test_cheque_exactly_90_days_old_is_valid(self):
        """90 days = boundary — still valid, not stale."""
        from modules.cts.workflows.activities.decision import synthesise_decision
        boundary_date = date.today() - timedelta(days=90)
        result = await synthesise_decision(
            _make_clean_signals(cheque_date=boundary_date),
            config=_make_config(),
        )
        assert result.decision != "STP_RETURN" or result.return_reason_code != "31"

    @pytest.mark.asyncio
    async def test_validity_days_from_config_not_hardcoded(self):
        """Changing cheque_validity_days in config changes the boundary."""
        from modules.cts.workflows.activities.decision import synthesise_decision
        # 30-day config: a 31-day-old cheque should be stale
        tight_config = {**_make_config(), "cheque_validity_days": 30}
        old_date = date.today() - timedelta(days=31)
        result = await synthesise_decision(
            _make_clean_signals(cheque_date=old_date),
            config=tight_config,
        )
        assert result.decision == "STP_RETURN"
        assert result.return_reason_code == "31"


class TestPostDatedChequeGate:
    @pytest.mark.asyncio
    async def test_post_dated_cheque_gives_stp_return(self):
        """Future-dated cheque → auto-return, code 30."""
        from modules.cts.workflows.activities.decision import synthesise_decision
        future_date = date.today() + timedelta(days=5)
        result = await synthesise_decision(
            _make_clean_signals(cheque_date=future_date),
            config=_make_config(),
        )
        assert result.decision == "STP_RETURN"
        assert result.return_reason_code == "30"

    @pytest.mark.asyncio
    async def test_post_dated_is_not_customer_fault(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        future_date = date.today() + timedelta(days=3)
        result = await synthesise_decision(
            _make_clean_signals(cheque_date=future_date),
            config=_make_config(),
        )
        assert result.is_customer_fault is False


class TestUndatedChequeGate:
    @pytest.mark.asyncio
    async def test_undated_cheque_gives_stp_return(self):
        """No date on cheque → auto-return, code 32."""
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_clean_signals(cheque_date=None),
            config=_make_config(),
        )
        assert result.decision == "STP_RETURN"
        assert result.return_reason_code == "32"


# ── CTS alteration specificity ──────────────────────────────────────────────

class TestCTSAlterationSpecificity:
    @pytest.mark.asyncio
    async def test_non_date_alteration_gives_stp_return_code_85(self):
        """CTS rule: alteration in amount/payee/etc → code 85, no human review."""
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_clean_signals(alteration_detected=True, altered_fields=["amount_figures"]),
            config=_make_config(),
        )
        assert result.decision == "STP_RETURN"
        assert result.return_reason_code == "85"

    @pytest.mark.asyncio
    async def test_multiple_non_date_fields_altered_gives_code_85(self):
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_clean_signals(
                alteration_detected=True,
                altered_fields=["amount_figures", "payee_name"],
            ),
            config=_make_config(),
        )
        assert result.decision == "STP_RETURN"
        assert result.return_reason_code == "85"

    @pytest.mark.asyncio
    async def test_date_only_alteration_routes_to_human_review(self):
        """Date-field alteration only → human review (bank policy decision)."""
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_clean_signals(alteration_detected=True, altered_fields=["date"]),
            config=_make_config(),
        )
        assert result.decision == "HUMAN_REVIEW"
        assert result.return_reason_code is None

    @pytest.mark.asyncio
    async def test_alteration_code_85_is_customer_fault(self):
        """Fraudulent alteration — customer (drawer) is at fault."""
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_clean_signals(alteration_detected=True, altered_fields=["payee_name"]),
            config=_make_config(),
        )
        assert result.is_customer_fault is True

    @pytest.mark.asyncio
    async def test_no_alteration_does_not_trigger_gate(self):
        """When no alteration, existing STP flow runs normally."""
        from modules.cts.workflows.activities.decision import synthesise_decision
        result = await synthesise_decision(
            _make_clean_signals(alteration_detected=False, altered_fields=[]),
            config=_make_config(),
        )
        assert result.decision == "STP_CONFIRM"


# ── Return code on CBS-driven returns ────────────────────────────────────────

class TestCBSReturnCodes:
    @pytest.mark.asyncio
    async def test_cbs_return_with_reason_nsf_gives_code_01(self):
        """CBS return reason NSF → return code 01."""
        from modules.cts.workflows.activities.decision import synthesise_decision, DecisionInput
        today = date.today()
        inp = DecisionInput(
            instrument_id="INST001",
            bank_id="test-bank",
            fraud_score=0.05,
            ocr_confidence=0.97,
            signature_match_score=0.95,
            cbs_outcome="RETURN",
            cbs_return_reason="NSF",
            alteration_detected=False,
            altered_fields=[],
            pps_outcome="FOUND",
            available_balance=0.0,
            cheque_amount=50000.0,
            shap_values={},
            cheque_date=today,
        )
        result = await synthesise_decision(inp, config=_make_config())
        assert result.decision == "STP_RETURN"
        assert result.return_reason_code == "01"

    @pytest.mark.asyncio
    async def test_cbs_return_with_reason_stop_payment_gives_code_20(self):
        from modules.cts.workflows.activities.decision import synthesise_decision, DecisionInput
        today = date.today()
        inp = DecisionInput(
            instrument_id="INST001",
            bank_id="test-bank",
            fraud_score=0.05,
            ocr_confidence=0.97,
            signature_match_score=0.95,
            cbs_outcome="RETURN",
            cbs_return_reason="STOP_PAYMENT",
            alteration_detected=False,
            altered_fields=[],
            pps_outcome="FOUND",
            available_balance=100000.0,
            cheque_amount=50000.0,
            shap_values={},
            cheque_date=today,
        )
        result = await synthesise_decision(inp, config=_make_config())
        assert result.decision == "STP_RETURN"
        assert result.return_reason_code == "20"

    @pytest.mark.asyncio
    async def test_cbs_return_with_reason_account_frozen_gives_code_55(self):
        from modules.cts.workflows.activities.decision import synthesise_decision, DecisionInput
        today = date.today()
        inp = DecisionInput(
            instrument_id="INST001",
            bank_id="test-bank",
            fraud_score=0.05,
            ocr_confidence=0.97,
            signature_match_score=0.95,
            cbs_outcome="RETURN",
            cbs_return_reason="ACCOUNT_FROZEN",
            alteration_detected=False,
            altered_fields=[],
            pps_outcome="FOUND",
            available_balance=100000.0,
            cheque_amount=50000.0,
            shap_values={},
            cheque_date=today,
        )
        result = await synthesise_decision(inp, config=_make_config())
        assert result.decision == "STP_RETURN"
        assert result.return_reason_code == "55"
        assert result.is_customer_fault is False
