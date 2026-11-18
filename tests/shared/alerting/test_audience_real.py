"""audience.deliverable_targets on the real dev YugabyteDB: routing targets (a user, a role, an external address ...) become the concrete deliveries
(which address or phone, on which channel). People are reached on the bell by user id; on email and WhatsApp by the contact details of their account."""
import asyncio
import socket
import uuid

import pytest

from shared.alerting.audience import deliverable_targets
from shared.alerting.directory import record_sign_in
from shared.alerting.engine import Target
from shared.alerting.routing_policy import ResolvedTarget

HOST, PORT = "localhost", 15433


def _up():
    try:
        socket.create_connection((HOST, PORT), timeout=1).close()
        return True
    except OSError:
        return False


pytestmark = [pytest.mark.integration, pytest.mark.skipif(not _up(), reason="dev YugabyteDB not reachable")]


class Cfg:
    async def get(self, key):
        from shared.config.config_service import ConfigKeyNotFoundError
        raise ConfigKeyNotFoundError(key)


def _run(fn):
    async def go():
        import asyncpg
        pool = await asyncpg.create_pool(host=HOST, port=PORT, user="yugabyte", password="yugabyte", database="yugabyte", min_size=1, max_size=4)
        bank = f"it-{uuid.uuid4().hex[:8]}"
        try:
            return await fn(pool, bank)
        finally:
            await pool.execute("DELETE FROM platform.local_auth_accounts WHERE bank_id=$1", bank)
            await pool.execute("DELETE FROM platform.user_directory WHERE bank_id=$1", bank)
            await pool.close()
    return asyncio.run(go())


async def _account(pool, bank, user, role, email=None, phone=None, active=True):
    await pool.execute("INSERT INTO platform.local_auth_accounts (user_id, bank_id, entity_type, entity_id, username, password_hash, role, is_active, email, phone) "
                       "VALUES ($1,$2,'BANK',$2,$1,'x',$3,$4,$5,$6)", user, bank, role, active, email, phone)


def RT(kind, ref, *channels):
    return ResolvedTarget(kind=kind, ref=ref, channels=list(channels))


async def _go(pool, bank, targets):
    return await deliverable_targets(targets, pool=pool, config_service=Cfg(), bank_id=bank)


def test_an_external_address_or_phone_is_used_as_given_on_its_channel():
    async def go(pool, bank):
        t, w = await _go(pool, bank, [RT("external", "ops@x.in", "email"), RT("external", "+919800000001", "whatsapp", "sms")])
        assert sorted((x.channel, x.recipient) for x in t) == [("email", "ops@x.in"), ("sms", "+919800000001"), ("whatsapp", "+919800000001")] and w == []
    _run(go)


def test_a_user_is_reached_on_the_bell_by_id_and_on_email_and_whatsapp_by_their_account_contact():
    async def go(pool, bank):
        u = f"{bank}-alice"
        await _account(pool, bank, u, "ops_manager", email="alice@x.in", phone="+919811111111")
        t, w = await _go(pool, bank, [RT("user", u, "bell", "email", "whatsapp")])
        assert sorted((x.channel, x.recipient) for x in t) == [("bell", u), ("email", "alice@x.in"), ("whatsapp", "+919811111111")] and w == []
    _run(go)


def test_a_user_with_no_contact_detail_is_still_reached_on_the_bell_and_the_gap_is_reported():
    async def go(pool, bank):
        t, w = await _go(pool, bank, [RT("user", "idp-user-1", "bell", "email")])
        assert [(x.channel, x.recipient) for x in t] == [("bell", "idp-user-1")] and w == ["no_contact:email:idp-user-1"]
    _run(go)


def test_a_role_reaches_every_active_user_of_that_role_and_not_other_roles_or_banks():
    async def go(pool, bank):
        await _account(pool, bank, f"{bank}-a", "ops_manager", email="a@x.in")
        await _account(pool, bank, f"{bank}-b", "ops_manager", email="b@x.in")
        await _account(pool, bank, f"{bank}-c", "ops_reviewer", email="c@x.in")
        await _account(pool, bank, f"{bank}-d", "ops_manager", email="d@x.in", active=False)
        await record_sign_in(pool, bank, "idp-1", "ops_manager")
        t, w = await _go(pool, bank, [RT("role", "ops_manager", "bell", "email")])
        got = sorted((x.channel, x.recipient) for x in t)
        assert got == sorted([("bell", f"{bank}-a"), ("bell", f"{bank}-b"), ("bell", "idp-1"), ("email", "a@x.in"), ("email", "b@x.in")])
        assert w == ["no_contact:email:idp-1"]
    _run(go)


def test_a_group_is_not_supported_yet_and_says_so():
    async def go(pool, bank):
        t, w = await _go(pool, bank, [RT("group", "everyone", "email")])
        assert t == [] and w == ["group_unsupported:everyone"]
    _run(go)


def test_the_same_delivery_is_listed_once_when_two_targets_lead_to_it():
    async def go(pool, bank):
        u = f"{bank}-a"
        await _account(pool, bank, u, "ops_manager", email="a@x.in")
        t, _ = await _go(pool, bank, [RT("user", u, "email"), RT("role", "ops_manager", "email"), RT("external", "a@x.in", "email")])
        assert [(x.channel, x.recipient) for x in t] == [("email", "a@x.in")]
    _run(go)


def test_a_channel_that_needs_no_address_is_never_looked_up_and_unknown_kinds_are_skipped():
    async def go(pool, bank):
        t, w = await _go(pool, bank, [RT("user", "u1", "bell")])
        assert t == [Target("bell", "u1")] and w == []
        t2, w2 = await _go(pool, bank, [])
        assert t2 == [] and w2 == []
    _run(go)
