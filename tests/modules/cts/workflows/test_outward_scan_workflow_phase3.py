"""
Phase 3 tests for OutwardScanWorkflow — PU context + Vision LLM last step + mismatch.

These tests extend the original test_outward_scan_workflow.py without modifying it.
New fields: pu_id in OutwardScanInput and OutwardScanResult.
New step: vision_llm runs AFTER lot assignment (last step before audit).
New outcome: MISMATCH_HELD when Vision LLM disagrees with scanner.
New: when mismatch, MismatchResolutionWorkflow is referenced by result.
"""
import pytest
from unittest.mock import MagicMock


def _make_p3_input(**kwargs):
    from modules.cts.workflows.outward_scan_workflow import OutwardScanInput
    defaults = dict(
        scan_id="SCAN-P3-001",
        instrument_id="OUT-INST-P3-001",
        bank_id="saraswat-coop",
        bank_ifsc="SVCB0000001",
        session_id="SES-0704-001",
        image_front_url="minio://cts/front/SCAN-P3-001.tiff",
        image_rear_url="minio://cts/rear/SCAN-P3-001.tiff",
        pu_id="MUMBAI-MAIN",
        branch_id="BRANCH-ANDHERI-01",
    )
    defaults.update(kwargs)
    return OutwardScanInput(**defaults)


def _make_p3_mocks(
    compliance_ok=True,
    lot_number="LOT-0007",
    vision_match=True,
    vision_mismatch_fields=None,
):
    """Build the Phase 3 mock_results dict with vision_llm entry."""
    vision_mock = MagicMock()
    if vision_match:
        vision_mock.has_mismatch = False
        vision_mock.mismatch_fields = []
        vision_mock.vision_amount_str = "45000.00"
    else:
        vision_mock.has_mismatch = True
        vision_mock.mismatch_fields = vision_mismatch_fields or ["amount_figures"]
        vision_mock.vision_amount_str = "4500.00"

    return {
        "micr": MagicMock(micr_line="123456789", confidence=0.98),
        "compliance": MagicMock(is_compliant=compliance_ok, violations=[]),
        "lot": MagicMock(lot_number=lot_number),
        "vision_llm": vision_mock,
        "audit": MagicMock(audit_event_id="AUD-P3"),
    }


class TestOutwardScanP3Input:
    def test_pu_id_field_accepted(self):
        inp = _make_p3_input()
        assert inp.pu_id == "MUMBAI-MAIN"

    def test_branch_id_field_accepted(self):
        inp = _make_p3_input()
        assert inp.branch_id == "BRANCH-ANDHERI-01"

    def test_pu_id_in_workflow_id(self):
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        wid = wf.workflow_id("saraswat-coop", "SCAN-001", pu_id="MUMBAI-MAIN")
        assert "MUMBAI-MAIN" in wid

    def test_workflow_id_with_pu_format(self):
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        wid = wf.workflow_id("bank-a", "SCAN-001", pu_id="PU-X")
        assert wid == "cts-outscan-bank-a-PU-X-SCAN-001"

    def test_workflow_id_without_pu_backward_compat(self):
        """Calling workflow_id without pu_id still works (backward compat)."""
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        wid = wf.workflow_id("bank-a", "SCAN-001")
        assert "bank-a" in wid
        assert "SCAN-001" in wid


class TestOutwardScanP3VisionMatch:
    @pytest.mark.asyncio
    async def test_vision_match_produces_accepted(self):
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        result = await wf.run_with_mocks(
            _make_p3_input(),
            mock_results=_make_p3_mocks(vision_match=True),
        )
        assert result.outcome == "ACCEPTED"

    @pytest.mark.asyncio
    async def test_pu_id_in_result(self):
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        result = await wf.run_with_mocks(
            _make_p3_input(pu_id="DELHI-MAIN"),
            mock_results=_make_p3_mocks(vision_match=True),
        )
        assert result.pu_id == "DELHI-MAIN"

    @pytest.mark.asyncio
    async def test_audit_written_on_vision_match_accepted(self):
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        result = await wf.run_with_mocks(
            _make_p3_input(),
            mock_results=_make_p3_mocks(vision_match=True),
        )
        assert result.audit_written is True


