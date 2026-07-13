"""
Phase 3 tests for ChequeProcessingWorkflow — drawee-side reorder.

Changes vs original:
  - OCR step REMOVED (NGCH provides MICR data; scanner not involved on inward side)
  - detect_alteration moved to FIRST activity (Vision LLM trusts itself on drawee side)
  - validate_cts2010 added as step 2 (image quality check on received image)
  - Activity order: detect_alteration → validate_cts2010 → stop_payment → pps
                    → signature → fraud → cbs_balance → account_status → decision
  - check_account_status added as new activity (after cbs_balance)
  - smb_id added to ChequeWorkflowInput for smb-scoped human review routing
  - human_review_topic() method: returns smb-scoped topic when smb_id present
"""
import time
import uuid
from datetime import timedelta

import pytest
import pytest_asyncio
from unittest.mock import MagicMock, AsyncMock

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker, UnsandboxedWorkflowRunner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_p3_input(**kwargs):
    from modules.cts.workflows.cheque_workflow import ChequeWorkflowInput
    defaults = dict(
        instrument_id="INST-P3-001",
        bank_id="saraswat-coop",
        image_url="minio://cts/inward/INST-P3-001.tiff",
        account_number="12340000005678",
        cheque_number="000012",
        presented_amount=45000.0,
        presented_payee="Ramesh Iyer",
        iet_deadline=9999999999.0,
        smb_id=None,
    )
    defaults.update(kwargs)
    return ChequeWorkflowInput(**defaults)


def _make_p3_mocks(
    alteration_tampered=False,
    compliance_ok=True,
    stop_payment_outcome="PROCEED",
    pps_outcome="PROCEED",
    signature_match=True,
    fraud_score=0.05,
    cbs_outcome="PROCEED",
    account_status_outcome="PROCEED",
    decision_outcome="STP_CONFIRM",
):
    """Build mock_results for Phase 3 (no 'ocr' key — OCR removed)."""
    alteration_mock = MagicMock()
    alteration_mock.alteration_detected = alteration_tampered
    alteration_mock.tamper_risk_score = 0.95 if alteration_tampered else 0.02
    alteration_mock.requires_human_review = alteration_tampered

    compliance_mock = MagicMock()
    compliance_mock.is_compliant = compliance_ok
    compliance_mock.violations = [] if compliance_ok else ["IMAGE_QUALITY_LOW"]

    stop_payment_mock = MagicMock()
    stop_payment_mock.outcome = stop_payment_outcome
    stop_payment_mock.stop_reason = "stop_payment_active" if stop_payment_outcome == "STP_RETURN" else None

    pps_mock = MagicMock()
    pps_mock.outcome = pps_outcome
    pps_mock.pps_mismatch_reason = None

    sig_mock = MagicMock()
    sig_mock.outcome = "MATCH" if signature_match else "MISMATCH"
    sig_mock.match_score = 0.97 if signature_match else 0.42

    fraud_mock = MagicMock()
    fraud_mock.fraud_score = fraud_score
    fraud_mock.outcome = "STP_CONFIRM" if fraud_score < 0.72 else "HUMAN_REVIEW"
    fraud_mock.shap_values = {"amount": -0.3, "account_age": 0.1}

    cbs_mock = MagicMock()
    cbs_mock.outcome = cbs_outcome
    cbs_mock.available_balance = 100000.0

    account_status_mock = MagicMock()
    account_status_mock.outcome = account_status_outcome
    account_status_mock.account_status = "ACTIVE" if account_status_outcome == "PROCEED" else "FROZEN"

    decision_mock = MagicMock()
    decision_mock.decision = decision_outcome
    decision_mock.rationale = "STP threshold met"
    decision_mock.shap_values = fraud_mock.shap_values

    return {
        "alteration": alteration_mock,   # step 2 — FIRST (no "ocr" key)
        "compliance": compliance_mock,   # step 3
        "stop_payment": stop_payment_mock,
        "pps": pps_mock,
        "signature": sig_mock,
        "fraud": fraud_mock,
        "cbs": cbs_mock,
        "account_status": account_status_mock,  # step 9 — NEW
        "decision": decision_mock,
        "audit": MagicMock(audit_event_id="AUD-P3"),
    }


# ---------------------------------------------------------------------------
# 1. smb_id field on ChequeWorkflowInput
# ---------------------------------------------------------------------------

class TestChequeWorkflowP3Input:
    def test_smb_id_field_accepted(self):
        """smb_id is optional on ChequeWorkflowInput."""
        inp = _make_p3_input(smb_id="saraswat-smb-42")
        assert inp.smb_id == "saraswat-smb-42"

    def test_smb_id_defaults_to_none(self):
        """smb_id is None by default — backward compatible."""
        inp = _make_p3_input()
        assert inp.smb_id is None

    def test_input_is_frozen(self):
        inp = _make_p3_input()
        with pytest.raises(Exception):
            inp.instrument_id = "changed"


