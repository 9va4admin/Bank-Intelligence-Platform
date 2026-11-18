"""Live: the escalation workflow on the REAL Temporal dev server, with the real YugabyteDB (incident, stored routing policy, delivery outbox, the bell inbox) and a
real worker running the real activities. An unacknowledged critical incident reaches level 1 at once and level 2 a minute later, each person getting exactly one
notification and the escalation recorded on the incident; acknowledging stops it before the next level. Skipped when Temporal or the database is not reachable.
Takes about 80 seconds because it runs in real time."""
import asyncio
import os
import socket
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.integration


def _env():
    env = {}
    for line in (ROOT / "scripts" / ".env.dev").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("export ") and "=" in line:
            k, v = line[7:].split("=", 1)
            env[k] = v.strip().strip('"').strip("'")
    return env


def _up(hostport):
    host, _, port = hostport.partition(":")
    try:
        socket.create_connection((host, int(port or 7233)), timeout=1).close()
        return True
    except OSError:
        return False


try:
    TEMPORAL = _env().get("ASTRA_SECRET_TEMPORAL_HOST", "")
except OSError:
    TEMPORAL = ""
needs = pytest.mark.skipif(not (TEMPORAL and _up(TEMPORAL)), reason="dev Temporal not reachable")


class Cfg:
    """Settings and secrets for the services under test (test-only key, not a secret)."""
    async def get(self, key):
        from shared.config.config_service import ConfigKeyNotFoundError
        values = {"alerting.timezone": "Asia/Kolkata", "alerting.bell_max_recipients": 50}
        if key not in values:
            raise ConfigKeyNotFoundError(key)
        return values[key]

    async def get_secret(self, key):
        return "live-escalation-key-not-a-secret" if key.endswith("pii_enc_key") else "live-escalation-pepper-not-a-secret"


async def _fixture(bank):
    import asyncpg
    from shared.alerting.incidents import IncidentStore
    from shared.alerting.policy_store import PolicyStore
    from shared.alerting.routing_policy import EscalationStep, Policy, Rule, TargetSpec
    pool = await asyncpg.create_pool(host="localhost", port=15433, user="yugabyte", password="yugabyte", database="yugabyte", min_size=1, max_size=6)
    policy = Policy(rules=[Rule(id="p0", severities=["P0"], targets=[TargetSpec(kind="user", ref="first-line", channels=["bell"]), TargetSpec(kind="external", ref="ops@bank.example", channels=["email"])],      # two channels: the bank policy must cover P0 on two
                                escalation=[EscalationStep(level=1, after_minutes=0, targets=[TargetSpec(kind="user", ref="lead", channels=["bell"])]),
                                            EscalationStep(level=2, after_minutes=1, targets=[TargetSpec(kind="user", ref="director", channels=["bell"])])]),
                         Rule(id="rest", targets=[TargetSpec(kind="user", ref="first-line", channels=["bell"])])])
    store = PolicyStore(pool, pii_key="live-escalation-key-not-a-secret")
    p = await store.propose(bank, "BANK", None, policy, proposed_by="maker")
    await store.approve(bank, p.policy_id, approved_by="checker")
    inc = await IncidentStore(pool).open_or_update(bank_id=bank, dedup_key="component:redis:down", alert_id="COMPONENT_DOWN", component="redis", severity="P0",
                                                   summary="redis is not responding")
    return pool, inc.incident_id


async def _cleanup(pool, bank):
    for t in ("alert_routing_policies", "alert_incidents", "alert_deliveries", "user_notifications"):
        await pool.execute(f"DELETE FROM platform.{t} WHERE bank_id=$1", bank)
    await pool.close()


def _worker(client, pool, bank, tq, events):
    from temporalio import activity
    from temporalio.worker import UnsandboxedWorkflowRunner, Worker
    from modules.cts.workflows.activities import alert_escalation_activities as acts
    from modules.cts.workflows.alert_escalation_workflow import AlertEscalationWorkflow
    from shared.alerting.audit import AlertAuditor
    from shared.alerting.bell import BellChannel
    from shared.alerting.delivery import DeliveryStore
    from shared.alerting.engine import DeliveryEngine, DeliveryPolicy
    from shared.alerting.inbox import InboxStore
    from shared.alerting.templates import TemplateSettings
    from shared.notifications.dispatcher import NotificationDispatcher

    async def sink(event_type, bank_id, entity_id, actor_id, payload):
        events.append((event_type, payload))
        return "tx"
    auditor = AlertAuditor(sink)
    dispatcher = NotificationDispatcher(bank)
    dispatcher.connect(bell_channel=BellChannel(InboxStore(pool), TemplateSettings()))
    engine = DeliveryEngine(DeliveryStore(pool, pii_key="live-escalation-key-not-a-secret", pepper="live-escalation-pepper-not-a-secret"), dispatcher, auditor, DeliveryPolicy())

    @activity.defn(name="plan_escalation")
    async def plan(inp: acts.PlanInput) -> acts.EscalationPlan:
        return await acts.plan_escalation(inp, db_pool=pool, config_service=Cfg())

    @activity.defn(name="run_escalation_step")
    async def step(inp: acts.EscalationStepInput) -> acts.EscalationStepResult:
        return await acts.run_escalation_step(inp, db_pool=pool, config_service=Cfg(), delivery_engine=engine, alert_auditor=auditor)
    return Worker(client, task_queue=tq, workflows=[AlertEscalationWorkflow], activities=[plan, step], workflow_runner=UnsandboxedWorkflowRunner())


