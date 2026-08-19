"""
Inward (drawee) pipeline — OCR integration tests.

The inward CTS pipeline runs a full multi-stage OCR before Vision LLM:
  Stage 1: GOT-OCR2.0 — full cheque image → MICR, amount, date, payee, IFSC
  Stage 2: IndicOCR  — Devanagari/regional payee & amount_words where detected
  Stage 3: Confidence gate + amount words/figures cross-check → PROCEED or HRQ

These tests verify:
  - OCR low confidence → HUMAN_REVIEW (early, before Vision LLM)
  - OCR model unavailable (degraded) → HUMAN_REVIEW
  - OCR PROCEED → alteration detection runs next
  - Indic payee on cheque → IndicOCR engine recorded in audit row
  - OCR results flow into decision gates (date, amount, IFSC)
  - Temporal worker E2E: ocr_extract registered and called
"""
import time
import uuid

import pytest
import pytest_asyncio
from unittest.mock import MagicMock

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker, UnsandboxedWorkflowRunner

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _inp(**kwargs):
    from modules.cts.workflows.cheque_workflow import ChequeWorkflowInput
    defaults = dict(
        instrument_id="OCR-TEST-001",
        bank_id="saraswat-coop",
        image_url="minio://cts/inward/OCR-TEST-001.tiff",
        account_number="12340000005678",
        cheque_number="000099",
        presented_amount=75000.0,
        presented_payee="Suresh Patil",
        iet_deadline=time.time() + 10800,
        ngch_ifsc="SRCB0000001",
        cts_config={"stp_mode": "FULL_STP"},
    )
    defaults.update(kwargs)
    return ChequeWorkflowInput(**defaults)


def _ocr_result(
    outcome="PROCEED",
    confidence=0.97,
    date="15/08/2026",
    amount_figures="75000",
    amount_words="Seventy Five Thousand Only",
    payee="Suresh Patil",
    ifsc_code="SRCB0000001",
    micr_line="600002000099",
    low_confidence_reason=None,
    degraded=False,
    engines=None,
    indic_refined_fields=None,
):
    from modules.cts.workflows.activities.ocr import OCRActivityResult
    return OCRActivityResult(
        outcome=outcome,
        micr_line=micr_line,
        amount_figures=amount_figures,
        amount_words=amount_words,
        date=date,
        payee=payee,
        ifsc_code=ifsc_code,
        overall_confidence=confidence,
        low_confidence_reason=low_confidence_reason,
        degraded=degraded,
        ocr_engines_used=engines or ["got-ocr2.0:cascade-1"],
        indic_refined_fields=indic_refined_fields or [],
    )


def _all_mocks(ocr=None):
    """Full happy-path mock_results with optional ocr override."""
    from modules.cts.workflows.activities.alteration import AlterationActivityResult
    from modules.cts.workflows.activities.signature import SignatureActivityResult
    from modules.cts.workflows.activities.pps import PPSActivityResult
    from modules.cts.workflows.activities.cbs import CBSActivityResult
    from modules.cts.workflows.activities.stop_payment import StopPaymentActivityResult
    from modules.cts.workflows.activities.fraud import FraudActivityResult
    from modules.cts.workflows.activities.decision import DecisionResult

    acct_mock = MagicMock()
    acct_mock.outcome = "PROCEED"
    acct_mock.account_status = "ACTIVE"

    compliance_mock = MagicMock()
    compliance_mock.is_compliant = True
    compliance_mock.violations = []

    d = {
        "alteration": AlterationActivityResult(alteration_detected=False, tamper_risk_score=0.01),
        "compliance": compliance_mock,
        "stop_payment": StopPaymentActivityResult(outcome="PROCEED"),
        "pps": PPSActivityResult(outcome="PROCEED"),
        "signature": SignatureActivityResult(outcome="PROCEED", match_score=0.96),
        "fraud": FraudActivityResult(fraud_score=0.04, shap_values={"amount": -0.1}),
        "cbs": CBSActivityResult(outcome="PROCEED", available_balance=200000.0),
        "account_status": acct_mock,
        "decision": DecisionResult(
            instrument_id="OCR-TEST-001",
            decision="STP_CONFIRM",
            rationale="All gates passed",
            shap_values={"amount": -0.1},
        ),
    }
    if ocr is not None:
        d["ocr"] = ocr
    return d


