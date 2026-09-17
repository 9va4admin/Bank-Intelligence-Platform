"""
Cut 1 conftest — Temporal + Kafka + OCR stub + YugabyteDB + Immudb.
No Redis (vault miss always routes to HUMAN_REVIEW in these tests).

Temporal is exercised via WorkflowEnvironment.start_local() — an embedded
in-process Temporal server. This avoids the external Docker container entirely
while still testing real Temporal activity registration and workflow execution.

Requires the integration stack (YugabyteDB, Immudb, Kafka):
    docker compose -f infra/docker-compose.integration.yml up -d yugabyte immudb kafka

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
    _require, _port_open,
)
from tests.integration.stubs.ocr_server import OCR_STUB_PORT

OCR_STUB_URL = f"http://localhost:{OCR_STUB_PORT}"

TEST_BANK_ID = "cut1-test-bank"
TEST_PEPPER  = "cut1-test-pepper-deadbeef01234567"


# ── Infrastructure requirements ──────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def require_cut1_infra():
    _require(YUGABYTE_HOST, YUGABYTE_PORT, "YugabyteDB (Cut 1)")
    _require(IMMUDB_HOST,   IMMUDB_PORT,   "Immudb (Cut 1)")
    _require("localhost",   9093,          "Kafka (Cut 1)")
    _bootstrap_schema_sync()
    _ensure_kafka_topics()


def _ensure_kafka_topics():
    """Pre-create topics so Kafka metadata is stable before any consumer subscribes."""
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
        pass
    finally:
        admin.close()
    time.sleep(1.0)


# ── OCR stub subprocess ──────────────────────────────────────────────────────

def _stub_healthy(url: str) -> bool:
    try:
        import httpx
        r = httpx.get(f"{url}/health", timeout=1.0)
        return r.status_code == 200 and r.json().get("service") == "ocr-stub"
    except Exception:
        return False


@pytest.fixture(scope="session")
def ocr_stub_server():
    if _stub_healthy(OCR_STUB_URL):
        yield OCR_STUB_URL
        return

    proc = subprocess.Popen(
        [sys.executable, "-m", "tests.integration.stubs.ocr_server"],
        env={**__import__("os").environ, "OCR_STUB_PORT": str(OCR_STUB_PORT)},
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


# ── YugabyteDB pool + minimal schema bootstrap ───────────────────────────────

_BOOTSTRAP_DDL = [
    'CREATE EXTENSION IF NOT EXISTS "uuid-ossp"',
    "CREATE SCHEMA IF NOT EXISTS cts",
    """CREATE TABLE IF NOT EXISTS cts.agent_decisions (
        decision_id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        instrument_id        TEXT NOT NULL,
        bank_id              TEXT NOT NULL,
        workflow_id          TEXT NOT NULL UNIQUE,
        decision             TEXT NOT NULL,
        decision_reason      TEXT,
        fraud_score          NUMERIC(5,4),
        shap_values          TEXT,
        processing_started_at TIMESTAMPTZ,
        processing_completed_at TIMESTAMPTZ,
        processing_duration_ms INTEGER,
        ocr_confidence       NUMERIC(5,4),
        alteration_detected  BOOLEAN DEFAULT false,
        signature_match_score NUMERIC(5,4),
        signature_verdict    TEXT,
        pps_checked          BOOLEAN DEFAULT false,
        pps_verdict          TEXT,
        cbs_balance_status   TEXT,
        degraded_mode        BOOLEAN DEFAULT false,
        ocr_engines_used     TEXT[],
        indic_ocr_kill_switch_active BOOLEAN DEFAULT false,
        iet_margin_seconds   INTEGER DEFAULT 0,
        steps_digest         TEXT,
        registry_version     TEXT,
        created_at           TIMESTAMPTZ DEFAULT now()
    )""",
]


def _bootstrap_schema_sync():
    """Run DDL synchronously using psycopg2 (no event-loop dependency)."""
    import psycopg2
    conn = psycopg2.connect(
        host=YUGABYTE_HOST, port=YUGABYTE_PORT,
        user=YUGABYTE_USER, password=YUGABYTE_PASSWORD, dbname=YUGABYTE_DATABASE,
    )
    conn.autocommit = True
    cur = conn.cursor()
    for stmt in _BOOTSTRAP_DDL:
        cur.execute(stmt)
    cur.close()
    conn.close()


@pytest_asyncio.fixture
async def cut1_db_pool(require_cut1_infra):
    """Function-scoped pool — each test gets its own pool in its event loop."""
    import asyncpg
    pool = await asyncpg.create_pool(
        host=YUGABYTE_HOST, port=YUGABYTE_PORT,
        user=YUGABYTE_USER, password=YUGABYTE_PASSWORD, database=YUGABYTE_DATABASE,
        min_size=1, max_size=3,
    )
    yield pool
    await pool.close()


# ── Immudb client ────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def cut1_immudb_client(require_cut1_infra):
    from shared.audit.immudb_client import ImmudbClient
    client = ImmudbClient()
    client.connect(
        host=IMMUDB_HOST, port=IMMUDB_PORT,
        bank_id="cut1-test",
        collection="cts_cut1_events",
        username=IMMUDB_USERNAME, password=IMMUDB_PASSWORD,
    )
    yield client


# ── AsyncImmudbWriter (what write_audit activity expects) ────────────────────

@pytest.fixture(scope="session")
def cut1_immudb_writer(cut1_immudb_client):
    from shared.audit.immudb_writer import AsyncImmudbWriter
    return AsyncImmudbWriter(cut1_immudb_client)


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
        acks="all",
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
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            group_id=group_id,
            auto_offset_reset="latest",
            consumer_timeout_ms=8000,
            value_deserializer=lambda v: _json.loads(v.decode("utf-8")),
            enable_auto_commit=False,
        )
        c.subscribe([topic])
        deadline = time.time() + 10.0
        assigned = set()
        while not assigned and time.time() < deadline:
            c.poll(timeout_ms=1000)
            assigned = c.assignment()
        if assigned:
            c.seek_to_end(*assigned)
            c.poll(timeout_ms=200)
        consumers.append(c)
        return c

    yield _make
    for c in consumers:
        c.close()


# ── Temporal — embedded in-process (WorkflowEnvironment.start_local) ─────────

@pytest_asyncio.fixture(scope="session")
async def temporal_env():
    """
    Embedded Temporal server — no external Docker container needed.
    WorkflowEnvironment.start_local() starts a real Temporal server inside
    the test process. Cut 1 uses this for activity registration checks and
    workflow execution tests.
    """
    from temporalio.testing import WorkflowEnvironment
    env = await WorkflowEnvironment.start_local()
    yield env
    await env.shutdown()


@pytest_asyncio.fixture(scope="session")
async def temporal_client(temporal_env):
    yield temporal_env.client