async def _bell(pool, bank, user):
    return await pool.fetchval("SELECT COUNT(*) FROM platform.user_notifications WHERE bank_id=$1 AND user_id=$2", bank, user)


async def _wait_for(check, seconds):
    for _ in range(seconds * 2):
        if await check():
            return True
        await asyncio.sleep(0.5)
    return False


@needs
def test_an_unacknowledged_incident_escalates_level_by_level_each_person_told_once():
    async def scenario():
        import time
        from temporalio.client import Client
        from modules.cts.workflows.alert_escalation_workflow import AlertEscalationInput, AlertEscalationWorkflow
        from shared.temporal.converter import pydantic_data_converter
        bank = f"it-{uuid.uuid4().hex[:8]}"
        pool, incident_id = await _fixture(bank)
        events = []
        client = await Client.connect(TEMPORAL, data_converter=pydantic_data_converter)
        try:
            async with _worker(client, pool, bank, f"tq-live-{bank}", events):
                h = await client.start_workflow(AlertEscalationWorkflow.run, AlertEscalationInput(bank_id=bank, incident_id=incident_id, started_at=time.time()),
                                                id=f"live-esc-{bank}", task_queue=f"tq-live-{bank}")
                assert await _wait_for(lambda: _count_is(pool, bank, "lead", 1), 30), "level 1 never reached the lead"
                assert await _bell(pool, bank, "director") == 0                                  # level 2 is a minute away
                assert await _wait_for(lambda: _count_is(pool, bank, "director", 1), 90), "level 2 never reached the director"
                assert await h.result() == "COMPLETED"
            assert [await _bell(pool, bank, u) for u in ("lead", "director")] == [1, 1]
            level = await pool.fetchval("SELECT escalation_level FROM platform.alert_incidents WHERE incident_id=$1", incident_id)
            assert level == 2
            assert [p["level"] for k, p in events if k == "ALERT_ESCALATED"] == [1, 2]
            row = await pool.fetchrow("SELECT title, body FROM platform.user_notifications WHERE bank_id=$1 AND user_id='director'", bank)
            assert "Escalation level 2" in row["body"]
        finally:
            await _cleanup(pool, bank)
    asyncio.run(scenario())


async def _count_is(pool, bank, user, n):
    return await _bell(pool, bank, user) == n


@needs
def test_acknowledging_stops_the_escalation_before_the_next_level():
    async def scenario():
        import time
        from temporalio.client import Client
        from modules.cts.workflows.alert_escalation_workflow import AlertEscalationInput, AlertEscalationWorkflow
        from shared.alerting.incidents import IncidentStore
        from shared.temporal.converter import pydantic_data_converter
        bank = f"it-{uuid.uuid4().hex[:8]}"
        pool, incident_id = await _fixture(bank)
        client = await Client.connect(TEMPORAL, data_converter=pydantic_data_converter)
        try:
            async with _worker(client, pool, bank, f"tq-live-{bank}", []):
                h = await client.start_workflow(AlertEscalationWorkflow.run, AlertEscalationInput(bank_id=bank, incident_id=incident_id, started_at=time.time()),
                                                id=f"live-esc-{bank}", task_queue=f"tq-live-{bank}")
                assert await _wait_for(lambda: _count_is(pool, bank, "lead", 1), 30)
                assert await IncidentStore(pool).acknowledge(bank, incident_id, "someone") is True
                await h.signal(AlertEscalationWorkflow.stop, "acknowledged")
                assert await h.result() == "STOPPED:acknowledged"
            await asyncio.sleep(1)
            assert await _bell(pool, bank, "director") == 0
        finally:
            await _cleanup(pool, bank)
    asyncio.run(scenario())
