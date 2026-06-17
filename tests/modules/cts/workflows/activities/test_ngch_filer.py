"""
Tests for modules/cts/workflows/activities/ngch_filer.py

The ONLY place in the entire codebase that may call NGCHAdapter.file_decision().
Enforces exactly-once via idempotency key (workflow_id).
Emits audit event to Kafka after every filing.
"""
from unittest.mock import AsyncMock, MagicMock
import pytest


def _make_input(
    instrument_id="INST001",
    bank_id="test-bank",
    workflow_id="cts-test-bank-INST001",
    decision="CONFIRM",
):
    from modules.cts.workflows.activities.ngch_filer import NGCHFilerInput
    return NGCHFilerInput(
        instrument_id=instrument_id,
        bank_id=bank_id,
        workflow_id=workflow_id,
        decision=decision,
    )


class TestNGCHFilerInput:
    def test_requires_instrument_id(self):
        from modules.cts.workflows.activities.ngch_filer import NGCHFilerInput
        with pytest.raises(Exception):
            NGCHFilerInput(bank_id="b", workflow_id="wf-1", decision="CONFIRM")

    def test_only_accepts_confirm_or_return(self):
        from modules.cts.workflows.activities.ngch_filer import NGCHFilerInput
        with pytest.raises(Exception):
            NGCHFilerInput(instrument_id="I", bank_id="b", workflow_id="wf-1", decision="APPROVE")

    def test_accepts_confirm(self):
        from modules.cts.workflows.activities.ngch_filer import NGCHFilerInput
        inp = NGCHFilerInput(instrument_id="I", bank_id="b", workflow_id="wf-1", decision="CONFIRM")
        assert inp.decision == "CONFIRM"

    def test_accepts_return(self):
        from modules.cts.workflows.activities.ngch_filer import NGCHFilerInput
        inp = NGCHFilerInput(instrument_id="I", bank_id="b", workflow_id="wf-1", decision="RETURN")
        assert inp.decision == "RETURN"

    def test_is_frozen(self):
        inp = _make_input()
        with pytest.raises(Exception):
            inp.decision = "RETURN"


class TestNGCHFilerHappyPath:
    @pytest.mark.asyncio
    async def test_calls_ngch_adapter_file_decision(self):
        from modules.cts.workflows.activities.ngch_filer import file_to_ngch

        mock_adapter = AsyncMock()
        mock_adapter.file_decision = AsyncMock(
            return_value={"acknowledgement_id": "ACK001", "status": "ACCEPTED"}
        )
        mock_producer = AsyncMock()
        mock_producer.publish = AsyncMock()

        await file_to_ngch(_make_input(), ngch_adapter=mock_adapter, event_producer=mock_producer)
        mock_adapter.file_decision.assert_called_once()

    @pytest.mark.asyncio
    async def test_passes_workflow_id_as_idempotency_key(self):
        from modules.cts.workflows.activities.ngch_filer import file_to_ngch

        mock_adapter = AsyncMock()
        mock_adapter.file_decision = AsyncMock(
            return_value={"acknowledgement_id": "ACK001", "status": "ACCEPTED"}
        )
        mock_producer = AsyncMock()
        mock_producer.publish = AsyncMock()

        await file_to_ngch(
            _make_input(workflow_id="cts-bank-INST999"),
            ngch_adapter=mock_adapter,
            event_producer=mock_producer,
        )
        call_kwargs = mock_adapter.file_decision.call_args
        assert "cts-bank-INST999" in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_publishes_audit_event_after_filing(self):
        """Audit event must be published after every NGCH filing."""
        from modules.cts.workflows.activities.ngch_filer import file_to_ngch

        mock_adapter = AsyncMock()
        mock_adapter.file_decision = AsyncMock(
            return_value={"acknowledgement_id": "ACK001", "status": "ACCEPTED"}
        )
        mock_producer = AsyncMock()
        mock_producer.publish = AsyncMock()

        await file_to_ngch(_make_input(), ngch_adapter=mock_adapter, event_producer=mock_producer)
        mock_producer.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_audit_event_topic_is_cts_decisions(self):
        from modules.cts.workflows.activities.ngch_filer import file_to_ngch

        mock_adapter = AsyncMock()
        mock_adapter.file_decision = AsyncMock(
            return_value={"acknowledgement_id": "ACK001", "status": "ACCEPTED"}
        )
        mock_producer = AsyncMock()
        mock_producer.publish = AsyncMock()

        await file_to_ngch(_make_input(bank_id="kotak"), ngch_adapter=mock_adapter, event_producer=mock_producer)
        topic = mock_producer.publish.call_args[1].get("topic") or mock_producer.publish.call_args[0][0]
        assert "cts" in topic

    @pytest.mark.asyncio
    async def test_returns_filing_result(self):
        from modules.cts.workflows.activities.ngch_filer import file_to_ngch

        mock_adapter = AsyncMock()
        mock_adapter.file_decision = AsyncMock(
            return_value={"acknowledgement_id": "ACK999", "status": "ACCEPTED"}
        )
        mock_producer = AsyncMock()
        mock_producer.publish = AsyncMock()

        result = await file_to_ngch(_make_input(), ngch_adapter=mock_adapter, event_producer=mock_producer)
        assert result.acknowledgement_id == "ACK999"


class TestNGCHFilerDuplicateFiling:
    @pytest.mark.asyncio
    async def test_duplicate_filing_raises_duplicate_error(self):
        """Temporal retry should see DuplicateFilingError and not retry again."""
        from modules.cts.workflows.activities.ngch_filer import file_to_ngch
        from modules.cts.mcp.ngch_adapter import DuplicateFilingError

        mock_adapter = AsyncMock()
        mock_adapter.file_decision = AsyncMock(side_effect=DuplicateFilingError("already filed"))
        mock_producer = AsyncMock()

        with pytest.raises(DuplicateFilingError):
            await file_to_ngch(_make_input(), ngch_adapter=mock_adapter, event_producer=mock_producer)

    @pytest.mark.asyncio
    async def test_duplicate_filing_does_not_publish_audit_event(self):
        """Don't double-count filings in audit trail."""
        from modules.cts.workflows.activities.ngch_filer import file_to_ngch
        from modules.cts.mcp.ngch_adapter import DuplicateFilingError

        mock_adapter = AsyncMock()
        mock_adapter.file_decision = AsyncMock(side_effect=DuplicateFilingError("already filed"))
        mock_producer = AsyncMock()
        mock_producer.publish = AsyncMock()

        try:
            await file_to_ngch(_make_input(), ngch_adapter=mock_adapter, event_producer=mock_producer)
        except DuplicateFilingError:
            pass

        mock_producer.publish.assert_not_called()


class TestNGCHFilerNetworkError:
    @pytest.mark.asyncio
    async def test_ngch_unavailable_raises_to_temporal(self):
        """NGCHUnavailableError propagates — Temporal retries with backoff."""
        from modules.cts.workflows.activities.ngch_filer import file_to_ngch
        from modules.cts.mcp.ngch_adapter import NGCHUnavailableError

        mock_adapter = AsyncMock()
        mock_adapter.file_decision = AsyncMock(side_effect=NGCHUnavailableError("NGCH down"))
        mock_producer = AsyncMock()

        with pytest.raises(NGCHUnavailableError):
            await file_to_ngch(_make_input(), ngch_adapter=mock_adapter, event_producer=mock_producer)
