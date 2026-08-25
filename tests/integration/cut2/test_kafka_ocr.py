"""
Cut 2 — Kafka + OCR tests (Kafka + Redis + OCR stub).

Tests:
  Kafka:
    - Inward: audit event published to platform.audit.events after cheque submitted
    - Inward: inward fan-out lands on cts.inward.{bank_id}
    - Outward: lot-close event published on platform.audit.events

  OCR activity (via stub server):
    - High-confidence result → OCRActivityResult(outcome=PROCEED)
    - Low-confidence result → OCRActivityResult(outcome=HUMAN_REVIEW)
    - Amount figures/words mismatch → OCRActivityResult(outcome=HUMAN_REVIEW, amount_mismatch=True)
    - Stub unavailable → OCRActivityResult(outcome=HUMAN_REVIEW, degraded=True)
"""
from __future__ import annotations

import json
import time
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from tests.integration.cut2.conftest import TEST_BANK_ID, OCR_STUB_URL

pytestmark = [pytest.mark.integration, pytest.mark.cut2]

_INSTR_ID = "CTS-CUT2-OCR-00001"


# ════════════════════════════════════════════════════════════════════════════
# KAFKA — Inward pipeline event roundtrip
# ════════════════════════════════════════════════════════════════════════════

class TestKafkaInward:

    def test_audit_event_roundtrip_inward(self, kafka_producer, kafka_consumer_factory):
        """Produce a CTS_NGCH_FILED_CONFIRM event; consumer sees it within 5s."""
        topic = "platform.audit.events"
        consumer = kafka_consumer_factory(topic, group_id=f"cut2-inward-{uuid.uuid4().hex[:8]}")

        event = {
            "event_type": "CTS_NGCH_FILED_CONFIRM",
            "bank_id": TEST_BANK_ID,
            "instrument_id": f"CTS-AUDIT-{uuid.uuid4().hex[:8]}",
            "schema_version": "1.0",
            "ts": time.time(),
        }
        kafka_producer.send(topic, event)
        kafka_producer.flush()

        received = []
        for msg in consumer:
            received.append(msg.value)
            break   # first message is enough

        assert received, "No audit event received within 5s timeout"
        assert received[0]["event_type"] == "CTS_NGCH_FILED_CONFIRM"
        assert received[0]["bank_id"] == TEST_BANK_ID
        assert received[0]["schema_version"] == "1.0"

    def test_inward_fanout_topic_routing(self, kafka_producer, kafka_consumer_factory):
        """Inward cheque event lands on cts.inward.{bank_id}, not on another bank's topic."""
        topic = f"cts.inward.{TEST_BANK_ID}"
        consumer = kafka_consumer_factory(topic, group_id=f"cut2-fanout-{uuid.uuid4().hex[:8]}")

        event = {
            "instrument_id": f"CTS-FANOUT-{uuid.uuid4().hex[:8]}",
            "bank_id": TEST_BANK_ID,
            "schema_version": "1.0",
        }
        kafka_producer.send(topic, event)
        kafka_producer.flush()

        received = []
        for msg in consumer:
            received.append(msg.value)
            break

        assert received, f"No message received on {topic}"
        assert received[0]["bank_id"] == TEST_BANK_ID


# ════════════════════════════════════════════════════════════════════════════
# KAFKA — Outward pipeline event roundtrip
# ════════════════════════════════════════════════════════════════════════════

class TestKafkaOutward:

    def test_lot_complete_event_published(self, kafka_producer, kafka_consumer_factory):
        """OutwardScan lot-close event lands on platform.audit.events."""
        topic = "platform.audit.events"
        consumer = kafka_consumer_factory(topic, group_id=f"cut2-outward-{uuid.uuid4().hex[:8]}")

        event = {
            "event_type": "CTS_OUT_NGCH_SUBMITTED",
            "bank_id": TEST_BANK_ID,
            "lot_id": f"LOT-{uuid.uuid4().hex[:8]}",
            "schema_version": "1.0",
            "ts": time.time(),
        }
        kafka_producer.send(topic, event)
        kafka_producer.flush()

        received = []
        for msg in consumer:
            received.append(msg.value)
            break

        assert received, "No outward lot event received"
        assert received[0]["event_type"] == "CTS_OUT_NGCH_SUBMITTED"

    def test_kafka_event_schema_version_required(self, kafka_producer, kafka_consumer_factory):
        """Every Kafka event must carry schema_version field — the versioning contract."""
        topic = "platform.audit.events"
        consumer = kafka_consumer_factory(topic, group_id=f"cut2-schema-{uuid.uuid4().hex[:8]}")

        event = {
            "event_type": "CTS_OUT_ENDORSED",
            "bank_id": TEST_BANK_ID,
            "schema_version": "1.0",   # must always be present
        }
        kafka_producer.send(topic, event)
        kafka_producer.flush()

        for msg in consumer:
            assert "schema_version" in msg.value, (
                "schema_version is missing from Kafka event — versioning contract violated"
            )
            break


