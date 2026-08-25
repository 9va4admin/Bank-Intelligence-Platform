"""
Cut 3 conftest — Temporal + Redis + OCR stub + YugabyteDB + Immudb.
No Kafka (Kafka events are mocked/skipped to isolate Temporal ↔ vault interaction).

Requires:
    docker compose -f infra/docker-compose.integration.yml up -d redis yugabyte immudb temporal

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
    TEMPORAL_HOST, TEMPORAL_PORT,
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
    _require(TEMPORAL_HOST, TEMPORAL_PORT, "Temporal (Cut 3)")


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
            pytest.fail("OCR stub did not start")
        time.sleep(0.2)
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


# ── SignatureVault (Redis + DB fallback) ─────────────────────────────────────

@pytest.fixture
def sig_vault(redis_sync, cut3_db_pool):
    from modules.cts.vaults.signature_vault import SignatureVault
    vault = SignatureVault(bank_id=TEST_BANK_ID, pepper=TEST_PEPPER, db_pool=cut3_db_pool)
    vault.connect(redis_client=redis_sync)
    return vault


# ── YugabyteDB pool ──────────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="session")
async def cut3_db_pool(require_cut3_infra):
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
def cut3_immudb_client(require_cut3_infra):
    from shared.audit.immudb_client import ImmudbClient
    client = ImmudbClient(
        host=IMMUDB_HOST, port=IMMUDB_PORT,
        username=IMMUDB_USERNAME, password=IMMUDB_PASSWORD,
    )
    client.connect()
    yield client
    client.disconnect()


# ── Temporal client (time-skipping enabled) ──────────────────────────────────

@pytest_asyncio.fixture(scope="session")
async def temporal_client_timeskip(require_cut3_infra):
    """Standard Temporal client — time-skipping is per-WorkflowEnvironment, not client-level."""
    from temporalio.client import Client
    client = await Client.connect(f"{TEMPORAL_HOST}:{TEMPORAL_PORT}")
    yield client


@pytest_asyncio.fixture
async def time_skip_env():
    """
    Temporal WorkflowEnvironment with time-skipping enabled.
    Collapses 3-hour IET window and 55-min human review timeout into milliseconds.
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