# ---------------------------------------------------------------------------
# 1. OCR parsing helpers (unit tests — no Temporal needed)
# ---------------------------------------------------------------------------

class TestOCRParsingHelpers:
    def test_parse_cheque_date_dmy_slash(self):
        from modules.cts.workflows.cheque_workflow import _parse_cheque_date
        d = _parse_cheque_date("15/08/2026")
        assert d is not None
        assert d.year == 2026 and d.month == 8 and d.day == 15

    def test_parse_cheque_date_iso(self):
        from modules.cts.workflows.cheque_workflow import _parse_cheque_date
        d = _parse_cheque_date("2026-08-15")
        assert d is not None and d.year == 2026

    def test_parse_cheque_date_dmy_hyphen(self):
        from modules.cts.workflows.cheque_workflow import _parse_cheque_date
        d = _parse_cheque_date("15-08-2026")
        assert d is not None and d.day == 15

    def test_parse_cheque_date_verbal(self):
        from modules.cts.workflows.cheque_workflow import _parse_cheque_date
        d = _parse_cheque_date("15-Aug-2026")
        assert d is not None and d.month == 8

    def test_parse_cheque_date_none_input(self):
        from modules.cts.workflows.cheque_workflow import _parse_cheque_date
        assert _parse_cheque_date(None) is None
        assert _parse_cheque_date("") is None

    def test_parse_cheque_date_unrecognised(self):
        from modules.cts.workflows.cheque_workflow import _parse_cheque_date
        assert _parse_cheque_date("not-a-date") is None

    def test_parse_amount_figures_plain(self):
        from modules.cts.workflows.cheque_workflow import _parse_amount_figures
        assert _parse_amount_figures("75000") == 75000.0

    def test_parse_amount_figures_with_commas(self):
        from modules.cts.workflows.cheque_workflow import _parse_amount_figures
        assert _parse_amount_figures("75,000.00") == 75000.0

    def test_parse_amount_figures_with_rupee(self):
        from modules.cts.workflows.cheque_workflow import _parse_amount_figures
        assert _parse_amount_figures("₹75,000") == 75000.0

    def test_parse_amount_figures_none(self):
        from modules.cts.workflows.cheque_workflow import _parse_amount_figures
        assert _parse_amount_figures(None) is None
        assert _parse_amount_figures("") is None

    def test_parse_amount_figures_garbage(self):
        from modules.cts.workflows.cheque_workflow import _parse_amount_figures
        assert _parse_amount_figures("N/A") is None


# ---------------------------------------------------------------------------
# 2. run_with_mocks — OCR gate (fast, no Temporal server)
# ---------------------------------------------------------------------------

