"""BellChannel writes alerts into each user's inbox; the recipient lookup finds the people a bank wants on the bell. Real dev YugabyteDB."""
import asyncio
import socket
import uuid
from types import SimpleNamespace

import pytest

from shared.alerting.bell import BellChannel, resolve_bell_users
from shared.alerting.inbox import InboxStore
from shared.alerting.templates import TemplateSettings

HOST, PORT = "localhost", 15433


def _up():
    try:
        socket.create_connection((HOST, PORT), timeout=1).close()
        return True
    except OSError:
        return False


pytestmark = [pytest.mark.integration, pytest.mark.skipif(not _up(), reason="dev YugabyteDB not reachable")]


def _run(fn):
    async def go():
        import asyncpg
        pool = await asyncpg.create_pool(host=HOST, port=PORT, user="yugabyte", password="yugabyte", database="yugabyte", min_size=1, max_size=4)
        bank = f"it-{uuid.uuid4().hex[:8]}"
        try:
            return await fn(pool, bank)
        finally:
            await pool.execute("DELETE FROM platform.user_notifications WHERE bank_id=$1", bank)
            await pool.execute("DELETE FROM platform.local_auth_accounts WHERE bank_id=$1", bank)
            await pool.close()
    return asyncio.run(go())


def _request(user="u1", priority="P0", **ctx):
    context = {"bank_id": "kbl", "event_type": "COMPONENT_DOWN", "severity": "CRITICAL", "component": "redis", "message": "redis is not responding",
               "incident_id": "inc-9", "occurred_at": 0.0, **ctx}
    return SimpleNamespace(recipient=user, template_id="PLATFORM_HEALTH_ALERT", notification_id="n", context=context, priority=priority, channel="bell")


def test_an_alert_lands_in_the_users_inbox_with_a_title_body_severity_and_a_link_into_the_app():
    async def scenario(pool, bank):
        ch = BellChannel(InboxStore(pool), TemplateSettings(incident_path="/ops/incidents/{incident_id}"))
        await ch.send(_request(bank_id=bank))
        item = (await InboxStore(pool).list_for_user(bank, "u1", limit=5)).items[0]
        assert item["severity"] == "P0" and item["title"].startswith("P0 redis") and "redis is not responding" in item["body"]
        assert item["incident_id"] == "inc-9" and item["action_link"] == "/ops/incidents/inc-9"
    _run(scenario)


def test_a_recovery_is_titled_resolved_and_is_not_critical():
    async def scenario(pool, bank):
        ch = BellChannel(InboxStore(pool), TemplateSettings())
        await ch.send(_request(bank_id=bank, event_type="COMPONENT_RECOVERED", message="redis is responding again"))
        item = (await InboxStore(pool).list_for_user(bank, "u1", limit=5)).items[0]
        assert item["title"].startswith("Resolved") and item["severity"] == "P0"
    _run(scenario)


def test_the_channel_refuses_to_send_before_it_is_connected_to_a_store():
    with pytest.raises(RuntimeError):
        asyncio.run(BellChannel(None, TemplateSettings()).send(_request()))


async def _account(pool, bank, user, role, active=True):
    await pool.execute(
        "INSERT INTO platform.local_auth_accounts (user_id, bank_id, entity_type, entity_id, username, password_hash, role, is_active) "
        "VALUES ($1,$2,'BANK',$2,$1,'x',$3,$4)", user, bank, role, active)


def test_the_people_on_the_bell_are_the_active_users_of_the_configured_roles_in_that_bank():
    async def scenario(pool, bank):
        await _account(pool, bank, f"{bank}-a", "ops_manager")
        await _account(pool, bank, f"{bank}-b", "bank_it_admin")
        await _account(pool, bank, f"{bank}-c", "ops_reviewer")
        await _account(pool, bank, f"{bank}-d", "ops_manager", active=False)
        users = await resolve_bell_users(pool, bank, roles=["ops_manager", "bank_it_admin"], limit=50)
        assert sorted(users) == [f"{bank}-a", f"{bank}-b"]
        assert await resolve_bell_users(pool, bank, roles=["ops_manager"], limit=50) == [f"{bank}-a"]
        assert await resolve_bell_users(pool, bank, roles=[], limit=50) == []
        assert await resolve_bell_users(pool, "another-bank", roles=["ops_manager"], limit=50) == []
    _run(scenario)


def test_the_recipient_limit_is_respected():
    async def scenario(pool, bank):
        for i in range(4):
            await _account(pool, bank, f"{bank}-{i}", "ops_manager")
        assert len(await resolve_bell_users(pool, bank, roles=["ops_manager"], limit=2)) == 2
    _run(scenario)
