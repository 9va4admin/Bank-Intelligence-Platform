"""
OutwardScanWorkflow — CTS Presentee Bank outward clearing.

Orchestrates the scanner → MICR → CTS-2010 compliance → lot assignment pipeline
for each physical cheque deposited by a customer.

Activity sequence:
  1. capture_image      — scanner adapter captures front + rear TIFF images
  2. extract_micr       — GOT-OCR2.0 extracts MICR line fields
  3. validate_cts2010   — CTS-2010 image compliance check (DPI, size, MICR zone)
  4. create_lot_entry   — lot manager assigns instrument to current clearing lot
  5. write_audit        — Immudb audit (ALL terminal outcomes)

Terminal states: ACCEPTED | CTS_REJECTED
Workflow ID: cts-outscan-{bank_id}-{scan_id}  (idempotent)
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


class OutwardScanResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str                        # "ACCEPTED" | "CTS_REJECTED"
    scan_id: str
    bank_id: str
    instrument_id: str
    micr_line: Optional[str] = None
    lot_number: Optional[str] = None
    violations: Optional[list[str]] = None
    audit_written: bool = False


class OutwardScanWorkflow:
    def workflow_id(self, bank_id: str, scan_id: str) -> str:
        return f"cts-outscan-{bank_id}-{scan_id}"

    async def run_with_mocks(
        self,
        inp: OutwardScanInput,
        mock_results: dict,
    ) -> OutwardScanResult:
        # Step 1: MICR extraction result (capture + extract combined in mock)
        micr_result = mock_results["micr"]
        micr_line = getattr(micr_result, "micr_line", None)

        # Step 2: CTS-2010 compliance validation
        compliance_result = mock_results["compliance"]

        if not compliance_result.is_compliant:
            log.info(
                "outward_scan_workflow.cts_rejected",
                scan_id=inp.scan_id,
                bank_id=inp.bank_id,
                violations=compliance_result.violations,
            )
            # Step 5: Audit — write for ALL outcomes
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
            )

        # Step 3: Lot assignment
        lot_result = mock_results["lot"]
        lot_number = getattr(lot_result, "lot_number", None)

        log.info(
            "outward_scan_workflow.accepted",
            scan_id=inp.scan_id,
            bank_id=inp.bank_id,
            lot_number=lot_number,
        )

        # Step 5: Audit — write for ALL outcomes
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
        )

    async def _write_audit(self, mock_results: dict, outcome: str, inp: OutwardScanInput) -> None:
        audit_result = mock_results.get("audit")  # noqa: F841 — Temporal activity in production
        log.info(
            "outward_scan_workflow.audit_written",
            outcome=outcome,
            scan_id=inp.scan_id,
            bank_id=inp.bank_id,
        )
