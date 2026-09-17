"""
Cut 1 — Outward pipeline (Temporal + Kafka + OCR + YugabyteDB + Immudb).

Tests:
  - All workflows + activities load without ImportError / DI collision
  - OutwardScan OCR on a cheque image (via OCR stub) → PROCEED
  - Outward lot-close event: Kafka + Immudb audit write pair
  - OCR result fields flow into persist_agent_decision input schema
"""
from __future__ import annotations

import time
import uuid
from unittest.mock import AsyncMock

import pytest

from tests.integration.cut1.conftest import TEST_BANK_ID, TEST_PEPPER, OCR_STUB_URL

pytestmark = [pytest.mark.integration, pytest.mark.cut1]

_LOT_ID   = lambda: f"LOT-CUT1-OUT-{uuid.uuid4().hex[:8]}"
_INSTR_ID = lambda: f"CTS-OUT-CUT1-{uuid.uuid4().hex[:8]}"


def _mock_config():
    cfg = AsyncMock()
    cfg.get_ai_config = AsyncMock(return_value={
        "ai.ocr.min_confidence": 0.80,
        "services.indic_ocr.url": "",
        "ai.ocr.min_indic_confidence": 0.60,
        "ai.cascade.l1_confidence_threshold": 0.85,
        "ai.cascade.high_value_threshold": 5_000_000.0,
        "ai.cascade.l2_escalation_enabled": False,
        "ai.cascade.l1_model_ocr": "got-ocr2-stub",
        "ai.cascade.l2_model_ocr": "got-ocr2-stub",
    })
    cfg.get = AsyncMock(return_value=None)
    return cfg


def _make_decision_input(instr_id: str, decision: str = "STP_CONFIRM"):
    from modules.cts.workflows.activities.persist_decision import PersistDecisionInput
    now = time.time()
    return PersistDecisionInput(
        instrument_id=instr_id,
        bank_id=TEST_BANK_ID,
        workflow_id=f"cts-{TEST_BANK_ID}-{instr_id}",
        decision=decision,
        decision_reason="outward_ngch_submitted",
        fraud_score=0.04,
        shap_values={},
        processing_started_at=now - 0.095,
        processing_completed_at=now,
    )


# ════════════════════════════════════════════════════════════════════════════
# Temporal worker — outward activity registration
# ════════════════════════════════════════════════════════════════════════════

class TestOutwardActivityRegistration:

    @pytest.mark.asyncio
    async def test_all_outward_activities_registered(self, temporal_client):
        """
        Spin up a worker with the full activity + workflow list.
        Catches: missing @activity.defn, name collisions, import failures.
        """
        from temporalio.worker import Worker, UnsandboxedWorkflowRunner
        from modules.cts.worker import ALL_WORKFLOWS, NO_DI_ACTIVITIES

        async with Worker(
            temporal_client,
            task_queue=f"cts-out-reg-{uuid.uuid4().hex[:6]}",
            workflows=ALL_WORKFLOWS,
            activities=NO_DI_ACTIVITIES,
            workflow_runner=UnsandboxedWorkflowRunner(),
        ) as worker:
            assert worker is not None


# ════════════════════════════════════════════════════════════════════════════
# OCR activity — outward cheque scan
# ════════════════════════════════════════════════════════════════════════════

class TestOutwardOCR:

    @pytest.mark.asyncio
    async def test_outward_ocr_high_confidence_proceed(self, ocr_orchestrator):
        """OutwardScan: OCR on cheque scan returns PROCEED when confidence is high."""
        from modules.cts.workflows.activities.ocr import OCRActivityInput, ocr_extract

        instr_id = _INSTR_ID()
        inp = OCRActivityInput(
            image_url=(
                f"https://minio/cts/outward/{instr_id}.tif?scenario=high_confidence"
            ),
            instrument_id=instr_id,
            bank_id=TEST_BANK_ID,
        )
        result = await ocr_extract(inp, ocr_orchestrator, _mock_config())
        assert result.outcome == "PROCEED"
        assert result.degraded is False


