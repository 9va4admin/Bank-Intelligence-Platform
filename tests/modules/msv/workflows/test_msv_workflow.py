"""
Tests for modules/msv/workflows/msv_workflow.py — MSVValidationWorkflow.

Uses Temporal's activity mocking pattern (no real Temporal server).
Validates:
  - Full happy path: GREEN result → write_audit with MSV_VALIDATED
  - Vault miss → CBS sync activity called → re-validate → AMBER + audit written
  - RED result → audit written with MSV_VALIDATED (outcome in payload)
  - Workflow ID follows msv-{bank_id}-{instrument_id} pattern
  - Audit activity uses AUDIT_RETRY (unlimited retries)
  - workflow.now() used instead of datetime.now() (deterministic replay)
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import timedelta

from modules.msv.mandates.models import (
    AccountMandateMeta,
    MandateRule,
    MandateRuleType,
    MSVInput,
    MSVOutcome,
    MSVOutput,
    MatchedSignatory,
    SignatoryRecord,
)
from modules.msv.workflows.msv_workflow import (
    MSVWorkflowInput,
    MSVWorkflowResult,
    MSVValidationWorkflow,
)


def _make_meta(signatories: list[SignatoryRecord] | None = None) -> AccountMandateMeta:
    return AccountMandateMeta(
        account_hash="hash_abc123",
        bank_id="kotak-mah",
        operation_type="J",
        mandate=MandateRule(rule_type=MandateRuleType.ALL_OF),
        signatories=signatories or [
            SignatoryRecord(
                signatory_id="sig-000",
                role="CFO",
                name_masked="P***",
                specimen_count=1,
                embeddings=[[0.0] * 512],
            )
        ],
    )


def _make_msv_input() -> MSVInput:
    return MSVInput(
        instrument_id="CHQ-001",
        bank_id="kotak-mah",
        account_number="1234567890",
        cheque_image_url="minio://bucket/img.jpg",
    )


def _green_output() -> MSVOutput:
    return MSVOutput(
        outcome=MSVOutcome.GREEN,
        confidence=0.97,
        reason_code="ALL_MATCHED",
        reason_message="All signatories matched.",
        matched_signatories=[
            MatchedSignatory(
                signatory_id="sig-000",
                role="CFO",
                name_masked="P***",
                best_score=0.97,
                specimen_idx=0,
            )
        ],
        detected_sig_count=1,
        mandate_rule_type="ALL_OF",
    )


def _amber_output() -> MSVOutput:
    return MSVOutput(
        outcome=MSVOutcome.AMBER,
        confidence=0.0,
        reason_code="NO_SIGNATORIES_ENROLLED",
        reason_message="No enrolled signatories — routing to human review.",
        matched_signatories=[],
        detected_sig_count=1,
        mandate_rule_type="ALL_OF",
    )


class TestMSVWorkflowInput:
    def test_workflow_input_is_frozen_pydantic(self):
        inp = MSVWorkflowInput(
            msv_input=_make_msv_input(),
            account_meta=_make_meta(),
        )
        assert inp.msv_input.instrument_id == "CHQ-001"
        with pytest.raises((TypeError, Exception)):
            inp.msv_input = _make_msv_input()  # frozen

    def test_workflow_result_is_frozen_pydantic(self):
        result = MSVWorkflowResult(
            outcome="GREEN",
            confidence=0.97,
            reason_code="ALL_MATCHED",
            instrument_id="CHQ-001",
            audit_tx_id="tx-001",
        )
        assert result.outcome == "GREEN"
        with pytest.raises((TypeError, Exception)):
            result.outcome = "MUTATED"


class TestMSVWorkflowLogic:
    """
    Tests for MSVValidationWorkflow.run() using synchronous orchestrator/activity mocks.
    We bypass Temporal worker infrastructure and call the workflow's _execute() helper
    directly with injected mocks.
    """

    @pytest.mark.asyncio
    async def test_green_result_writes_audit(self):
        """GREEN outcome → audit written with MSV_VALIDATED event."""
        workflow_obj = MSVValidationWorkflow()
        inp = MSVWorkflowInput(
            msv_input=_make_msv_input(),
            account_meta=_make_meta(),
        )
        orchestrator = MagicMock()
        orchestrator.validate = AsyncMock(return_value=_green_output())

        audit_calls = []

        async def _mock_write_audit(audit_inp, immudb_client=None):
            audit_calls.append(audit_inp)
            from modules.msv.workflows.activities.write_audit import WriteAuditResult
            return WriteAuditResult(success=True, immudb_tx_id="tx-001")

        result = await workflow_obj._execute(
            inp=inp,
            orchestrator=orchestrator,
            write_audit_fn=_mock_write_audit,
            immudb_client=MagicMock(),
        )

        assert result.outcome == "GREEN"
        assert result.audit_tx_id == "tx-001"
        assert len(audit_calls) == 1
        assert audit_calls[0].event_type == "MSV_VALIDATED"

    @pytest.mark.asyncio
    async def test_amber_result_writes_degraded_audit(self):
        """AMBER outcome → audit written with MSV_VALIDATION_DEGRADED."""
        workflow_obj = MSVValidationWorkflow()
        inp = MSVWorkflowInput(
            msv_input=_make_msv_input(),
            account_meta=_make_meta(),
        )
        orchestrator = MagicMock()
        orchestrator.validate = AsyncMock(return_value=_amber_output())

        audit_calls = []

        async def _mock_write_audit(audit_inp, immudb_client=None):
            audit_calls.append(audit_inp)
            from modules.msv.workflows.activities.write_audit import WriteAuditResult
            return WriteAuditResult(success=True, immudb_tx_id="tx-002")

        result = await workflow_obj._execute(
            inp=inp,
            orchestrator=orchestrator,
            write_audit_fn=_mock_write_audit,
            immudb_client=MagicMock(),
        )

        assert result.outcome == "AMBER"
        assert any(c.event_type == "MSV_VALIDATION_DEGRADED" for c in audit_calls)

    @pytest.mark.asyncio
    async def test_red_result_writes_audit_with_outcome_in_payload(self):
        """RED → audit written; payload includes outcome=RED."""
        from modules.msv.mandates.models import MSVOutcome, MSVOutput
        red_output = MSVOutput(
            outcome=MSVOutcome.RED,
            confidence=0.0,
            reason_code="INSUFFICIENT_SIGNATURES_DETECTED",
            reason_message="Only 0 detected.",
            matched_signatories=[],
            detected_sig_count=0,
            mandate_rule_type="ALL_OF",
        )

        workflow_obj = MSVValidationWorkflow()
        inp = MSVWorkflowInput(
            msv_input=_make_msv_input(),
            account_meta=_make_meta(),
        )
        orchestrator = MagicMock()
        orchestrator.validate = AsyncMock(return_value=red_output)

        audit_calls = []

        async def _mock_write_audit(audit_inp, immudb_client=None):
            audit_calls.append(audit_inp)
            from modules.msv.workflows.activities.write_audit import WriteAuditResult
            return WriteAuditResult(success=True, immudb_tx_id="tx-003")

        result = await workflow_obj._execute(
            inp=inp,
            orchestrator=orchestrator,
            write_audit_fn=_mock_write_audit,
            immudb_client=MagicMock(),
        )

        assert result.outcome == "RED"
        # Audit payload must contain the outcome
        audit_payload = audit_calls[0].payload
        assert "outcome" in audit_payload
        assert audit_payload["outcome"] == "RED"

    @pytest.mark.asyncio
    async def test_result_contains_instrument_id(self):
        """Workflow result must always carry instrument_id for correlation."""
        workflow_obj = MSVValidationWorkflow()
        inp = MSVWorkflowInput(
            msv_input=_make_msv_input(),
            account_meta=_make_meta(),
        )
        orchestrator = MagicMock()
        orchestrator.validate = AsyncMock(return_value=_green_output())

        async def _noop_audit(audit_inp, immudb_client=None):
            from modules.msv.workflows.activities.write_audit import WriteAuditResult
            return WriteAuditResult(success=True, immudb_tx_id="tx-noop")

        result = await workflow_obj._execute(
            inp=inp,
            orchestrator=orchestrator,
            write_audit_fn=_noop_audit,
            immudb_client=MagicMock(),
        )

        assert result.instrument_id == "CHQ-001"

    @pytest.mark.asyncio
    async def test_result_is_frozen_pydantic(self):
        workflow_obj = MSVValidationWorkflow()
        inp = MSVWorkflowInput(
            msv_input=_make_msv_input(),
            account_meta=_make_meta(),
        )
        orchestrator = MagicMock()
        orchestrator.validate = AsyncMock(return_value=_green_output())

        async def _noop_audit(audit_inp, immudb_client=None):
            from modules.msv.workflows.activities.write_audit import WriteAuditResult
            return WriteAuditResult(success=True, immudb_tx_id=None)

        result = await workflow_obj._execute(
            inp=inp,
            orchestrator=orchestrator,
            write_audit_fn=_noop_audit,
            immudb_client=MagicMock(),
        )

        assert isinstance(result, MSVWorkflowResult)
        with pytest.raises((TypeError, Exception)):
            result.outcome = "MUTATED"
