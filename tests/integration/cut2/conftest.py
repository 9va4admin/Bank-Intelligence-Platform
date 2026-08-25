"""
Cut 2 conftest — Kafka + Redis + OCR stub.
No Temporal, no YugabyteDB, no Immudb.

Requires the integration stack:
    docker compose -f infra/docker-compose.integration.yml up -d redis kafka

Run:
    pytest tests/integration/cut2/ -m cut2 -v
"""
from __future__ import annotations

import subprocess
import sys
import time
import socket

import pytest
import pytest_asyncio

# Re-use port constants from parent conftest
from tests.integration.conftest import (
    REDIS_HOST, REDIS_PORT,
    KAFKA_BOOTSTRAP_SERVERS,
    _require, _port_open,
)

OCR_STUB_PORT = 8010
OCR_STUB_URL = f"http://localhost:{OCR_STUB_PORT}"

TEST_BANK_ID = "cut2-test-bank"
TEST_PEPPER  = "cut2-test-pepper-deadbeef01234567"


# ── Infrastructure requirements ──────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def require_cut2_infra():
    _require(REDIS_HOST, REDIS_PORT, "Redis (Cut 2)")
    _require("localhost", 9093, "Kafka (Cut 2)")


# ── OCR stub subprocess ──────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def ocr_stub_server():
    """Start the OCR stub as a subprocess; kill it after the session."""
    if _port_open("localhost", OCR_STUB_PORT):
        yield OCR_STUB_URL
        return

    proc = subprocess.Popen(
        [sys.executable, "-m", "tests.integration.stubs.ocr_server"],
        env={**__import__("os").environ, "OCR_STUB_PORT": str(OCR_STUB_PORT)},
    )
    # Wait until the stub is accepting connections (max 10s)
    deadline = time.time() + 10
    while not _port_open("localhost", OCR_STUB_PORT):
        if time.time() > deadline:
            proc.kill()
            pytest.fail("OCR stub did not start within 10 seconds")
        time.sleep(0.2)

    yield OCR_STUB_URL
    proc.kill()
    proc.wait()


# ── Redis client (sync — SignatureVault uses sync redis) ─────────────────────

@pytest.fixture
def redis_sync(require_cut2_infra):
    import redis as sync_redis
    client = sync_redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=1, decode_responses=False)
    yield client
    client.flushdb()   # clean up test keys after each test
    client.close()


# ── SignatureVault (Redis-only — no DB pool) ─────────────────────────────────

@pytest.fixture
def sig_vault(redis_sync):
    from modules.cts.vaults.signature_vault import SignatureVault
    vault = SignatureVault(bank_id=TEST_BANK_ID, pepper=TEST_PEPPER, db_pool=None)
    vault.connect(redis_client=redis_sync)
    return vault


# ── PPSVault (Redis-only — no DB pool) ───────────────────────────────────────

@pytest.fixture
def pps_vault(redis_sync):
    from modules.cts.vaults.pps_vault import PPSVault
    vault = PPSVault(bank_id=TEST_BANK_ID, pepper=TEST_PEPPER, db_pool=None)
    vault.connect(redis_client=redis_sync)
    return vault


# ── Kafka producer / consumer helpers ────────────────────────────────────────

@pytest.fixture
def kafka_producer(require_cut2_infra):
    from kafka import KafkaProducer
    import json as _json
    producer = KafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        value_serializer=lambda v: _json.dumps(v).encode("utf-8"),
    )
    yield producer
    producer.close()


@pytest.fixture
def kafka_consumer_factory(require_cut2_infra):
    from kafka import KafkaConsumer
    import json as _json
    consumers = []

    def _make(topic: str, group_id: str = "cut2-test-consumer"):
        c = KafkaConsumer(
            topic,
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            group_id=group_id,
            auto_offset_reset="latest",
            consumer_timeout_ms=5000,
            value_deserializer=lambda v: _json.loads(v.decode("utf-8")),
        )
        consumers.append(c)
        return c

    yield _make

    for c in consumers:
        c.close()


# ── CascadeOrchestrator pointed at the stub ──────────────────────────────────

@pytest.fixture
def ocr_orchestrator(ocr_stub_server):
    """Returns a CascadeOrchestrator whose L1 and L2 both point at the OCR stub."""
    from openai import AsyncOpenAI
    from shared.ai.model_cascade import CascadeOrchestrator

    client = AsyncOpenAI(base_url=f"{ocr_stub_server}/v1", api_key="stub")
    config = {
        "ai.cascade.l1_confidence_threshold": 0.85,
        "ai.cascade.high_value_threshold": 5_000_000.0,
        "ai.cascade.l2_escalation_enabled": False,   # always L1 in stub tests
        "ai.cascade.l1_model_ocr": "got-ocr2-stub",
        "ai.cascade.l2_model_ocr": "got-ocr2-stub",
    }
    return CascadeOrchestrator(l1_client=client, l2_client=client, config=config, bank_id=TEST_BANK_ID)