# ════════════════════════════════════════════════════════════════════════════
# Outward lot — DB write + Kafka + Immudb chain
# ════════════════════════════════════════════════════════════════════════════

class TestOutwardLotChain:

    @pytest.mark.asyncio
    async def test_lot_close_db_kafka_immudb_chain(
        self, cut1_db_pool, cut1_immudb_writer, kafka_producer, kafka_consumer_factory
    ):
        """
        Outward lot close: record written to DB, event on Kafka,
        audit entry in Immudb — all three must succeed.
        """
        from modules.cts.workflows.activities.persist_decision import persist_agent_decision
        from modules.cts.workflows.activities.write_audit import WriteAuditInput, write_audit

        lot_id = _LOT_ID()
        topic = "platform.audit.events"
        consumer = kafka_consumer_factory(topic, group_id=f"cut1-lot-{uuid.uuid4().hex[:8]}")

        # DB write
        async with cut1_db_pool.acquire() as conn:
            await persist_agent_decision(_make_decision_input(lot_id), db_conn=conn)

        # Immudb write (must pair with DB write)
        aud_result = await write_audit(
            WriteAuditInput(
                event_type="CTS_OUT_NGCH_SUBMITTED",
                bank_id=TEST_BANK_ID,
                instrument_id=lot_id,
                payload={"lot_id": lot_id, "instrument_count": 8},
            ),
            cut1_immudb_writer,
            hsm=None,
        )
        assert aud_result.success is True

        # Kafka event
        kafka_producer.send(topic, {
            "event_type": "CTS_OUT_NGCH_SUBMITTED",
            "bank_id": TEST_BANK_ID,
            "instrument_id": lot_id,
            "schema_version": "1.0",
        })
        kafka_producer.flush()

        # Verify DB
        async with cut1_db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT decision FROM cts.agent_decisions WHERE instrument_id = $1",
                lot_id,
            )
        assert row is not None

        # Verify Kafka
        received = []
        for msg in consumer:
            if msg.value.get("instrument_id") == lot_id:
                received.append(msg.value)
                break
        assert received, f"Kafka lot event for {lot_id} not received"

    @pytest.mark.asyncio
    async def test_outward_ocr_then_db_write(self, ocr_orchestrator, cut1_db_pool):
        """
        OutwardScan pipeline: OCR result flows into DB persist.
        Catches: OCR result field names/types not matching persist_decision input schema.
        """
        from modules.cts.workflows.activities.ocr import OCRActivityInput, ocr_extract
        from modules.cts.workflows.activities.persist_decision import persist_agent_decision

        instr_id = _INSTR_ID()
        ocr_inp = OCRActivityInput(
            image_url=(
                f"https://minio/cts/outward/{instr_id}.tif?scenario=high_confidence"
            ),
            instrument_id=instr_id,
            bank_id=TEST_BANK_ID,
        )
        ocr_result = await ocr_extract(ocr_inp, ocr_orchestrator, _mock_config())
        assert ocr_result.outcome == "PROCEED"

        decision = "STP_CONFIRM" if ocr_result.outcome == "PROCEED" else "HUMAN_REVIEW"
        now = time.time()
        from modules.cts.workflows.activities.persist_decision import PersistDecisionInput
        dec_inp = PersistDecisionInput(
            instrument_id=instr_id,
            bank_id=TEST_BANK_ID,
            workflow_id=f"cts-{TEST_BANK_ID}-{instr_id}",
            decision=decision,
            decision_reason=f"ocr_cascade_{ocr_result.cascade_level}",
            fraud_score=0.0,
            shap_values={"ocr_confidence": ocr_result.overall_confidence},
            processing_started_at=now - 0.13,
            processing_completed_at=now,
            ocr_confidence=ocr_result.overall_confidence,
            ocr_engines_used=ocr_result.engines_used if hasattr(ocr_result, "engines_used") else [],
        )
        async with cut1_db_pool.acquire() as conn:
            await persist_agent_decision(dec_inp, db_conn=conn)

        async with cut1_db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT decision FROM cts.agent_decisions WHERE instrument_id = $1",
                instr_id,
            )
        assert row is not None and row["decision"] == "STP_CONFIRM"