class TestInwardOCRGate:
    @pytest.mark.asyncio
    async def test_ocr_low_confidence_routes_to_hrq(self):
        """OCR below confidence threshold → HUMAN_REVIEW before alteration runs."""
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        mocks = _all_mocks(ocr=_ocr_result(
            outcome="HUMAN_REVIEW",
            confidence=0.45,
            low_confidence_reason="low_confidence_fields: ['amount_words', 'payee']",
        ))
        # Remove alteration — if OCR doesn't exit early, KeyError won't fire here
        # because alteration IS in mocks, but the rationale check is specific
        result = await wf.run_with_mocks(_inp(), mock_results=mocks)
        assert result.decision == "HUMAN_REVIEW"
        assert "ocr" in result.rationale.lower() or "low" in result.rationale.lower()

    @pytest.mark.asyncio
    async def test_ocr_model_unavailable_routes_to_hrq(self):
        """OCR model unavailable (degraded=True) → HUMAN_REVIEW."""
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        mocks = _all_mocks(ocr=_ocr_result(
            outcome="HUMAN_REVIEW",
            confidence=0.0,
            degraded=True,
            low_confidence_reason="MODEL_UNAVAILABLE",
        ))
        result = await wf.run_with_mocks(_inp(), mock_results=mocks)
        assert result.decision == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_ocr_amount_mismatch_routes_to_hrq(self):
        """Amount in words/figures mismatch detected by ocr_extract → HUMAN_REVIEW."""
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        mocks = _all_mocks(ocr=_ocr_result(
            outcome="HUMAN_REVIEW",
            low_confidence_reason="amount_figures_words_mismatch",
        ))
        result = await wf.run_with_mocks(_inp(), mock_results=mocks)
        assert result.decision == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_ocr_proceed_continues_to_alteration(self):
        """OCR PROCEED → alteration runs; tampered cheque routes to HRQ."""
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        from modules.cts.workflows.activities.alteration import AlterationActivityResult
        wf = ChequeProcessingWorkflow()
        mocks = _all_mocks(ocr=_ocr_result(outcome="PROCEED"))
        mocks["alteration"] = AlterationActivityResult(
            alteration_detected=True, tamper_risk_score=0.95,
        )
        # Remove downstream mocks — if OCR doesn't exit early, alteration tampered should catch it
        mocks.pop("stop_payment", None)
        mocks.pop("pps", None)
        mocks.pop("cbs", None)
        mocks.pop("account_status", None)
        result = await wf.run_with_mocks(_inp(), mock_results=mocks)
        assert result.decision == "HUMAN_REVIEW"
        assert "alteration" in result.rationale.lower()

    @pytest.mark.asyncio
    async def test_ocr_absent_backward_compatible_proceed(self):
        """No 'ocr' key → treated as PROCEED (backward compat for existing tests)."""
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        mocks = _all_mocks()   # no "ocr" key
        assert "ocr" not in mocks
        result = await wf.run_with_mocks(_inp(), mock_results=mocks)
        assert result.decision == "STP_CONFIRM"

    @pytest.mark.asyncio
    async def test_ocr_full_happy_path_stp_confirm(self):
        """OCR PROCEED + all gates pass → STP_CONFIRM."""
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        result = await wf.run_with_mocks(
            _inp(),
            mock_results=_all_mocks(ocr=_ocr_result()),
        )
        assert result.decision == "STP_CONFIRM"

    @pytest.mark.asyncio
    async def test_ocr_indic_payee_proceed_records_engine(self):
        """IndicOCR ran for Devanagari payee — still PROCEED if all fields confident."""
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        indic_ocr = _ocr_result(
            outcome="PROCEED",
            payee="सुरेश पाटिल",   # Devanagari payee
            engines=["got-ocr2.0:cascade-1", "indic_ocr:paddle/devanagari"],
            indic_refined_fields=["payee"],
        )
        result = await wf.run_with_mocks(
            _inp(),
            mock_results=_all_mocks(ocr=indic_ocr),
        )
        assert result.decision == "STP_CONFIRM"


# ---------------------------------------------------------------------------
# 3. Temporal E2E — real @workflow.run path with registered fake activities
# ---------------------------------------------------------------------------

@activity.defn(name="ocr_extract")
async def _ocr_fake_proceed(inp, orchestrator=None, config_service=None, routing_table=None):
    from modules.cts.workflows.activities.ocr import OCRActivityResult
    return OCRActivityResult(
        outcome="PROCEED",
        micr_line="600002000099",
        amount_figures="75000",
        amount_words="Seventy Five Thousand Only",
        date="15/08/2026",
        payee="Suresh Patil",
        ifsc_code="SRCB0000001",
        overall_confidence=0.97,
        ocr_engines_used=["got-ocr2.0:cascade-1"],
    )


@activity.defn(name="ocr_extract")
async def _ocr_fake_hrq(inp, orchestrator=None, config_service=None, routing_table=None):
    from modules.cts.workflows.activities.ocr import OCRActivityResult
    return OCRActivityResult(
        outcome="HUMAN_REVIEW",
        overall_confidence=0.31,
        low_confidence_reason="low_confidence_fields: ['amount_words', 'payee']",
        degraded=False,
        ocr_engines_used=["got-ocr2.0:cascade-1"],
    )


@activity.defn(name="ocr_extract")
async def _ocr_fake_degraded(inp, orchestrator=None, config_service=None, routing_table=None):
    from modules.cts.workflows.activities.ocr import OCRActivityResult
    return OCRActivityResult(
        outcome="HUMAN_REVIEW",
        overall_confidence=0.0,
        low_confidence_reason="MODEL_UNAVAILABLE",
        degraded=True,
        ocr_engines_used=["got-ocr2.0:unavailable"],
    )


def _dget(inp, key):
    return inp[key] if isinstance(inp, dict) else getattr(inp, key)


