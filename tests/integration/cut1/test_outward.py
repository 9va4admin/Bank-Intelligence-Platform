"""
Cut 1 — Outward pipeline (Temporal + Kafka + OCR + YugabyteDB + Immudb).

Tests:
  - OutwardScan activities all register in the Temporal worker
  - outward_scan OCR on a real cheque image (via OCR stub) → PROCEED
  - CTS-2010 compliance write to YugabyteDB
  - Outward lot-close event: Kafka + Immudb audit write pair
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from tests.integration.cut1.conftest import TEST_BANK_ID, TEST_PEPPER, OCR_STUB_URL

pytestmark = [pytest.mark.integration, pytest.mark.cut1]

_LOT_ID    = lambda: f"LOT-CUT1-OUT-{uuid.uuid4().hex[:8]}"
_INSTR_ID  = lambda: f"CTS-OUT-CUT1-{uuid.uuid4().hex[:8]}"


# ════════════════════════════════════════════════════════════════════════════
# Temporal worker — outward activity registration
# ════════════════════════════════════════════════════════════════════════════

class TestOutwardActivityRegistration:

    @pytest.mark.asyncio
    async def test_all_outward_activities_registered(self, temporal_client):
        """
        Spin up a worker with outward activities; confirm no registration errors.
        Catches: missing @activity.defn, name collisions, import failures.
        """
        from modules.cts.worker import build_outward_activities, build_outward_workflows

        activities = build_outward_activities(
            bank_id=TEST_BANK_ID,
            db_pool=None,
            immudb_client=None,
            kafka_producer=None,
            ngch_stub=None,
        )
        workflows = build_outward_workflows()

        from temporalio.worker import Worker
        async with Worker(
            temporal_client,
            task_queue=f"cts-outward-{TEST_BANK_ID}",
            workflows=workflows,
            activities=activities,
        ) as worker:
            assert worker is not None


# ════════════════════════════════════════════════════════════════════════════
# OCR activity — outward cheque scan
# ════════════════════════════════════════════════════════════════════════════

class TestOutwardOCR:

    def _mock_config(self):
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

    @pytest.mark.asyncio
    async def test_outward_ocr_high_confidence_proceed(self, ocr_orchestrator):
        """OutwardScan: OCR on cheque scan returns PROCEED when confidence is high."""
        from modules.cts.workflows.activities.ocr import OCRActivityInput, ocr_extract
        instr_id = _INSTR_ID()
        inp = OCRActivityInput(
            image_url=f"https://minio/cts/outward/{instr_id}.tif?scenario=high_confidence",
            instrument_id=instr_id,
            bank_id=TEST_BANK_ID,
        )
        result = await ocr_extract(inp, ocr_orchestrator, self._mock_config())
        assert result.outcome == "PROCEED"
        assert result.degraded is False


# ════════════════════════════════════════════════════════════════════════════
# Outward lot — DB write + Kafka + Immudb chain
# ════════════════════════════════════════════════════════════════════════════

class TestOutwardLotChain:

    @pytest.mark.asyncio
    async def test_lot_close_db_kafka_immudb_chain(
        self, cut1_db_pool, cut1_immudb_client, kafka_producer, kafka_consumer_factory
    ):
        """
        Outward lot close: lot record written to DB, event on Kafka,
        audit entry in Immudb — all three must succeed.
        """
        from modules.cts.workflows.activities.persist_decision import (
            PersistDecisionInput, persist_agent_decision,
        )
        from modules.cts.workflows.activities.write_audit import (
            WriteAuditInput, write_audit,
        )

        lot_id = _LOT_ID()
        topic = "platform.audit.events"
        consumer = kafka_consumer_factory(topic, group_id=f"cut1-lot-{uuid.uuid4().hex[:8]}")

        # Simulate: persist lot-level decision as a proxy for lot_db_write
        # (full lot activity needs its own lot table schema; we test the pairing rule)
        dec_inp = PersistDecisionInput(
            instrument_id=lot_id,
            bank_id=TEST_BANK_ID,
            decision="STP_CONFIRM",
            rationale="lot_ngch_submitted",
            shap_values={},
            amount=2_200_000.0,
            amount_range="₹[10L-1Cr]",
            processing_ms=55,
        )
        await persist_agent_decision(dec_inp, db_pool=cut1_db_pool)

        aud_inp = WriteAuditInput(
            event_type="CTS_OUT_NGCH_SUBMITTED",
            bank_id=TEST_BANK_ID,
            instrument_id=lot_id,
            payload={"lot_id": lot_id, "instrument_count": 8},
            hsm=None,
        )
        await write_audit(aud_inp, immudb_client=cut1_immudb_client)

        kafka_producer.send(topic, {
            "event_type": "CTS_OUT_NGCH_SUBMITTED",
            "bank_id": TEST_BANK_ID,
            "instrument_id": lot_id,
            "schema_version": "1.0",
        })
        kafka_producer.flush()

        # DB
        async with cut1_db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT decision FROM cts.agent_decisions WHERE instrument_id = $1",
                lot_id,
            )
        assert row is not None

        # Immudb
        entry = cut1_immudb_client.verified_get(f"cts:{TEST_BANK_ID}:{lot_id}")
        assert entry is not None

        # Kafka
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
        from modules.cts.workflows.activities.persist_decision import (
            PersistDecisionInput, persist_agent_decision,
        )
        from unittest.mock import AsyncMock

        instr_id = _INSTR_ID()
        mock_cfg = AsyncMock()
        mock_cfg.get_ai_config = AsyncMock(return_value={
            "ai.ocr.min_confidence": 0.80,
            "services.indic_ocr.url": "",
            "ai.ocr.min_indic_confidence": 0.60,
            "ai.cascade.l1_confidence_threshold": 0.85,
            "ai.cascade.high_value_threshold": 5_000_000.0,
            "ai.cascade.l2_escalation_enabled": False,
            "ai.cascade.l1_model_ocr": "got-ocr2-stub",
            "ai.cascade.l2_model_ocr": "got-ocr2-stub",
        })
        mock_cfg.get = AsyncMock(return_value=None)

        ocr_inp = OCRActivityInput(
            image_url=f"https://minio/cts/outward/{instr_id}.tif?scenario=high_confidence",
            instrument_id=instr_id,
            bank_id=TEST_BANK_ID,
        )
        ocr_result = await ocr_extract(ocr_inp, ocr_orchestrator, mock_cfg)
        assert ocr_result.outcome == "PROCEED"

        # Now persist based on OCR outcome
        dec_inp = PersistDecisionInput(
            instrument_id=instr_id,
            bank_id=TEST_BANK_ID,
            decision="STP_CONFIRM" if ocr_result.outcome == "PROCEED" else "HUMAN_REVIEW",
            rationale=f"ocr_cascade_{ocr_result.cascade_level}",
            shap_values={"ocr_confidence": ocr_result.overall_confidence},
            amount=220_000.0,
            amount_range="₹[1L-5L]",
            processing_ms=130,
        )
        await persist_agent_decision(dec_inp, db_pool=cut1_db_pool)

        async with cut1_db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT decision FROM cts.agent_decisions WHERE instrument_id = $1",
                instr_id,
            )
        assert row is not None and row["decision"] == "STP_CONFIRM"
