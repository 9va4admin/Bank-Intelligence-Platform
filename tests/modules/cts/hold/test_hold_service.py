"""
Phase F — HoldService TDD tests.

HoldService manages inward instruments placed on hold by an ops_reviewer.
Key constraints:
  - IET clock NEVER pauses during a hold — iet_deadline is immutable
  - Holds are persisted to YugabyteDB (cts.instrument_holds table)
  - Branch notified via email + WhatsApp when hold is placed
  - Every hold/release action writes to Immudb via audit_writer
  - All timing fields recorded for audit trail
"""
import pytest
import time
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now():
    return time.time()


def _make_db():
    """Fake DB pool — records all writes."""
    db = AsyncMock()
    db._rows = []
    db._updates = []

    async def execute(query, *args, **kwargs):
        if "INSERT" in query.upper():
            db._rows.append({"query": query, "args": args})
        elif "UPDATE" in query.upper():
            db._updates.append({"query": query, "args": args})
        return None

    async def fetchrow(query, *args):
        return None  # not found by default

    db.execute = AsyncMock(side_effect=execute)
    db.fetchrow = AsyncMock(side_effect=fetchrow)
    return db


def _make_dispatcher():
    dispatcher = AsyncMock()
    dispatcher._sent = []

    async def send(req):
        dispatcher._sent.append(req)

    dispatcher.send = AsyncMock(side_effect=send)
    return dispatcher


def _make_audit_writer():
    writer = AsyncMock()
    writer._events = []

    async def write(event_type, bank_id, payload):
        writer._events.append({"event_type": event_type, "bank_id": bank_id, "payload": payload})

    writer.write = AsyncMock(side_effect=write)
    return writer


# ---------------------------------------------------------------------------
# 1. HoldRecord schema
# ---------------------------------------------------------------------------

class TestHoldRecord:
    def test_hold_record_importable(self):
        from modules.cts.hold.hold_service import HoldRecord
        assert HoldRecord is not None

    def test_hold_record_required_fields(self):
        from modules.cts.hold.hold_service import HoldRecord
        now = _now()
        rec = HoldRecord(
            instrument_id="INST001",
            bank_id="test-bank",
            held_by="reviewer-1",
            held_at=now,
            iet_deadline=now + 3600,
            hold_reason="Needs branch confirmation",
        )
        assert rec.instrument_id == "INST001"
        assert rec.held_by == "reviewer-1"

    def test_hold_record_iet_deadline_immutable(self):
        """IET deadline must be set at creation and never change."""
        from modules.cts.hold.hold_service import HoldRecord
        now = _now()
        deadline = now + 3600
        rec = HoldRecord(
            instrument_id="INST001", bank_id="test-bank",
            held_by="reviewer-1", held_at=now,
            iet_deadline=deadline, hold_reason="reason",
        )
        assert rec.iet_deadline == deadline

    def test_hold_record_optional_fields_default_none(self):
        from modules.cts.hold.hold_service import HoldRecord
        now = _now()
        rec = HoldRecord(
            instrument_id="INST001", bank_id="test-bank",
            held_by="reviewer-1", held_at=now,
            iet_deadline=now + 3600, hold_reason="reason",
        )
        assert rec.released_at is None
        assert rec.branch_notified_at is None
        assert rec.branch_note is None
        assert rec.branch_recommendation is None

    def test_hold_record_with_all_fields(self):
        from modules.cts.hold.hold_service import HoldRecord
        now = _now()
        rec = HoldRecord(
            instrument_id="INST001", bank_id="test-bank",
            held_by="reviewer-1", held_at=now,
            iet_deadline=now + 3600, hold_reason="reason",
            released_at=now + 600,
            branch_notified_at=now + 5,
            branch_note="Branch confirms account closed",
            branch_recommendation="RETURN",
        )
        assert rec.branch_recommendation == "RETURN"
        assert rec.released_at is not None


# ---------------------------------------------------------------------------
# 2. HoldService initialises
# ---------------------------------------------------------------------------

