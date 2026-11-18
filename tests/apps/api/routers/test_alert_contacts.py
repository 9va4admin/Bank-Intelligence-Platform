"""/v1/admin/alert-contacts: add an address, a code is sent to it, the person who has it gives the code back, and only then is it a verified contact.
Real ASGI against the real dev YugabyteDB. Skipped when the database is not reachable."""
import asyncio
import re
import socket
import uuid

import httpx
import pytest
from fastapi import FastAPI

from shared.alerting.audit import AlertAuditor

HOST, PORT = "localhost", 15433


def _up():
    try:
        socket.create_connection((HOST, PORT), timeout=1).close()
        return True
    except OSError:
        return False


pytestmark = [pytest.mark.integration, pytest.mark.skipif(not _up(), reason="dev YugabyteDB not reachable")]


class Cfg:
    def __init__(self):
        self.v = {"alerting.contact_code_ttl_minutes": 15, "alerting.contact_code_max_attempts": 3}

    async def get(self, key):
        from shared.config.config_service import ConfigKeyNotFoundError
        if key not in self.v:
            raise ConfigKeyNotFoundError(key)
        return self.v[key]

    async def get_secret(self, key):
        return "contacts-secret-not-a-real-one"


class Dispatcher:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    async def send(self, request):
        if self.fail:
            raise ConnectionError("smtp down")
        self.sent.append(request)

    def last_code(self):
        return re.search(r"\b(\d{6})\b", self.sent[-1].context["message"]).group(1)


def _scenario(fn, *, role="bank_it_admin", dispatcher="default"):
    async def go():
        import asyncpg
        from apps.api.routers.alert_contacts import get_current_user, router_v1
        pool = await asyncpg.create_pool(host=HOST, port=PORT, user="yugabyte", password="yugabyte", database="yugabyte", min_size=1, max_size=4)
        bank = f"ac-{uuid.uuid4().hex[:8]}"
        events = []

        async def sink(event_type, bank_id, entity_id, actor_id, payload):
            events.append((event_type, entity_id, actor_id, payload))
            return "tx"
        who = {"role": role}
        disp = Dispatcher() if dispatcher == "default" else dispatcher
        app = FastAPI()
        app.include_router(router_v1)
        app.dependency_overrides[get_current_user] = lambda: {"bank_id": bank, "user_id": "admin-1", "role": who["role"]}
        app.state.db_pool_cts = pool
        app.state.config_service = Cfg()
        app.state.alert_auditor = AlertAuditor(sink)
        app.state.alert_dispatcher = disp
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
        try:
            return await fn(client, bank, pool, disp, events, who)
        finally:
            await pool.execute("DELETE FROM platform.alert_contacts WHERE bank_id LIKE 'ac-%'")
            await client.aclose()
            await pool.close()
    return asyncio.run(go())


def test_adding_an_address_sends_it_a_code_and_the_response_never_shows_the_address_or_the_code():
    async def fn(client, bank, pool, disp, events, who):
        r = await client.post("/v1/admin/alert-contacts", json={"kind": "email", "address": "Duty@Bank.Example", "label": "Duty officer"})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["sent"] is True and body["contact"]["status"] == "UNVERIFIED" and body["contact"]["label"] == "Duty officer"
        assert "duty@bank.example" not in r.text.lower() and disp.last_code() not in r.text
        assert disp.sent[0].channel == "email" and disp.sent[0].recipient == "duty@bank.example" and disp.sent[0].priority == "P0"
        audit = [e for e in events if e[0] == "ALERT_CONTACT_CHANGED"]
        assert audit and "bank.example" not in str(audit) and audit[0][2] == "admin-1"
    _scenario(fn)


def test_the_right_code_verifies_the_contact_and_the_list_then_says_so_in_masked_form():
    async def fn(client, bank, pool, disp, events, who):
        created = (await client.post("/v1/admin/alert-contacts", json={"kind": "email", "address": "duty@bank.example"})).json()["contact"]
        v = await client.post(f"/v1/admin/alert-contacts/{created['contact_id']}/verify", json={"code": disp.last_code()})
        assert v.status_code == 200 and v.json() == {"ok": True, "reason": "ok"}
        listed = (await client.get("/v1/admin/alert-contacts")).json()["contacts"]
        assert listed[0]["status"] == "VERIFIED" and listed[0]["verified_by"] == "admin-1" and "duty@bank.example" not in str(listed)
    _scenario(fn)


