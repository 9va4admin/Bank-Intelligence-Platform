"""
Representation activities for ChequeRepresentationWorkflow.

notify_representation_pending   : alerts ops / customer that re-presentation is pending
re_submit_to_ngch_for_representation : re-files the instrument to NGCH after fix is applied
"""
from __future__ import annotations

from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import activity

log = structlog.get_logger()


# ── notify_representation_pending ─────────────────────────────────────────────

class NotifyRepresentationInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    instrument_id: str
    bank_id: str
    return_reason_code: str
    original_session_id: str
    clearing_date: str
    representation_window_hours: int    # from config_service — never hardcoded


class NotifyRepresentationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    notified: bool
    degraded: bool = False


@activity.defn
async def notify_representation_pending(
    inp: NotifyRepresentationInput,
    dispatcher: Any = None,
) -> NotifyRepresentationResult:
    """
    Notifies ops team that the instrument needs to be fixed and re-presented.
    Degrades gracefully when dispatcher is unavailable.
    """
    if dispatcher is None:
        log.warning(
            "notify_representation_pending.dispatcher_unavailable",
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            return_reason_code=inp.return_reason_code,
        )
        return NotifyRepresentationResult(notified=False, degraded=True)

    await dispatcher.send(
        channel="UI",
        bank_id=inp.bank_id,
        message_key="CTS_OUT_REPRESENTATION_PENDING",
        variables={
            "instrument_id": inp.instrument_id,
            "return_reason_code": inp.return_reason_code,
            "representation_window_hours": str(inp.representation_window_hours),
        },
    )

    log.info(
        "notify_representation_pending.complete",
        instrument_id=inp.instrument_id,
        bank_id=inp.bank_id,
        return_reason_code=inp.return_reason_code,
        representation_window_hours=inp.representation_window_hours,
    )
    return NotifyRepresentationResult(notified=True, degraded=False)


# ── re_submit_to_ngch_for_representation ──────────────────────────────────────

class ResubmitNgchInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    instrument_id: str
    bank_id: str
    bank_ifsc: str
    return_reason_code: str
    original_session_id: str
    clearing_date: str


class ResubmitNgchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    submitted: bool
    ngch_reference: Optional[str] = None
    degraded: bool = False


@activity.defn
async def re_submit_to_ngch_for_representation(
    inp: ResubmitNgchInput,
    ngch_client: Any = None,
) -> ResubmitNgchResult:
    """
    Re-files the instrument to NGCH via the ngch_filer pathway.
    Degrades gracefully when ngch_client is unavailable.
    """
    if ngch_client is None:
        log.warning(
            "re_submit_to_ngch_for_representation.ngch_unavailable",
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
        )
        return ResubmitNgchResult(submitted=False, degraded=True)

    ngch_reference = await ngch_client.submit_representation(
        instrument_id=inp.instrument_id,
        bank_ifsc=inp.bank_ifsc,
        return_reason_code=inp.return_reason_code,
        original_session_id=inp.original_session_id,
    )

    log.info(
        "re_submit_to_ngch_for_representation.complete",
        instrument_id=inp.instrument_id,
        bank_id=inp.bank_id,
        ngch_reference=ngch_reference,
    )
    return ResubmitNgchResult(
        submitted=True,
        ngch_reference=ngch_reference,
        degraded=False,
    )