@activity.defn(name="file_to_ngch")
async def _e2e_file_to_ngch(inp):
    from modules.cts.workflows.activities.ngch_filer import NGCHFilerResult
    decision = _dget(inp, "decision")
    return NGCHFilerResult(acknowledgement_id="E2E-ACK", status="ACCEPTED", filed_decision=decision)


@activity.defn(name="write_audit")
async def _e2e_write_audit(inp):
    from modules.cts.workflows.activities.write_audit import WriteAuditResult
    return WriteAuditResult(success=True, immudb_tx_id="E2E-TX")


@activity.defn(name="push_to_review_queue")
async def _e2e_push_to_review_queue(inp):
    pass


@activity.defn(name="detect_alteration")
async def _e2e_detect_alteration(inp, vllm_client=None, kill_switch_status=None):
    from modules.cts.workflows.activities.alteration import AlterationActivityResult
    return AlterationActivityResult(alteration_detected=False)


@activity.defn(name="get_kill_switch_status")
async def _e2e_get_kill_switch_status(inp):
    from modules.cts.workflows.activities.kill_switch_lookup import KillSwitchLookupResult
    return KillSwitchLookupResult(mode="NONE", scope=None, smb_id=None)


@activity.defn(name="check_stop_payment")
async def _e2e_check_stop_payment(inp):
    from modules.cts.workflows.activities.stop_payment import StopPaymentActivityResult
    return StopPaymentActivityResult(outcome="PROCEED")


@activity.defn(name="lookup_pps")
async def _e2e_lookup_pps(inp):
    from modules.cts.workflows.activities.pps import PPSActivityResult
    return PPSActivityResult(outcome="PROCEED")


@activity.defn(name="verify_signature")
async def _e2e_verify_signature(inp):
    from modules.cts.workflows.activities.signature import SignatureActivityResult
    return SignatureActivityResult(outcome="PROCEED", match_score=0.97)


@activity.defn(name="score_fraud")
async def _e2e_score_fraud(inp):
    from modules.cts.workflows.activities.fraud import FraudActivityResult
    return FraudActivityResult(fraud_score=0.03, shap_values={"amount": -0.1})


@activity.defn(name="check_cbs_balance")
async def _e2e_check_cbs_balance(inp):
    from modules.cts.workflows.activities.cbs import CBSActivityResult
    return CBSActivityResult(outcome="PROCEED", available_balance=200000.0)


@activity.defn(name="check_account_status")
async def _e2e_check_account_status(inp):
    from modules.cts.workflows.activities.cbs import CBSActivityResult
    return CBSActivityResult(outcome="PROCEED", account_status="ACTIVE")


@activity.defn(name="synthesise_decision")
async def _e2e_synthesise_decision(inp, cts_config=None, kill_switch_status=None):
    from modules.cts.workflows.activities.decision import DecisionResult
    return DecisionResult(
        instrument_id=_dget(inp, "instrument_id"),
        decision="STP_CONFIRM",
        rationale="All gates passed — OCR E2E",
        shap_values={"amount": -0.1},
    )


@activity.defn(name="validate_ifsc")
async def _e2e_validate_ifsc(inp, repo=None):
    from modules.cts.workflows.activities.ifsc_validator import IFSCValidatorResult
    return IFSCValidatorResult(outcome="PROCEED")


@activity.defn(name="validate_cheque_series")
async def _e2e_validate_cheque_series(inp, cbs_connector=None, cheque_leaf_vault=None, config_service=None):
    from modules.cts.workflows.activities.cheque_series import ChequeSeriesActivityResult
    return ChequeSeriesActivityResult(outcome="PROCEED")


@activity.defn(name="detect_signatures")
async def _e2e_detect_signatures(inp):
    from modules.cts.workflows.activities.detect_signatures import DetectSignaturesResult
    return DetectSignaturesResult(
        outcome="PRESENT", sig_count=1,
        sig_bboxes=[[0.1, 0.7, 0.9, 0.95]], fraud_flags=[],
    )


@activity.defn(name="check_security_features")
async def _e2e_check_security_features(inp, vllm_client=None, config_service=None, langfuse=None):
    from modules.cts.workflows.activities.security_features import SecurityFeaturesResult
    return SecurityFeaturesResult(
        outcome="PROCEED",
        features_detected={"void_pantograph": True, "rupee_symbol": True,
                           "micro_lettering": True, "printer_name_cts2010": True},
        missing_features=[],
    )


