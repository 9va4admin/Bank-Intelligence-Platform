"""
Cut 1 conftest — Temporal + Kafka + OCR stub + YugabyteDB + Immudb.
No Redis (vault miss always routes to HUMAN_REVIEW in these tests).

Requires the integration stack:
    docker compose -f infra/docker-compose.integration.yml up -d yugabyte immudb kafka temporal

Run:
    pytest tests/integration/cut1/ -m cut1 -v
"""
from __future__ import annotations

import subprocess
import sys
import time

import pytest
import pytest_asyncio

from tests.integration.conftest import (
    YUGABYTE_HOST, YUGABYTE_PORT, YUGABYTE_USER, YUGABYTE_PASSWORD, YUGABYTE_DATABASE,
    IMMUDB_HOST, IMMUDB_PORT, IMMUDB_USERNAME, IMMUDB_PASSWORD,
    KAFKA_BOOTSTRAP_SERVERS,
    TEMPORAL_HOST, TEMPORAL_PORT,
    _require, _port_open,
)
from tests.integration.stubs.ocr_server import OCR_STUB_PORT  # reuse same port
OCR_STUB_URL = f"http://localhost:{OCR_STUB_PORT}"

TEST_BANK_ID = "cut1-test-bank"
TEST_PEPPER  = "cut1-test-pepper-deadbeef01234567"


# ── Infrastructure requirements ──────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def require_cut1_infra():
    _require(YUGABYTE_HOST, YUGABYTE_PORT, "YugabyteDB (Cut 1)")
    _require(IMMUDB_HOST,   IMMUDB_PORT,   "Immudb (Cut 1)")
    _require("localhost",   9093,          "Kafka (Cut 1)")
    _require(TEMPORAL_HOST, TEMPORAL_PORT, "Temporal (Cut 1)")


# ── OCR stub subprocess ──────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def ocr_stub_server():
    if _port_open("localhost", OCR_STUB_PORT):
        yield OCR_STUB_URL
        return

    proc = subprocess.Popen(
        [sys.executable, "-m", "tests.integration.stubs.ocr_server"],
        env={**__import__("os").environ, "OCR_STUB_PORT": str(OCR_STUB_PORT)},
    )
    deadline = time.time() + 10
    while not _port_open("localhost", OCR_STUB_PORT):
        if time.time() > deadline:
            proc.kill()
            pytest.fail("OCR stub did not start within 10 seconds")
        time.sleep(0.2)

    yield OCR_STUB_URL
    proc.kill()
    proc.wait()


# ── YugabyteDB pool ──────────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="session")
async def cut1_db_pool(require_cut1_infra):
    import asyncpg
    pool = await asyncpg.create_pool(
        host=YUGABYTE_HOST, port=YUGABYTE_PORT,
        user=YUGABYTE_USER, password=YUGABYTE_PASSWORD, database=YUGABYTE_DATABASE,
        min_size=1, max_size=5,
    )
    yield pool
    await pool.close()


# ── Immudb client ────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def cut1_immudb_client(require_cut1_infra):
    from shared.audit.immudb_client import ImmudbClient
    client = ImmudbClient(
        host=IMMUDB_HOST, port=IMMUDB_PORT,
        username=IMMUDB_USERNAME, password=IMMUDB_PASSWORD,
    )
    client.connect()
    yield client
    client.disconnect()


# ── CascadeOrchestrator pointed at the stub ──────────────────────────────────

@pytest.fixture(scope="session")
def ocr_orchestrator(ocr_stub_server):
    from openai import AsyncOpenAI
    from shared.ai.model_cascade import CascadeOrchestrator
    client = AsyncOpenAI(base_url=f"{ocr_stub_server}/v1", api_key="stub")
    config = {
        "ai.cascade.l1_confidence_threshold": 0.85,
        "ai.cascade.high_value_threshold": 5_000_000.0,
        "ai.cascade.l2_escalation_enabled": False,
        "ai.cascade.l1_model_ocr": "got-ocr2-stub",
        "ai.cascade.l2_model_ocr": "got-ocr2-stub",
    }
    return CascadeOrchestrator(
        l1_client=client, l2_client=client, config=config, bank_id=TEST_BANK_ID
    )


# ── Kafka producer ───────────────────────────────────────────────────────────

@pytest.fixture
def kafka_producer(require_cut1_infra):
    from kafka import KafkaProducer
    import json as _json
    producer = KafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        value_serializer=lambda v: _json.dumps(v).encode("utf-8"),
    )
    yield producer
    producer.close()


@pytest.fixture
def kafka_consumer_factory(require_cut1_infra):
    from kafka import KafkaConsumer
    import json as _json
    consumers = []

    def _make(topic: str, group_id: str = "cut1-consumer"):
        c = KafkaConsumer(
            topic,
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            group_id=group_id,
            auto_offset_reset="latest",
            consumer_timeout_ms=8000,
            value_deserializer=lambda v: _json.loads(v.decode("utf-8")),
        )
        consumers.append(c)
        return c

    yield _make
    for c in consumers:
        c.close()


# ── Temporal client ──────────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="session")
async def temporal_client(require_cut1_infra):
    from temporalio.client import Client
    client = await Client.connect(f"{TEMPORAL_HOST}:{TEMPORAL_PORT}")
    yield client
