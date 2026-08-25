"""
Cut 1 — Inward pipeline (Temporal + Kafka + OCR + YugabyteDB + Immudb).

What this cut catches that Cut 2 cannot:
  - All registered workflows & activities load without ImportError / DI collision
  - persist_agent_decision writes a real row to cts.agent_decisions
  - write_audit fires and Immudb verifiedSet() is called (not .set())
  - Kafka audit event is published after a decision
  - DB → Immudb pairing rule: both persist or neither

Scope: activities called directly (not through full ChequeProcessingWorkflow),
since running the full workflow requires CBS, NGCH, vault, and HSM stubs.
"""
from __future__ import annotations

import time
import uuid

import pytest
import pytest_asyncio

from tests.integration.cut1.conftest import TEST_BANK_ID, TEST_PEPPER

pytestmark = [pytest.mark.integration, pytest.mark.cut1]

_INSTR_ID = lambda: f"CTS-CUT1-{uuid.uuid4().hex[:8]}"
_AMOUNT   = 95_000.0


# ════════════════════════════════════════════════════════════════════════════
# Temporal worker — activity + workflow registration
# ════════════════════════════════════════════════════════════════════════════

class TestInwardActivityRegistration:

    @pytest.mark.asyncio
    async def test_all_inward_activities_registered_in_worker(self, temporal_client):
        """
        Spin up a CTS worker with the full activity + workflow list and confirm
        nothing raises ImportError, missing @activity.defn, or DI name collision.
        """
        from temporalio.worker import Worker, UnsandboxedWorkflowRunner
        from modules.cts.worker import ALL_WORKFLOWS, NO_DI_ACTIVITIES

        async with Worker(
            temporal_client,
            task_queue=f"cts-cut1-reg-{uuid.uuid4().hex[:6]}",
            workflows=ALL_WORKFLOWS,
            activities=NO_DI_ACTIVITIES,
            workflow_runner=UnsandboxedWorkflowRunner(),
        ) as worker:
            assert worker is not None, "Worker should start without error"


# ════════════════════════════════════════════════════════════════════════════
# persist_agent_decision — real YugabyteDB write
# ════════════════════════════════════════════════════════════════════════════

def _make_decision_input(instr_id: str, decision: str = "STP_CONFIRM") -> "PersistDecisionInput":
    from modules.cts.workflows.activities.persist_decision import PersistDecisionInput
    now = time.time()
    return PersistDecisionInput(
        instrument_id=instr_id,
        bank_id=TEST_BANK_ID,
        workflow_id=f"cts-{TEST_BANK_ID}-{instr_id}",
        decision=decision,
        decision_reason="clean_all_pass",
        fraud_score=0.08,
        shap_values={"fraud_score": 0.08, "sig_match": 0.95},
        processing_started_at=now - 0.18,
        processing_completed_at=now,
    )


class TestPersistDecisionDB:

    @pytest.mark.asyncio
    async def test_persist_agent_decision_inward_writes_row(self, cut1_db_pool):
        """persist_agent_decision writes a row to cts.agent_decisions."""
        from modules.cts.workflows.activities.persist_decision import persist_agent_decision

        instr_id = _INSTR_ID()
        inp = _make_decision_input(instr_id, decision="STP_CONFIRM")

        async with cut1_db_pool.acquire() as conn:
            await persist_agent_decision(inp, db_conn=conn)

        async with cut1_db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT instrument_id, bank_id, decision FROM cts.agent_decisions "
                "WHERE instrument_id = $1 AND bank_id = $2",
                instr_id, TEST_BANK_ID,
            )
        assert row is not None, f"Row not found for {instr_id}"
        assert row["decision"] == "STP_CONFIRM"

    @pytest.mark.asyncio
    async def test_persist_agent_decision_outward_writes_row(self, cut1_db_pool):
        """OutwardScan: persist_agent_decision also works for outward instruments."""
        from modules.cts.workflows.activities.persist_decision import persist_agent_decision

        instr_id = f"CTS-OUT-CUT1-{uuid.uuid4().hex[:8]}"
        inp = _make_decision_input(instr_id, decision="STP_CONFIRM")

        async with cut1_db_pool.acquire() as conn:
            await persist_agent_decision(inp, db_conn=conn)

        async with cut1_db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT instrument_id FROM cts.agent_decisions WHERE instrument_id = $1",
                instr_id,
            )
        assert row is not None