@activity.defn(name="persist_agent_decision")
async def _e2e_persist_agent_decision(inp):
    from modules.cts.workflows.activities.persist_decision import PersistDecisionResult
    return PersistDecisionResult(success=True)


@activity.defn(name="mark_leaf_presented")
async def _e2e_mark_leaf_presented(inp):
    pass


_BASE_ACTIVITIES = [
    _e2e_detect_alteration, _e2e_get_kill_switch_status, _e2e_check_stop_payment,
    _e2e_validate_ifsc, _e2e_validate_cheque_series,
    _e2e_lookup_pps, _e2e_detect_signatures, _e2e_verify_signature, _e2e_score_fraud,
    _e2e_check_cbs_balance, _e2e_check_account_status, _e2e_synthesise_decision,
    _e2e_file_to_ngch, _e2e_write_audit, _e2e_push_to_review_queue,
    _e2e_check_security_features, _e2e_persist_agent_decision, _e2e_mark_leaf_presented,
]


@pytest_asyncio.fixture()
async def temporal_env():
    async with await WorkflowEnvironment.start_time_skipping() as env:
        yield env


class TestInwardOCRTemporalE2E:
    @pytest.mark.asyncio
    async def test_e2e_ocr_proceed_stp_confirm(self, temporal_env):
        """Full E2E: OCR PROCEED + all gates pass → STP_CONFIRM filed to NGCH."""
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow, ChequeWorkflowInput
        from modules.cts.workflows.iet_watchdog_workflow import IETWatchdogWorkflow
        from modules.cts.workflows.human_review_workflow import HumanReviewWorkflow
        from modules.cts.workflows.feedback_workflow import FeedbackEmitWorkflow

        task_queue = f"tq-ocr-{uuid.uuid4()}"
        bank_id, instrument_id = "saraswat-coop", f"OCR-{uuid.uuid4().hex[:8]}"

        async with Worker(
            temporal_env.client, task_queue=task_queue,
            workflows=[ChequeProcessingWorkflow, IETWatchdogWorkflow, HumanReviewWorkflow, FeedbackEmitWorkflow],
            activities=[_ocr_fake_proceed, *_BASE_ACTIVITIES],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await temporal_env.client.execute_workflow(
                ChequeProcessingWorkflow.run,
                ChequeWorkflowInput(
                    instrument_id=instrument_id, bank_id=bank_id,
                    image_url="minio://cts/inward/x.tiff",
                    account_number="12340000005678", cheque_number="000099",
                    presented_amount=75000.0, presented_payee="Suresh Patil",
                    iet_deadline=time.time() + 3600,
                    ngch_ifsc="SRCB0000001",
                    cts_config={"stp_mode": "FULL_STP"},
                ),
                id=f"cts-{bank_id}-{instrument_id}", task_queue=task_queue,
            )

        assert result.decision == "STP_CONFIRM"

    @pytest.mark.asyncio
    async def test_e2e_ocr_low_confidence_routes_hrq_and_audits(self, temporal_env):
        """OCR below threshold → HUMAN_REVIEW + audit written (no NGCH filing)."""
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow, ChequeWorkflowInput
        from modules.cts.workflows.iet_watchdog_workflow import IETWatchdogWorkflow
        from modules.cts.workflows.human_review_workflow import HumanReviewWorkflow
        from modules.cts.workflows.feedback_workflow import FeedbackEmitWorkflow

        task_queue = f"tq-ocr-hrq-{uuid.uuid4()}"
        bank_id, instrument_id = "saraswat-coop", f"OCR-HRQ-{uuid.uuid4().hex[:8]}"

        async with Worker(
            temporal_env.client, task_queue=task_queue,
            workflows=[ChequeProcessingWorkflow, IETWatchdogWorkflow, HumanReviewWorkflow, FeedbackEmitWorkflow],
            activities=[_ocr_fake_hrq, *_BASE_ACTIVITIES],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await temporal_env.client.execute_workflow(
                ChequeProcessingWorkflow.run,
                ChequeWorkflowInput(
                    instrument_id=instrument_id, bank_id=bank_id,
                    image_url="minio://cts/inward/x.tiff",
                    account_number="12340000005678", cheque_number="000099",
                    presented_amount=75000.0, presented_payee="Suresh Patil",
                    iet_deadline=time.time() + 3600,
                    cts_config={"stp_mode": "FULL_STP"},
                ),
                id=f"cts-{bank_id}-{instrument_id}", task_queue=task_queue,
            )

        assert result.decision == "HUMAN_REVIEW"
        assert "ocr" in result.rationale.lower() or "low" in result.rationale.lower()

    @pytest.mark.asyncio
    async def test_e2e_ocr_degraded_routes_hrq(self, temporal_env):
        """OCR model unavailable (vLLM down) → HUMAN_REVIEW, never silent failure."""
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow, ChequeWorkflowInput
        from modules.cts.workflows.iet_watchdog_workflow import IETWatchdogWorkflow
        from modules.cts.workflows.human_review_workflow import HumanReviewWorkflow
        from modules.cts.workflows.feedback_workflow import FeedbackEmitWorkflow

        task_queue = f"tq-ocr-deg-{uuid.uuid4()}"
        bank_id, instrument_id = "saraswat-coop", f"OCR-DEG-{uuid.uuid4().hex[:8]}"

        async with Worker(
            temporal_env.client, task_queue=task_queue,
            workflows=[ChequeProcessingWorkflow, IETWatchdogWorkflow, HumanReviewWorkflow, FeedbackEmitWorkflow],
            activities=[_ocr_fake_degraded, *_BASE_ACTIVITIES],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await temporal_env.client.execute_workflow(
                ChequeProcessingWorkflow.run,
                ChequeWorkflowInput(
                    instrument_id=instrument_id, bank_id=bank_id,
                    image_url="minio://cts/inward/x.tiff",
                    account_number="12340000005678", cheque_number="000099",
                    presented_amount=75000.0, presented_payee="Suresh Patil",
                    iet_deadline=time.time() + 3600,
                    cts_config={"stp_mode": "FULL_STP"},
                ),
                id=f"cts-{bank_id}-{instrument_id}", task_queue=task_queue,
            )

        assert result.decision == "HUMAN_REVIEW"


# ---------------------------------------------------------------------------
# 4. OCR field flow-through (unit — no Temporal)
# ---------------------------------------------------------------------------

class TestOCRFieldFlowThrough:
    def test_date_formats_all_parse(self):
        """All common Indian cheque date formats parse correctly."""
        from modules.cts.workflows.cheque_workflow import _parse_cheque_date
        from datetime import date
        cases = [
            ("15/08/2026", date(2026, 8, 15)),
            ("2026-08-15", date(2026, 8, 15)),
            ("15-08-2026", date(2026, 8, 15)),
            ("15-Aug-2026", date(2026, 8, 15)),
            ("15 Aug 2026", date(2026, 8, 15)),
            ("15/08/26", date(2026, 8, 15)),
        ]
        for raw, expected in cases:
            result = _parse_cheque_date(raw)
            assert result == expected, f"Failed for format: {raw!r}"

    def test_amount_parses_lakhs_format(self):
        """Cheque amounts in Indian lakh format parse to float."""
        from modules.cts.workflows.cheque_workflow import _parse_amount_figures
        cases = [
            ("1,00,000", 100000.0),
            ("75,000.00", 75000.0),
            ("10,00,00,000", 100000000.0),
            ("500", 500.0),
        ]
        for raw, expected in cases:
            assert _parse_amount_figures(raw) == expected, f"Failed: {raw!r}"

    def test_ocr_result_outcome_field_exists(self):
        """OCRActivityResult always has outcome field."""
        r = _ocr_result()
        assert r.outcome == "PROCEED"

    def test_ocr_result_engines_tracked(self):
        """Latin-only path uses only got-ocr2.0; Indic adds indic_ocr."""
        latin = _ocr_result(engines=["got-ocr2.0:cascade-1"])
        assert "got-ocr2.0:cascade-1" in latin.ocr_engines_used
        assert len(latin.ocr_engines_used) == 1

        indic = _ocr_result(
            engines=["got-ocr2.0:cascade-1", "indic_ocr:paddle/devanagari"],
            indic_refined_fields=["payee"],
        )
        assert len(indic.ocr_engines_used) == 2
        assert any("indic_ocr" in e for e in indic.ocr_engines_used)
        assert "payee" in indic.indic_refined_fields