class TestOutwardScanP3VisionMismatch:
    @pytest.mark.asyncio
    async def test_vision_mismatch_produces_mismatch_held(self):
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        result = await wf.run_with_mocks(
            _make_p3_input(),
            mock_results=_make_p3_mocks(vision_match=False, vision_mismatch_fields=["amount_figures"]),
        )
        assert result.outcome == "MISMATCH_HELD"

    @pytest.mark.asyncio
    async def test_mismatch_result_has_mismatch_id(self):
        """MISMATCH_HELD result must include the mismatch_id used to spawn child workflow."""
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        result = await wf.run_with_mocks(
            _make_p3_input(),
            mock_results=_make_p3_mocks(vision_match=False),
        )
        assert result.mismatch_id is not None
        assert len(result.mismatch_id) > 0

    @pytest.mark.asyncio
    async def test_mismatch_id_is_deterministic_from_scan_id(self):
        """Same scan_id → same mismatch_id (idempotent child workflow spawn)."""
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        result1 = await wf.run_with_mocks(
            _make_p3_input(scan_id="SCAN-123"),
            mock_results=_make_p3_mocks(vision_match=False),
        )
        result2 = await wf.run_with_mocks(
            _make_p3_input(scan_id="SCAN-123"),
            mock_results=_make_p3_mocks(vision_match=False),
        )
        assert result1.mismatch_id == result2.mismatch_id

    @pytest.mark.asyncio
    async def test_mismatch_fields_in_result(self):
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        result = await wf.run_with_mocks(
            _make_p3_input(),
            mock_results=_make_p3_mocks(vision_match=False, vision_mismatch_fields=["amount_figures", "amount_words"]),
        )
        assert result.mismatch_fields == ["amount_figures", "amount_words"]

    @pytest.mark.asyncio
    async def test_lot_number_preserved_on_mismatch(self):
        """Lot assignment happens before vision — lot_number should be in result."""
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        result = await wf.run_with_mocks(
            _make_p3_input(),
            mock_results=_make_p3_mocks(lot_number="LOT-0007", vision_match=False),
        )
        assert result.lot_number == "LOT-0007"

    @pytest.mark.asyncio
    async def test_audit_written_on_mismatch_held(self):
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        result = await wf.run_with_mocks(
            _make_p3_input(),
            mock_results=_make_p3_mocks(vision_match=False),
        )
        assert result.audit_written is True

    @pytest.mark.asyncio
    async def test_cts_rejected_before_lot_skips_vision(self):
        """If CTS-2010 fails, vision LLM is never reached (no vision_llm in mocks needed)."""
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        mocks = _make_p3_mocks(compliance_ok=False)
        mocks["compliance"] = MagicMock(is_compliant=False, violations=["MICR_LINE_MISSING"])
        # Remove vision_llm — if workflow tries to access it, it won't crash with KeyError
        mocks.pop("vision_llm", None)
        result = await wf.run_with_mocks(_make_p3_input(), mock_results=mocks)
        assert result.outcome == "CTS_REJECTED"


class TestOutwardScanP3MismatchIdGeneration:
    def test_generate_mismatch_id_format(self):
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        mid = wf.generate_mismatch_id("saraswat-coop", "SCAN-001")
        assert "saraswat-coop" in mid
        assert "SCAN-001" in mid

    def test_generate_mismatch_id_deterministic(self):
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        mid1 = wf.generate_mismatch_id("bank-a", "SCAN-X")
        mid2 = wf.generate_mismatch_id("bank-a", "SCAN-X")
        assert mid1 == mid2

    def test_generate_mismatch_id_unique_per_scan(self):
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        wf = OutwardScanWorkflow()
        assert (
            wf.generate_mismatch_id("bank-a", "SCAN-1")
            != wf.generate_mismatch_id("bank-a", "SCAN-2")
        )


# ---------------------------------------------------------------------------
# OutwardScanWorkflow.run() — the real @workflow.run, driven through an
# actual Temporal Worker + time-skipping test server. Every test above only
# ever exercised run_with_mocks() (raw dict lookups, no serialization
# boundary, no real activity dispatch at all) — this proves the
# @activity.defn/@workflow.defn decorators and workflow.execute_activity()
# calls added in this fix actually work end to end, including spawning
# MismatchResolutionWorkflow as a real ABANDON child on a Vision mismatch.
# ---------------------------------------------------------------------------

import uuid
from temporalio import activity as _activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker, UnsandboxedWorkflowRunner


