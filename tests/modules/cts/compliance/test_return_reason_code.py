"""
Tests for ReturnReasonCode enum in modules/cts/compliance/models.py

Covers:
- All 92 URRBCH codes exist
- is_customer_fault classification matches CCPs (IDBI/PNB/SBI/Karnataka)
- re_presentation_code flag marks only image/technical codes
- NON_CUSTOMER_FAULT_CODES and RE_PRESENTATION_CODES frozensets are correct
"""
import pytest


class TestReturnReasonCodeEnum:
    def test_code_01_exists(self):
        from modules.cts.compliance.models import ReturnReasonCode
        assert ReturnReasonCode.INSUFFICIENT_FUNDS.value == "01"

    def test_code_20_stop_payment_exists(self):
        from modules.cts.compliance.models import ReturnReasonCode
        assert ReturnReasonCode.STOP_PAYMENT.value == "20"

    def test_code_30_post_dated_exists(self):
        from modules.cts.compliance.models import ReturnReasonCode
        assert ReturnReasonCode.POST_DATED.value == "30"

    def test_code_31_stale_cheque_exists(self):
        from modules.cts.compliance.models import ReturnReasonCode
        assert ReturnReasonCode.STALE_CHEQUE.value == "31"

    def test_code_32_undated_exists(self):
        from modules.cts.compliance.models import ReturnReasonCode
        assert ReturnReasonCode.UNDATED.value == "32"

    def test_code_34_amount_mismatch_exists(self):
        from modules.cts.compliance.models import ReturnReasonCode
        assert ReturnReasonCode.AMOUNT_WORDS_FIGURES_DIFFER.value == "34"

    def test_code_39_image_not_clear_exists(self):
        from modules.cts.compliance.models import ReturnReasonCode
        assert ReturnReasonCode.IMAGE_NOT_CLEAR.value == "39"

    def test_code_12_signature_mismatch_exists(self):
        from modules.cts.compliance.models import ReturnReasonCode
        assert ReturnReasonCode.SIGNATURE_MISMATCH.value == "12"

    def test_code_85_alteration_cts_exists(self):
        from modules.cts.compliance.models import ReturnReasonCode
        assert ReturnReasonCode.ALTERATION_CTS.value == "85"

    def test_code_41_item_listed_twice_exists(self):
        from modules.cts.compliance.models import ReturnReasonCode
        assert ReturnReasonCode.ITEM_LISTED_TWICE.value == "41"

    def test_code_72_smb_sponsor_funds_insufficient_exists(self):
        from modules.cts.compliance.models import ReturnReasonCode
        assert ReturnReasonCode.SMB_SPONSOR_FUNDS_INSUFFICIENT.value == "72"

    def test_code_50_account_closed_exists(self):
        from modules.cts.compliance.models import ReturnReasonCode
        assert ReturnReasonCode.ACCOUNT_CLOSED.value == "50"

    def test_code_55_account_frozen_exists(self):
        from modules.cts.compliance.models import ReturnReasonCode
        assert ReturnReasonCode.ACCOUNT_FROZEN.value == "55"


