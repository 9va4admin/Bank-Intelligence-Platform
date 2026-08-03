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

    # Set after branch notification
    branch_notified_at: Optional[float] = None

    # Set on release
    released_at: Optional[float] = None
    branch_note: Optional[str] = None         # reviewer notes from branch conversation
    branch_recommendation: Optional[str] = None  # "CONFIRM" | "RETURN" | None


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
        record = HoldRecord(
            instrument_id=instrument_id,
            bank_id=bank_id,
            held_by=reviewer_id,
            held_at=now,
            iet_deadline=iet_deadline,
            hold_reason=hold_reason,
        )

        # Persist to DB
        await self._db.execute(
            """
            INSERT INTO cts.instrument_holds
              (instrument_id, bank_id, held_by, held_at, iet_deadline, hold_reason)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            instrument_id, bank_id, reviewer_id, now, iet_deadline, hold_reason,
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

        # Audit — every hold is an auditable decision
        await self._audit.write(
            event_type="CTS_WF_HOLD_PLACED",
            bank_id=bank_id,
            payload={
                "instrument_id": instrument_id,
                "held_by": reviewer_id,
                "hold_reason": hold_reason,
                "iet_deadline": iet_deadline,
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

        hold_record.released_at = now
        if branch_note is not None:
            hold_record.branch_note = branch_note
        if branch_recommendation is not None:
            hold_record.branch_recommendation = branch_recommendation

        # Persist release to DB
        await self._db.execute(
            """
            UPDATE cts.instrument_holds
               SET released_at = $1,
                   branch_note = $2,
                   branch_recommendation = $3
             WHERE instrument_id = $4 AND bank_id = $5
            """,
            now, branch_note, branch_recommendation, instrument_id, bank_id,
        )

        # Audit
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
            },
        )

        log.info(
            "hold.released",
            instrument_id=instrument_id,
            bank_id=bank_id,
            reviewer_id=reviewer_id,
        )
        return hold_record
