"""
Tests for modules/msv/workflows/activities/orchestrate.py.

Covers:
  - Happy path: orchestrator returns GREEN output
  - Graceful degradation: orchestrator=None → AMBER + ORCHESTRATOR_UNAVAILABLE
  - Graceful degradation: orchestrator raises → re-raises for Temporal retry
  - @activity.defn is present (name="orchestrate_msv_validation")
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

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
from modules.msv.workflows.msv_workflow import MSVWorkflowInput
from modules.msv.workflows.activities.orchestrate import orchestrate_msv_validation


def _make_input() -> MSVWorkflowInput:
    return MSVWorkflowInput(
        msv_input=MSVInput(
            instrument_id="CHQ-ORCH-001",
            bank_id="kotak-mah",
            account_number="9876543210",
            cheque_image_url="minio://bucket/chq.jpg",
        ),
        account_meta=AccountMandateMeta(
            account_hash="hash_xyz",
            bank_id="kotak-mah",
            operation_type="J",
            mandate=MandateRule(rule_type=MandateRuleType.ALL_OF),
            signatories=[
                SignatoryRecord(
                    signatory_id="sig-001",
                    role="Director",
                    name_masked="A***",
                    specimen_count=1,
                    embeddings=[[0.1] * 512],
                )
            ],
        ),
    )


def _green_output() -> MSVOutput:
    return MSVOutput(
        outcome=MSVOutcome.GREEN,
        confidence=0.95,
        reason_code="ALL_MATCHED",
        reason_message="All signatories matched.",
        matched_signatories=[
            MatchedSignatory(
                signatory_id="sig-001",
                role="Director",
                name_masked="A***",
                best_score=0.95,
                specimen_idx=0,
            )
        ],
        detected_sig_count=1,
        mandate_rule_type="ALL_OF",
    )


class TestOrchestrateActivity:
    def test_activity_defn_name(self):
        """@activity.defn must register the correct name for Temporal dispatch."""
        # Use getattr() to avoid Python's double-underscore name-mangling inside a class.
        defn = getattr(orchestrate_msv_validation, "__temporal_activity_definition")
        assert defn is not None
        assert defn.name == "orchestrate_msv_validation"

    @pytest.mark.asyncio
    async def test_happy_path_returns_output(self):
        """When orchestrator is provided, its result is returned as-is."""
        inp = _make_input()
        orchestrator = MagicMock()
        orchestrator.validate = AsyncMock(return_value=_green_output())

        result = await orchestrate_msv_validation(inp, orchestrator=orchestrator)

        assert result.outcome == MSVOutcome.GREEN
        assert result.confidence == 0.95
        orchestrator.validate.assert_awaited_once_with(inp.msv_input, inp.account_meta)

    @pytest.mark.asyncio
    async def test_none_orchestrator_returns_amber(self):
        """orchestrator=None → AMBER + ORCHESTRATOR_UNAVAILABLE (graceful degradation)."""
        inp = _make_input()
        result = await orchestrate_msv_validation(inp, orchestrator=None)

        assert result.outcome == MSVOutcome.AMBER
        assert result.reason_code == "ORCHESTRATOR_UNAVAILABLE"
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_orchestrator_exception_reraises(self):
        """Orchestrator failure re-raises so Temporal retries with MSV_ACTIVITY_RETRY."""
        inp = _make_input()
        orchestrator = MagicMock()
        orchestrator.validate = AsyncMock(side_effect=RuntimeError("detector crashed"))

        with pytest.raises(RuntimeError, match="detector crashed"):
            await orchestrate_msv_validation(inp, orchestrator=orchestrator)

    @pytest.mark.asyncio
    async def test_amber_output_passes_through(self):
        """AMBER from orchestrator (e.g. no enrolled signatories) passes through unchanged."""
        inp = _make_input()
        amber = MSVOutput(
            outcome=MSVOutcome.AMBER,
            confidence=0.0,
            reason_code="NO_SIGNATORIES_ENROLLED",
            reason_message="No enrolled signatories.",
            matched_signatories=[],
            detected_sig_count=1,
            mandate_rule_type="ALL_OF",
        )
        orchestrator = MagicMock()
        orchestrator.validate = AsyncMock(return_value=amber)

        result = await orchestrate_msv_validation(inp, orchestrator=orchestrator)

        assert result.outcome == MSVOutcome.AMBER
        assert result.reason_code == "NO_SIGNATORIES_ENROLLED"
