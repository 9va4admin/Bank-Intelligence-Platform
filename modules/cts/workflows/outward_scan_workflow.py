"""
OutwardScanWorkflow — CTS Presentee Bank outward clearing.

Orchestrates the scanner → MICR → CTS-2010 compliance → Vision LLM pipeline
for each physical cheque deposited by a customer.

Activity sequence:
  1. capture_image      — scanner adapter captures front + rear TIFF images
  2. extract_micr       — GOT-OCR2.0 extracts MICR line fields (scanner-side, not Vision)
  3. validate_cts2010   — CTS-2010 image compliance check (DPI, size, MICR zone)
  4. vision_llm         — Qwen2-VL sanity check: confirm amount_figures match scanner
                          On MISMATCH → spawns MismatchResolutionWorkflow child (ABANDON policy)
  5. write_audit        — Immudb audit (ALL terminal outcomes)

Lot assignment is NOT performed here. Accepted instruments land in PENDING_LOT state.
Lot grouping happens in ClearingSessionWorkflow when the operator opens a clearing slot
(AM / PM / EVE). A cheque scanned today may be submitted in tomorrow's session if today's
NGCH cutoff has already passed — lot assignment must be clearing-schedule–driven, not
tied to the physical scan event.

Terminal states: ACCEPTED | CTS_REJECTED | MISMATCH_HELD
Workflow ID: cts-outscan-{bank_id}-{pu_id}-{scan_id}  (pu_id optional for backward compat)

Phase 3 note: Vision LLM runs LAST because:
- Presentment: scanner is the authoritative source; Vision is a sanity cross-check.
- Cost: most cheques pass — skip Vision on CTS_REJECTED (no lot needed, no Vision needed).
- Drawee: Vision runs FIRST (different workflow) — trust Vision over scanner on inward side.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.workflow import ParentClosePolicy

log = structlog.get_logger()

_AI_RETRY = RetryPolicy(
    maximum_attempts=2,
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
)
_INFRA_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=1.5,
)
_AUDIT_RETRY = RetryPolicy(
    maximum_attempts=0,   # 0 = unlimited in Temporal Python SDK
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(minutes=5),
)


class OutwardScanInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    scan_id: str
    instrument_id: str
    bank_id: str
    bank_ifsc: str
    session_id: str
    image_front_url: str
    image_rear_url: str
    pu_id: Optional[str] = None         # Phase 3: Processing Unit identifier
    branch_id: Optional[str] = None     # Phase 3: originating branch (EEH session)
    cheque_number: str = ""

    # Image quality metrics — reported by the scanner OEM software / upstream
    # capture pipeline (out of this workflow's scope; see ScanResult in
    # modules/cts/scanner/models.py for the hardware-native equivalents).
    # Optional and additive (non-breaking per api-versioning.md): if absent,
    # validate_cts2010 fails closed rather than fabricating a pass.
    front_dpi: Optional[int] = None
    rear_dpi: Optional[int] = None
    front_colour_depth: Optional[int] = None
    rear_colour_depth: Optional[int] = None
    front_file_size_kb: Optional[float] = None
    rear_file_size_kb: Optional[float] = None

    # CR-120 hardware MICR — when present, triggers the new single-pass
    # vision_extract_and_check path (no GOT-OCR2 call on outward side).
    micr_hardware_raw: Optional[str] = None


class OutwardScanResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str                        # "ACCEPTED" | "CTS_REJECTED" | "MISMATCH_HELD"
    scan_id: str
    bank_id: str
    instrument_id: str
    micr_line: Optional[str] = None
    lot_number: Optional[str] = None
    violations: Optional[list[str]] = None
    audit_written: bool = False
    pu_id: Optional[str] = None         # Phase 3: PU that processed this instrument
    mismatch_id: Optional[str] = None   # Phase 3: set when outcome=MISMATCH_HELD
    mismatch_fields: Optional[list[str]] = None   # Phase 3: fields that mismatched


@workflow.defn
class OutwardScanWorkflow:
    def workflow_id(self, bank_id: str, scan_id: str, pu_id: Optional[str] = None) -> str:
        if pu_id:
            return f"cts-outscan-{bank_id}-{pu_id}-{scan_id}"
        return f"cts-outscan-{bank_id}-{scan_id}"

    def generate_mismatch_id(self, bank_id: str, scan_id: str) -> str:
        """Deterministic mismatch ID — same scan_id always produces same mismatch_id."""
        return f"MM-{bank_id}-{scan_id}"

    @workflow.run
    async def run(self, inp: OutwardScanInput) -> OutwardScanResult:
        """
        Production Temporal @workflow.run entry point.

        capture_image / drop-folder parsing / MinIO upload happen upstream of
        this workflow (see module docstring) — image_front_url/image_rear_url
        already point at uploaded images by the time this runs.
        """
        from modules.cts.workflows.activities.ocr import ocr_extract, OCRActivityInput
        from modules.cts.workflows.activities.outward_scan_activities import (
            validate_cts2010, CTS2010ValidationInput,
            run_vision_presentment_check, VisionPresentmentCheckInput,
            vision_extract_and_check, VisionExtractAndCheckInput,
        )
        from modules.cts.workflows.activities.write_audit import WriteAuditInput, write_audit
        from modules.cts.workflows.mismatch_resolution_workflow import (
            MismatchResolutionWorkflow, MismatchInput,
        )

        # ---------------------------------------------------------------------------
        # CR-120 path: hardware MICR present — skip GOT-OCR2, use single Qwen2-VL call
        # Legacy path: no hardware MICR — keep original ocr_extract → vision flow
        # ---------------------------------------------------------------------------
        if inp.micr_hardware_raw:
            return await self._run_cr120_path(inp, validate_cts2010, CTS2010ValidationInput,
                                               vision_extract_and_check, VisionExtractAndCheckInput,
                                               write_audit, WriteAuditInput,
                                               MismatchResolutionWorkflow, MismatchInput)

        # --- Legacy path (drop-folder / no hardware MICR) ---
        # Step 1+2: MICR + amount extraction via GOT-OCR2
        ocr_result = await workflow.execute_activity(
            ocr_extract,
            OCRActivityInput(
                image_url=inp.image_front_url,
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
            ),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_AI_RETRY,
        )
        micr_line = ocr_result.micr_line
        scanner_amount_str = ocr_result.amount_figures
        quality_score = None if ocr_result.degraded else ocr_result.overall_confidence

        # Step 3: CTS-2010 compliance
        compliance_result = await workflow.execute_activity(
            validate_cts2010,
            CTS2010ValidationInput(
                instrument_id=inp.instrument_id,
                cheque_number=inp.cheque_number,
                front_dpi=inp.front_dpi,
                rear_dpi=inp.rear_dpi,
                front_colour_depth=inp.front_colour_depth,
                rear_colour_depth=inp.rear_colour_depth,
                front_file_size_kb=inp.front_file_size_kb,
                rear_file_size_kb=inp.rear_file_size_kb,
                front_iqa_score=quality_score,
                rear_iqa_score=quality_score,
                micr_band_score=quality_score,
            ),
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=_INFRA_RETRY,
        )

        if not compliance_result.is_compliant:
            log.info("outward_scan_workflow.cts_rejected",
                     scan_id=inp.scan_id, bank_id=inp.bank_id,
                     violations=compliance_result.violations)
            await workflow.execute_activity(
                write_audit,
                WriteAuditInput(event_type="CTS_OUT_CTS2010_FAIL", bank_id=inp.bank_id,
                                instrument_id=inp.instrument_id,
                                payload={"violations": compliance_result.violations,
                                         "scan_id": inp.scan_id}),
                start_to_close_timeout=timedelta(seconds=15), retry_policy=_AUDIT_RETRY,
            )
            return OutwardScanResult(
                outcome="CTS_REJECTED", scan_id=inp.scan_id, bank_id=inp.bank_id,
                instrument_id=inp.instrument_id, micr_line=micr_line, lot_number=None,
                violations=list(compliance_result.violations), audit_written=True, pu_id=inp.pu_id,
            )

        # Step 4: Vision cross-check (lot assignment deferred to ClearingSessionWorkflow)
        vision_result = None
        if scanner_amount_str is not None:
            vision_result = await workflow.execute_activity(
                run_vision_presentment_check,
                VisionPresentmentCheckInput(
                    instrument_id=inp.instrument_id, image_front_url=inp.image_front_url,
                    scanner_amount_str=scanner_amount_str, cheque_amount=float(scanner_amount_str),
                    bank_id=inp.bank_id,
                ),
                start_to_close_timeout=timedelta(seconds=120), retry_policy=_AI_RETRY,
            )

        if vision_result is not None and vision_result.has_mismatch:
            return await self._spawn_mismatch(
                inp, None, micr_line,
                scanner_amount_str or "", vision_result.vision_amount_str or "",
                vision_result.mismatch_fields,
                write_audit, WriteAuditInput, MismatchResolutionWorkflow, MismatchInput,
            )

        log.info("outward_scan_workflow.accepted_pending_lot",
                 scan_id=inp.scan_id, bank_id=inp.bank_id)
        await workflow.execute_activity(
            write_audit,
            WriteAuditInput(event_type="CTS_OUT_INSTRUMENT_PENDING", bank_id=inp.bank_id,
                            instrument_id=inp.instrument_id,
                            payload={"scan_id": inp.scan_id, "lot_number": None}),
            start_to_close_timeout=timedelta(seconds=15), retry_policy=_AUDIT_RETRY,
        )
        return OutwardScanResult(
            outcome="ACCEPTED", scan_id=inp.scan_id, bank_id=inp.bank_id,
            instrument_id=inp.instrument_id, micr_line=micr_line, lot_number=None,
            violations=None, audit_written=True, pu_id=inp.pu_id,
        )

    async def _run_cr120_path(
        self, inp: "OutwardScanInput",
        validate_cts2010, CTS2010ValidationInput,
        vision_extract_and_check, VisionExtractAndCheckInput,
        write_audit, WriteAuditInput,
        MismatchResolutionWorkflow, MismatchInput,
    ) -> "OutwardScanResult":
        """
        CR-120 path: hardware MICR provided by scanner agent.

        Step 1 — validate_cts2010 (DPI/colour from OutwardScanInput; IQA defaults
                  to 1.0 because the scanner's double-feed detection and hardware
                  capture already guarantee image quality).
        Step 2 — vision_extract_and_check (single Qwen2-VL call: field extraction
                  + alteration check + optional hardware MICR cross-validation).

        Lot assignment is deferred — accepted instruments enter PENDING_LOT state.
        """
        # CR-120 hardware guarantees image quality at capture — use 1.0 as IQA default
        # when scanner-provided metric fields are absent from OutwardScanInput.
        iqa_default = 1.0
        compliance_result = await workflow.execute_activity(
            validate_cts2010,
            CTS2010ValidationInput(
                instrument_id=inp.instrument_id,
                cheque_number=inp.cheque_number,
                front_dpi=inp.front_dpi,
                rear_dpi=inp.rear_dpi,
                front_colour_depth=inp.front_colour_depth,
                rear_colour_depth=inp.rear_colour_depth,
                front_file_size_kb=inp.front_file_size_kb,
                rear_file_size_kb=inp.rear_file_size_kb,
                front_iqa_score=iqa_default,
                rear_iqa_score=iqa_default,
                micr_band_score=iqa_default,
            ),
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=_INFRA_RETRY,
        )

        if not compliance_result.is_compliant:
            log.info("outward_scan_workflow.cr120.cts_rejected",
                     scan_id=inp.scan_id, bank_id=inp.bank_id,
                     violations=compliance_result.violations)
            await workflow.execute_activity(
                write_audit,
                WriteAuditInput(event_type="CTS_OUT_CTS2010_FAIL", bank_id=inp.bank_id,
                                instrument_id=inp.instrument_id,
                                payload={"violations": compliance_result.violations,
                                         "scan_id": inp.scan_id, "path": "cr120"}),
                start_to_close_timeout=timedelta(seconds=15), retry_policy=_AUDIT_RETRY,
            )
            return OutwardScanResult(
                outcome="CTS_REJECTED", scan_id=inp.scan_id, bank_id=inp.bank_id,
                instrument_id=inp.instrument_id, micr_line=inp.micr_hardware_raw,
                lot_number=None, violations=list(compliance_result.violations),
                audit_written=True, pu_id=inp.pu_id,
            )

        vision_result = await workflow.execute_activity(
            vision_extract_and_check,
            VisionExtractAndCheckInput(
                instrument_id=inp.instrument_id,
                image_front_url=inp.image_front_url,
                bank_id=inp.bank_id,
                micr_hardware_raw=inp.micr_hardware_raw,
            ),
            start_to_close_timeout=timedelta(seconds=120),
            retry_policy=_AI_RETRY,
        )

        if vision_result.outcome == "HUMAN_REVIEW":
            log.info("outward_scan_workflow.cr120.human_review",
                     scan_id=inp.scan_id, bank_id=inp.bank_id,
                     micr_mismatch=vision_result.micr_mismatch,
                     alteration=vision_result.alteration_detected)
            await workflow.execute_activity(
                write_audit,
                WriteAuditInput(event_type="CTS_OUT_HUMAN_REVIEW", bank_id=inp.bank_id,
                                instrument_id=inp.instrument_id,
                                payload={"scan_id": inp.scan_id, "lot_number": None,
                                         "micr_mismatch": vision_result.micr_mismatch,
                                         "alteration_detected": vision_result.alteration_detected}),
                start_to_close_timeout=timedelta(seconds=15), retry_policy=_AUDIT_RETRY,
            )
            return OutwardScanResult(
                outcome="MISMATCH_HELD", scan_id=inp.scan_id, bank_id=inp.bank_id,
                instrument_id=inp.instrument_id, micr_line=inp.micr_hardware_raw,
                lot_number=None, violations=None, audit_written=True, pu_id=inp.pu_id,
                mismatch_fields=vision_result.mismatch_fields or [],
            )

        if vision_result.outcome == "MISMATCH":
            return await self._spawn_mismatch(
                inp, None, inp.micr_hardware_raw,
                vision_result.amount_figures or "",
                vision_result.amount_words or "",
                vision_result.mismatch_fields,
                write_audit, WriteAuditInput, MismatchResolutionWorkflow, MismatchInput,
            )

        # PROCEED — accepted, pending lot assignment at clearing session time
        log.info("outward_scan_workflow.cr120.accepted_pending_lot",
                 scan_id=inp.scan_id, bank_id=inp.bank_id,
                 micr_validated=vision_result.micr_validated)
        await workflow.execute_activity(
            write_audit,
            WriteAuditInput(event_type="CTS_OUT_INSTRUMENT_PENDING", bank_id=inp.bank_id,
                            instrument_id=inp.instrument_id,
                            payload={"scan_id": inp.scan_id, "lot_number": None,
                                     "micr_validated": vision_result.micr_validated,
                                     "path": "cr120"}),
            start_to_close_timeout=timedelta(seconds=15), retry_policy=_AUDIT_RETRY,
        )
        return OutwardScanResult(
            outcome="ACCEPTED", scan_id=inp.scan_id, bank_id=inp.bank_id,
            instrument_id=inp.instrument_id, micr_line=inp.micr_hardware_raw,
            lot_number=None, violations=None, audit_written=True, pu_id=inp.pu_id,
        )

    async def _spawn_mismatch(
        self, inp, lot_number, micr_line,
        scanner_amount_str, vision_amount_str, mismatch_fields,
        write_audit, WriteAuditInput, MismatchResolutionWorkflow, MismatchInput,
    ) -> "OutwardScanResult":
        mismatch_id = self.generate_mismatch_id(inp.bank_id, inp.scan_id)
        log.info("outward_scan_workflow.mismatch_held",
                 scan_id=inp.scan_id, bank_id=inp.bank_id, mismatch_id=mismatch_id,
                 mismatch_fields=mismatch_fields, lot_number=lot_number)
        await workflow.start_child_workflow(
            MismatchResolutionWorkflow.run,
            MismatchInput(
                mismatch_id=mismatch_id, bank_id=inp.bank_id,
                branch_id=inp.branch_id or "", scan_id=inp.scan_id,
                instrument_id=inp.instrument_id, pu_id=inp.pu_id or "",
                scanner_amount_str=scanner_amount_str,
                vision_amount_str=vision_amount_str,
                mismatch_fields=mismatch_fields, payee_display="",
                session_id=inp.session_id,
            ),
            id=f"cts-mismatch-{inp.bank_id}-{inp.branch_id or 'NA'}-{mismatch_id}",
            parent_close_policy=ParentClosePolicy.ABANDON,
        )
        await workflow.execute_activity(
            write_audit,
            WriteAuditInput(event_type="CTS_OUT_MISMATCH_HELD", bank_id=inp.bank_id,
                            instrument_id=inp.instrument_id,
                            payload={"mismatch_id": mismatch_id,
                                     "mismatch_fields": mismatch_fields,
                                     "lot_number": lot_number}),
            start_to_close_timeout=timedelta(seconds=15), retry_policy=_AUDIT_RETRY,
        )
        return OutwardScanResult(
            outcome="MISMATCH_HELD", scan_id=inp.scan_id, bank_id=inp.bank_id,
            instrument_id=inp.instrument_id, micr_line=micr_line,
            lot_number=lot_number, violations=None, audit_written=True, pu_id=inp.pu_id,
            mismatch_id=mismatch_id, mismatch_fields=list(mismatch_fields),
        )

    async def run_with_mocks(
        self,
        inp: OutwardScanInput,
        mock_results: dict,
    ) -> OutwardScanResult:
        """
        Testable orchestration. In production this is a Temporal @workflow.run method.
        mock_results replaces each activity call result.

        Phase 3 keys:
          "micr"       — MICR extraction result
          "compliance" — CTS-2010 compliance result
          "lot"        — lot assignment result
          "vision_llm" — Vision LLM result (optional — not accessed on CTS_REJECTED path)
          "audit"      — audit write result
        """
        # Step 1+2: MICR extraction (capture + extract combined in mock)
        micr_result = mock_results["micr"]
        micr_line = getattr(micr_result, "micr_line", None)

        # Step 3: CTS-2010 compliance validation
        compliance_result = mock_results["compliance"]

        if not compliance_result.is_compliant:
            log.info(
                "outward_scan_workflow.cts_rejected",
                scan_id=inp.scan_id,
                bank_id=inp.bank_id,
                violations=compliance_result.violations,
            )
            # Audit — write for ALL outcomes; vision_llm skipped (no lot assigned)
            await self._write_audit(mock_results, "CTS_REJECTED", inp)
            return OutwardScanResult(
                outcome="CTS_REJECTED",
                scan_id=inp.scan_id,
                bank_id=inp.bank_id,
                instrument_id=inp.instrument_id,
                micr_line=micr_line,
                lot_number=None,
                violations=list(compliance_result.violations),
                audit_written=True,
                pu_id=inp.pu_id,
            )

        # Step 4: Vision LLM sanity cross-check (lot assignment deferred to ClearingSessionWorkflow)
        # In production: workflow.execute_activity(run_vision_presentment_check, ...)
        # with queue=cts-vision-l1 (cascade to l2 on low confidence or high-value)
        vision_result = mock_results.get("vision_llm")

        if vision_result is not None and vision_result.has_mismatch:
            mismatch_id = self.generate_mismatch_id(inp.bank_id, inp.scan_id)
            log.info(
                "outward_scan_workflow.mismatch_held",
                scan_id=inp.scan_id,
                bank_id=inp.bank_id,
                mismatch_id=mismatch_id,
                mismatch_fields=vision_result.mismatch_fields,
            )
            # In production: spawn MismatchResolutionWorkflow as child with ABANDON policy
            # The child workflow persists independently — parent records the mismatch_id
            await self._write_audit(mock_results, "MISMATCH_HELD", inp)
            return OutwardScanResult(
                outcome="MISMATCH_HELD",
                scan_id=inp.scan_id,
                bank_id=inp.bank_id,
                instrument_id=inp.instrument_id,
                micr_line=micr_line,
                lot_number=None,
                violations=None,
                audit_written=True,
                pu_id=inp.pu_id,
                mismatch_id=mismatch_id,
                mismatch_fields=list(vision_result.mismatch_fields),
            )

        # Vision matched (or no vision step) → ACCEPTED (pending lot at clearing session time)
        log.info(
            "outward_scan_workflow.accepted_pending_lot",
            scan_id=inp.scan_id,
            bank_id=inp.bank_id,
        )
        await self._write_audit(mock_results, "ACCEPTED", inp)
        return OutwardScanResult(
            outcome="ACCEPTED",
            scan_id=inp.scan_id,
            bank_id=inp.bank_id,
            instrument_id=inp.instrument_id,
            micr_line=micr_line,
            lot_number=None,
            violations=None,
            audit_written=True,
            pu_id=inp.pu_id,
        )

    async def _write_audit(self, mock_results: dict, outcome: str, inp: OutwardScanInput) -> None:
        audit_result = mock_results.get("audit")  # noqa: F841 — Temporal activity in production
        log.info(
            "outward_scan_workflow.audit_written",
            outcome=outcome,
            scan_id=inp.scan_id,
            bank_id=inp.bank_id,
        )
