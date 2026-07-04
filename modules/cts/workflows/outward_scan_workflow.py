"""
OutwardScanWorkflow — CTS Presentee Bank outward clearing.

Orchestrates the scanner → MICR → CTS-2010 compliance → lot assignment → Vision LLM pipeline
for each physical cheque deposited by a customer.

Activity sequence (Phase 3):
  1. capture_image      — scanner adapter captures front + rear TIFF images
  2. extract_micr       — GOT-OCR2.0 extracts MICR line fields (scanner-side, not Vision)
  3. validate_cts2010   — CTS-2010 image compliance check (DPI, size, MICR zone)
  4. create_lot_entry   — lot manager assigns instrument to current clearing lot
  5. vision_llm         — Qwen2-VL sanity check: confirm amount_figures match scanner
                          On MISMATCH → spawns MismatchResolutionWorkflow child (ABANDON policy)
  6. write_audit        — Immudb audit (ALL terminal outcomes)

Terminal states: ACCEPTED | CTS_REJECTED | MISMATCH_HELD
Workflow ID: cts-outscan-{bank_id}-{pu_id}-{scan_id}  (pu_id optional for backward compat)

Phase 3 note: Vision LLM runs LAST (after lot assignment) because:
- Presentment: scanner is the authoritative source; Vision is a sanity cross-check.
- Cost: most cheques pass — skip Vision on CTS_REJECTED (no lot assigned, no Vision needed).
- Drawee: Vision runs FIRST (different workflow) — trust Vision over scanner on inward side.
"""
from __future__ import annotations

from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()


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


class OutwardScanWorkflow:
    def workflow_id(self, bank_id: str, scan_id: str, pu_id: Optional[str] = None) -> str:
        if pu_id:
            return f"cts-outscan-{bank_id}-{pu_id}-{scan_id}"
        return f"cts-outscan-{bank_id}-{scan_id}"

    def generate_mismatch_id(self, bank_id: str, scan_id: str) -> str:
        """Deterministic mismatch ID — same scan_id always produces same mismatch_id."""
        return f"MM-{bank_id}-{scan_id}"

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

        # Step 4: Lot assignment
        lot_result = mock_results["lot"]
        lot_number = getattr(lot_result, "lot_number", None)

        # Step 5: Vision LLM sanity cross-check (LAST — runs only on compliant instruments)
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
                lot_number=lot_number,
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
                lot_number=lot_number,
                violations=None,
                audit_written=True,
                pu_id=inp.pu_id,
                mismatch_id=mismatch_id,
                mismatch_fields=list(vision_result.mismatch_fields),
            )

        # Vision matched (or no vision step) → ACCEPTED
        log.info(
            "outward_scan_workflow.accepted",
            scan_id=inp.scan_id,
            bank_id=inp.bank_id,
            lot_number=lot_number,
        )
        await self._write_audit(mock_results, "ACCEPTED", inp)
        return OutwardScanResult(
            outcome="ACCEPTED",
            scan_id=inp.scan_id,
            bank_id=inp.bank_id,
            instrument_id=inp.instrument_id,
            micr_line=micr_line,
            lot_number=lot_number,
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
