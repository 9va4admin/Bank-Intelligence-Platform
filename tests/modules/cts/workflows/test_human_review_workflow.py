"""Tests for HumanReviewWorkflow — signal path, timeout, audit, NGCH filing."""
import time
import pytest
from unittest.mock import AsyncMock, MagicMock

from modules.cts.workflows.human_review_workflow import (
    HumanReviewInput,
    HumanReviewWorkflow,
    HumanReviewResult,
    ReviewDecision,
    push_to_review_queue,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_input(**kwargs):
    defaults = dict(
        instrument_id="CHQ-TEST-001",
        bank_id="test-bank",
        workflow_id="cts-test-bank-CHQ-TEST-001",
        context_bundle={"fraud_score": 0.85, "ocr_confidence": 0.92},
        iet_deadline=time.time() + 3600,
    )
    defaults.update(kwargs)
    return HumanReviewInput(**defaults)


def _make_decision(action="CONFIRM"):
    return ReviewDecision(
        action=action,
        reason="Verified with branch manager",
        reviewer_id="reviewer-001",
        decided_at=time.time(),
    )


def _make_ngch():
    ngch = AsyncMock()
    ngch.file_decision.return_value = {"acknowledgement_id": "ACK-001", "status": "FILED"}
    return ngch


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------

class TestHumanReviewInput:
    def test_requires_instrument_id(self):
        with pytest.raises(Exception):
            HumanReviewInput(bank_id="b", workflow_id="w",
                             context_bundle={}, iet_deadline=1.0)

    def test_is_frozen(self):
        inp = _make_input()
        with pytest.raises(Exception):
            inp.instrument_id = "other"

    def test_workflow_id_pattern(self):
        wf = HumanReviewWorkflow()
        wid = wf.workflow_id("test-bank", "CHQ-001")
        assert wid == "cts-humanreview-test-bank-CHQ-001"

    def test_workflow_id_unique_per_instrument(self):
        wf = HumanReviewWorkflow()
        assert wf.workflow_id("bank", "A") != wf.workflow_id("bank", "B")


# ---------------------------------------------------------------------------
# push_to_review_queue
# ---------------------------------------------------------------------------

class TestPushToReviewQueue:
    @pytest.mark.asyncio
    async def test_publishes_to_correct_topic(self):
        producer = AsyncMock()
        await push_to_review_queue(_make_input(), event_producer=producer)
        topic = producer.publish.call_args.kwargs["topic"]
        assert topic == "cts.human.review.test-bank"

    @pytest.mark.asyncio
    async def test_publishes_instrument_id(self):
        producer = AsyncMock()
        await push_to_review_queue(_make_input(instrument_id="CHQ-XYZ"), event_producer=producer)
        payload = producer.publish.call_args.kwargs["payload"]
        assert payload["instrument_id"] == "CHQ-XYZ"

    @pytest.mark.asyncio
    async def test_publishes_schema_version(self):
        producer = AsyncMock()
        await push_to_review_queue(_make_input(), event_producer=producer)
        assert producer.publish.call_args.kwargs["schema_version"] == "1.0"


# ---------------------------------------------------------------------------
# Signal path — reviewer confirms
# ---------------------------------------------------------------------------

class TestReviewerConfirms:
    @pytest.mark.asyncio
    async def test_outcome_reviewer_confirmed(self):
        wf = HumanReviewWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            event_producer=AsyncMock(),
            ngch_adapter=_make_ngch(),
            injected_decision=_make_decision("CONFIRM"),
        )
        assert result.outcome == "REVIEWER_CONFIRMED"

    @pytest.mark.asyncio
    async def test_filed_decision_is_confirm(self):
        wf = HumanReviewWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            event_producer=AsyncMock(),
            ngch_adapter=_make_ngch(),
            injected_decision=_make_decision("CONFIRM"),
        )
        assert result.filed_decision == "CONFIRM"

    @pytest.mark.asyncio
    async def test_not_timed_out(self):
        wf = HumanReviewWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            event_producer=AsyncMock(),
            ngch_adapter=_make_ngch(),
            injected_decision=_make_decision("CONFIRM"),
        )
        assert result.timed_out is False

    @pytest.mark.asyncio
    async def test_reviewer_id_in_result(self):
        wf = HumanReviewWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            event_producer=AsyncMock(),
            ngch_adapter=_make_ngch(),
            injected_decision=_make_decision("CONFIRM"),
        )
        assert result.reviewer_id == "reviewer-001"

    @pytest.mark.asyncio
    async def test_files_to_ngch(self):
        ngch = _make_ngch()
        wf = HumanReviewWorkflow()
        await wf.run_with_mocks(
            _make_input(),
            event_producer=AsyncMock(),
            ngch_adapter=ngch,
            injected_decision=_make_decision("CONFIRM"),
        )
        ngch.file_decision.assert_called_once()
        _, kwargs = ngch.file_decision.call_args
        assert kwargs["decision"] == "CONFIRM"


# ---------------------------------------------------------------------------
# Signal path — reviewer returns
# ---------------------------------------------------------------------------

