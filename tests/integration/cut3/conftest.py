"""
Cut 3 conftest — Temporal + Redis + OCR stub + YugabyteDB + Immudb.
No Kafka (Kafka events are mocked/skipped to isolate Temporal ↔ vault interaction).

Temporal uses WorkflowEnvironment.start_time_skipping() — an embedded in-process
server with time-skip support. No external Temporal Docker container required.

Requires:
    docker compose -f infra/docker-compose.integration.yml up -d redis yugabyte immudb

Run:
    pytest tests/integration/cut3/ -m cut3 -v
"""
from __future__ import annotations

import subprocess
import sys
import time

import pytest
import pytest_asyncio

from tests.integration.conftest import (
    REDIS_HOST, REDIS_PORT,
    YUGABYTE_HOST, YUGABYTE_PORT, YUGABYTE_USER, YUGABYTE_PASSWORD, YUGABYTE_DATABASE,
    IMMUDB_HOST, IMMUDB_PORT, IMMUDB_USERNAME, IMMUDB_PASSWORD,
    _require, _port_open,
)
from tests.integration.stubs.ocr_server import OCR_STUB_PORT

OCR_STUB_URL = f"http://localhost:{OCR_STUB_PORT}"

TEST_BANK_ID = "cut3-test-bank"
TEST_PEPPER  = "cut3-test-pepper-deadbeef01234567"


# ── Infrastructure requirements ──────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def require_cut3_infra():
    _require(REDIS_HOST,    REDIS_PORT,    "Redis (Cut 3)")
    _require(YUGABYTE_HOST, YUGABYTE_PORT, "YugabyteDB (Cut 3)")
    _require(IMMUDB_HOST,   IMMUDB_PORT,   "Immudb (Cut 3)")
    _bootstrap_schema_sync()


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
    """CREATE TABLE IF NOT EXISTS cts.signature_embeddings (
        id               BIGSERIAL PRIMARY KEY,
        bank_id          TEXT NOT NULL,
        account_hash     TEXT NOT NULL,
        signatory_id     TEXT NOT NULL DEFAULT 'PRIMARY',
        specimen_index   INTEGER NOT NULL,
        embedding        BYTEA NOT NULL,
        source           TEXT NOT NULL DEFAULT 'CBS',
        created_at       TIMESTAMPTZ DEFAULT now(),
        updated_at       TIMESTAMPTZ DEFAULT now(),
        UNIQUE (bank_id, account_hash, signatory_id, specimen_index)
    )""",
    """CREATE TABLE IF NOT EXISTS cts.account_signatories (
        id            BIGSERIAL PRIMARY KEY,
        bank_id       TEXT NOT NULL,
        account_hash  TEXT NOT NULL,
        signatory_id  TEXT NOT NULL DEFAULT 'PRIMARY',
        mandate_rule  TEXT NOT NULL DEFAULT 'ANY_ONE',
        quorum_n      INTEGER,
        is_active     BOOLEAN DEFAULT true,
        created_at    TIMESTAMPTZ DEFAULT now()
    )""",
]


def _bootstrap_schema_sync():
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


# ── Redis (sync — SignatureVault uses sync redis) ─────────────────────────────

@pytest.fixture
def redis_sync(require_cut3_infra):
    import redis as sync_redis
    client = sync_redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=2, decode_responses=False)
    yield client
    client.flushdb()
    client.close()


# ── YugabyteDB pool (function-scoped — avoids cross-event-loop issues) ────────

@pytest_asyncio.fixture
async def cut3_db_pool(require_cut3_infra):
    import asyncpg
    pool = await asyncpg.create_pool(
        host=YUGABYTE_HOST, port=YUGABYTE_PORT,
        user=YUGABYTE_USER, password=YUGABYTE_PASSWORD, database=YUGABYTE_DATABASE,
        min_size=1, max_size=3,
    )
    yield pool
    await pool.close()


# ── SignatureVault (Redis + DB fallback) ─────────────────────────────────────

@pytest_asyncio.fixture
async def sig_vault(redis_sync, cut3_db_pool):
    from modules.cts.vaults.signature_vault import SignatureVault
    vault = SignatureVault(bank_id=TEST_BANK_ID, pepper=TEST_PEPPER, db_pool=cut3_db_pool)
    vault.connect(redis_client=redis_sync)
    return vault


# ── Immudb client ────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def cut3_immudb_client(require_cut3_infra):
    from shared.audit.immudb_client import ImmudbClient
    client = ImmudbClient()
    client.connect(
        host=IMMUDB_HOST, port=IMMUDB_PORT,
        bank_id="cut3-test",
        collection="cts_cut3_events",
        username=IMMUDB_USERNAME, password=IMMUDB_PASSWORD,
    )
    yield client


@pytest.fixture(scope="session")
def cut3_immudb_writer(cut3_immudb_client):
    from shared.audit.immudb_writer import AsyncImmudbWriter
    return AsyncImmudbWriter(cut3_immudb_client)


# ── Temporal — embedded time-skipping environment ────────────────────────────

@pytest_asyncio.fixture
async def time_skip_env():
    """
    Temporal WorkflowEnvironment with time-skipping enabled (embedded in-process).
    Collapses 3-hour IET window and 55-min human review timeout into milliseconds.
    No external Docker Temporal container required.
    """
    from temporalio.testing import WorkflowEnvironment
    async with await WorkflowEnvironment.start_time_skipping() as env:
        yield env


# ── CascadeOrchestrator ──────────────────────────────────────────────────────

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
