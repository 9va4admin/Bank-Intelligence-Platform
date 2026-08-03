"""
HoldService — places and releases holds on inward CTS instruments.

A "hold" means an ops_reviewer has paused the instrument in the review queue
and notified the branch for additional information (account details, drawer
confirmation, stop-payment status, etc.).

CRITICAL constraint: IET clock NEVER pauses during a hold.
The iet_deadline field is immutable after creation. The IETWatchdogWorkflow
(running as a sibling) will still file at T-30s regardless of hold status.
Ops must release the hold and make a decision before IET expires.

Flow:
  1. ops_reviewer clicks "Hold" → place_hold() called
  2. HoldRecord created and persisted to cts.instrument_holds
  3. Branch notified via email (mandatory) + WhatsApp (if phone available)
  4. Audit event written: CTS_WF_HOLD_PLACED
  5. Branch responds (out of band) — reviewer adds note via UI
  6. ops_reviewer clicks "Release Hold" → release_hold() called
  7. HoldRecord updated with released_at, branch_note, branch_recommendation
  8. Audit event written: CTS_WF_HOLD_RELEASED
  9. Instrument re-enters the review queue for final decision
"""
from __future__ import annotations

import time
from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()


class HoldRecord(BaseModel):
    model_config = ConfigDict(frozen=False)  # mutable — fields updated on release

    instrument_id: str
    bank_id: str
    held_by: str                     # ops_reviewer user_id
    held_at: float                   # Unix timestamp — when hold was placed
    iet_deadline: float              # IMMUTABLE — IET clock never pauses
    hold_reason: str                 # ops_reviewer's reason text

    # IET timing — computed at placement (iet_deadline - held_at)
    iet_remaining_at_hold_start: Optional[float] = None   # seconds of IET remaining when held

    # Set after branch notification
    branch_notified_at: Optional[float] = None

    # Set on release
    released_at: Optional[float] = None
    released_by: Optional[str] = None
    branch_note: Optional[str] = None         # reviewer notes from branch conversation
    branch_recommendation: Optional[str] = None  # "CONFIRM" | "RETURN" | None

    # IET timing — computed at release
    hold_duration_seconds: Optional[float] = None     # released_at - held_at
    iet_remaining_at_release: Optional[float] = None  # iet_deadline - released_at
    iet_consumed_on_hold: Optional[float] = None      # hold_duration_seconds (IET clock never pauses)