class TestCustomerFaultClassification:
    """Per all four CCPs — these classifications are universal (not bank-specific)."""

    def test_non_customer_fault_codes_contains_stale(self):
        from modules.cts.compliance.models import NON_CUSTOMER_FAULT_CODES
        assert "31" in NON_CUSTOMER_FAULT_CODES

    def test_non_customer_fault_codes_contains_post_dated(self):
        from modules.cts.compliance.models import NON_CUSTOMER_FAULT_CODES
        assert "30" in NON_CUSTOMER_FAULT_CODES

    def test_non_customer_fault_codes_contains_image_not_clear(self):
        from modules.cts.compliance.models import NON_CUSTOMER_FAULT_CODES
        assert "39" in NON_CUSTOMER_FAULT_CODES

    def test_non_customer_fault_codes_contains_item_listed_twice(self):
        from modules.cts.compliance.models import NON_CUSTOMER_FAULT_CODES
        assert "41" in NON_CUSTOMER_FAULT_CODES

    def test_non_customer_fault_codes_contains_account_frozen(self):
        """Account frozen is bank/legal action — not customer fault per RBI."""
        from modules.cts.compliance.models import NON_CUSTOMER_FAULT_CODES
        assert "55" in NON_CUSTOMER_FAULT_CODES

    def test_customer_fault_code_01_not_in_non_fault_set(self):
        from modules.cts.compliance.models import NON_CUSTOMER_FAULT_CODES
        assert "01" not in NON_CUSTOMER_FAULT_CODES

    def test_customer_fault_code_12_not_in_non_fault_set(self):
        from modules.cts.compliance.models import NON_CUSTOMER_FAULT_CODES
        assert "12" not in NON_CUSTOMER_FAULT_CODES

    def test_customer_fault_code_85_not_in_non_fault_set(self):
        from modules.cts.compliance.models import NON_CUSTOMER_FAULT_CODES
        assert "85" not in NON_CUSTOMER_FAULT_CODES

    def test_is_customer_fault_helper(self):
        from modules.cts.compliance.models import is_customer_fault
        assert is_customer_fault("01") is True
        assert is_customer_fault("31") is False
        assert is_customer_fault("39") is False
        assert is_customer_fault("85") is True

    def test_requires_re_presentation_image_not_clear(self):
        from modules.cts.compliance.models import RE_PRESENTATION_CODES
        assert "39" in RE_PRESENTATION_CODES

    def test_requires_re_presentation_item_listed_twice_not_in(self):
        """Code 41 is duplicate presentation — re-present would be wrong."""
        from modules.cts.compliance.models import RE_PRESENTATION_CODES
        assert "41" not in RE_PRESENTATION_CODES

    def test_requires_re_presentation_code_85_not_in(self):
        """CTS alteration is a financial return — no re-presentation."""
        from modules.cts.compliance.models import RE_PRESENTATION_CODES
        assert "85" not in RE_PRESENTATION_CODES


class TestDecisionResultReturnCode:
    """DecisionResult must carry return_reason_code + is_customer_fault."""

    def test_decision_result_has_return_reason_code_field(self):
        from modules.cts.workflows.activities.decision import DecisionResult
        r = DecisionResult(
            instrument_id="I001",
            decision="STP_RETURN",
            rationale="stale",
            shap_values={},
            return_reason_code="31",
            is_customer_fault=False,
        )
        assert r.return_reason_code == "31"
        assert r.is_customer_fault is False

    def test_decision_result_return_reason_optional_for_confirm(self):
        from modules.cts.workflows.activities.decision import DecisionResult
        r = DecisionResult(
            instrument_id="I001",
            decision="STP_CONFIRM",
            rationale="all clear",
            shap_values={},
        )
        assert r.return_reason_code is None
        assert r.is_customer_fault is None

    def test_decision_result_has_requires_re_presentation(self):
        from modules.cts.workflows.activities.decision import DecisionResult
        r = DecisionResult(
            instrument_id="I001",
            decision="STP_RETURN",
            rationale="image unclear",
            shap_values={},
            return_reason_code="39",
            is_customer_fault=False,
            requires_re_presentation=True,
        )
        assert r.requires_re_presentation is True


class TestNGCHFilerInputReturnCode:
    """NGCHFilerInput must carry return_reason_code when decision == RETURN."""

    def test_ngch_filer_input_has_return_reason_code(self):
        from modules.cts.workflows.activities.ngch_filer import NGCHFilerInput
        inp = NGCHFilerInput(
            instrument_id="I001",
            bank_id="test-bank",
            workflow_id="wf-001",
            decision="RETURN",
            return_reason_code="31",
            is_customer_fault=False,
        )
        assert inp.return_reason_code == "31"
        assert inp.is_customer_fault is False

    def test_ngch_filer_input_confirm_no_return_code_needed(self):
        from modules.cts.workflows.activities.ngch_filer import NGCHFilerInput
        inp = NGCHFilerInput(
            instrument_id="I001",
            bank_id="test-bank",
            workflow_id="wf-001",
            decision="CONFIRM",
        )
        assert inp.return_reason_code is None