class TestReviewerReturns:
    @pytest.mark.asyncio
    async def test_outcome_reviewer_returned(self):
        wf = HumanReviewWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            event_producer=AsyncMock(),
            ngch_adapter=_make_ngch(),
            injected_decision=_make_decision("RETURN"),
        )
        assert result.outcome == "REVIEWER_RETURNED"

    @pytest.mark.asyncio
    async def test_filed_decision_is_return(self):
        wf = HumanReviewWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            event_producer=AsyncMock(),
            ngch_adapter=_make_ngch(),
            injected_decision=_make_decision("RETURN"),
        )
        assert result.filed_decision == "RETURN"


# ---------------------------------------------------------------------------
# Timeout path
# ---------------------------------------------------------------------------

class TestReviewTimeout:
    @pytest.mark.asyncio
    async def test_outcome_timeout_auto_returned(self):
        wf = HumanReviewWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            event_producer=AsyncMock(),
            ngch_adapter=_make_ngch(),
            simulate_timeout=True,
        )
        assert result.outcome == "TIMEOUT_AUTO_RETURNED"

    @pytest.mark.asyncio
    async def test_timed_out_flag_set(self):
        wf = HumanReviewWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            event_producer=AsyncMock(),
            ngch_adapter=_make_ngch(),
            simulate_timeout=True,
        )
        assert result.timed_out is True

    @pytest.mark.asyncio
    async def test_timeout_files_return_to_ngch(self):
        ngch = _make_ngch()
        wf = HumanReviewWorkflow()
        await wf.run_with_mocks(
            _make_input(),
            event_producer=AsyncMock(),
            ngch_adapter=ngch,
            simulate_timeout=True,
        )
        _, kwargs = ngch.file_decision.call_args
        assert kwargs["decision"] == "RETURN"

    @pytest.mark.asyncio
    async def test_timeout_reason_set(self):
        wf = HumanReviewWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            event_producer=AsyncMock(),
            ngch_adapter=_make_ngch(),
            simulate_timeout=True,
        )
        assert "timeout" in result.reason

    @pytest.mark.asyncio
    async def test_timeout_reviewer_id_is_none(self):
        wf = HumanReviewWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            event_producer=AsyncMock(),
            ngch_adapter=_make_ngch(),
            simulate_timeout=True,
        )
        assert result.reviewer_id is None


# ---------------------------------------------------------------------------
# Audit write
# ---------------------------------------------------------------------------

class TestAuditWrite:
    @pytest.mark.asyncio
    async def test_audit_written_on_confirm(self):
        audit = AsyncMock()
        wf = HumanReviewWorkflow()
        await wf.run_with_mocks(
            _make_input(),
            event_producer=AsyncMock(),
            ngch_adapter=_make_ngch(),
            audit_writer=audit,
            injected_decision=_make_decision("CONFIRM"),
        )
        audit.write.assert_called_once()
        kwargs = audit.write.call_args.kwargs
        assert kwargs["event_type"] == "CTS_HUMAN_REVIEW_DECIDED"

    @pytest.mark.asyncio
    async def test_audit_written_on_timeout(self):
        audit = AsyncMock()
        wf = HumanReviewWorkflow()
        await wf.run_with_mocks(
            _make_input(),
            event_producer=AsyncMock(),
            ngch_adapter=_make_ngch(),
            audit_writer=audit,
            simulate_timeout=True,
        )
        audit.write.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_audit_writer_does_not_crash(self):
        wf = HumanReviewWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            event_producer=AsyncMock(),
            ngch_adapter=_make_ngch(),
            audit_writer=None,
            injected_decision=_make_decision("CONFIRM"),
        )
        assert result.outcome == "REVIEWER_CONFIRMED"


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

class TestHumanReviewResult:
    def test_result_is_frozen(self):
        r = HumanReviewResult(
            instrument_id="X", outcome="REVIEWER_CONFIRMED",
            filed_decision="CONFIRM", acknowledgement_id="ACK",
        )
        with pytest.raises(Exception):
            r.outcome = "other"

    def test_result_has_instrument_id(self):
        r = HumanReviewResult(
            instrument_id="CHQ-001", outcome="REVIEWER_RETURNED",
            filed_decision="RETURN", acknowledgement_id="ACK",
        )
        assert r.instrument_id == "CHQ-001"


class TestHumanReviewMissingBranches:
    def test_receive_decision_sets_internal_state(self):
        """Covers line 105: receive_decision() signal handler stores the decision."""
        from modules.cts.workflows.human_review_workflow import HumanReviewWorkflow, ReviewDecision
        wf = HumanReviewWorkflow()
        decision = ReviewDecision(action="CONFIRM", reason="looks fine", reviewer_id="rev-001", decided_at=1234567890.0)
        wf.receive_decision(decision)
        assert wf._decision is decision

    @pytest.mark.asyncio
    async def test_no_injected_decision_no_timeout_falls_through(self):
        """Covers line 134: else branch — no injected decision and not simulating timeout."""
        from modules.cts.workflows.human_review_workflow import HumanReviewWorkflow
        from unittest.mock import AsyncMock

        wf = HumanReviewWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            event_producer=AsyncMock(),
            ngch_adapter=_make_ngch(),
            injected_decision=None,
            simulate_timeout=False,
        )
        # No decision → treated as timeout path (_decision=None)
        assert result.outcome == "TIMEOUT_AUTO_RETURNED"