class TestHoldServiceInit:
    def test_hold_service_importable(self):
        from modules.cts.hold.hold_service import HoldService
        assert HoldService is not None

    def test_hold_service_instantiable(self):
        from modules.cts.hold.hold_service import HoldService
        db = _make_db()
        dispatcher = _make_dispatcher()
        audit_writer = _make_audit_writer()
        svc = HoldService(db_pool=db, dispatcher=dispatcher, audit_writer=audit_writer)
        assert svc is not None


# ---------------------------------------------------------------------------
# 3. place_hold — persist + notify + audit
# ---------------------------------------------------------------------------

class TestPlaceHold:
    @pytest.mark.asyncio
    async def test_place_hold_returns_hold_record(self):
        from modules.cts.hold.hold_service import HoldService
        db = _make_db()
        svc = HoldService(db_pool=db, dispatcher=_make_dispatcher(), audit_writer=_make_audit_writer())
        now = _now()
        record = await svc.place_hold(
            instrument_id="INST001",
            bank_id="test-bank",
            reviewer_id="reviewer-1",
            hold_reason="Needs branch signature check",
            iet_deadline=now + 3600,
            branch_contact={"email": "mgr@branch.com", "phone": "+919876543210"},
        )
        assert record.instrument_id == "INST001"
        assert record.held_by == "reviewer-1"
        assert record.iet_deadline == pytest.approx(now + 3600)

    @pytest.mark.asyncio
    async def test_place_hold_writes_to_db(self):
        from modules.cts.hold.hold_service import HoldService
        db = _make_db()
        svc = HoldService(db_pool=db, dispatcher=_make_dispatcher(), audit_writer=_make_audit_writer())
        await svc.place_hold(
            instrument_id="INST002", bank_id="test-bank",
            reviewer_id="reviewer-1", hold_reason="reason",
            iet_deadline=_now() + 3600,
            branch_contact={"email": "mgr@branch.com"},
        )
        assert db.execute.call_count >= 1

    @pytest.mark.asyncio
    async def test_place_hold_sends_email_to_branch(self):
        from modules.cts.hold.hold_service import HoldService
        db = _make_db()
        dispatcher = _make_dispatcher()
        svc = HoldService(db_pool=db, dispatcher=dispatcher, audit_writer=_make_audit_writer())
        await svc.place_hold(
            instrument_id="INST003", bank_id="test-bank",
            reviewer_id="reviewer-1", hold_reason="reason",
            iet_deadline=_now() + 3600,
            branch_contact={"email": "mgr@branch.com"},
        )
        email_sent = any(
            getattr(r, "channel", None) == "email"
            for r in dispatcher._sent
        )
        assert email_sent

    @pytest.mark.asyncio
    async def test_place_hold_sends_whatsapp_when_phone_provided(self):
        from modules.cts.hold.hold_service import HoldService
        db = _make_db()
        dispatcher = _make_dispatcher()
        svc = HoldService(db_pool=db, dispatcher=dispatcher, audit_writer=_make_audit_writer())
        await svc.place_hold(
            instrument_id="INST004", bank_id="test-bank",
            reviewer_id="reviewer-1", hold_reason="reason",
            iet_deadline=_now() + 3600,
            branch_contact={"email": "mgr@branch.com", "phone": "+919876543210"},
        )
        wa_sent = any(
            getattr(r, "channel", None) == "whatsapp"
            for r in dispatcher._sent
        )
        assert wa_sent

    @pytest.mark.asyncio
    async def test_place_hold_writes_audit_event(self):
        from modules.cts.hold.hold_service import HoldService
        db = _make_db()
        audit_writer = _make_audit_writer()
        svc = HoldService(db_pool=db, dispatcher=_make_dispatcher(), audit_writer=audit_writer)
        await svc.place_hold(
            instrument_id="INST005", bank_id="test-bank",
            reviewer_id="reviewer-1", hold_reason="reason",
            iet_deadline=_now() + 3600,
            branch_contact={"email": "mgr@branch.com"},
        )
        assert len(audit_writer._events) >= 1
        event = audit_writer._events[0]
        assert event["event_type"] == "CTS_WF_HOLD_PLACED"
        assert event["bank_id"] == "test-bank"

    @pytest.mark.asyncio
    async def test_place_hold_records_branch_notified_at(self):
        from modules.cts.hold.hold_service import HoldService
        db = _make_db()
        svc = HoldService(db_pool=db, dispatcher=_make_dispatcher(), audit_writer=_make_audit_writer())
        record = await svc.place_hold(
            instrument_id="INST006", bank_id="test-bank",
            reviewer_id="reviewer-1", hold_reason="reason",
            iet_deadline=_now() + 3600,
            branch_contact={"email": "mgr@branch.com"},
        )
        assert record.branch_notified_at is not None
        assert record.branch_notified_at > 0


