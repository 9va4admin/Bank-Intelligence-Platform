"""
NGCH submission activities — build file, submit, confirm acknowledgement.

DI note: submit_to_ngch receives an `ngch_client` (the MCP adapter) injected
at worker startup via BoundCTSActivities. build_ngch_file and
confirm_acknowledgement are pure logic with no external DI requirement beyond
what the lot record provides.
"""
from __future__ import annotations

from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import activity

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# build_ngch_file
# ---------------------------------------------------------------------------

class BuildNGCHFileInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    lot_number: str
    bank_id: str
    bank_ifsc: str
    session_id: str
    clearing_date: str
    instrument_count: int


class BuildNGCHFileResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    file_path: str           # MinIO object key where the NGCH file was stored
    checksum_sha256: str
    instrument_count: int


@activity.defn
async def build_ngch_file(
    inp: BuildNGCHFileInput,
    lot_store: Any = None,
) -> BuildNGCHFileResult:
    """
    Assembles the CTS-2010 NGCH file from all endorsed instruments in the lot.
    Writes the file to MinIO and returns the object key + SHA-256 checksum.

    lot_store is DI-injected. Falls back to a stub path when unavailable
    (submission will still be attempted — NGCH will reject if file is bad).
    """
    if lot_store is None:
        log.warning(
            "build_ngch_file.lot_store_unavailable",
            lot_number=inp.lot_number,
            bank_id=inp.bank_id,
        )
        return BuildNGCHFileResult(
            file_path=f"cts/ngch/{inp.bank_id}/{inp.lot_number}/ngch_file.xml",
            checksum_sha256="unavailable",
            instrument_count=inp.instrument_count,
        )

    file_path, checksum = await lot_store.build_ngch_file(
        lot_number=inp.lot_number,
        bank_id=inp.bank_id,
        bank_ifsc=inp.bank_ifsc,
        session_id=inp.session_id,
        clearing_date=inp.clearing_date,
    )
    log.info(
        "build_ngch_file.built",
        lot_number=inp.lot_number,
        bank_id=inp.bank_id,
        file_path=file_path,
    )
    return BuildNGCHFileResult(
        file_path=file_path,
        checksum_sha256=checksum,
        instrument_count=inp.instrument_count,
    )


# ---------------------------------------------------------------------------
# submit_to_ngch
# ---------------------------------------------------------------------------

class SubmitToNGCHInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    lot_number: str
    bank_id: str
    bank_ifsc: str
    file_path: str
    checksum_sha256: str
    instrument_count: int


class SubmitToNGCHResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    submitted: bool
    ngch_reference: Optional[str] = None
    failure_reason: Optional[str] = None


@activity.defn
async def submit_to_ngch(
    inp: SubmitToNGCHInput,
    ngch_client: Any = None,
) -> SubmitToNGCHResult:
    """
    Submits the NGCH file via the ngch_adapter MCP tool.
    ngch_client is injected at worker startup.
    """
    if ngch_client is None:
        log.warning(
            "submit_to_ngch.ngch_client_unavailable",
            lot_number=inp.lot_number,
            bank_id=inp.bank_id,
        )
        return SubmitToNGCHResult(
            submitted=False,
            failure_reason="NGCH_CLIENT_UNAVAILABLE",
        )

    try:
        ref = await ngch_client.submit_outward_lot(
            bank_ifsc=inp.bank_ifsc,
            lot_number=inp.lot_number,
            file_path=inp.file_path,
            checksum=inp.checksum_sha256,
        )
        log.info(
            "submit_to_ngch.submitted",
            lot_number=inp.lot_number,
            bank_id=inp.bank_id,
            ngch_reference=ref,
        )
        return SubmitToNGCHResult(submitted=True, ngch_reference=ref)
    except Exception as exc:
        log.error(
            "submit_to_ngch.failed",
            lot_number=inp.lot_number,
            bank_id=inp.bank_id,
            error=str(exc),
        )
        return SubmitToNGCHResult(submitted=False, failure_reason=str(exc)[:200])


# ---------------------------------------------------------------------------
# confirm_acknowledgement
# ---------------------------------------------------------------------------

class ConfirmAcknowledgementInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    lot_number: str
    bank_id: str
    ngch_reference: Optional[str]


class ConfirmAcknowledgementResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    acknowledged: bool
    reference_number: Optional[str] = None
    reason: Optional[str] = None


@activity.defn
async def confirm_acknowledgement(
    inp: ConfirmAcknowledgementInput,
    ngch_client: Any = None,
) -> ConfirmAcknowledgementResult:
    """
    Polls NGCH for acknowledgement of the submitted lot.
    If ngch_reference is None (submission failed), returns not-acknowledged immediately.
    """
    if inp.ngch_reference is None:
        return ConfirmAcknowledgementResult(
            acknowledged=False,
            reason="NO_NGCH_REFERENCE",
        )

    if ngch_client is None:
        log.warning(
            "confirm_acknowledgement.ngch_client_unavailable",
            lot_number=inp.lot_number,
            bank_id=inp.bank_id,
        )
        return ConfirmAcknowledgementResult(
            acknowledged=False,
            reason="NGCH_CLIENT_UNAVAILABLE",
        )

    try:
        ack = await ngch_client.query_status(reference=inp.ngch_reference)
        acknowledged = getattr(ack, "acknowledged", False)
        log.info(
            "confirm_acknowledgement.result",
            lot_number=inp.lot_number,
            bank_id=inp.bank_id,
            acknowledged=acknowledged,
            reference=inp.ngch_reference,
        )
        return ConfirmAcknowledgementResult(
            acknowledged=acknowledged,
            reference_number=inp.ngch_reference,
            reason=None if acknowledged else getattr(ack, "reason", "NGCH_REJECTED"),
        )
    except Exception as exc:
        log.error(
            "confirm_acknowledgement.error",
            lot_number=inp.lot_number,
            bank_id=inp.bank_id,
            error=str(exc),
        )
        return ConfirmAcknowledgementResult(
            acknowledged=False,
            reason=str(exc)[:200],
        )