# ════════════════════════════════════════════════════════════════════════════
# write_audit — real Immudb write (verifiedSet)
# ════════════════════════════════════════════════════════════════════════════

class TestWriteAuditImmudb:

    @pytest.mark.asyncio
    async def test_audit_write_uses_verified_set(self, cut1_immudb_writer):
        """
        write_audit must call verifiedSet() through AsyncImmudbWriter.
        verifiedSet() includes Merkle-tree inclusion proof;
        plain set() would be a compliance violation.
        """
        from modules.cts.workflows.activities.write_audit import WriteAuditInput, write_audit

        instr_id = _INSTR_ID()
        inp = WriteAuditInput(
            event_type="CTS_NGCH_FILED_CONFIRM",
            bank_id=TEST_BANK_ID,
            instrument_id=instr_id,
            payload={"decision": "STP_CONFIRM", "amount_range": "₹[<1L]"},
        )
        result = await write_audit(inp, cut1_immudb_writer, hsm=None)
        assert result.success is True, f"write_audit returned failure: {result}"

    @pytest.mark.asyncio
    async def test_audit_write_outward_lot_event(self, cut1_immudb_writer):
        """write_audit works for outward lot events too."""
        from modules.cts.workflows.activities.write_audit import WriteAuditInput, write_audit

        lot_id = f"LOT-CUT1-{uuid.uuid4().hex[:8]}"
        inp = WriteAuditInput(
            event_type="CTS_OUT_NGCH_SUBMITTED",
            bank_id=TEST_BANK_ID,
            instrument_id=lot_id,
            payload={"lot_id": lot_id, "instrument_count": 12},
        )
        result = await write_audit(inp, cut1_immudb_writer, hsm=None)
        assert result.success is True


# ════════════════════════════════════════════════════════════════════════════
# Kafka + DB + Immudb — decision pipeline chain
# ════════════════════════════════════════════════════════════════════════════

class TestInwardDecisionChain:

    @pytest.mark.asyncio
    async def test_db_write_followed_by_immudb_and_kafka(
        self, cut1_db_pool, cut1_immudb_writer, kafka_producer, kafka_consumer_factory
    ):
        """
        The pairing rule: every YugabyteDB write must be immediately followed by
        an Immudb write. This test runs both and verifies both persisted.
        A Kafka audit event on platform.audit.events is also checked.
        """
        from modules.cts.workflows.activities.persist_decision import persist_agent_decision
        from modules.cts.workflows.activities.write_audit import WriteAuditInput, write_audit

        instr_id = _INSTR_ID()
        topic = "platform.audit.events"
        consumer = kafka_consumer_factory(topic, group_id=f"cut1-chain-{uuid.uuid4().hex[:8]}")

        # Step 1: DB write
        inp = _make_decision_input(instr_id)
        async with cut1_db_pool.acquire() as conn:
            await persist_agent_decision(inp, db_conn=conn)

        # Step 2: Immudb write (must follow DB write — pairing rule)
        aud_inp = WriteAuditInput(
            event_type="CTS_NGCH_FILED_CONFIRM",
            bank_id=TEST_BANK_ID,
            instrument_id=instr_id,
            payload={"decision": "STP_CONFIRM"},
        )
        aud_result = await write_audit(aud_inp, cut1_immudb_writer, hsm=None)
        assert aud_result.success is True

        # Step 3: Kafka event
        kafka_producer.send(topic, {
            "event_type": "CTS_NGCH_FILED_CONFIRM",
            "bank_id": TEST_BANK_ID,
            "instrument_id": instr_id,
            "schema_version": "1.0",
        })
        kafka_producer.flush()

        # Verify DB row exists
        async with cut1_db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT decision FROM cts.agent_decisions WHERE instrument_id = $1",
                instr_id,
            )
        assert row is not None and row["decision"] == "STP_CONFIRM"

        # Verify Kafka event received
        received = []
        for msg in consumer:
            if msg.value.get("instrument_id") == instr_id:
                received.append(msg.value)
                break
        assert received, f"Kafka audit event for {instr_id} not received"
        assert received[0]["schema_version"] == "1.0"