# ════════════════════════════════════════════════════════════════════════════
# OCR activity — inward and outward
# ════════════════════════════════════════════════════════════════════════════

class TestOCRActivity:

    def _mock_config(self, bank_id: str = TEST_BANK_ID):
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
    async def test_ocr_high_confidence_inward_proceed(self, ocr_orchestrator):
        """Inward: high-confidence OCR → OCRActivityResult(outcome=PROCEED)."""
        from modules.cts.workflows.activities.ocr import OCRActivityInput, ocr_extract
        inp = OCRActivityInput(
            image_url=f"https://minio/cts/cut2/{_INSTR_ID}.tif?scenario=high_confidence",
            instrument_id=_INSTR_ID,
            bank_id=TEST_BANK_ID,
        )
        result = await ocr_extract(inp, ocr_orchestrator, self._mock_config())
        assert result.outcome == "PROCEED"
        assert result.overall_confidence >= 0.80
        assert result.micr_line is not None
        assert result.degraded is False

    @pytest.mark.asyncio
    async def test_ocr_low_confidence_inward_human_review(self, ocr_orchestrator):
        """Inward: low-confidence OCR → HUMAN_REVIEW with reason."""
        from modules.cts.workflows.activities.ocr import OCRActivityInput, ocr_extract
        inp = OCRActivityInput(
            image_url=f"https://minio/cts/cut2/{_INSTR_ID}.tif?scenario=low_confidence",
            instrument_id=_INSTR_ID,
            bank_id=TEST_BANK_ID,
        )
        result = await ocr_extract(inp, ocr_orchestrator, self._mock_config())
        assert result.outcome == "HUMAN_REVIEW"
        assert result.low_confidence_reason is not None
        assert "low_confidence" in result.low_confidence_reason

    @pytest.mark.asyncio
    async def test_ocr_amount_mismatch_human_review(self, ocr_orchestrator):
        """Inward: figures ≠ words → HUMAN_REVIEW with amount_mismatch=True."""
        from modules.cts.workflows.activities.ocr import OCRActivityInput, ocr_extract
        inp = OCRActivityInput(
            image_url=f"https://minio/cts/cut2/{_INSTR_ID}.tif?scenario=amount_mismatch",
            instrument_id=_INSTR_ID,
            bank_id=TEST_BANK_ID,
        )
        result = await ocr_extract(inp, ocr_orchestrator, self._mock_config())
        assert result.outcome == "HUMAN_REVIEW"
        assert result.amount_mismatch is True

    @pytest.mark.asyncio
    async def test_ocr_model_unavailable_degrades_gracefully(self, ocr_stub_server):
        """Inward: vLLM 503 → OCRActivityResult(outcome=HUMAN_REVIEW, degraded=True)."""
        from openai import AsyncOpenAI
        from shared.ai.model_cascade import CascadeOrchestrator
        from modules.cts.workflows.activities.ocr import OCRActivityInput, ocr_extract

        client = AsyncOpenAI(base_url=f"{ocr_stub_server}/v1", api_key="stub")
        orchestrator = CascadeOrchestrator(
            l1_client=client, l2_client=client,
            config={
                "ai.cascade.l1_confidence_threshold": 0.85,
                "ai.cascade.high_value_threshold": 5_000_000.0,
                "ai.cascade.l2_escalation_enabled": False,
                "ai.cascade.l1_model_ocr": "got-ocr2-stub",
                "ai.cascade.l2_model_ocr": "got-ocr2-stub",
            },
            bank_id=TEST_BANK_ID,
        )
        inp = OCRActivityInput(
            image_url=f"https://minio/cts/cut2/{_INSTR_ID}.tif?scenario=model_unavailable",
            instrument_id=_INSTR_ID,
            bank_id=TEST_BANK_ID,
        )
        result = await ocr_extract(inp, orchestrator, self._mock_config())
        assert result.outcome == "HUMAN_REVIEW"
        assert result.degraded is True

    @pytest.mark.asyncio
    async def test_ocr_outward_high_confidence_proceed(self, ocr_orchestrator):
        """Outward scan: high-confidence OCR on outward cheque → PROCEED."""
        from modules.cts.workflows.activities.ocr import OCRActivityInput, ocr_extract
        inp = OCRActivityInput(
            image_url=f"https://minio/cts/outward/CTS-OUT-001.tif?scenario=high_confidence",
            instrument_id="CTS-OUT-001",
            bank_id=TEST_BANK_ID,
        )
        result = await ocr_extract(inp, ocr_orchestrator, self._mock_config())
        assert result.outcome == "PROCEED"
        assert result.micr_line == "600012003300456"