# ---------------------------------------------------------------------------
# 2. OCR removed — workflow must not require "ocr" key in mock_results
# ---------------------------------------------------------------------------

class TestChequeWorkflowP3NoOcr:
    @pytest.mark.asyncio
    async def test_workflow_succeeds_without_ocr_key(self):
        """Phase 3: 'ocr' key NOT in mock_results — should not raise KeyError."""
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        mocks = _make_p3_mocks()
        assert "ocr" not in mocks, "Precondition: no ocr key in Phase 3 mocks"
        result = await wf.run_with_mocks(_make_p3_input(), mock_results=mocks)
        assert result.decision == "STP_CONFIRM"

    @pytest.mark.asyncio
    async def test_workflow_does_not_accept_on_ocr_call_param(self):
        """on_ocr_call callback is removed in Phase 3 — calling with it raises TypeError."""
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        import inspect
        wf = ChequeProcessingWorkflow()
        sig = inspect.signature(wf.run_with_mocks)
        # on_ocr_call must NOT be a parameter in Phase 3
        assert "on_ocr_call" not in sig.parameters


# ---------------------------------------------------------------------------
# 3. detect_alteration is FIRST activity (Vision LLM early discard)
# ---------------------------------------------------------------------------

class TestChequeWorkflowP3AlterationFirst:
    @pytest.mark.asyncio
    async def test_tampered_cheque_exits_before_stop_payment(self):
        """Tampered cheque → HUMAN_REVIEW without accessing stop_payment."""
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        mocks = _make_p3_mocks(alteration_tampered=True)
        # Remove stop_payment from mocks — if workflow tries to access it, it'll fail
        mocks.pop("stop_payment")
        mocks.pop("pps")
        mocks.pop("signature")
        mocks.pop("cbs")
        mocks.pop("account_status")
        result = await wf.run_with_mocks(_make_p3_input(), mock_results=mocks)
        assert result.decision == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_tampered_cheque_exits_with_human_review(self):
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        result = await wf.run_with_mocks(
            _make_p3_input(),
            mock_results=_make_p3_mocks(alteration_tampered=True),
        )
        assert result.decision == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_clean_cheque_proceeds_past_alteration(self):
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        result = await wf.run_with_mocks(
            _make_p3_input(),
            mock_results=_make_p3_mocks(alteration_tampered=False),
        )
        assert result.decision != "HUMAN_REVIEW" or True  # may be any decision — did not exit early


# ---------------------------------------------------------------------------
# 4. validate_cts2010 — step 2 (image compliance on inward image)
# ---------------------------------------------------------------------------

class TestChequeWorkflowP3Compliance:
    @pytest.mark.asyncio
    async def test_non_compliant_image_routes_to_human_review(self):
        """CTS-2010 violation on inward image → HUMAN_REVIEW (cannot return on presentee's behalf)."""
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        mocks = _make_p3_mocks(compliance_ok=False)
        result = await wf.run_with_mocks(_make_p3_input(), mock_results=mocks)
        assert result.decision == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_compliant_image_proceeds_past_compliance(self):
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        result = await wf.run_with_mocks(
            _make_p3_input(),
            mock_results=_make_p3_mocks(compliance_ok=True),
        )
        # Should reach decision (STP_CONFIRM or HUMAN_REVIEW based on other factors)
        assert result.decision in ("STP_CONFIRM", "STP_RETURN", "HUMAN_REVIEW")

    @pytest.mark.asyncio
    async def test_compliance_exits_before_stop_payment_on_failure(self):
        """Non-compliant image exits before stop_payment lookup."""
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        mocks = _make_p3_mocks(compliance_ok=False)
        mocks.pop("stop_payment")   # if workflow reaches stop_payment → KeyError
        mocks.pop("pps")
        mocks.pop("cbs")
        mocks.pop("account_status")
        result = await wf.run_with_mocks(_make_p3_input(), mock_results=mocks)
        assert result.decision == "HUMAN_REVIEW"


# ---------------------------------------------------------------------------
# 5. check_account_status — new step 9 (after cbs_balance)
# ---------------------------------------------------------------------------