def test_a_wrong_code_is_a_plain_answer_and_a_new_code_replaces_the_old_one():
    async def fn(client, bank, pool, disp, events, who):
        created = (await client.post("/v1/admin/alert-contacts", json={"kind": "phone", "address": "+919800000001"})).json()["contact"]
        assert disp.sent[0].channel == "whatsapp"
        first = disp.last_code()
        wrong = "000000" if first != "000000" else "111111"
        assert (await client.post(f"/v1/admin/alert-contacts/{created['contact_id']}/verify", json={"code": wrong})).json()["reason"] == "wrong_code"
        again = await client.post(f"/v1/admin/alert-contacts/{created['contact_id']}/send-code")
        assert again.status_code == 200 and again.json()["sent"] is True and len(disp.sent) == 2
        second = disp.last_code()
        if second != first:
            assert (await client.post(f"/v1/admin/alert-contacts/{created['contact_id']}/verify", json={"code": first})).json()["ok"] is False
        assert (await client.post(f"/v1/admin/alert-contacts/{created['contact_id']}/verify", json={"code": second})).json()["ok"] is True
    _scenario(fn)


def test_a_bad_address_is_refused_in_words_and_a_repeat_is_a_conflict():
    async def fn(client, bank, pool, disp, events, who):
        bad = await client.post("/v1/admin/alert-contacts", json={"kind": "email", "address": "nope"})
        assert bad.status_code == 422 and bad.json()["detail"]
        assert (await client.post("/v1/admin/alert-contacts", json={"kind": "fax", "address": "x"})).status_code == 422
        assert (await client.post("/v1/admin/alert-contacts", json={"kind": "email", "address": "a@bank.example"})).status_code == 201
        assert (await client.post("/v1/admin/alert-contacts", json={"kind": "email", "address": "A@bank.example"})).status_code == 409
    _scenario(fn)


def test_when_the_code_cannot_be_sent_the_contact_is_kept_and_the_answer_says_it_was_not_sent():
    async def fn(client, bank, pool, disp, events, who):
        r = await client.post("/v1/admin/alert-contacts", json={"kind": "email", "address": "a@bank.example"})
        assert r.status_code == 201 and r.json()["sent"] is False
        assert len((await client.get("/v1/admin/alert-contacts")).json()["contacts"]) == 1
    _scenario(fn, dispatcher=Dispatcher(fail=True))
    _scenario(fn, dispatcher=None)


def test_a_contact_can_be_removed_and_a_missing_one_is_not_found():
    async def fn(client, bank, pool, disp, events, who):
        c = (await client.post("/v1/admin/alert-contacts", json={"kind": "email", "address": "a@bank.example"})).json()["contact"]
        assert (await client.delete(f"/v1/admin/alert-contacts/{c['contact_id']}")).status_code == 204
        assert (await client.delete(f"/v1/admin/alert-contacts/{c['contact_id']}")).status_code == 404
        assert (await client.post("/v1/admin/alert-contacts/nope/verify", json={"code": "123456"})).status_code == 404
        assert (await client.post("/v1/admin/alert-contacts/nope/send-code")).status_code == 404
    _scenario(fn)


def test_a_role_that_may_read_cannot_change_contacts_and_an_unrelated_role_cannot_read():
    async def fn(client, bank, pool, disp, events, who):
        assert (await client.get("/v1/admin/alert-contacts")).status_code == 200
        assert (await client.post("/v1/admin/alert-contacts", json={"kind": "email", "address": "a@bank.example"})).status_code == 403
    _scenario(fn, role="compliance_officer")

    async def fn2(client, bank, pool, disp, events, who):
        assert (await client.get("/v1/admin/alert-contacts")).status_code == 403
    _scenario(fn2, role="ops_reviewer")
