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

# ── Date validation helpers ───────────────────────────────────────────────────

_DATE_FORMATS = ("%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d")
_STALE_DAYS = 90   # RBI: cheques older than 3 months cannot be presented


def _parse_cheque_date(date_str: str):
    """Parse cheque date string in common Indian formats. Returns date or None."""
    from datetime import date as _date
    for fmt in _DATE_FORMATS:
        try:
            return __import__("datetime").datetime.strptime(date_str.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _validate_cheque_date(date_str):
    """
    Returns (ok: bool, violation: str | None).
    violation is None when date is valid.
    Non-string values (e.g. None, or missing attr) → UNDATED_CHEQUE.
    """
    from datetime import date as _date
    if not isinstance(date_str, str) or not date_str.strip():
        return False, "UNDATED_CHEQUE"
    parsed = _parse_cheque_date(date_str)
    if parsed is None:
        return False, "UNDATED_CHEQUE"
    today = _date.today()
    if parsed > today:
        return False, "POST_DATED_CHEQUE"
    if (today - parsed).days > _STALE_DAYS:
        return False, "STALE_CHEQUE"
    return True, None


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

    # Payee / beneficiary details — from deposit slip (kiosk digital entry, teller
    # counter, or rear-image OCR). If payee_account_number is present, validate_payee_account
    # runs before CTS-2010 compliance. On CBS_UNAVAILABLE, workflow continues degraded
    # so the IET window is never blocked by a CBS outage.
    payee_account_number: Optional[str] = None    # KBL account number of the depositing customer
    payee_name_from_slip: Optional[str] = None    # name as written on deposit slip / cheque back
    payee_mobile: Optional[str] = None            # optional; for teller notification only
    rear_image_ocr_required: bool = False         # True → run extract_rear_payee_details first

    # NGCH metadata cross-check fields (Item 6) — filled at deposit registration.
    # Optional and additive: if absent, cross-check degrades gracefully to PROCEED.
    registered_drawee_ifsc: Optional[str] = None   # IFSC of drawee bank (from teller entry)
    registered_amount_str: Optional[str] = None    # amount entered at deposit (decimal string)

    # UV scanner image bundle — populated by DropFolderWatcher when scanner has UV lamp.
    # Both optional: standard non-UV scanners omit them; workflow skips those checks.
    image_front_gray_url: Optional[str] = None     # front grayscale — alteration detection
    image_uv_url: Optional[str] = None             # UV wavelength — security feature verification

    # Bank-level payee account status routing policy — populated by the trigger
    # from config_service.get_cts_config(bank_id) before starting the workflow.
    # Values: "HUMAN_REVIEW" (default) | "AUTO_RETURN"
    # CLOSED is always AUTO_RETURN regardless of these fields.
    outward_frozen_payee_action: str = "HUMAN_REVIEW"
    outward_dormant_payee_action: str = "HUMAN_REVIEW"
    outward_npa_payee_action: str = "HUMAN_REVIEW"


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
        """Production Temporal @workflow.run entry point."""
        from modules.cts.workflows.activities.outward_scan_activities import (
            record_outward_scan_event, RecordScanEventInput,
        )
        result = await self._run_impl(inp)
        # Record scan event for branch monitor (best-effort — never fail workflow for this)
        try:
            micr_suffix = (result.micr_line or "")[-4:] or None
            await workflow.execute_activity(
                record_outward_scan_event,
                RecordScanEventInput(
                    bank_id=inp.bank_id,
                    scan_id=inp.scan_id,
                    instrument_id=inp.instrument_id,
                    branch_id=getattr(inp, "branch_id", None),
                    session_id=getattr(inp, "session_id", None),
                    micr_suffix=micr_suffix if micr_suffix else None,
                    amount_range=None,
                    outcome=result.outcome,
                    lot_id=result.lot_number,
                    mismatch_id=result.mismatch_id,
                    mismatch_fields=result.mismatch_fields,
                    reject_reason=(result.violations[0] if result.violations else None),
                ),
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=_INFRA_RETRY,
            )
        except Exception:
            pass  # non-critical — never fail scan for event recording
        return result

    async def _run_impl(self, inp: OutwardScanInput) -> OutwardScanResult:
        """
        Core scan logic — delegated from run() so event recording wraps all paths.

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
        _ocr_engines = getattr(ocr_result, "ocr_engines_used", [])
        _indic_ks = getattr(ocr_result, "indic_ocr_kill_switch_active", False)

        # Emit CTS_KILL_SWITCH_APPLIED if IndicOCR was bypassed by kill switch.
        if _indic_ks:
            await workflow.execute_activity(
                write_audit,
                WriteAuditInput(
                    event_type="CTS_KILL_SWITCH_APPLIED",
                    bank_id=inp.bank_id,
                    instrument_id=inp.instrument_id,
                    payload={
                        "scope": "indic_ocr",
                        "mode": "KC",
                        "scan_id": inp.scan_id,
                        "ocr_engines_used": _ocr_engines,
                    },
                ),
                start_to_close_timeout=timedelta(seconds=15),
                retry_policy=_AUDIT_RETRY,
            )

        # Step 1.5: Date validation — stale / post-dated / undated cheques handled here.
        date_ok, date_violation = _validate_cheque_date(getattr(ocr_result, "date", None))
        if not date_ok:
            log.info("outward_scan_workflow.date_issue",
                     scan_id=inp.scan_id, bank_id=inp.bank_id,
                     violation=date_violation, date_extracted=getattr(ocr_result, "date", None))
            await workflow.execute_activity(
                write_audit,
                WriteAuditInput(
                    event_type="CTS_OUT_DATE_INVALID",
                    bank_id=inp.bank_id,
                    instrument_id=inp.instrument_id,
                    payload={"scan_id": inp.scan_id, "violation": date_violation},
                ),
                start_to_close_timeout=timedelta(seconds=15),
                retry_policy=_AUDIT_RETRY,
            )
            if date_violation == "POST_DATED_CHEQUE":
                # Post-dated: physical cheque accepted; Temporal holds until maturity.
                from modules.cts.workflows.postdated_hold_workflow import (
                    PostDatedHoldWorkflow, PostDatedHoldInput, make_hold_workflow_id,
                )
                from datetime import date as _date
                release_date = _parse_cheque_date(getattr(ocr_result, "date", "") or "")
                if release_date is None:
                    release_date = _date.today()   # safe fallback — hold won't sleep
                hold_id = make_hold_workflow_id(inp.bank_id, inp.instrument_id)
                await workflow.start_child_workflow(
                    PostDatedHoldWorkflow.run,
                    PostDatedHoldInput(
                        instrument_id=inp.instrument_id,
                        bank_id=inp.bank_id,
                        release_date=release_date,
                        original_workflow_data={
                            "instrument_id": inp.instrument_id,
                            "bank_id": inp.bank_id,
                            "image_front_url": inp.image_front_url,
                        },
                    ),
                    id=hold_id,
                    parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                )
                return OutwardScanResult(
                    outcome="POST_DATED_HELD",
                    scan_id=inp.scan_id,
                    bank_id=inp.bank_id,
                    instrument_id=inp.instrument_id,
                    micr_line=micr_line,
                    violations=["POST_DATED_CHEQUE"],
                    audit_written=True,
                    pu_id=inp.pu_id,
                )
            return OutwardScanResult(
                outcome="CTS_REJECTED",
                scan_id=inp.scan_id,
                bank_id=inp.bank_id,
                instrument_id=inp.instrument_id,
                micr_line=micr_line,
                violations=[date_violation],
                audit_written=True,
                pu_id=inp.pu_id,
            )

        # Step 2.05: Cheque de-duplication — reject BEFORE any lot admission
        # Uses MICR code (bank+branch) + cheque_number for a globally unique key.
        # Redis TTL = 18 months; YugabyteDB persistence is caller's responsibility via audit write.
        if micr_line and inp.cheque_number:
            from modules.cts.workflows.activities.outward_scan_activities import (
                check_cheque_dedup, ChequeDedupInput,
            )
            dedup_result = await workflow.execute_activity(
                check_cheque_dedup,
                ChequeDedupInput(
                    instrument_id=inp.instrument_id,
                    bank_id=inp.bank_id,
                    micr_line=micr_line,
                    cheque_number=inp.cheque_number,
                    presented_at=workflow.now().isoformat(),
                ),
                start_to_close_timeout=timedelta(seconds=5),
                retry_policy=_INFRA_RETRY,
            )
            if dedup_result.is_duplicate:
                await workflow.execute_activity(
                    write_audit,
                    WriteAuditInput(
                        event_type="CTS_OUT_DUPLICATE_CHEQUE",
                        bank_id=inp.bank_id,
                        instrument_id=inp.instrument_id,
                        payload={
                            "scan_id": inp.scan_id,
                            "cheque_number": inp.cheque_number[-4:],
                            "original_instrument_id": dedup_result.original_instrument_id or "unknown",
                        },
                    ),
                    start_to_close_timeout=timedelta(seconds=15),
                    retry_policy=_AUDIT_RETRY,
                )
                return OutwardScanResult(
                    outcome="CTS_REJECTED",
                    scan_id=inp.scan_id,
                    bank_id=inp.bank_id,
                    instrument_id=inp.instrument_id,
                    micr_line=micr_line,
                    violations=["DUPLICATE_CHEQUE"],
                    audit_written=True,
                    pu_id=inp.pu_id,
                )

        # Step 2.1: Rear-image OCR → extract payee account + name (if deposit slip not pre-entered)
        if inp.rear_image_ocr_required and inp.image_rear_url:
            from modules.cts.workflows.activities.outward_scan_activities import (
                extract_rear_payee_details, RearPayeeExtractionInput,
            )
            rear = await workflow.execute_activity(
                extract_rear_payee_details,
                RearPayeeExtractionInput(
                    instrument_id=inp.instrument_id,
                    bank_id=inp.bank_id,
                    image_rear_url=inp.image_rear_url,
                ),
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=_AI_RETRY,
            )
            # Merge OCR output into payee fields (don't override what teller pre-entered)
            if not inp.payee_account_number and rear.account_number:
                inp = inp.model_copy(update={
                    "payee_account_number": rear.account_number,
                    "payee_name_from_slip": rear.depositor_name or inp.payee_name_from_slip,
                })

        # Step 2.2: Payee account validation — Account Vault first, CBS on miss / for name match
        if inp.payee_account_number:
            from modules.cts.workflows.activities.outward_scan_activities import (
                validate_payee_account, PayeeValidationInput,
            )
            payee_result = await workflow.execute_activity(
                validate_payee_account,
                PayeeValidationInput(
                    instrument_id=inp.instrument_id,
                    bank_id=inp.bank_id,
                    payee_account_number=inp.payee_account_number,
                    payee_name_from_slip=inp.payee_name_from_slip,
                ),
                start_to_close_timeout=timedelta(seconds=15),
                retry_policy=_INFRA_RETRY,
            )
            if payee_result.outcome == "ACCOUNT_NOT_FOUND":
                log.info("outward_scan_workflow.payee_not_found",
                         scan_id=inp.scan_id, bank_id=inp.bank_id,
                         account_last4=inp.payee_account_number[-4:])
                await workflow.execute_activity(
                    write_audit,
                    WriteAuditInput(event_type="CTS_OUT_PAYEE_NOT_FOUND", bank_id=inp.bank_id,
                                    instrument_id=inp.instrument_id,
                                    payload={"scan_id": inp.scan_id,
                                             "account_last4": inp.payee_account_number[-4:]}),
                    start_to_close_timeout=timedelta(seconds=15), retry_policy=_AUDIT_RETRY,
                )
                return OutwardScanResult(
                    outcome="CTS_REJECTED", scan_id=inp.scan_id, bank_id=inp.bank_id,
                    instrument_id=inp.instrument_id, micr_line=micr_line, lot_number=None,
                    violations=["PAYEE_ACCOUNT_NOT_FOUND"], audit_written=True, pu_id=inp.pu_id,
                )
            if payee_result.outcome == "ACCOUNT_INACTIVE":
                acct_status = payee_result.account_status or "UNKNOWN"
                # CLOSED → always auto-return (account no longer exists).
                # FROZEN / DORMANT / NPA → bank-level policy from inp (populated by trigger
                # via config_service.get_cts_config). Default: HUMAN_REVIEW.
                _policy_map = {
                    "FROZEN":  inp.outward_frozen_payee_action,
                    "DORMANT": inp.outward_dormant_payee_action,
                    "NPA":     inp.outward_npa_payee_action,
                }
                action = "AUTO_RETURN" if acct_status == "CLOSED" else _policy_map.get(acct_status, "HUMAN_REVIEW")
                log.info("outward_scan_workflow.payee_inactive",
                         scan_id=inp.scan_id, bank_id=inp.bank_id,
                         account_status=acct_status, action=action)
                if action == "HUMAN_REVIEW":
                    await workflow.execute_activity(
                        write_audit,
                        WriteAuditInput(event_type="CTS_OUT_PAYEE_INACTIVE_HELD", bank_id=inp.bank_id,
                                        instrument_id=inp.instrument_id,
                                        payload={"scan_id": inp.scan_id,
                                                 "account_status": acct_status, "action": "HUMAN_REVIEW"}),
                        start_to_close_timeout=timedelta(seconds=15), retry_policy=_AUDIT_RETRY,
                    )
                    return OutwardScanResult(
                        outcome="MISMATCH_HELD", scan_id=inp.scan_id, bank_id=inp.bank_id,
                        instrument_id=inp.instrument_id, micr_line=micr_line, lot_number=None,
                        violations=[f"PAYEE_ACCOUNT_{acct_status}"],
                        mismatch_fields=["payee_account_status"],
                        audit_written=True, pu_id=inp.pu_id,
                    )
                await workflow.execute_activity(
                    write_audit,
                    WriteAuditInput(event_type="CTS_OUT_PAYEE_INACTIVE", bank_id=inp.bank_id,
                                    instrument_id=inp.instrument_id,
                                    payload={"scan_id": inp.scan_id,
                                             "account_status": acct_status, "action": "AUTO_RETURN"}),
                    start_to_close_timeout=timedelta(seconds=15), retry_policy=_AUDIT_RETRY,
                )
                return OutwardScanResult(
                    outcome="CTS_REJECTED", scan_id=inp.scan_id, bank_id=inp.bank_id,
                    instrument_id=inp.instrument_id, micr_line=micr_line, lot_number=None,
                    violations=[f"PAYEE_ACCOUNT_{acct_status}"],
                    audit_written=True, pu_id=inp.pu_id,
                )
            if payee_result.outcome == "NAME_MISMATCH":
                # Name mismatch → human review (not outright rejection; teller can override)
                log.info("outward_scan_workflow.payee_name_mismatch",
                         scan_id=inp.scan_id, bank_id=inp.bank_id,
                         score=payee_result.name_match_score)
                await workflow.execute_activity(
                    write_audit,
                    WriteAuditInput(event_type="CTS_OUT_PAYEE_NAME_MISMATCH", bank_id=inp.bank_id,
                                    instrument_id=inp.instrument_id,
                                    payload={"scan_id": inp.scan_id,
                                             "name_match_score": payee_result.name_match_score,
                                             "payee_display": payee_result.payee_display}),
                    start_to_close_timeout=timedelta(seconds=15), retry_policy=_AUDIT_RETRY,
                )
                return OutwardScanResult(
                    outcome="MISMATCH_HELD", scan_id=inp.scan_id, bank_id=inp.bank_id,
                    instrument_id=inp.instrument_id, micr_line=micr_line, lot_number=None,
                    violations=["PAYEE_NAME_MISMATCH"], audit_written=True, pu_id=inp.pu_id,
                    mismatch_fields=["payee_name"],
                )
            # CBS_UNAVAILABLE → proceed degraded; vault says account exists; teller notified via UI flag

        # Step 2.5: NGCH metadata cross-check — MICR band vs registered instrument metadata
        from modules.cts.workflows.activities.ngch_metadata_cross_check import (
            cross_check_ngch_metadata, NGCHMetadataCrossCheckInput,
        )
        xcheck_result = await workflow.execute_activity(
            cross_check_ngch_metadata,
            NGCHMetadataCrossCheckInput(
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                micr_line=micr_line,
                registered_cheque_number=inp.cheque_number or None,
                ifsc_from_ocr=ocr_result.ifsc_code,
                registered_drawee_ifsc=inp.registered_drawee_ifsc,
                registered_amount_str=inp.registered_amount_str,
                amount_from_ocr=scanner_amount_str,
            ),
            start_to_close_timeout=timedelta(seconds=5),
            retry_policy=_INFRA_RETRY,
        )
        if xcheck_result.outcome == "HUMAN_REVIEW":
            log.info(
                "outward_scan_workflow.ngch_metadata_mismatch",
                scan_id=inp.scan_id, bank_id=inp.bank_id,
                mismatches=xcheck_result.mismatch_fields,
            )
            await workflow.execute_activity(
                write_audit,
                WriteAuditInput(
                    event_type="CTS_OUT_NGCH_METADATA_MISMATCH",
                    bank_id=inp.bank_id, instrument_id=inp.instrument_id,
                    payload={
                        "scan_id": inp.scan_id,
                        "mismatch_fields": xcheck_result.mismatch_fields,
                    },
                ),
                start_to_close_timeout=timedelta(seconds=15), retry_policy=_AUDIT_RETRY,
            )
            return OutwardScanResult(
                outcome="CTS_REJECTED", scan_id=inp.scan_id, bank_id=inp.bank_id,
                instrument_id=inp.instrument_id, micr_line=micr_line, lot_number=None,
                violations=[f"NGCH_METADATA_MISMATCH:{f}" for f in xcheck_result.mismatch_fields],
                audit_written=True, pu_id=inp.pu_id,
            )
        # DEGRADED → proceed optimistically (MICR parse failure is not clearing-blocking)

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

        # Step 3.5: detect_signatures — presence check only (outward never validates vs vault)
        from modules.cts.workflows.activities.detect_signatures import (
            detect_signatures, DetectSignaturesInput,
        )
        sig_detect = await workflow.execute_activity(
            detect_signatures,
            DetectSignaturesInput(
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                image_url=inp.image_front_url,
            ),
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=_AI_RETRY,
        )
        if sig_detect.outcome == "ABSENT":
            log.info("outward_scan_workflow.signature_absent",
                     scan_id=inp.scan_id, bank_id=inp.bank_id)
            await workflow.execute_activity(
                write_audit,
                WriteAuditInput(event_type="CTS_OUT_SIGNATURE_ABSENT", bank_id=inp.bank_id,
                                instrument_id=inp.instrument_id,
                                payload={"scan_id": inp.scan_id, "violation": "SIGNATURE_ABSENT"}),
                start_to_close_timeout=timedelta(seconds=15), retry_policy=_AUDIT_RETRY,
            )
            return OutwardScanResult(
                outcome="CTS_REJECTED", scan_id=inp.scan_id, bank_id=inp.bank_id,
                instrument_id=inp.instrument_id, micr_line=micr_line, lot_number=None,
                violations=["SIGNATURE_ABSENT"], audit_written=True, pu_id=inp.pu_id,
            )
        # DEGRADED → proceed optimistically; do not block lot on AI failure.
        # Fraud flags → outward bank does not validate signatures; logged by drawee inward.

        # Step 3.6: CTS-2010 security feature presence (void pantograph, ₹ symbol, micro-lettering)
        from modules.cts.workflows.activities.security_features import (
            check_security_features, SecurityFeaturesInput,
        )
        sec_result = await workflow.execute_activity(
            check_security_features,
            args=[
                SecurityFeaturesInput(
                    instrument_id=inp.instrument_id,
                    bank_id=inp.bank_id,
                    image_url=inp.image_front_url,
                    smb_id=inp.smb_id if hasattr(inp, "smb_id") else None,
                ),
                None,   # vllm_client — worker-level DI
                None,   # config_service — worker-level DI
                None,   # langfuse — worker-level DI
            ],
            start_to_close_timeout=timedelta(seconds=120),
            retry_policy=_AI_RETRY,
        )
        if sec_result.outcome == "HUMAN_REVIEW":
            log.info(
                "outward_scan_workflow.security_features_missing",
                scan_id=inp.scan_id, bank_id=inp.bank_id,
                missing=sec_result.missing_features,
            )
            await workflow.execute_activity(
                write_audit,
                WriteAuditInput(
                    event_type="CTS_OUT_SECURITY_FEATURES_MISSING",
                    bank_id=inp.bank_id, instrument_id=inp.instrument_id,
                    payload={
                        "scan_id": inp.scan_id,
                        "missing_features": sec_result.missing_features,
                    },
                ),
                start_to_close_timeout=timedelta(seconds=15), retry_policy=_AUDIT_RETRY,
            )
            return OutwardScanResult(
                outcome="CTS_REJECTED", scan_id=inp.scan_id, bank_id=inp.bank_id,
                instrument_id=inp.instrument_id, micr_line=micr_line, lot_number=None,
                violations=[f"SECURITY_FEATURE_ABSENT:{f}" for f in sec_result.missing_features],
                audit_written=True, pu_id=inp.pu_id,
            )
        # DEGRADED → proceed optimistically (AI failure never blocks physical clearing)

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
                            payload={
                                "scan_id": inp.scan_id,
                                "lot_number": None,
                                "ocr_engines_used": _ocr_engines,
                                "indic_ocr_kill_switch_active": _indic_ks,
                            }),
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

        # Step 1.5 (CR-120): Payee account validation — same logic as legacy path
        if inp.payee_account_number:
            from modules.cts.workflows.activities.outward_scan_activities import (
                validate_payee_account, PayeeValidationInput,
            )
            payee_cr = await workflow.execute_activity(
                validate_payee_account,
                PayeeValidationInput(
                    instrument_id=inp.instrument_id,
                    bank_id=inp.bank_id,
                    payee_account_number=inp.payee_account_number,
                    payee_name_from_slip=inp.payee_name_from_slip,
                ),
                start_to_close_timeout=timedelta(seconds=15),
                retry_policy=_INFRA_RETRY,
            )
            if payee_cr.outcome == "ACCOUNT_NOT_FOUND":
                await workflow.execute_activity(
                    write_audit,
                    WriteAuditInput(event_type="CTS_OUT_PAYEE_NOT_FOUND", bank_id=inp.bank_id,
                                    instrument_id=inp.instrument_id,
                                    payload={"scan_id": inp.scan_id, "path": "cr120",
                                             "account_last4": inp.payee_account_number[-4:]}),
                    start_to_close_timeout=timedelta(seconds=15), retry_policy=_AUDIT_RETRY,
                )
                return OutwardScanResult(
                    outcome="CTS_REJECTED", scan_id=inp.scan_id, bank_id=inp.bank_id,
                    instrument_id=inp.instrument_id, micr_line=inp.micr_hardware_raw,
                    lot_number=None, violations=["PAYEE_ACCOUNT_NOT_FOUND"],
                    audit_written=True, pu_id=inp.pu_id,
                )
            if payee_cr.outcome == "ACCOUNT_INACTIVE":
                acct_status = payee_cr.account_status or "UNKNOWN"
                _policy_map = {
                    "FROZEN":  inp.outward_frozen_payee_action,
                    "DORMANT": inp.outward_dormant_payee_action,
                    "NPA":     inp.outward_npa_payee_action,
                }
                action = "AUTO_RETURN" if acct_status == "CLOSED" else _policy_map.get(acct_status, "HUMAN_REVIEW")
                log.info("outward_scan_workflow.payee_inactive",
                         scan_id=inp.scan_id, bank_id=inp.bank_id,
                         account_status=acct_status, action=action, path="cr120")
                if action == "HUMAN_REVIEW":
                    await workflow.execute_activity(
                        write_audit,
                        WriteAuditInput(event_type="CTS_OUT_PAYEE_INACTIVE_HELD", bank_id=inp.bank_id,
                                        instrument_id=inp.instrument_id,
                                        payload={"scan_id": inp.scan_id, "path": "cr120",
                                                 "account_status": acct_status, "action": "HUMAN_REVIEW"}),
                        start_to_close_timeout=timedelta(seconds=15), retry_policy=_AUDIT_RETRY,
                    )
                    return OutwardScanResult(
                        outcome="MISMATCH_HELD", scan_id=inp.scan_id, bank_id=inp.bank_id,
                        instrument_id=inp.instrument_id, micr_line=inp.micr_hardware_raw,
                        lot_number=None, violations=[f"PAYEE_ACCOUNT_{acct_status}"],
                        mismatch_fields=["payee_account_status"],
                        audit_written=True, pu_id=inp.pu_id,
                    )
                await workflow.execute_activity(
                    write_audit,
                    WriteAuditInput(event_type="CTS_OUT_PAYEE_INACTIVE", bank_id=inp.bank_id,
                                    instrument_id=inp.instrument_id,
                                    payload={"scan_id": inp.scan_id, "path": "cr120",
                                             "account_status": acct_status, "action": "AUTO_RETURN"}),
                    start_to_close_timeout=timedelta(seconds=15), retry_policy=_AUDIT_RETRY,
                )
                return OutwardScanResult(
                    outcome="CTS_REJECTED", scan_id=inp.scan_id, bank_id=inp.bank_id,
                    instrument_id=inp.instrument_id, micr_line=inp.micr_hardware_raw,
                    lot_number=None, violations=[f"PAYEE_ACCOUNT_{acct_status}"],
                    audit_written=True, pu_id=inp.pu_id,
                )
            if payee_cr.outcome == "NAME_MISMATCH":
                await workflow.execute_activity(
                    write_audit,
                    WriteAuditInput(event_type="CTS_OUT_PAYEE_NAME_MISMATCH", bank_id=inp.bank_id,
                                    instrument_id=inp.instrument_id,
                                    payload={"scan_id": inp.scan_id, "path": "cr120",
                                             "name_match_score": payee_cr.name_match_score}),
                    start_to_close_timeout=timedelta(seconds=15), retry_policy=_AUDIT_RETRY,
                )
                return OutwardScanResult(
                    outcome="MISMATCH_HELD", scan_id=inp.scan_id, bank_id=inp.bank_id,
                    instrument_id=inp.instrument_id, micr_line=inp.micr_hardware_raw,
                    lot_number=None, violations=["PAYEE_NAME_MISMATCH"],
                    audit_written=True, pu_id=inp.pu_id, mismatch_fields=["payee_name"],
                )

        # Step 1.6 (CR-120): detect_signatures — presence only, same as legacy path
        from modules.cts.workflows.activities.detect_signatures import (
            detect_signatures, DetectSignaturesInput,
        )
        sig_detect_cr = await workflow.execute_activity(
            detect_signatures,
            DetectSignaturesInput(
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                image_url=inp.image_front_url,
            ),
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=_AI_RETRY,
        )
        if sig_detect_cr.outcome == "ABSENT":
            log.info("outward_scan_workflow.cr120.signature_absent",
                     scan_id=inp.scan_id, bank_id=inp.bank_id)
            await workflow.execute_activity(
                write_audit,
                WriteAuditInput(event_type="CTS_OUT_SIGNATURE_ABSENT", bank_id=inp.bank_id,
                                instrument_id=inp.instrument_id,
                                payload={"scan_id": inp.scan_id, "path": "cr120",
                                         "violation": "SIGNATURE_ABSENT"}),
                start_to_close_timeout=timedelta(seconds=15), retry_policy=_AUDIT_RETRY,
            )
            return OutwardScanResult(
                outcome="CTS_REJECTED", scan_id=inp.scan_id, bank_id=inp.bank_id,
                instrument_id=inp.instrument_id, micr_line=inp.micr_hardware_raw,
                lot_number=None, violations=["SIGNATURE_ABSENT"], audit_written=True,
                pu_id=inp.pu_id,
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

        # Step 1.5: Date validation — stale / post-dated / undated cheques handled here.
        date_str = getattr(micr_result, "date", None)
        date_ok, date_violation = _validate_cheque_date(date_str)
        if not date_ok:
            log.info("outward_scan_workflow.date_issue",
                     scan_id=inp.scan_id, bank_id=inp.bank_id,
                     violation=date_violation, date_extracted=date_str)
            if date_violation == "POST_DATED_CHEQUE":
                # Post-dated: valid instrument — hold it, don't reject.
                # In run_with_mocks(), no child workflow is started; caller should observe
                # POST_DATED_HELD outcome and treat the instrument as held by the branch.
                await self._write_audit(mock_results, "POST_DATED_HELD", inp)
                return OutwardScanResult(
                    outcome="POST_DATED_HELD", scan_id=inp.scan_id, bank_id=inp.bank_id,
                    instrument_id=inp.instrument_id, micr_line=micr_line,
                    lot_number=None, violations=["POST_DATED_CHEQUE"], audit_written=True,
                    pu_id=getattr(inp, "pu_id", None),
                )
            await self._write_audit(mock_results, "CTS_REJECTED", inp)
            return OutwardScanResult(
                outcome="CTS_REJECTED", scan_id=inp.scan_id, bank_id=inp.bank_id,
                instrument_id=inp.instrument_id, micr_line=micr_line,
                lot_number=None, violations=[date_violation], audit_written=True,
                pu_id=getattr(inp, "pu_id", None),
            )

        # Step 2.2: Payee account validation (optional mock — skipped when payee_account_number absent)
        if inp.payee_account_number:
            payee_result = mock_results.get("payee")
            if payee_result is not None:
                if getattr(payee_result, "outcome", "PROCEED") == "ACCOUNT_NOT_FOUND":
                    log.info("outward_scan_workflow.payee_not_found",
                             scan_id=inp.scan_id, bank_id=inp.bank_id,
                             account_last4=inp.payee_account_number[-4:])
                    await self._write_audit(mock_results, "CTS_REJECTED", inp)
                    return OutwardScanResult(
                        outcome="CTS_REJECTED", scan_id=inp.scan_id, bank_id=inp.bank_id,
                        instrument_id=inp.instrument_id, micr_line=micr_line,
                        lot_number=None, violations=["PAYEE_ACCOUNT_NOT_FOUND"],
                        audit_written=True, pu_id=getattr(inp, "pu_id", None),
                    )
                if getattr(payee_result, "outcome", "PROCEED") == "ACCOUNT_INACTIVE":
                    acct_status = getattr(payee_result, "account_status", "UNKNOWN")
                    # CLOSED is always auto-returned — account no longer exists.
                    # FROZEN / DORMANT / NPA are bank-level policy (Layer 3):
                    #   outward_frozen_payee_action / outward_dormant_payee_action / outward_npa_payee_action
                    # Default: HUMAN_REVIEW — the teller should not make this call.
                    _policy_map = {
                        "FROZEN":  inp.outward_frozen_payee_action,
                        "DORMANT": inp.outward_dormant_payee_action,
                        "NPA":     inp.outward_npa_payee_action,
                    }
                    if acct_status == "CLOSED":
                        action = "AUTO_RETURN"
                    else:
                        action = _policy_map.get(acct_status, "HUMAN_REVIEW")
                    log.info("outward_scan_workflow.payee_inactive",
                             scan_id=inp.scan_id, bank_id=inp.bank_id,
                             account_status=acct_status, action=action)
                    if action == "HUMAN_REVIEW":
                        await self._write_audit(mock_results, "MISMATCH_HELD", inp)
                        return OutwardScanResult(
                            outcome="MISMATCH_HELD", scan_id=inp.scan_id, bank_id=inp.bank_id,
                            instrument_id=inp.instrument_id, micr_line=micr_line,
                            lot_number=None,
                            violations=[f"PAYEE_ACCOUNT_{acct_status}"],
                            mismatch_fields=["payee_account_status"],
                            audit_written=True, pu_id=getattr(inp, "pu_id", None),
                        )
                    # AUTO_RETURN path
                    await self._write_audit(mock_results, "CTS_REJECTED", inp)
                    return OutwardScanResult(
                        outcome="CTS_REJECTED", scan_id=inp.scan_id, bank_id=inp.bank_id,
                        instrument_id=inp.instrument_id, micr_line=micr_line,
                        lot_number=None, violations=[f"PAYEE_ACCOUNT_{acct_status}"],
                        audit_written=True, pu_id=getattr(inp, "pu_id", None),
                    )
                if getattr(payee_result, "outcome", "PROCEED") == "NAME_MISMATCH":
                    log.info("outward_scan_workflow.payee_name_mismatch",
                             scan_id=inp.scan_id, bank_id=inp.bank_id,
                             score=getattr(payee_result, "name_match_score", None))
                    await self._write_audit(mock_results, "MISMATCH_HELD", inp)
                    return OutwardScanResult(
                        outcome="MISMATCH_HELD", scan_id=inp.scan_id, bank_id=inp.bank_id,
                        instrument_id=inp.instrument_id, micr_line=micr_line,
                        lot_number=None, violations=["PAYEE_NAME_MISMATCH"],
                        audit_written=True, pu_id=getattr(inp, "pu_id", None),
                        mismatch_fields=["payee_name"],
                    )

        # Step 2.5: NGCH metadata cross-check (optional mock — defaults to PROCEED)
        xcheck_result = mock_results.get("cross_check")
        if xcheck_result is not None and getattr(xcheck_result, "outcome", "PROCEED") == "HUMAN_REVIEW":
            await self._write_audit(mock_results, "CTS_REJECTED", inp)
            return OutwardScanResult(
                outcome="CTS_REJECTED",
                scan_id=inp.scan_id,
                bank_id=inp.bank_id,
                instrument_id=inp.instrument_id,
                micr_line=micr_line,
                lot_number=None,
                violations=[f"NGCH_METADATA_MISMATCH:{f}" for f in getattr(xcheck_result, "mismatch_fields", [])],
                audit_written=True,
                pu_id=inp.pu_id,
            )

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

        # Step 3.5: Front-gray alteration detection — only when gray image was captured.
        # Graceful degradation: model unavailable (degraded=True) → proceed, never block.
        if inp.image_front_gray_url:
            alteration_result = mock_results.get("alteration")
            if alteration_result is not None:
                if alteration_result.alteration_detected and not alteration_result.degraded:
                    altered = getattr(alteration_result, "altered_fields", ["unknown"])
                    log.info("outward_scan_workflow.alteration_detected",
                             scan_id=inp.scan_id, bank_id=inp.bank_id,
                             altered_fields=altered)
                    await self._write_audit(mock_results, "MISMATCH_HELD", inp)
                    return OutwardScanResult(
                        outcome="MISMATCH_HELD", scan_id=inp.scan_id, bank_id=inp.bank_id,
                        instrument_id=inp.instrument_id, micr_line=micr_line,
                        lot_number=None,
                        violations=[f"ALTERATION_DETECTED:{f}" for f in altered],
                        audit_written=True, pu_id=getattr(inp, "pu_id", None),
                        mismatch_fields=list(altered),
                    )
                # degraded or no alteration → proceed

        # Step 3.6: UV security check — only when UV image was captured by scanner.
        # Failure (uv_security_passed=False, not degraded) → MISMATCH_HELD for teller review.
        # Degraded (UV lamp absent/offline) → proceed optimistically.
        if inp.image_uv_url:
            uv_result = mock_results.get("uv")
            if uv_result is not None:
                if not uv_result.uv_security_passed and not uv_result.degraded:
                    log.info("outward_scan_workflow.uv_security_failed",
                             scan_id=inp.scan_id, bank_id=inp.bank_id,
                             uv_risk_score=getattr(uv_result, "uv_risk_score", None))
                    await self._write_audit(mock_results, "MISMATCH_HELD", inp)
                    return OutwardScanResult(
                        outcome="MISMATCH_HELD", scan_id=inp.scan_id, bank_id=inp.bank_id,
                        instrument_id=inp.instrument_id, micr_line=micr_line,
                        lot_number=None,
                        violations=["UV_SECURITY_FAILED"],
                        audit_written=True, pu_id=getattr(inp, "pu_id", None),
                        mismatch_fields=["uv_security"],
                    )
                # degraded or passed → proceed

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
