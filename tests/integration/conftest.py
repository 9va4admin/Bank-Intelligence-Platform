"""
Shared fixtures for tests/integration/ — real Redis, YugabyteDB, Immudb,
Kafka, MinIO. Nothing in this directory mocks I/O; every test here talks to
the containers in infra/docker-compose.integration.yml.

Why this directory exists: every other test in this repo (~3,300+ at last
count) verifies application code against mocked I/O boundaries only. That
caught interface bugs the mocks happened to get right by construction, but
missed several real ones the mocks quietly assumed away — see
shared/audit/immudb_client.py's write_event() (was calling a nonexistent
.immudb_database.set(), then the non-cryptographically-verified .set()
instead of .verifiedSet()) and the three real, previously-undiscovered
Alembic bugs fixed the same session these tests were written in (orphaned
migration file outside version_locations, ConfigParser %(...)s interpolation
crash, version_table_schema bootstrap ordering, a partitioned-table UNIQUE
constraint Postgres/YugabyteDB actually rejects). None of those were
reachable by a mock that had already decided what the real dependency does.

Run:
    docker compose -f infra/docker-compose.integration.yml up -d
    pytest tests/integration/ -m integration -v

Skipped automatically (not failed) when the compose stack isn't running --
see _require() below. CI's integration stage brings the stack up first;
local unit-test runs (`pytest -k "not integration"`, per cicd.md) never
reach these at all.
"""
import socket
from typing import Iterator

import pytest
import pytest_asyncio

# ---------------------------------------------------------------------------
# Connection constants -- match infra/docker-compose.integration.yml exactly.
# Host-mapped ports (left of the ':' in each service's `ports:` entry), since
# these tests run on the host, not inside the compose network.
# ---------------------------------------------------------------------------

REDIS_HOST = "localhost"
REDIS_PORT = 6389

YUGABYTE_HOST = "localhost"
YUGABYTE_PORT = 5443
YUGABYTE_USER = "yugabyte"
YUGABYTE_PASSWORD = "yugabyte"
YUGABYTE_DATABASE = "astra"

IMMUDB_HOST = "localhost"
IMMUDB_PORT = 3332
IMMUDB_USERNAME = "immudb"
IMMUDB_PASSWORD = "astra-it-immudb-pw"

KAFKA_BOOTSTRAP_SERVERS = "localhost:9093"

MINIO_ENDPOINT = "localhost:9020"
MINIO_ACCESS_KEY = "astra-it-admin"
MINIO_SECRET_KEY = "astra-it-password"

TEMPORAL_HOST = "localhost"
TEMPORAL_PORT = 7234


def _port_open(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _require(host: str, port: int, service: str) -> None:
    if not _port_open(host, port):
        pytest.skip(
            f"{service} not reachable at {host}:{port} -- start the stack with "
            f"`docker compose -f infra/docker-compose.integration.yml up -d`"
        )


@pytest.fixture(scope="session")
def require_redis() -> None:
    _require(REDIS_HOST, REDIS_PORT, "Redis")


@pytest.fixture(scope="session")
def require_yugabyte() -> None:
    _require(YUGABYTE_HOST, YUGABYTE_PORT, "YugabyteDB")


@pytest.fixture(scope="session")
def require_immudb() -> None:
    _require(IMMUDB_HOST, IMMUDB_PORT, "Immudb")


@pytest.fixture(scope="session")
def require_kafka() -> None:
    _require("localhost", 9093, "Kafka")


@pytest.fixture(scope="session")
def require_minio() -> None:
    _require("localhost", 9020, "MinIO")


@pytest.fixture(scope="session")
def require_temporal() -> None:
    _require(TEMPORAL_HOST, TEMPORAL_PORT, "Temporal")


@pytest_asyncio.fixture
async def redis_client(require_redis) -> Iterator["object"]:
    import redis.asyncio as aioredis

    client = aioredis.from_url(
        f"redis://{REDIS_HOST}:{REDIS_PORT}", encoding="utf-8", decode_responses=True,
    )
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def yugabyte_pool(require_yugabyte):
    import asyncpg

    pool = await asyncpg.create_pool(
        host=YUGABYTE_HOST, port=YUGABYTE_PORT,
        user=YUGABYTE_USER, password=YUGABYTE_PASSWORD, database=YUGABYTE_DATABASE,
        min_size=1, max_size=3,
    )
    yield pool
    await pool.close()