def _compliant_input(**overrides):
    from modules.cts.workflows.outward_scan_workflow import OutwardScanInput
    defaults = dict(
        scan_id="SCAN-REAL-001", instrument_id="OUT-REAL-001",
        bank_id="saraswat-coop", bank_ifsc="SVCB0000001", session_id="SES-001",
        image_front_url="minio://cts/front/SCAN-REAL-001.tiff",
        image_rear_url="minio://cts/rear/SCAN-REAL-001.tiff",
        branch_id="BRANCH-01", cheque_number="000123",
        front_dpi=203, rear_dpi=203, front_colour_depth=24, rear_colour_depth=24,
        front_file_size_kb=40.0, rear_file_size_kb=30.0,
    )
    defaults.update(overrides)
    return OutwardScanInput(**defaults)


@_activity.defn(name="ocr_extract")
async def _fake_ocr_matching(inp):
    from modules.cts.workflows.activities.ocr import OCRActivityResult
    return OCRActivityResult(
        outcome="PROCEED", micr_line="123456789", amount_figures="45000.00",
        overall_confidence=0.95, degraded=False,
    )


@_activity.defn(name="ocr_extract")
async def _fake_ocr_low_quality(inp):
    from modules.cts.workflows.activities.ocr import OCRActivityResult
    return OCRActivityResult(
        outcome="PROCEED", micr_line="123456789", amount_figures="45000.00",
        overall_confidence=0.3, degraded=False,
    )


@_activity.defn(name="ocr_extract")
async def _fake_ocr_degraded(inp):
    from modules.cts.workflows.activities.ocr import OCRActivityResult
    return OCRActivityResult(
        outcome="HUMAN_REVIEW", degraded=True, low_confidence_reason="MODEL_UNAVAILABLE",
    )


@_activity.defn(name="validate_cts2010")
async def _fake_validate_pass(inp):
    from modules.cts.workflows.activities.outward_scan_activities import CTS2010ValidationResult
    return CTS2010ValidationResult(is_compliant=True, violations=[])


@_activity.defn(name="create_lot_entry")
async def _fake_lot(inp):
    from modules.cts.workflows.activities.outward_scan_activities import LotAssignmentResult
    return LotAssignmentResult(lot_number="LOT_SVCB0000001_20260714_SES-001_01")


@_activity.defn(name="run_vision_presentment_check")
async def _fake_vision_match(inp):
    from modules.cts.workflows.activities.outward_scan_activities import VisionPresentmentCheckResult
    return VisionPresentmentCheckResult(has_mismatch=False, mismatch_fields=[], vision_amount_str="45000.00")


@_activity.defn(name="run_vision_presentment_check")
async def _fake_vision_mismatch(inp):
    from modules.cts.workflows.activities.outward_scan_activities import VisionPresentmentCheckResult
    return VisionPresentmentCheckResult(
        has_mismatch=True, mismatch_fields=["amount_figures"], vision_amount_str="4500.00",
    )


@_activity.defn(name="write_audit")
async def _fake_write_audit(inp):
    from modules.cts.workflows.activities.write_audit import WriteAuditResult
    return WriteAuditResult(success=True, immudb_tx_id="TEST-TX")


@_activity.defn(name="publish_mismatch_hold")
async def _fake_publish_hold(inp):
    return {"published": True}


def _worker(env, task_queue, ocr_fake, vision_fake, compliance_fake=_fake_validate_pass):
    from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
    from modules.cts.workflows.mismatch_resolution_workflow import MismatchResolutionWorkflow
    return Worker(
        env.client, task_queue=task_queue,
        workflows=[OutwardScanWorkflow, MismatchResolutionWorkflow],
        activities=[
            ocr_fake, compliance_fake, _fake_lot, vision_fake,
            _fake_write_audit, _fake_publish_hold,
        ],
        workflow_runner=UnsandboxedWorkflowRunner(),
    )


