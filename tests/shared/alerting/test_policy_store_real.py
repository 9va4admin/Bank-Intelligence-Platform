"""PolicyStore on the real dev YugabyteDB: versioned routing policies with maker-checker (the person who proposes cannot approve), one active policy per
bank and scope, an audit event for every change, and the policy body stored encrypted (it can name external email addresses)."""
import asyncio
import os
import socket
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from shared.alerting.audit import AlertAuditor
from shared.alerting.policy_store import PolicyInvalid, PolicyNotPending, PolicyStore, SameUserError
from shared.alerting.routing_policy import EscalationStep, IncidentFacts, Policy, Rule, TargetSpec

ROOT = Path(__file__).resolve().parents[3]
HOST, PORT = "localhost", 15433


def _up():
    try:
        socket.create_connection((HOST, PORT), timeout=1).close()
        return True
    except OSError:
        return False


pytestmark = [pytest.mark.integration, pytest.mark.skipif(not _up(), reason="dev YugabyteDB not reachable")]


@pytest.fixture(scope="module", autouse=True)
def migrated():
    env = {**os.environ, "PLATFORM_DB_URL": f"postgresql+asyncpg://yugabyte:yugabyte@{HOST}:{PORT}/yugabyte"}
    r = subprocess.run([sys.executable, "-m", "alembic", "-c", "infra/migrations/platform/alembic.ini", "upgrade", "head"], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr


def T(kind, ref, *channels):
    return TargetSpec(kind=kind, ref=ref, channels=list(channels))


def good(extra_email="ops@bank.example"):
    return Policy(rules=[
        Rule(id="p0", severities=["P0"], targets=[T("external", extra_email, "email"), T("role", "ops_manager", "bell")],
             escalation=[EscalationStep(level=1, after_minutes=10, targets=[T("role", "bank_it_admin", "email", "bell")])]),
        Rule(id="rest", targets=[T("role", "ops_manager", "bell")])])


def _run(fn):
    async def go():
        import asyncpg
        pool = await asyncpg.create_pool(host=HOST, port=PORT, user="yugabyte", password="yugabyte", database="yugabyte", min_size=1, max_size=6)
        bank = f"it-{uuid.uuid4().hex[:8]}"
        events = []

        async def sink(event_type, bank_id, entity_id, actor_id, payload):
            events.append((event_type, entity_id, actor_id, payload))
            return "tx"
        store = PolicyStore(pool, pii_key="policy-test-key-not-a-secret", auditor=AlertAuditor(sink))
        try:
            return await fn(store, bank, pool, events)
        finally:
            await pool.execute("DELETE FROM platform.alert_routing_policies WHERE bank_id=$1", bank)
            await pool.close()
    return asyncio.run(go())


def test_a_valid_policy_is_proposed_as_pending_version_one_and_audited():
    async def go(store, bank, pool, events):
        p = await store.propose(bank, "BANK", None, good(), proposed_by="maker-1", note="first")
        assert p.status == "PENDING" and p.version == 1 and p.scope_level == "BANK"
        assert await store.get_active(bank, "BANK", None) is None                    # not live until approved
        ev = events[-1]
        assert ev[0] == "ALERT_ROUTING_POLICY_CHANGED" and ev[2] == "maker-1" and ev[3]["action"] == "PROPOSED" and ev[3]["version"] == 1
        assert "ops@bank.example" not in str(events)                                  # no personal data in the audit trail
    _run(go)


def test_an_invalid_policy_is_refused_with_the_reasons_and_nothing_is_stored():
    async def go(store, bank, pool, events):
        bad = Policy(rules=[Rule(id="x", severities=["P1"], targets=[T("role", "a", "email")])])
        with pytest.raises(PolicyInvalid) as err:
            await store.propose(bank, "BANK", None, bad, proposed_by="maker-1")
        assert "p0_not_covered" in err.value.codes
        assert await pool.fetchval("SELECT COUNT(*) FROM platform.alert_routing_policies WHERE bank_id=$1", bank) == 0 and events == []
    _run(go)


def test_the_proposer_cannot_approve_but_someone_else_can_and_it_becomes_the_active_policy():
    async def go(store, bank, pool, events):
        p = await store.propose(bank, "BANK", None, good(), proposed_by="maker-1")
        with pytest.raises(SameUserError):
            await store.approve(bank, p.policy_id, approved_by="maker-1")
        a = await store.approve(bank, p.policy_id, approved_by="checker-2")
        assert a.status == "ACTIVE" and a.approved_by == "checker-2"
        active = await store.get_active(bank, "BANK", None)
        assert [r.id for r in active.rules] == ["p0", "rest"] and active.rules[0].targets[0].ref == "ops@bank.example"      # round trip, decrypted
        assert events[-1][3]["action"] == "APPROVED" and events[-1][2] == "checker-2"
    _run(go)


def test_the_stored_policy_is_encrypted_the_address_is_nowhere_in_the_clear():
    async def go(store, bank, pool, events):
        p = await store.propose(bank, "BANK", None, good(), proposed_by="m")
        await store.approve(bank, p.policy_id, approved_by="c")
        row = await pool.fetchrow("SELECT * FROM platform.alert_routing_policies WHERE bank_id=$1", bank)
        blob = " ".join(str(v) for v in row.values()) + bytes(row["policy_enc"]).decode("latin-1")
        assert "ops@bank.example" not in blob and row["rule_ids"] == ["p0", "rest"]
    _run(go)


def test_a_new_approved_version_replaces_the_old_which_is_kept_as_history():
    async def go(store, bank, pool, events):
        v1 = await store.propose(bank, "BANK", None, good(), proposed_by="m")
        await store.approve(bank, v1.policy_id, approved_by="c")
        v2 = await store.propose(bank, "BANK", None, good("other@bank.example"), proposed_by="m")
        assert v2.version == 2
        await store.approve(bank, v2.policy_id, approved_by="c")
        active = await store.get_active(bank, "BANK", None)
        assert active.rules[0].targets[0].ref == "other@bank.example"
        history = await store.history(bank, "BANK", None, limit=10)
        assert [(h.version, h.status) for h in history] == [(2, "ACTIVE"), (1, "SUPERSEDED")]
        assert await pool.fetchval("SELECT COUNT(*) FROM platform.alert_routing_policies WHERE bank_id=$1 AND status='ACTIVE'", bank) == 1
    _run(go)


def test_a_pending_proposal_can_be_rejected_and_then_cannot_be_approved():
    async def go(store, bank, pool, events):
        p = await store.propose(bank, "BANK", None, good(), proposed_by="m")
        r = await store.reject(bank, p.policy_id, rejected_by="c", note="too broad")
        assert r.status == "REJECTED" and events[-1][3]["action"] == "REJECTED"
        with pytest.raises(PolicyNotPending):
            await store.approve(bank, p.policy_id, approved_by="c")
        with pytest.raises(PolicyNotPending):
            await store.reject(bank, p.policy_id, rejected_by="c")
    _run(go)


def test_scopes_are_independent_and_other_banks_never_see_them():
    async def go(store, bank, pool, events):
        pu = Policy(rules=[Rule(id="pu", targets=[T("role", "pu_head", "bell")])], scope_id="PU1")
        a = await store.propose(bank, "PU", "PU1", pu, proposed_by="m")
        await store.approve(bank, a.policy_id, approved_by="c")
        b = await store.propose(bank, "BANK", None, good(), proposed_by="m")
        await store.approve(bank, b.policy_id, approved_by="c")
        assert (await store.get_active(bank, "PU", "PU1")).scope_id == "PU1" and await store.get_active(bank, "PU", "PU2") is None
        assert await store.get_active("another-bank", "BANK", None) is None
        assert await store.get_pending(bank, a.policy_id + "x") is None
    _run(go)


def test_the_effective_policies_for_an_incident_are_the_active_bank_pu_and_smb_ones():
    async def go(store, bank, pool, events):
        for level, scope, pol in (("BANK", None, good()), ("PU", "PU1", Policy(rules=[Rule(id="pu", targets=[T("role", "pu_head", "bell")])], scope_id="PU1")),
                                  ("SMB", "SMB7", Policy(rules=[Rule(id="smb", targets=[T("user", "smb-admin", "email")])], scope_id="SMB7"))):
            p = await store.propose(bank, level, scope, pol, proposed_by="m")
            await store.approve(bank, p.policy_id, approved_by="c")
        eff = await store.effective(bank, IncidentFacts(severity="P0", component="redis", pu_id="PU1", smb_id="SMB7"))
        assert set(eff) == {"BANK", "PU", "SMB"} and eff["PU"][0].scope_id == "PU1"
        only_bank = await store.effective(bank, IncidentFacts(severity="P0", pu_id="PU9"))
        assert set(only_bank) == {"BANK"}
    _run(go)


def test_two_proposals_at_once_get_different_versions():
    async def go(store, bank, pool, events):
        a, b = await asyncio.gather(store.propose(bank, "BANK", None, good(), proposed_by="m1"), store.propose(bank, "BANK", None, good("x@y.in"), proposed_by="m2"))
        assert sorted([a.version, b.version]) == [1, 2]
    _run(go)


def test_a_policy_for_a_pu_must_name_that_pu():
    async def go(store, bank, pool, events):
        with pytest.raises(PolicyInvalid) as err:
            await store.propose(bank, "PU", "PU1", Policy(rules=[Rule(id="x", targets=[T("role", "a", "bell")])], scope_id="PU2"), proposed_by="m")
        assert "scope_mismatch" in err.value.codes
        with pytest.raises(PolicyInvalid):
            await store.propose(bank, "PU", None, Policy(rules=[Rule(id="x", targets=[T("role", "a", "bell")])]), proposed_by="m")
    _run(go)