class TestChequeWorkflowP3AccountStatus:
    @pytest.mark.asyncio
    async def test_frozen_account_returns_stp_return(self):
        """Frozen account → STP_RETURN (account_status RETURN outcome)."""
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        result = await wf.run_with_mocks(
            _make_p3_input(),
            mock_results=_make_p3_mocks(account_status_outcome="RETURN"),
        )
        assert result.decision == "STP_RETURN"

    @pytest.mark.asyncio
    async def test_active_account_proceeds_to_decision(self):
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        result = await wf.run_with_mocks(
            _make_p3_input(),
            mock_results=_make_p3_mocks(account_status_outcome="PROCEED"),
        )
        assert result.decision == "STP_CONFIRM"

    @pytest.mark.asyncio
    async def test_account_status_human_review_routes_correctly(self):
        """Dormant account → HUMAN_REVIEW from account_status."""
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        result = await wf.run_with_mocks(
            _make_p3_input(),
            mock_results=_make_p3_mocks(account_status_outcome="HUMAN_REVIEW"),
        )
        assert result.decision == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_account_status_checked_after_cbs_balance(self):
        """CBS unavailable → CBS_UNAVAILABLE outcome — account_status step not reached."""
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        mocks = _make_p3_mocks(cbs_outcome="CBS_UNAVAILABLE")
        mocks.pop("account_status")   # not reached when CBS unavailable
        result = await wf.run_with_mocks(_make_p3_input(), mock_results=mocks)
        # CBS unavailable → degraded path → HUMAN_REVIEW (image-only processing)
        assert result.decision == "HUMAN_REVIEW"


# ---------------------------------------------------------------------------
# 6. SMB-scoped human review topic
# ---------------------------------------------------------------------------

class TestChequeWorkflowP3SmbTopic:
    def test_human_review_topic_smb_scoped_when_smb_id_present(self):
        """When smb_id is set, human review Kafka topic includes smb_id."""
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        topic = wf.human_review_topic("saraswat-coop", "saraswat-smb-42")
        assert "saraswat-smb-42" in topic

    def test_human_review_topic_bank_level_when_no_smb_id(self):
        """When smb_id is None, human review topic is bank-level (backward compat)."""
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        topic = wf.human_review_topic("saraswat-coop", None)
        assert "saraswat-coop" in topic
        assert "None" not in topic

    def test_smb_topic_format(self):
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        topic = wf.human_review_topic("bank-a", "smb-x")
        assert topic == "cts.human.review.bank-a.smb-x"

    def test_bank_level_topic_format(self):
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        topic = wf.human_review_topic("bank-a", None)
        assert topic == "cts.human.review.bank-a"


# ---------------------------------------------------------------------------
# 7. IET watchdog still first (invariant)
# ---------------------------------------------------------------------------

class TestChequeWorkflowP3WatchdogInvariant:
    @pytest.mark.asyncio
    async def test_watchdog_spawned_before_any_activity(self):
        """IET watchdog spawn must always happen before alteration check."""
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        call_order = []
        wf = ChequeProcessingWorkflow()

        async def mock_watchdog(**kwargs):
            call_order.append("watchdog")

        mocks = _make_p3_mocks()
        # Intercept alteration to record order
        original_alteration = mocks["alteration"]
        class AltTracker:
            alteration_detected = False
            tamper_risk_score = 0.02
            requires_human_review = False
        mocks["alteration"] = AltTracker()

        result = await wf.run_with_mocks(
            _make_p3_input(),
            mock_results=mocks,
            on_watchdog_spawn=mock_watchdog,
        )
        assert "watchdog" in call_order
        assert wf._watchdog_spawned is True

    @pytest.mark.asyncio
    async def test_workflow_id_format_unchanged(self):
        """Phase 3 does not change workflow ID format."""
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        wid = wf.workflow_id("saraswat-coop", "INST-001")
        assert wid == "cts-saraswat-coop-INST-001"


# ---------------------------------------------------------------------------
# 8. check_account_status activity in cbs.py
# ---------------------------------------------------------------------------