class TestOutwardScanWorkflowRealRun:
    @pytest.mark.asyncio
    async def test_real_run_accepted_on_vision_match(self):
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow

        async with await WorkflowEnvironment.start_time_skipping() as env:
            task_queue = f"tq-{uuid.uuid4()}"
            async with _worker(env, task_queue, _fake_ocr_matching, _fake_vision_match):
                result = await env.client.execute_workflow(
                    OutwardScanWorkflow.run,
                    _compliant_input(),
                    id=f"cts-outscan-real-{uuid.uuid4().hex[:8]}",
                    task_queue=task_queue,
                )

        assert result.outcome == "ACCEPTED"
        assert result.micr_line == "123456789"
        assert result.lot_number == "LOT_SVCB0000001_20260714_SES-001_01"
        assert result.audit_written is True

    @pytest.mark.asyncio
    async def test_real_run_cts_rejected_on_missing_metrics(self):
        """Image metrics deliberately omitted from input — validate_cts2010
        (the REAL activity, not a fake) must fail closed, not fabricate a
        pass."""
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        from modules.cts.workflows.activities.outward_scan_activities import (
            validate_cts2010 as real_validate_cts2010,
        )

        async with await WorkflowEnvironment.start_time_skipping() as env:
            task_queue = f"tq-{uuid.uuid4()}"
            async with _worker(
                env, task_queue, _fake_ocr_matching, _fake_vision_match,
                compliance_fake=real_validate_cts2010,
            ):
                result = await env.client.execute_workflow(
                    OutwardScanWorkflow.run,
                    _compliant_input(front_dpi=None),
                    id=f"cts-outscan-real-{uuid.uuid4().hex[:8]}",
                    task_queue=task_queue,
                )

        assert result.outcome == "CTS_REJECTED"
        assert result.violations == ["MISSING_IMAGE_METRICS"]
        assert result.lot_number is None

    @pytest.mark.asyncio
    async def test_real_run_mismatch_held_spawns_child_workflow(self):
        """Vision disagrees with scanner → MISMATCH_HELD, and the child
        MismatchResolutionWorkflow must actually be reachable/resolvable —
        proves the ABANDON child spawn is wired for real, not just a
        log line."""
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        from modules.cts.workflows.mismatch_resolution_workflow import (
            MismatchResolutionWorkflow, MismatchSignal,
        )

        async with await WorkflowEnvironment.start_time_skipping() as env:
            task_queue = f"tq-{uuid.uuid4()}"
            async with _worker(env, task_queue, _fake_ocr_matching, _fake_vision_mismatch):
                result = await env.client.execute_workflow(
                    OutwardScanWorkflow.run,
                    _compliant_input(scan_id="SCAN-MM-01", instrument_id="OUT-MM-01"),
                    id=f"cts-outscan-real-{uuid.uuid4().hex[:8]}",
                    task_queue=task_queue,
                )
                assert result.outcome == "MISMATCH_HELD"
                assert result.mismatch_id is not None

                # Resolve the spawned child directly, proving it's a real,
                # independently-addressable workflow (not just referenced).
                child_id = f"cts-mismatch-saraswat-coop-BRANCH-01-{result.mismatch_id}"
                child_handle = env.client.get_workflow_handle(child_id)
                await child_handle.signal(
                    MismatchResolutionWorkflow.resolve,
                    MismatchSignal(action="GO_AHEAD", resolved_by="op-test"),
                )
                child_result = await child_handle.result()

        # No pydantic converter in this temporalio version (already-documented,
        # pre-existing, project-wide gap — see project memory): a child
        # workflow's result comes back as a plain dict, not the typed
        # MismatchResult, since get_workflow_handle() has no static return
        # type to reconstruct against. Same class of issue, different call
        # site, not something this fix can resolve in isolation.
        outcome = child_result["outcome"] if isinstance(child_result, dict) else child_result.outcome
        assert outcome == "GO_AHEAD"

    @pytest.mark.asyncio
    async def test_real_run_ocr_degraded_fails_closed_not_open(self):
        """A degraded OCR result (model unavailable — the real ocr_extract's
        own graceful-degradation path, already covered by test_ocr.py) must
        flow into validate_cts2010's fail-closed MISSING_IMAGE_METRICS path
        — never a silent ACCEPTED. Uses a fake that reproduces the degraded
        *shape* rather than the real ocr_extract activity: exercising the
        real one here would hit the same pre-existing no-pydantic-converter
        gap as the child-workflow-result case above (unrelated to this
        workflow's own wiring, already tracked separately)."""
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        from modules.cts.workflows.activities.outward_scan_activities import (
            validate_cts2010 as real_validate_cts2010,
        )

        async with await WorkflowEnvironment.start_time_skipping() as env:
            task_queue = f"tq-{uuid.uuid4()}"
            async with _worker(
                env, task_queue, _fake_ocr_degraded, _fake_vision_match,
                compliance_fake=real_validate_cts2010,
            ):
                result = await env.client.execute_workflow(
                    OutwardScanWorkflow.run,
                    _compliant_input(scan_id="SCAN-DEGRADED-01", instrument_id="OUT-DEGRADED-01"),
                    id=f"cts-outscan-real-{uuid.uuid4().hex[:8]}",
                    task_queue=task_queue,
                )

        assert result.outcome == "CTS_REJECTED"
        assert result.violations == ["MISSING_IMAGE_METRICS"]
