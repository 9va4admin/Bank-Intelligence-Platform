"""
Cut 2 conftest — Kafka + Redis + OCR stub.
No Temporal, no YugabyteDB, no Immudb.

Requires:
    docker compose -f infra/docker-compose.integration.yml up -d redis kafka

Run:
    pytest tests/integration/cut2/ -m cut2 -v
"""
from __future__ import annotations

import subprocess
import sys
import time

import pytest
import pytest_asyncio

from tests.integration.conftest import (
    REDIS_HOST, REDIS_PORT,
    KAFKA_BOOTSTRAP_SERVERS,
    _require, _port_open,
)
from tests.integration.stubs.ocr_server import OCR_STUB_PORT

OCR_STUB_URL = f"http://localhost:{OCR_STUB_PORT}"

TEST_BANK_ID = "cut2-test-bank"
TEST_PEPPER  = "cut2-test-pepper-deadbeef01234567"


# ── Infrastructure requirements ──────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def require_cut2_infra():
    _require(REDIS_HOST, REDIS_PORT, "Redis (Cut 2)")
    _require("localhost", 9093, "Kafka (Cut 2)")
    _ensure_kafka_topics()


def _ensure_kafka_topics():
    """
    Pre-create all topics used in Cut 2 so that partition metadata is stable
    before any consumer subscribes.  Without this, auto-created topics on first
    subscribe can still be in a metadata-propagation window when the consumer
    calls seek_to_end(), causing it to miss messages produced immediately after.
    """
    from kafka.admin import KafkaAdminClient, NewTopic
    from kafka.errors import TopicAlreadyExistsError

    topics_needed = [
        "platform.audit.events",
        f"cts.inward.{TEST_BANK_ID}",
    ]
    admin = KafkaAdminClient(bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS)
    new_topics = [
        NewTopic(name=t, num_partitions=1, replication_factor=1)
        for t in topics_needed
    ]
    try:
        admin.create_topics(new_topics=new_topics, validate_only=False)
    except TopicAlreadyExistsError:
        pass
    except Exception:
        pass  # broker may reject duplicates differently; proceed
    finally:
        admin.close()

    # Brief wait for metadata propagation
    time.sleep(1.0)


# ── OCR stub subprocess ──────────────────────────────────────────────────────

def _stub_healthy(url: str) -> bool:
    """Returns True only if OUR stub is running (checks /health service name)."""
    try:
        import httpx
        r = httpx.get(f"{url}/health", timeout=1.0)
        return r.status_code == 200 and r.json().get("service") == "ocr-stub"
    except Exception:
        return False


@pytest.fixture(scope="session")
def ocr_stub_server():
    """Start the OCR stub as a subprocess; kill it after the session."""
    if _stub_healthy(OCR_STUB_URL):
        yield OCR_STUB_URL
        return

    proc = subprocess.Popen(
        [sys.executable, "-m", "tests.integration.stubs.ocr_server"],
        env=__import__("os").environ.copy(),
    )
    deadline = time.time() + 12
    while not _stub_healthy(OCR_STUB_URL):
        if time.time() > deadline:
            proc.kill()
            pytest.fail(f"OCR stub did not start within 12s on port {OCR_STUB_PORT}")
        time.sleep(0.3)

    yield OCR_STUB_URL
    proc.kill()
    proc.wait()


# ── Redis client (sync — SignatureVault uses sync redis) ─────────────────────

@pytest.fixture
def redis_sync(require_cut2_infra):
    import redis as sync_redis
    client = sync_redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=1, decode_responses=False)
    yield client
    client.flushdb()
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


# ── Kafka producer ────────────────────────────────────────────────────────────

@pytest.fixture
def kafka_producer(require_cut2_infra):
    from kafka import KafkaProducer
    import json as _json
    producer = KafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        value_serializer=lambda v: _json.dumps(v).encode("utf-8"),
        acks="all",
    )
    yield producer
    producer.close()


# ── Kafka consumer factory (seek-to-end before producing) ───────────────────

@pytest.fixture
def kafka_consumer_factory(require_cut2_infra):
    """
    Returns a factory that creates a KafkaConsumer already positioned at the
    end of the topic partition — so only messages produced AFTER calling this
    factory are returned.  Call make(topic) before producing your test message.
    """
    from kafka import KafkaConsumer
    import json as _json
    consumers = []

    def _make(topic: str, group_id: str = "cut2-consumer"):
        c = KafkaConsumer(
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            group_id=group_id,
            auto_offset_reset="latest",
            consumer_timeout_ms=8000,
            value_deserializer=lambda v: _json.loads(v.decode("utf-8")),
            enable_auto_commit=False,
        )
        c.subscribe([topic])
        # Retry until partition assignment is stable, then seek to end.
        # Without the retry, the first poll may time out before Kafka's group
        # coordinator finishes rebalancing (especially on freshly created topics).
        deadline = time.time() + 10.0
        assigned = set()
        while not assigned and time.time() < deadline:
            c.poll(timeout_ms=1000)
            assigned = c.assignment()
        if assigned:
            c.seek_to_end(*assigned)
            # One more short poll to flush the seek internally
            c.poll(timeout_ms=200)
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

    # base_url must NOT include /v1 here — the OpenAI client appends /v1 internally
    # when using the standard chat.completions path.
    # Our stub serves at /v1/chat/completions, so base_url = http://host:port/v1
    client = AsyncOpenAI(base_url=f"{ocr_stub_server}/v1", api_key="stub")
    config = {
        "ai.cascade.l1_confidence_threshold": 0.85,
        "ai.cascade.high_value_threshold": 5_000_000.0,
        "ai.cascade.l2_escalation_enabled": False,
        "ai.cascade.l1_model_ocr": "got-ocr2-stub",
        "ai.cascade.l2_model_ocr": "got-ocr2-stub",
    }
    return CascadeOrchestrator(l1_client=client, l2_client=client, config=config, bank_id=TEST_BANK_ID)