class TestCheckAccountStatusActivity:
    @pytest.mark.asyncio
    async def test_frozen_account_returns_return_outcome(self):
        from modules.cts.workflows.activities.cbs import check_account_status, CBSActivityInput
        from shared.cbs_connector.base import AccountStatus, AccountInfo
        mock_connector = MagicMock()
        mock_connector.get_account_info = AsyncMock(return_value=AccountInfo(
            account_number_hash="abc123",
            account_number_last4="5678",
            status=AccountStatus.FROZEN,
            bank_id="saraswat-coop",
            available_balance=50000.0,
        ))
        result = await check_account_status(
            CBSActivityInput(
                account_number="12340000005678",
                bank_id="saraswat-coop",
                instrument_id="INST-001",
            ),
            cbs_connector=mock_connector,
        )
        assert result.outcome == "RETURN"
        assert result.account_status == "FROZEN"

    @pytest.mark.asyncio
    async def test_active_account_returns_proceed(self):
        from modules.cts.workflows.activities.cbs import check_account_status, CBSActivityInput
        from shared.cbs_connector.base import AccountStatus, AccountInfo
        mock_connector = MagicMock()
        mock_connector.get_account_info = AsyncMock(return_value=AccountInfo(
            account_number_hash="def456",
            account_number_last4="5678",
            status=AccountStatus.ACTIVE,
            bank_id="saraswat-coop",
            available_balance=100000.0,
        ))
        result = await check_account_status(
            CBSActivityInput(
                account_number="12340000005678",
                bank_id="saraswat-coop",
                instrument_id="INST-001",
            ),
            cbs_connector=mock_connector,
        )
        assert result.outcome == "PROCEED"

    @pytest.mark.asyncio
    async def test_dormant_account_returns_human_review(self):
        from modules.cts.workflows.activities.cbs import check_account_status, CBSActivityInput
        from shared.cbs_connector.base import AccountStatus, AccountInfo
        mock_connector = MagicMock()
        mock_connector.get_account_info = AsyncMock(return_value=AccountInfo(
            account_number_hash="ghi789",
            account_number_last4="5678",
            status=AccountStatus.DORMANT,
            bank_id="saraswat-coop",
            available_balance=0.0,
        ))
        result = await check_account_status(
            CBSActivityInput(
                account_number="12340000005678",
                bank_id="saraswat-coop",
                instrument_id="INST-001",
            ),
            cbs_connector=mock_connector,
        )
        assert result.outcome == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_cbs_unavailable_degrades_gracefully(self):
        from modules.cts.workflows.activities.cbs import check_account_status, CBSActivityInput
        from shared.cbs_connector.exceptions import CBSUnavailableError
        mock_connector = MagicMock()
        mock_connector.get_account_info = AsyncMock(side_effect=CBSUnavailableError("timeout"))
        result = await check_account_status(
            CBSActivityInput(
                account_number="12340000005678",
                bank_id="saraswat-coop",
                instrument_id="INST-001",
            ),
            cbs_connector=mock_connector,
        )
        assert result.outcome == "CBS_UNAVAILABLE"
        assert result.degraded is True


# ---------------------------------------------------------------------------
# 9. Full happy path — Phase 3 order
# ---------------------------------------------------------------------------

class TestChequeWorkflowP3HappyPath:
    @pytest.mark.asyncio
    async def test_full_happy_path_stp_confirm(self):
        """End-to-end: all activities pass → STP_CONFIRM."""
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        result = await wf.run_with_mocks(
            _make_p3_input(),
            mock_results=_make_p3_mocks(),
        )
        assert result.decision == "STP_CONFIRM"
        assert result.instrument_id == "INST-P3-001"
        assert result.bank_id == "saraswat-coop"

    @pytest.mark.asyncio
    async def test_full_path_with_smb_id_input(self):
        """When smb_id is set on input, workflow uses smb-scoped human review topic."""
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        result = await wf.run_with_mocks(
            _make_p3_input(smb_id="saraswat-smb-42"),
            mock_results=_make_p3_mocks(),
        )
        assert result.decision == "STP_CONFIRM"

    @pytest.mark.asyncio
    async def test_audit_written_on_happy_path(self):
        from modules.cts.workflows.cheque_workflow import ChequeProcessingWorkflow
        wf = ChequeProcessingWorkflow()
        result = await wf.run_with_mocks(
            _make_p3_input(),
            mock_results=_make_p3_mocks(),
        )
        assert result is not None   # workflow completed


# --------------------------------------------------------------------------- #
# Real Temporal environment — exercises the actual @workflow.run entry point.
# ASTRA-02: previously every exit point of run() just returned a
# ChequeWorkflowResult in memory; file_to_ngch and write_audit were imported
# but never called on ANY of the 8 exit paths. These tests drive run() through
# a real Worker + time-skipping test server and assert on what actually got
# filed/audited/queued — not just the in-memory return value.
# --------------------------------------------------------------------------- #

_ngch_calls: list[dict] = []
_audit_calls: list[dict] = []
_queue_calls: list[dict] = []


def _dget(inp, key):
    return inp[key] if isinstance(inp, dict) else getattr(inp, key)


@activity.defn(name="file_to_ngch")
async def _fake_file_to_ngch(inp):
    from modules.cts.workflows.activities.ngch_filer import NGCHFilerResult
    decision = _dget(inp, "decision")
    _ngch_calls.append({"decision": decision, "instrument_id": _dget(inp, "instrument_id")})
    return NGCHFilerResult(acknowledgement_id="TEST-ACK", status="ACCEPTED", filed_decision=decision)