# ---------------------------------------------------------------------------
# 4. IET clock never pauses during hold
# ---------------------------------------------------------------------------

class TestIETClockNeverPauses:
    @pytest.mark.asyncio
    async def test_iet_deadline_unchanged_after_place_hold(self):
        from modules.cts.hold.hold_service import HoldService
        db = _make_db()
        svc = HoldService(db_pool=db, dispatcher=_make_dispatcher(), audit_writer=_make_audit_writer())
        deadline = _now() + 7200  # 2 hours from now
        record = await svc.place_hold(
            instrument_id="INST007", bank_id="test-bank",
            reviewer_id="reviewer-1", hold_reason="reason",
            iet_deadline=deadline,
            branch_contact={"email": "mgr@branch.com"},
        )
        assert record.iet_deadline == pytest.approx(deadline)

    @pytest.mark.asyncio
    async def test_release_hold_does_not_change_iet_deadline(self):
        from modules.cts.hold.hold_service import HoldService, HoldRecord
        db = _make_db()
        deadline = _now() + 3600
        svc = HoldService(db_pool=db, dispatcher=_make_dispatcher(), audit_writer=_make_audit_writer())
        record = await svc.place_hold(
            instrument_id="INST008", bank_id="test-bank",
            reviewer_id="reviewer-1", hold_reason="reason",
            iet_deadline=deadline,
            branch_contact={"email": "mgr@branch.com"},
        )
        released = await svc.release_hold(
            instrument_id="INST008",
            bank_id="test-bank",
            reviewer_id="reviewer-1",
            hold_record=record,
        )
        assert released.iet_deadline == pytest.approx(deadline)


# ---------------------------------------------------------------------------
# 5. release_hold
# ---------------------------------------------------------------------------

