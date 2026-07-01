"""
TDD tests for modules/cts/kill_switch/kill_switch_event_handler.py

The handler listens to Kafka `platform.config.changed` events for
cts.vision_ai.kill_mode.* keys and:
  1. Writes an immutable audit record to Immudb
  2. Dispatches notifications via NotificationRoutingTable + NotificationDispatcher

Tests verify:
  - handle_engage() writes CTS_KILL_SWITCH_ENGAGED AuditEvent to Immudb
  - handle_engage() calls dispatcher with correct notification requests
  - handle_release() writes CTS_KILL_SWITCH_RELEASED AuditEvent to Immudb
  - handle_release() sends release notifications
  - All Immudb writes happen BEFORE any notification dispatch
  - Handler is resilient: notification failure does not prevent Immudb write
  - Handler validates required context fields
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, call, patch

from shared.audit.audit_event import AuditEventType, AuditEvent
from modules.cts.kill_switch.kill_switch_event_handler import KillSwitchEventHandler


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_hsm():
    hsm = MagicMock()
    hsm.sign = MagicMock(side_effect=lambda data: b"mock-sig-" + data[:8])
    return hsm


def _make_immudb():
    immudb = MagicMock()
    immudb.write_event = AsyncMock(return_value={"tx_id": "tx-001"})
    return immudb


def _make_dispatcher():
    dispatcher = MagicMock()
    dispatcher.send = AsyncMock(return_value={"status": "sent"})
    dispatcher.send_bulk = AsyncMock(return_value=[{"status": "sent"}])
    return dispatcher


def _make_users():
    u1 = MagicMock()
    u1.user_id = "user-it-admin"
    u1.role = "BANK_IT_ADMIN"
    u1.email = "itadmin@bank.com"
    u1.phone = "+919900001111"

    u2 = MagicMock()
    u2.user_id = "user-ops-mgr"
    u2.role = "OPS_MANAGER"
    u2.email = "opsmgr@bank.com"
    u2.phone = "+919900002222"

    u3 = MagicMock()
    u3.user_id = "user-compliance"
    u3.role = "COMPLIANCE_OFFICER"
    u3.email = "compliance@bank.com"
    u3.phone = "+919900003333"

    return [u1, u2, u3]


def _make_handler(immudb=None, dispatcher=None, hsm=None, users=None):
    return KillSwitchEventHandler(
        bank_id="test-bank",
        immudb_client=immudb or _make_immudb(),
        dispatcher=dispatcher or _make_dispatcher(),
        hsm=hsm or _make_hsm(),
        user_resolver=lambda bank_id: users or _make_users(),
    )


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------

class TestKillSwitchEventHandlerInit:
    def test_init_stores_bank_id(self):
        handler = _make_handler()
        assert handler.bank_id == "test-bank"

    def test_init_creates_routing_table(self):
        from shared.notifications.routing import NotificationRoutingTable
        handler = _make_handler()
        assert isinstance(handler.routing_table, NotificationRoutingTable)


# ---------------------------------------------------------------------------
# handle_engage — Immudb write
# ---------------------------------------------------------------------------

class TestHandleEngageImmudb:
    @pytest.mark.asyncio
    async def test_engage_writes_to_immudb(self):
        immudb = _make_immudb()
        handler = _make_handler(immudb=immudb)
        await handler.handle_engage(mode="KC", scope="GLOBAL", activated_by="itadmin@bank.com")
        immudb.write_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_engage_writes_correct_event_type(self):
        immudb = _make_immudb()
        handler = _make_handler(immudb=immudb)
        await handler.handle_engage(mode="KC", scope="GLOBAL", activated_by="itadmin@bank.com")
        call_args = immudb.write_event.call_args
        raw_bytes = call_args[0][0]
        import json
        data = json.loads(raw_bytes)
        assert data["event_type"] == AuditEventType.CTS_KILL_SWITCH_ENGAGED.value

    @pytest.mark.asyncio
    async def test_engage_audit_payload_contains_mode(self):
        immudb = _make_immudb()
        handler = _make_handler(immudb=immudb)
        await handler.handle_engage(mode="KP", scope="SB_OWN", activated_by="itadmin@bank.com")
        call_args = immudb.write_event.call_args
        raw_bytes = call_args[0][0]
        import json
        data = json.loads(raw_bytes)
        assert data["payload"]["mode"] == "KP"

    @pytest.mark.asyncio
    async def test_engage_audit_payload_contains_scope(self):
        immudb = _make_immudb()
        handler = _make_handler(immudb=immudb)
        await handler.handle_engage(mode="KC", scope="SMB", activated_by="itadmin@bank.com")
        call_args = immudb.write_event.call_args
        raw_bytes = call_args[0][0]
        import json
        data = json.loads(raw_bytes)
        assert data["payload"]["scope"] == "SMB"

    @pytest.mark.asyncio
    async def test_engage_audit_payload_contains_activated_by(self):
        immudb = _make_immudb()
        handler = _make_handler(immudb=immudb)
        await handler.handle_engage(mode="KC", scope="GLOBAL", activated_by="ops@bank.com")
        call_args = immudb.write_event.call_args
        raw_bytes = call_args[0][0]
        import json
        data = json.loads(raw_bytes)
        assert data["payload"]["activated_by"] == "ops@bank.com"

    @pytest.mark.asyncio
    async def test_engage_audit_is_hsm_signed(self):
        immudb = _make_immudb()
        hsm = _make_hsm()
        handler = _make_handler(immudb=immudb, hsm=hsm)
        await handler.handle_engage(mode="KC", scope="GLOBAL", activated_by="itadmin@bank.com")
        hsm.sign.assert_called_once()

    @pytest.mark.asyncio
    async def test_engage_audit_written_with_bank_id(self):
        immudb = _make_immudb()
        handler = _make_handler(immudb=immudb)
        await handler.handle_engage(mode="KC", scope="GLOBAL", activated_by="itadmin@bank.com")
        call_args = immudb.write_event.call_args
        raw_bytes = call_args[0][0]
        import json
        data = json.loads(raw_bytes)
        assert data["bank_id"] == "test-bank"


# ---------------------------------------------------------------------------
# handle_engage — notification dispatch
# ---------------------------------------------------------------------------

class TestHandleEngageNotifications:
    @pytest.mark.asyncio
    async def test_engage_calls_send_bulk(self):
        dispatcher = _make_dispatcher()
        handler = _make_handler(dispatcher=dispatcher)
        await handler.handle_engage(mode="KC", scope="GLOBAL", activated_by="itadmin@bank.com")
        dispatcher.send_bulk.assert_called_once()

    @pytest.mark.asyncio
    async def test_engage_notification_requests_not_empty(self):
        dispatcher = _make_dispatcher()
        handler = _make_handler(dispatcher=dispatcher)
        await handler.handle_engage(mode="KC", scope="GLOBAL", activated_by="itadmin@bank.com")
        call_args = dispatcher.send_bulk.call_args
        requests = call_args[0][0]
        assert len(requests) > 0

    @pytest.mark.asyncio
    async def test_engage_context_contains_mode(self):
        dispatcher = _make_dispatcher()
        handler = _make_handler(dispatcher=dispatcher)
        await handler.handle_engage(mode="KP", scope="SB_OWN", activated_by="itadmin@bank.com")
        call_args = dispatcher.send_bulk.call_args
        requests = call_args[0][0]
        assert all(r.context.get("mode") == "KP" for r in requests)

    @pytest.mark.asyncio
    async def test_engage_immudb_called_before_notifications(self):
        call_order = []
        immudb = MagicMock()
        async def _immudb_write(data):
            call_order.append("immudb")
            return {"tx_id": "tx-001"}
        immudb.write_event = _immudb_write

        dispatcher = MagicMock()
        async def _dispatch_bulk(requests):
            call_order.append("notifications")
            return [{"status": "sent"}]
        dispatcher.send_bulk = _dispatch_bulk

        handler = _make_handler(immudb=immudb, dispatcher=dispatcher)
        await handler.handle_engage(mode="KC", scope="GLOBAL", activated_by="itadmin@bank.com")

        assert call_order[0] == "immudb", "Immudb must be written BEFORE notifications"
        assert "notifications" in call_order

    @pytest.mark.asyncio
    async def test_engage_notification_failure_does_not_prevent_immudb_write(self):
        immudb = _make_immudb()
        dispatcher = MagicMock()
        dispatcher.send_bulk = AsyncMock(side_effect=Exception("SMTP timeout"))

        handler = _make_handler(immudb=immudb, dispatcher=dispatcher)
        # Should NOT raise — notification failure is non-fatal
        await handler.handle_engage(mode="KC", scope="GLOBAL", activated_by="itadmin@bank.com")

        immudb.write_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_engage_returns_audit_event_id(self):
        handler = _make_handler()
        result = await handler.handle_engage(mode="KC", scope="GLOBAL", activated_by="itadmin@bank.com")
        assert result["event_id"] is not None
        assert isinstance(result["event_id"], str)

    @pytest.mark.asyncio
    async def test_engage_returns_notification_count(self):
        handler = _make_handler()
        result = await handler.handle_engage(mode="KC", scope="GLOBAL", activated_by="itadmin@bank.com")
        assert "notification_count" in result
        assert result["notification_count"] >= 0


# ---------------------------------------------------------------------------
# handle_release — Immudb write
# ---------------------------------------------------------------------------

class TestHandleReleaseImmudb:
    @pytest.mark.asyncio
    async def test_release_writes_to_immudb(self):
        immudb = _make_immudb()
        handler = _make_handler(immudb=immudb)
        await handler.handle_release(previous_mode="KC", previous_scope="GLOBAL", released_by="itadmin@bank.com")
        immudb.write_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_release_writes_correct_event_type(self):
        immudb = _make_immudb()
        handler = _make_handler(immudb=immudb)
        await handler.handle_release(previous_mode="KC", previous_scope="GLOBAL", released_by="itadmin@bank.com")
        call_args = immudb.write_event.call_args
        raw_bytes = call_args[0][0]
        import json
        data = json.loads(raw_bytes)
        assert data["event_type"] == AuditEventType.CTS_KILL_SWITCH_RELEASED.value

    @pytest.mark.asyncio
    async def test_release_audit_payload_contains_previous_mode(self):
        immudb = _make_immudb()
        handler = _make_handler(immudb=immudb)
        await handler.handle_release(previous_mode="KP", previous_scope="SB_OWN", released_by="itadmin@bank.com")
        call_args = immudb.write_event.call_args
        raw_bytes = call_args[0][0]
        import json
        data = json.loads(raw_bytes)
        assert data["payload"]["previous_mode"] == "KP"

    @pytest.mark.asyncio
    async def test_release_audit_payload_contains_released_by(self):
        immudb = _make_immudb()
        handler = _make_handler(immudb=immudb)
        await handler.handle_release(previous_mode="KC", previous_scope="GLOBAL", released_by="ops@bank.com")
        call_args = immudb.write_event.call_args
        raw_bytes = call_args[0][0]
        import json
        data = json.loads(raw_bytes)
        assert data["payload"]["released_by"] == "ops@bank.com"


# ---------------------------------------------------------------------------
# handle_release — notification dispatch
# ---------------------------------------------------------------------------

class TestHandleReleaseNotifications:
    @pytest.mark.asyncio
    async def test_release_sends_notifications(self):
        dispatcher = _make_dispatcher()
        handler = _make_handler(dispatcher=dispatcher)
        await handler.handle_release(previous_mode="KC", previous_scope="GLOBAL", released_by="itadmin@bank.com")
        dispatcher.send_bulk.assert_called_once()

    @pytest.mark.asyncio
    async def test_release_immudb_called_before_notifications(self):
        call_order = []
        immudb = MagicMock()
        async def _immudb_write(data):
            call_order.append("immudb")
            return {"tx_id": "tx-002"}
        immudb.write_event = _immudb_write

        dispatcher = MagicMock()
        async def _dispatch_bulk(requests):
            call_order.append("notifications")
            return [{"status": "sent"}]
        dispatcher.send_bulk = _dispatch_bulk

        handler = _make_handler(immudb=immudb, dispatcher=dispatcher)
        await handler.handle_release(previous_mode="KC", previous_scope="GLOBAL", released_by="itadmin@bank.com")

        assert call_order[0] == "immudb", "Immudb must be written BEFORE notifications on release"

    @pytest.mark.asyncio
    async def test_release_returns_event_id(self):
        handler = _make_handler()
        result = await handler.handle_release(previous_mode="KP", previous_scope="GLOBAL", released_by="itadmin@bank.com")
        assert "event_id" in result
        assert isinstance(result["event_id"], str)
