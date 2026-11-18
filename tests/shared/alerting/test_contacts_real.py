"""Alert contacts on the real dev YugabyteDB: add an address, verify it with a code, expiry and attempt limits, masked listing, encryption, bank isolation."""
import asyncio
import socket
import uuid

import asyncpg
import pytest

from shared.alerting.contacts import ContactInvalid, ContactStore

HOST, PORT = "localhost", 15433

pytestmark = [pytest.mark.integration]


def _up():
    try:
        socket.create_connection((HOST, PORT), timeout=1).close()
        return True
    except OSError:
        return False


pytestmark.append(pytest.mark.skipif(not _up(), reason="dev YugabyteDB not reachable"))
BANKS: list[str] = []


def db(fn):
    def wrapper():
        async def go():
            pool = await asyncpg.create_pool(host=HOST, port=PORT, user="yugabyte", password="yugabyte", database="yugabyte", min_size=1, max_size=3)
            bank = f"ct-{uuid.uuid4().hex[:8]}"
            BANKS.append(bank)
            try:
                await fn(ContactStore(pool, pii_key="contacts-key-not-a-secret", pepper="contacts-pepper-not-a-secret", max_attempts=3), pool, bank)
            finally:
                await pool.execute("DELETE FROM platform.alert_contacts WHERE bank_id = ANY($1::text[])", BANKS)
                BANKS.clear()
                await pool.close()
        asyncio.run(go())
    return wrapper


@db
async def test_a_new_contact_is_unverified_listed_masked_and_its_address_is_stored_encrypted(store, pool, bank):
    contact, code = await store.add(bank, "email", "Ops@Bank.Example", "Ops desk", "admin-1")
    assert contact.status == "UNVERIFIED" and len(code) == 6 and code.isdigit()
    listed = (await store.list(bank))[0]
    assert listed.address_masked != "ops@bank.example" and "@" in listed.address_masked and listed.label == "Ops desk"
    raw = await pool.fetchrow("SELECT address_enc, address_hash, code_hash FROM platform.alert_contacts WHERE contact_id=$1", contact.contact_id)
    assert b"bank.example" not in bytes(raw["address_enc"]) and code not in raw["code_hash"] and "bank.example" not in raw["address_hash"]
    assert await store.address(bank, contact.contact_id) == "ops@bank.example"                    # lower-cased, decrypted only for sending


@db
async def test_the_right_code_verifies_the_contact_once_and_records_who(store, pool, bank):
    contact, code = await store.add(bank, "email", "a@bank.example", "", "admin-1")
    assert (await store.verify(bank, contact.contact_id, "000000" if code != "000000" else "111111", "admin-2")).reason == "wrong_code"
    ok = await store.verify(bank, contact.contact_id, code, "admin-2")
    assert ok.ok and ok.reason == "ok"
    listed = (await store.list(bank))[0]
    assert listed.status == "VERIFIED" and listed.verified_by == "admin-2" and listed.verified_at is not None
    assert (await store.verify(bank, contact.contact_id, code, "admin-2")).reason == "already_verified"       # a code is single use


@db
async def test_an_expired_code_and_too_many_wrong_tries_are_refused_until_a_new_code_is_sent(store, pool, bank):
    contact, code = await store.add(bank, "phone", "+919800000001", "", "admin-1")
    await pool.execute("UPDATE platform.alert_contacts SET code_expires_at = NOW() - interval '1 minute' WHERE contact_id=$1", contact.contact_id)
    assert (await store.verify(bank, contact.contact_id, code, "a")).reason == "expired"
    fresh = await store.issue_code(bank, contact.contact_id)
    wrong = "000000" if fresh != "000000" else "111111"
    for _ in range(3):
        assert (await store.verify(bank, contact.contact_id, wrong, "a")).reason == "wrong_code"
    assert (await store.verify(bank, contact.contact_id, fresh, "a")).reason == "too_many_attempts"            # even the right code, until a new one is sent
    newer = await store.issue_code(bank, contact.contact_id)
    assert (await store.verify(bank, contact.contact_id, newer, "a")).ok


@db
async def test_addresses_are_checked_and_not_added_twice(store, pool, bank):
    for kind, bad in (("email", "not-an-email"), ("phone", "98000"), ("phone", "+91 98000 00001x"), ("fax", "x")):
        with pytest.raises(ContactInvalid):
            await store.add(bank, kind, bad, "", "a")
    await store.add(bank, "email", "dup@bank.example", "", "a")
    with pytest.raises(ContactInvalid) as e:
        await store.add(bank, "email", "DUP@bank.example", "", "a")
    assert e.value.code == "duplicate"


@db
async def test_unverified_reports_only_addresses_that_are_not_verified_and_banks_are_kept_apart(store, pool, bank):
    a, ca = await store.add(bank, "email", "ok@bank.example", "", "x")
    await store.verify(bank, a.contact_id, ca, "x")
    await store.add(bank, "email", "pending@bank.example", "", "x")
    missing = await store.unverified(bank, ["ok@bank.example", "pending@bank.example", "unknown@bank.example", "OK@bank.example"])
    assert sorted(missing) == ["pending@bank.example", "unknown@bank.example"]
    other = await store.unverified(bank + "-other", ["ok@bank.example"])
    assert other == ["ok@bank.example"]                                                                     # verified for one bank is not verified for another


@db
async def test_a_contact_can_be_removed_and_an_unknown_one_is_not_found(store, pool, bank):
    c, _ = await store.add(bank, "email", "gone@bank.example", "", "x")
    assert await store.remove(bank, c.contact_id) is True and await store.list(bank) == []
    assert await store.remove(bank, c.contact_id) is False
    assert (await store.verify(bank, "nope", "123456", "x")).reason == "not_found"