class HoldService:
    def __init__(self, db_pool, dispatcher, audit_writer) -> None:
        self._db = db_pool
        self._dispatcher = dispatcher
        self._audit = audit_writer

    async def place_hold(
        self,
        instrument_id: str,
        bank_id: str,
        reviewer_id: str,
        hold_reason: str,
        iet_deadline: float,
        branch_contact: dict,
    ) -> HoldRecord:
        """Place a hold on an instrument and notify the branch.

        Args:
            instrument_id: the instrument being held
            bank_id: bank context
            reviewer_id: the ops_reviewer placing the hold
            hold_reason: free-text reason (shown to branch)
            iet_deadline: Unix timestamp — IET deadline (NEVER changed by this function)
            branch_contact: dict with "email" (required) and optionally "phone" (WhatsApp)

        Returns:
            HoldRecord with branch_notified_at set
        """
        now = time.time()
        iet_remaining_at_start = max(0.0, iet_deadline - now)
        record = HoldRecord(
            instrument_id=instrument_id,
            bank_id=bank_id,
            held_by=reviewer_id,
            held_at=now,
            iet_deadline=iet_deadline,
            hold_reason=hold_reason,
            iet_remaining_at_hold_start=iet_remaining_at_start,
        )

        # Persist to DB — timing fields stored upfront for audit trail accuracy
        await self._db.execute(
            """
            INSERT INTO cts.instrument_holds
              (instrument_id, bank_id, held_by, held_at, iet_deadline, hold_reason,
               iet_remaining_at_hold_start)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            instrument_id, bank_id, reviewer_id, now, iet_deadline, hold_reason,
            iet_remaining_at_start,
        )

        # Notify branch — email is mandatory
        from shared.notifications.dispatcher import NotificationRequest

        branch_email = branch_contact.get("email")
        if branch_email:
            await self._dispatcher.send(NotificationRequest(
                channel="email",
                recipient=branch_email,
                template_id="cts.hold_placed_branch_notification",
                context={
                    "instrument_id": instrument_id,
                    "held_by": reviewer_id,
                    "hold_reason": hold_reason,
                    "iet_deadline": iet_deadline,
                },
            ))

        # WhatsApp notification if phone number available
        branch_phone = branch_contact.get("phone")
        if branch_phone:
            await self._dispatcher.send(NotificationRequest(
                channel="whatsapp",
                recipient=branch_phone,
                template_id="cts.hold_placed_branch_notification",
                context={
                    "instrument_id": instrument_id,
                    "hold_reason": hold_reason,
                },
            ))

        notified_at = time.time()
        record.branch_notified_at = notified_at

        # Audit — every hold placement is an auditable event with IET timing
        await self._audit.write(
            event_type="CTS_WF_HOLD_PLACED",
            bank_id=bank_id,
            payload={
                "instrument_id": instrument_id,
                "held_by": reviewer_id,
                "hold_reason": hold_reason,
                "iet_deadline": iet_deadline,
                "iet_remaining_at_hold_start": iet_remaining_at_start,
                "branch_notified_at": notified_at,
            },
        )

        log.info(
            "hold.placed",
            instrument_id=instrument_id,
            bank_id=bank_id,
            reviewer_id=reviewer_id,
        )
        return record

    async def release_hold(
        self,
        instrument_id: str,
        bank_id: str,
        reviewer_id: str,
        hold_record: HoldRecord,
        branch_note: Optional[str] = None,
        branch_recommendation: Optional[str] = None,
    ) -> HoldRecord:
        """Release a hold — instrument returns to review queue.

        The IET deadline is never modified. Released_at is stamped now.

        Args:
            instrument_id: the instrument being released
            bank_id: bank context
            reviewer_id: reviewer releasing the hold
            hold_record: the existing HoldRecord to update
            branch_note: optional notes from branch conversation
            branch_recommendation: optional "CONFIRM" | "RETURN" from branch

        Returns:
            Updated HoldRecord with released_at set
        """
        now = time.time()
        hold_duration = now - hold_record.held_at
        iet_remaining_at_release = max(0.0, hold_record.iet_deadline - now)

        hold_record.released_at = now
        hold_record.released_by = reviewer_id
        hold_record.hold_duration_seconds = hold_duration
        hold_record.iet_remaining_at_release = iet_remaining_at_release
        # IET clock never pauses — seconds consumed on hold == hold duration
        hold_record.iet_consumed_on_hold = hold_duration
        if branch_note is not None:
            hold_record.branch_note = branch_note
        if branch_recommendation is not None:
            hold_record.branch_recommendation = branch_recommendation

        # Persist release to DB with full timing fields
        await self._db.execute(
            """
            UPDATE cts.instrument_holds
               SET released_at              = $1,
                   released_by              = $2,
                   branch_note              = $3,
                   branch_recommendation    = $4,
                   hold_duration_seconds    = $5,
                   iet_remaining_at_release = $6,
                   iet_consumed_on_hold     = $7
             WHERE instrument_id = $8 AND bank_id = $9
            """,
            now, reviewer_id, branch_note, branch_recommendation,
            hold_duration, iet_remaining_at_release, hold_duration,
            instrument_id, bank_id,
        )

        # Audit — release event includes full timing for IET impact reporting
        await self._audit.write(
            event_type="CTS_WF_HOLD_RELEASED",
            bank_id=bank_id,
            payload={
                "instrument_id": instrument_id,
                "released_by": reviewer_id,
                "released_at": now,
                "branch_note": branch_note,
                "branch_recommendation": branch_recommendation,
                "iet_deadline": hold_record.iet_deadline,  # confirm it never changed
                "hold_duration_seconds": hold_duration,
                "iet_remaining_at_release": iet_remaining_at_release,
                "iet_consumed_on_hold": hold_duration,
            },
        )

        log.info(
            "hold.released",
            instrument_id=instrument_id,
            bank_id=bank_id,
            reviewer_id=reviewer_id,
        )
        return hold_record