class TestReleaseHold:
    @pytest.mark.asyncio
    async def test_release_hold_sets_released_at(self):
        from modules.cts.hold.hold_service import HoldService
        db = _make_db()
        svc = HoldService(db_pool=db, dispatcher=_make_dispatcher(), audit_writer=_make_audit_writer())
        before = _now()
        record = await svc.place_hold(
            instrument_id="INST009", bank_id="test-bank",
            reviewer_id="reviewer-1", hold_reason="reason",
            iet_deadline=before + 3600,
            branch_contact={"email": "mgr@branch.com"},
        )
        released = await svc.release_hold(
            instrument_id="INST009",
            bank_id="test-bank",
            reviewer_id="reviewer-1",
            hold_record=record,
        )
        assert released.released_at is not None
        assert released.released_at >= before

    @pytest.mark.asyncio
    async def test_release_hold_writes_audit_event(self):
        from modules.cts.hold.hold_service import HoldService
        db = _make_db()
        audit_writer = _make_audit_writer()
        svc = HoldService(db_pool=db, dispatcher=_make_dispatcher(), audit_writer=audit_writer)
        record = await svc.place_hold(
            instrument_id="INST010", bank_id="test-bank",
            reviewer_id="reviewer-1", hold_reason="reason",
            iet_deadline=_now() + 3600,
            branch_contact={"email": "mgr@branch.com"},
        )
        audit_writer._events.clear()  # reset so only release event counted
        await svc.release_hold(
            instrument_id="INST010",
            bank_id="test-bank",
            reviewer_id="reviewer-1",
            hold_record=record,
        )
        release_events = [e for e in audit_writer._events if e["event_type"] == "CTS_WF_HOLD_RELEASED"]
        assert len(release_events) >= 1

    @pytest.mark.asyncio
    async def test_release_hold_accepts_branch_note(self):
        from modules.cts.hold.hold_service import HoldService
        db = _make_db()
        svc = HoldService(db_pool=db, dispatcher=_make_dispatcher(), audit_writer=_make_audit_writer())
        record = await svc.place_hold(
            instrument_id="INST011", bank_id="test-bank",
            reviewer_id="reviewer-1", hold_reason="reason",
            iet_deadline=_now() + 3600,
            branch_contact={"email": "mgr@branch.com"},
        )
        released = await svc.release_hold(
            instrument_id="INST011",
            bank_id="test-bank",
            reviewer_id="reviewer-1",
            hold_record=record,
            branch_note="Account confirmed closed by branch",
            branch_recommendation="RETURN",
        )
        assert released.branch_note == "Account confirmed closed by branch"
        assert released.branch_recommendation == "RETURN"

    @pytest.mark.asyncio
    async def test_release_hold_updates_db(self):
        from modules.cts.hold.hold_service import HoldService
        db = _make_db()
        svc = HoldService(db_pool=db, dispatcher=_make_dispatcher(), audit_writer=_make_audit_writer())
        record = await svc.place_hold(
            instrument_id="INST012", bank_id="test-bank",
            reviewer_id="reviewer-1", hold_reason="reason",
            iet_deadline=_now() + 3600,
            branch_contact={"email": "mgr@branch.com"},
        )
        db._updates.clear()
        await svc.release_hold(
            instrument_id="INST012",
            bank_id="test-bank",
            reviewer_id="reviewer-1",
            hold_record=record,
        )
        assert len(db._updates) >= 1


# ---------------------------------------------------------------------------
# 6. IET timing fields on place_hold and release_hold
# ---------------------------------------------------------------------------