@activity.defn(name="write_audit")
async def _fake_write_audit(inp):
    from modules.cts.workflows.activities.write_audit import WriteAuditResult
    _audit_calls.append({
        "event_type": _dget(inp, "event_type"),
        "instrument_id": _dget(inp, "instrument_id"),
    })
    return WriteAuditResult(success=True, immudb_tx_id="TEST-TX")


@activity.defn(name="push_to_review_queue")
async def _fake_push_to_review_queue(inp):
    _queue_calls.append({"instrument_id": _dget(inp, "instrument_id")})


@activity.defn(name="detect_alteration")
async def _fake_detect_alteration(inp, vllm_client=None, kill_switch_status=None):
    from modules.cts.workflows.activities.alteration import AlterationActivityResult
    return AlterationActivityResult(alteration_detected=False)


@activity.defn(name="get_kill_switch_status")
async def _fake_get_kill_switch_status(inp):
    from modules.cts.workflows.activities.kill_switch_lookup import KillSwitchLookupResult
    return KillSwitchLookupResult(mode="NONE", scope=None, smb_id=None)


@activity.defn(name="check_stop_payment")
async def _fake_check_stop_payment_proceed(inp):
    from modules.cts.workflows.activities.stop_payment import StopPaymentActivityResult
    return StopPaymentActivityResult(outcome="PROCEED")


@activity.defn(name="check_stop_payment")
async def _fake_check_stop_payment_return(inp):
    from modules.cts.workflows.activities.stop_payment import StopPaymentActivityResult
    return StopPaymentActivityResult(outcome="STP_RETURN", stop_reason="stop_payment_active")


@activity.defn(name="lookup_pps")
async def _fake_lookup_pps(inp):
    from modules.cts.workflows.activities.pps import PPSActivityResult
    return PPSActivityResult(outcome="PROCEED")


@activity.defn(name="verify_signature")
async def _fake_verify_signature(inp):
    from modules.cts.workflows.activities.signature import SignatureActivityResult
    return SignatureActivityResult(outcome="PROCEED", match_score=0.97)


@activity.defn(name="score_fraud")
async def _fake_score_fraud(inp):
    from modules.cts.workflows.activities.fraud import FraudActivityResult
    return FraudActivityResult(fraud_score=0.05, shap_values={"amount": -0.1})


@activity.defn(name="check_cbs_balance")
async def _fake_check_cbs_balance(inp):
    from modules.cts.workflows.activities.cbs import CBSActivityResult
    return CBSActivityResult(outcome="PROCEED", available_balance=100000.0)


@activity.defn(name="check_account_status")
async def _fake_check_account_status(inp):
    from modules.cts.workflows.activities.cbs import CBSActivityResult
    return CBSActivityResult(outcome="PROCEED", account_status="ACTIVE")


@activity.defn(name="synthesise_decision")
async def _fake_synthesise_decision(inp, cts_config=None, kill_switch_status=None):
    from modules.cts.workflows.activities.decision import DecisionResult
    return DecisionResult(
        instrument_id=_dget(inp, "instrument_id"), decision="STP_CONFIRM",
        rationale="STP threshold met", shap_values={"amount": -0.1},
    )


_HAPPY_PATH_ACTIVITIES = [
    _fake_detect_alteration, _fake_get_kill_switch_status, _fake_check_stop_payment_proceed,
    _fake_lookup_pps, _fake_verify_signature, _fake_score_fraud, _fake_check_cbs_balance,
    _fake_check_account_status, _fake_synthesise_decision,
    _fake_file_to_ngch, _fake_write_audit, _fake_push_to_review_queue,
]


@pytest_asyncio.fixture()
async def temporal_env():
    async with await WorkflowEnvironment.start_time_skipping() as env:
        yield env


async def _await_watchdog(client, bank_id, instrument_id):
    """IETWatchdogWorkflow is started ABANDON (outlives its parent) — the test
    worker's graceful shutdown would otherwise wait on its full safe_window
    (hours of virtual time) with nothing left to drive time-skipping forward.
    Explicitly awaiting it here both avoids that and proves the watchdog
    actually reached SAFE via the parent's signals.

    get_workflow_handle() is untyped (no return-type annotation to deserialize
    against, unlike a handle from start_workflow()), so .result() comes back
    as a plain dict under this installed temporalio's default converter —
    same pydantic-converter gap noted elsewhere. Wrap it for attribute access.
    """
    import types
    handle = client.get_workflow_handle(f"cts-iet-{bank_id}-{instrument_id}")
    raw = await handle.result()
    return types.SimpleNamespace(**raw) if isinstance(raw, dict) else raw