class TestIETTimingFields:
    @pytest.mark.asyncio
    async def test_place_hold_records_iet_remaining_at_hold_start(self):
        from modules.cts.hold.hold_service import HoldService
        db = _make_db()
        svc = HoldService(db_pool=db, dispatcher=_make_dispatcher(), audit_writer=_make_audit_writer())
        now = _now()
        iet_deadline = now + 3600
        record = await svc.place_hold(
            instrument_id="INST013", bank_id="test-bank",
            reviewer_id="reviewer-1", hold_reason="reason",
            iet_deadline=iet_deadline,
            branch_contact={"email": "mgr@branch.com"},
        )
        assert record.iet_remaining_at_hold_start is not None
        # Should be ~3600 seconds (allow ±2s for test execution time)
        assert 3598 <= record.iet_remaining_at_hold_start <= 3602

    @pytest.mark.asyncio
    async def test_place_hold_iet_remaining_is_zero_when_past_deadline(self):
        from modules.cts.hold.hold_service import HoldService
        db = _make_db()
        svc = HoldService(db_pool=db, dispatcher=_make_dispatcher(), audit_writer=_make_audit_writer())
        past_deadline = _now() - 10  # IET already expired
        record = await svc.place_hold(
            instrument_id="INST014", bank_id="test-bank",
            reviewer_id="reviewer-1", hold_reason="reason",
            iet_deadline=past_deadline,
            branch_contact={"email": "mgr@branch.com"},
        )
        assert record.iet_remaining_at_hold_start == 0.0

    @pytest.mark.asyncio
    async def test_release_hold_computes_hold_duration(self):
        from modules.cts.hold.hold_service import HoldService
        import time as t
        db = _make_db()
        svc = HoldService(db_pool=db, dispatcher=_make_dispatcher(), audit_writer=_make_audit_writer())
        record = await svc.place_hold(
            instrument_id="INST015", bank_id="test-bank",
            reviewer_id="reviewer-1", hold_reason="reason",
            iet_deadline=_now() + 3600,
            branch_contact={"email": "mgr@branch.com"},
        )
        released = await svc.release_hold(
            instrument_id="INST015",
            bank_id="test-bank",
            reviewer_id="reviewer-1",
            hold_record=record,
        )
        assert released.hold_duration_seconds is not None
        assert released.hold_duration_seconds >= 0.0

    @pytest.mark.asyncio
    async def test_release_hold_iet_remaining_at_release_non_negative(self):
        from modules.cts.hold.hold_service import HoldService
        db = _make_db()
        svc = HoldService(db_pool=db, dispatcher=_make_dispatcher(), audit_writer=_make_audit_writer())
        record = await svc.place_hold(
            instrument_id="INST016", bank_id="test-bank",
            reviewer_id="reviewer-1", hold_reason="reason",
            iet_deadline=_now() + 3600,
            branch_contact={"email": "mgr@branch.com"},
        )
        released = await svc.release_hold(
            instrument_id="INST016",
            bank_id="test-bank",
            reviewer_id="reviewer-1",
            hold_record=record,
        )
        assert released.iet_remaining_at_release is not None
        assert released.iet_remaining_at_release >= 0.0

    @pytest.mark.asyncio
    async def test_release_hold_iet_consumed_equals_hold_duration(self):
        """IET clock never pauses — consumed seconds == hold duration seconds."""
        from modules.cts.hold.hold_service import HoldService
        db = _make_db()
        svc = HoldService(db_pool=db, dispatcher=_make_dispatcher(), audit_writer=_make_audit_writer())
        record = await svc.place_hold(
            instrument_id="INST017", bank_id="test-bank",
            reviewer_id="reviewer-1", hold_reason="reason",
            iet_deadline=_now() + 3600,
            branch_contact={"email": "mgr@branch.com"},
        )
        released = await svc.release_hold(
            instrument_id="INST017",
            bank_id="test-bank",
            reviewer_id="reviewer-1",
            hold_record=record,
        )
        assert released.iet_consumed_on_hold == pytest.approx(released.hold_duration_seconds)

    @pytest.mark.asyncio
    async def test_release_hold_timing_in_audit_payload(self):
        from modules.cts.hold.hold_service import HoldService
        db = _make_db()
        audit_writer = _make_audit_writer()
        svc = HoldService(db_pool=db, dispatcher=_make_dispatcher(), audit_writer=audit_writer)
        record = await svc.place_hold(
            instrument_id="INST018", bank_id="test-bank",
            reviewer_id="reviewer-1", hold_reason="reason",
            iet_deadline=_now() + 3600,
            branch_contact={"email": "mgr@branch.com"},
        )
        audit_writer._events.clear()
        await svc.release_hold(
            instrument_id="INST018",
            bank_id="test-bank",
            reviewer_id="reviewer-1",
            hold_record=record,
        )
        release_event = next(e for e in audit_writer._events if e["event_type"] == "CTS_WF_HOLD_RELEASED")
        assert "hold_duration_seconds" in release_event["payload"]
        assert "iet_remaining_at_release" in release_event["payload"]
        assert "iet_consumed_on_hold" in release_event["payload"]

    @pytest.mark.asyncio
    async def test_place_hold_timing_in_audit_payload(self):
        from modules.cts.hold.hold_service import HoldService
        db = _make_db()
        audit_writer = _make_audit_writer()
        svc = HoldService(db_pool=db, dispatcher=_make_dispatcher(), audit_writer=audit_writer)
        await svc.place_hold(
            instrument_id="INST019", bank_id="test-bank",
            reviewer_id="reviewer-1", hold_reason="reason",
            iet_deadline=_now() + 3600,
            branch_contact={"email": "mgr@branch.com"},
        )
        place_event = next(e for e in audit_writer._events if e["event_type"] == "CTS_WF_HOLD_PLACED")
        assert "iet_remaining_at_hold_start" in place_event["payload"]
        assert "iet_deadline" in place_event["payload"]