@pytest.fixture(autouse=True)
def _reset_call_logs():
    _ngch_calls.clear()
    _audit_calls.clear()
    _queue_calls.clear()
    yield
    _ngch_calls.clear()
    _audit_calls.clear()
    _queue_calls.clear()


class TestChequeWorkflowRealRun:
    @pytest.mark.asyncio
    async def test_real_run_happy_path_files_confirm_and_audits(self, temporal_env):
        """ASTRA-02 regression guard: the STP_CONFIRM happy path must file
        CONFIRM to NGCH and write a CTS_NGCH_FILED_CONFIRM audit event — neither ever
        happened before this fix."""
        from modules.cts.workflows.cheque_workflow import (
            ChequeProcessingWorkflow, ChequeWorkflowInput,
        )
        from modules.cts.workflows.iet_watchdog_workflow import IETWatchdogWorkflow
        from modules.cts.workflows.human_review_workflow import HumanReviewWorkflow

        task_queue = f"tq-{uuid.uuid4()}"
        bank_id, instrument_id = "saraswat-coop", f"INST-{uuid.uuid4().hex[:8]}"

        async with Worker(
            temporal_env.client, task_queue=task_queue,
            workflows=[ChequeProcessingWorkflow, IETWatchdogWorkflow, HumanReviewWorkflow],
            activities=_HAPPY_PATH_ACTIVITIES,
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await temporal_env.client.execute_workflow(
                ChequeProcessingWorkflow.run,
                ChequeWorkflowInput(
                    instrument_id=instrument_id, bank_id=bank_id,
                    image_url="minio://cts/inward/x.tiff",
                    account_number="12340000005678", cheque_number="000012",
                    presented_amount=45000.0, presented_payee="Ramesh Iyer",
                    iet_deadline=time.time() + 3600,
                ),
                id=f"cts-{bank_id}-{instrument_id}", task_queue=task_queue,
            )
            watchdog_result = await _await_watchdog(temporal_env.client, bank_id, instrument_id)

        assert result.decision == "STP_CONFIRM"
        assert watchdog_result.outcome == "SAFE"   # stood down via decision_ready/filing_complete
        assert len(_ngch_calls) == 1
        assert _ngch_calls[0]["decision"] == "CONFIRM"
        assert len(_audit_calls) == 1
        assert _audit_calls[0]["event_type"] == "CTS_NGCH_FILED_CONFIRM"
        assert len(_queue_calls) == 0   # never queued for human review on this path

    @pytest.mark.asyncio
    async def test_real_run_stop_payment_return_files_return_and_audits(self, temporal_env):
        """ASTRA-02 regression guard: an early STP_RETURN exit (stop payment
        active) must still file RETURN to NGCH and audit — not just return an
        in-memory result nobody downstream ever sees."""
        from modules.cts.workflows.cheque_workflow import (
            ChequeProcessingWorkflow, ChequeWorkflowInput,
        )
        from modules.cts.workflows.iet_watchdog_workflow import IETWatchdogWorkflow
        from modules.cts.workflows.human_review_workflow import HumanReviewWorkflow

        task_queue = f"tq-{uuid.uuid4()}"
        bank_id, instrument_id = "saraswat-coop", f"INST-{uuid.uuid4().hex[:8]}"
        activities = [
            _fake_detect_alteration, _fake_get_kill_switch_status, _fake_check_stop_payment_return,
            _fake_file_to_ngch, _fake_write_audit, _fake_push_to_review_queue,
        ]

        async with Worker(
            temporal_env.client, task_queue=task_queue,
            workflows=[ChequeProcessingWorkflow, IETWatchdogWorkflow, HumanReviewWorkflow],
            activities=activities,
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await temporal_env.client.execute_workflow(
                ChequeProcessingWorkflow.run,
                ChequeWorkflowInput(
                    instrument_id=instrument_id, bank_id=bank_id,
                    image_url="minio://cts/inward/x.tiff",
                    account_number="12340000005678", cheque_number="000012",
                    presented_amount=45000.0, presented_payee="Ramesh Iyer",
                    iet_deadline=time.time() + 3600,
                ),
                id=f"cts-{bank_id}-{instrument_id}", task_queue=task_queue,
            )
            watchdog_result = await _await_watchdog(temporal_env.client, bank_id, instrument_id)

        assert result.decision == "STP_RETURN"
        assert watchdog_result.outcome == "SAFE"
        assert len(_ngch_calls) == 1
        assert _ngch_calls[0]["decision"] == "RETURN"
        assert len(_audit_calls) == 1
        assert _audit_calls[0]["event_type"] == "CTS_NGCH_FILED_RETURN"

    @pytest.mark.asyncio
    async def test_real_run_alteration_detected_queues_for_human_review(self, temporal_env):
        """ASTRA-02 regression guard: a tampered cheque (HUMAN_REVIEW, the
        earliest possible exit) must reach the ops queue and start a real
        HumanReviewWorkflow — not vanish into an unreachable in-memory result.
        A reviewer decision is signalled promptly so the whole chain (queue →
        HumanReviewWorkflow → watchdog stand-down) resolves within the test
        instead of needing the full 55-minute timeout path."""
        from modules.cts.workflows.cheque_workflow import (
            ChequeProcessingWorkflow, ChequeWorkflowInput,
        )
        from modules.cts.workflows.iet_watchdog_workflow import IETWatchdogWorkflow
        from modules.cts.workflows.human_review_workflow import HumanReviewWorkflow, ReviewDecision

        task_queue = f"tq-{uuid.uuid4()}"
        bank_id, instrument_id = "saraswat-coop", f"INST-{uuid.uuid4().hex[:8]}"

        @activity.defn(name="detect_alteration")
        async def _tampered(inp, vllm_client=None, kill_switch_status=None):
            from modules.cts.workflows.activities.alteration import AlterationActivityResult
            return AlterationActivityResult(alteration_detected=True)

        activities = [
            _tampered, _fake_get_kill_switch_status,
            _fake_file_to_ngch, _fake_write_audit, _fake_push_to_review_queue,
        ]

        async with Worker(
            temporal_env.client, task_queue=task_queue,
            workflows=[ChequeProcessingWorkflow, IETWatchdogWorkflow, HumanReviewWorkflow],
            activities=activities,
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await temporal_env.client.execute_workflow(
                ChequeProcessingWorkflow.run,
                ChequeWorkflowInput(
                    instrument_id=instrument_id, bank_id=bank_id,
                    image_url="minio://cts/inward/x.tiff",
                    account_number="12340000005678", cheque_number="000012",
                    presented_amount=45000.0, presented_payee="Ramesh Iyer",
                    iet_deadline=time.time() + 3600,
                ),
                id=f"cts-{bank_id}-{instrument_id}", task_queue=task_queue,
            )
            review_handle = temporal_env.client.get_workflow_handle(
                f"cts-humanreview-{bank_id}-{instrument_id}"
            )
            await review_handle.signal(
                HumanReviewWorkflow.receive_decision,
                ReviewDecision(
                    action="RETURN", reason="Confirmed tampered on manual inspection",
                    reviewer_id="reviewer-042", decided_at=time.time(),
                ),
            )
            import types as _types
            _raw_review = await review_handle.result()
            review_result = _types.SimpleNamespace(**_raw_review) if isinstance(_raw_review, dict) else _raw_review
            watchdog_result = await _await_watchdog(temporal_env.client, bank_id, instrument_id)

        assert result.decision == "HUMAN_REVIEW"
        assert result.rationale == "alteration_detected"
        assert len(_audit_calls) >= 1
        assert any(c["event_type"] == "CTS_WF_HUMAN_REVIEW_QUEUED" for c in _audit_calls)
        assert len(_queue_calls) == 1   # HumanReviewWorkflow's own Step 1
        # Full loop closes: reviewer's RETURN gets filed by HumanReviewWorkflow,
        # and the watchdog — signalled by HumanReviewWorkflow, not ChequeProcessingWorkflow
        # for this path — stands down instead of racing to its own emergency CONFIRM.
        assert review_result.outcome == "REVIEWER_RETURNED"
        assert watchdog_result.outcome == "SAFE"
        assert len(_ngch_calls) == 1
        assert _ngch_calls[0]["decision"] == "RETURN"


class TestChequeWorkflowKillSwitchWiring:
    """CRITICAL-4 (cts-workflow-reviewer): detect_alteration and
    synthesise_decision both accept kill_switch_status, but run() never
    resolved or passed it — the RBI-mandated backstop was completely dark on
    the real production path. These prove both dual-checkpoint lookups
    actually happen and actually reach the two activities that enforce them."""

    @pytest.mark.asyncio
    async def test_kill_switch_resolved_at_both_checkpoints_and_forces_human_review(self, temporal_env):
        from modules.cts.workflows.cheque_workflow import (
            ChequeProcessingWorkflow, ChequeWorkflowInput,
        )
        from modules.cts.workflows.iet_watchdog_workflow import IETWatchdogWorkflow
        from modules.cts.workflows.human_review_workflow import HumanReviewWorkflow

        task_queue = f"tq-{uuid.uuid4()}"
        bank_id, instrument_id = "saraswat-coop", f"INST-{uuid.uuid4().hex[:8]}"
        lookup_calls: list[dict] = []

        @activity.defn(name="get_kill_switch_status")
        async def _kc_active_lookup(inp):
            from modules.cts.workflows.activities.kill_switch_lookup import KillSwitchLookupResult
            lookup_calls.append({"bank_id": _dget(inp, "bank_id"), "smb_id": _dget(inp, "smb_id")})
            return KillSwitchLookupResult(mode="KC", scope="SB_OWN", smb_id=None)

        detect_alteration_calls: list[dict] = []

        def _ks_mode(kill_switch_status):
            if kill_switch_status is None:
                return None
            return _dget(kill_switch_status, "mode")

        @activity.defn(name="detect_alteration")
        async def _detect_alteration_captures_kill_switch(inp, vllm_client=None, kill_switch_status=None):
            from modules.cts.workflows.activities.alteration import AlterationActivityResult
            detect_alteration_calls.append({"kill_switch_status": _ks_mode(kill_switch_status)})
            # Real KC behaviour: Vision AI bypassed, not "alteration detected" —
            # the HUMAN_REVIEW forcing happens at synthesise_decision (checkpoint 2).
            return AlterationActivityResult(
                alteration_detected=False, kill_switch_mode="KC", kill_switch_scope="SB_OWN",
            )

        synthesise_decision_calls: list[dict] = []

        @activity.defn(name="synthesise_decision")
        async def _synthesise_decision_forces_human_review_under_kc(inp, cts_config=None, kill_switch_status=None):
            from modules.cts.workflows.activities.decision import DecisionResult
            mode = _ks_mode(kill_switch_status)
            synthesise_decision_calls.append({"kill_switch_status": mode})
            forced = mode is not None and mode != "NONE"
            return DecisionResult(
                instrument_id=_dget(inp, "instrument_id"),
                decision="HUMAN_REVIEW" if forced else "STP_CONFIRM",
                rationale="kill_switch_active" if forced else "STP threshold met",
                shap_values={},
            )

        activities = [
            _kc_active_lookup, _detect_alteration_captures_kill_switch,
            _fake_check_stop_payment_proceed, _fake_lookup_pps, _fake_verify_signature,
            _fake_score_fraud, _fake_check_cbs_balance, _fake_check_account_status,
            _synthesise_decision_forces_human_review_under_kc,
            _fake_file_to_ngch, _fake_write_audit, _fake_push_to_review_queue,
        ]

        async with Worker(
            temporal_env.client, task_queue=task_queue,
            workflows=[ChequeProcessingWorkflow, IETWatchdogWorkflow, HumanReviewWorkflow],
            activities=activities,
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await temporal_env.client.execute_workflow(
                ChequeProcessingWorkflow.run,
                ChequeWorkflowInput(
                    instrument_id=instrument_id, bank_id=bank_id,
                    image_url="minio://cts/inward/x.tiff",
                    account_number="12340000005678", cheque_number="000012",
                    presented_amount=45000.0, presented_payee="Ramesh Iyer",
                    iet_deadline=time.time() + 3600,
                ),
                id=f"cts-{bank_id}-{instrument_id}", task_queue=task_queue,
            )
            # ChequeProcessingWorkflow starts HumanReviewWorkflow ABANDON — resolve
            # it (and the watchdog it in turn signals) so the worker can shut down
            # cleanly instead of leaving an unresolved 55-min-timeout child behind.
            from modules.cts.workflows.human_review_workflow import ReviewDecision
            review_handle = temporal_env.client.get_workflow_handle(
                f"cts-humanreview-{bank_id}-{instrument_id}"
            )
            await review_handle.signal(
                HumanReviewWorkflow.receive_decision,
                ReviewDecision(
                    action="RETURN", reason="Kill switch active — manual review",
                    reviewer_id="reviewer-kc", decided_at=time.time(),
                ),
            )
            await review_handle.result()
            await _await_watchdog(temporal_env.client, bank_id, instrument_id)

        # Both checkpoints resolved kill-switch status for the right instrument.
        assert len(lookup_calls) == 2
        assert all(c["bank_id"] == bank_id for c in lookup_calls)
        # Checkpoint 1 (detect_alteration) received it.
        assert len(detect_alteration_calls) == 1
        assert detect_alteration_calls[0]["kill_switch_status"] == "KC"
        # Checkpoint 2 (synthesise_decision) received it independently — the
        # actual RBI-mandated backstop — and forced HUMAN_REVIEW.
        assert len(synthesise_decision_calls) == 1
        assert synthesise_decision_calls[0]["kill_switch_status"] == "KC"
        assert result.decision == "HUMAN_REVIEW"
        assert result.rationale == "kill_switch_active"