# ---------------------------------------------------------------------------
# 7. HoldEscalationWorkflow — input schema and signal
# ---------------------------------------------------------------------------

class TestHoldEscalationWorkflow:
    def test_workflow_importable(self):
        from modules.cts.workflows.hold_escalation_workflow import HoldEscalationWorkflow
        assert HoldEscalationWorkflow is not None

    def test_input_importable(self):
        from modules.cts.workflows.hold_escalation_workflow import HoldEscalationInput
        assert HoldEscalationInput is not None

    def test_input_required_fields(self):
        from modules.cts.workflows.hold_escalation_workflow import HoldEscalationInput
        now = _now()
        inp = HoldEscalationInput(
            instrument_id="INST001",
            bank_id="test-bank",
            reviewer_id="reviewer-1",
            iet_deadline=now + 3600,
            held_at=now,
        )
        assert inp.instrument_id == "INST001"
        assert inp.bank_id == "test-bank"
        assert inp.iet_deadline == pytest.approx(now + 3600)

    def test_input_optional_fields_default_none(self):
        from modules.cts.workflows.hold_escalation_workflow import HoldEscalationInput
        now = _now()
        inp = HoldEscalationInput(
            instrument_id="INST001", bank_id="test-bank",
            reviewer_id="reviewer-1", iet_deadline=now + 3600, held_at=now,
        )
        assert inp.branch_email is None
        assert inp.ops_manager_email is None

    def test_workflow_has_released_signal(self):
        from modules.cts.workflows.hold_escalation_workflow import HoldEscalationWorkflow
        # The `released` signal must exist on the class (registered via @workflow.signal)
        assert hasattr(HoldEscalationWorkflow, "released")

    def test_activities_importable(self):
        from modules.cts.workflows.activities.hold_escalation import (
            send_hold_reminder,
            send_hold_critical_alert,
            send_hold_p0_alert,
        )
        assert send_hold_reminder is not None
        assert send_hold_critical_alert is not None
        assert send_hold_p0_alert is not None

    def test_all_three_escalation_activities_are_distinct(self):
        from modules.cts.workflows.activities.hold_escalation import (
            send_hold_reminder,
            send_hold_critical_alert,
            send_hold_p0_alert,
        )
        assert send_hold_reminder is not send_hold_critical_alert
        assert send_hold_critical_alert is not send_hold_p0_alert
        assert send_hold_reminder is not send_hold_p0_alert


# ---------------------------------------------------------------------------
# 8. HoldService no-WhatsApp path
# ---------------------------------------------------------------------------

class TestHoldServiceNoWhatsApp:
    @pytest.mark.asyncio
    async def test_place_hold_without_phone_sends_only_email(self):
        from modules.cts.hold.hold_service import HoldService
        db = _make_db()
        dispatcher = _make_dispatcher()
        svc = HoldService(db_pool=db, dispatcher=dispatcher, audit_writer=_make_audit_writer())
        await svc.place_hold(
            instrument_id="INST020", bank_id="test-bank",
            reviewer_id="reviewer-1", hold_reason="reason",
            iet_deadline=_now() + 3600,
            branch_contact={"email": "mgr@branch.com"},  # no phone
        )
        email_count = sum(1 for r in dispatcher._sent if getattr(r, "channel", None) == "email")
        wa_count = sum(1 for r in dispatcher._sent if getattr(r, "channel", None) == "whatsapp")
        assert email_count >= 1
        assert wa_count == 0

    @pytest.mark.asyncio
    async def test_place_hold_without_email_sends_no_notifications(self):
        from modules.cts.hold.hold_service import HoldService
        db = _make_db()
        dispatcher = _make_dispatcher()
        svc = HoldService(db_pool=db, dispatcher=dispatcher, audit_writer=_make_audit_writer())
        await svc.place_hold(
            instrument_id="INST021", bank_id="test-bank",
            reviewer_id="reviewer-1", hold_reason="reason",
            iet_deadline=_now() + 3600,
            branch_contact={},  # no email, no phone
        )
        assert len(dispatcher._sent) == 0
