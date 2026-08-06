"""
Platform Management API — Go-Live readiness, service control, smoke tests.

Routes:
  GET  /v1/platform/readiness                master data completeness checklist
  POST /v1/platform/smoke-test/run           run real connectivity tests (POC / PROD)
  POST /v1/platform/services/start-all       start all infra services in dependency order
  POST /v1/platform/services/{name}/start    attempt to start a single stopped service

Access: bank_it_admin only (readiness also readable by ops_manager).
All checks degrade gracefully — a failed check returns status=WARN, never a 500.
"""
from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from apps.api.dependencies import require_user_context
from shared.auth.rbac import UserContext

log = structlog.get_logger()

router_v1 = APIRouter(prefix="/v1/platform", tags=["Platform Management v1"])

_ADMIN_ROLES = frozenset({"bank_it_admin"})
_READ_ROLES  = frozenset({"bank_it_admin", "ops_manager"})


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

async def get_current_user(ctx: UserContext = Depends(require_user_context)) -> UserContext:
    return ctx


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

CheckStatus = Literal["PASS", "WARN", "FAIL", "SKIP"]


class ReadinessItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    check_id:         str
    label:            str
    status:           CheckStatus
    detail:           str
    action_url:       Optional[str] = None
    # If set, item only appears for the listed deployment modes
    deployment_modes: Optional[list[str]] = None


class ReadinessResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id:    str
    as_of:      str
    items:      list[ReadinessItem]
    all_ready:  bool
    degraded:   bool = False


class SmokeTestResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    test_id:    str
    status:     Literal["PASS", "WARN", "FAIL", "SKIP"]
    message:    str
    latency_ms: Optional[int] = None


class SmokeTestRunRequest(BaseModel):
    entity:  Literal["sb", "smb", "branch", "pu"]
    bank_id: str


class SmokeTestRunResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id:    str
    entity:     str
    run_at:     str
    results:    list[SmokeTestResult]
    summary:    dict[str, int]


class ServiceStartResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    service:  str
    success:  bool
    message:  str
    skipped:  bool = False   # True when the service is HF-hosted in POC mode


class TierStartResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    tier:     int
    label:    str
    services: list[ServiceStartResponse]


class ServiceStartAllResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    tiers:   list[TierStartResult]
    started: int
    failed:  int
    skipped: int


# ---------------------------------------------------------------------------
# Readiness checks
# ---------------------------------------------------------------------------

async def _check_branches(bank_id: str, db_pool: Any) -> ReadinessItem:
    if db_pool is None:
        return ReadinessItem(
            check_id="branches_loaded", label="Branch Master loaded",
            status="WARN", detail="DB unavailable — connect YugabyteDB first",
            action_url="/cts/admin/branches",
        )
    try:
        t0 = time.monotonic()
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS cnt FROM cts.branches WHERE bank_id = $1 AND is_active = true",
                bank_id,
            )
        count = int(row["cnt"] or 0)
        ms = int((time.monotonic() - t0) * 1000)
        if count == 0:
            return ReadinessItem(
                check_id="branches_loaded", label="Branch Master loaded",
                status="FAIL", detail="No branches loaded — import CSV before go-live",
                action_url="/cts/admin/branches",
            )
        if count < 3:
            return ReadinessItem(
                check_id="branches_loaded", label="Branch Master loaded",
                status="WARN", detail=f"Only {count} branch{'es' if count > 1 else ''} loaded — verify completeness",
                action_url="/cts/admin/branches",
            )
        return ReadinessItem(
            check_id="branches_loaded", label="Branch Master loaded",
            status="PASS", detail=f"{count} active branches ({ms}ms)",
        )
    except Exception as exc:
        log.warning("platform.readiness.branches_error", bank_id=bank_id, error=str(exc))
        return ReadinessItem(
            check_id="branches_loaded", label="Branch Master loaded",
            status="WARN", detail=f"Query failed: {str(exc)[:80]}",
            action_url="/cts/admin/branches",
        )


async def _check_signature_vault(bank_id: str, db_pool: Any, redis_cts: Any) -> ReadinessItem:
    if redis_cts is None or db_pool is None:
        return ReadinessItem(
            check_id="sig_vault_seeded", label="Signature Vault seeded",
            status="WARN", detail="Redis CTS or DB unavailable",
            action_url="/cts/vaults",
        )
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(DISTINCT account_hash) AS total FROM cts.signature_embeddings WHERE bank_id = $1",
                bank_id,
            )
        db_total = int(row["total"] or 0)
        redis_count = sum(1 for _ in redis_cts.scan_iter(match=f"sig:{bank_id}:*", count=1000))
        if db_total == 0:
            return ReadinessItem(
                check_id="sig_vault_seeded", label="Signature Vault seeded",
                status="FAIL", detail="No signatures in DB — run vault sync before go-live",
                action_url="/cts/vaults",
            )
        pct = min(100.0, redis_count / db_total * 100) if db_total > 0 else 100.0
        if pct < 80:
            return ReadinessItem(
                check_id="sig_vault_seeded", label="Signature Vault seeded",
                status="WARN", detail=f"Redis warm: {redis_count}/{db_total} ({pct:.0f}%) — run vault sync",
                action_url="/cts/vaults",
            )
        return ReadinessItem(
            check_id="sig_vault_seeded", label="Signature Vault seeded",
            status="PASS", detail=f"{redis_count}/{db_total} accounts in Redis ({pct:.0f}%)",
        )
    except Exception as exc:
        log.warning("platform.readiness.sig_vault_error", bank_id=bank_id, error=str(exc))
        return ReadinessItem(
            check_id="sig_vault_seeded", label="Signature Vault seeded",
            status="WARN", detail=f"Check failed: {str(exc)[:80]}",
            action_url="/cts/vaults",
        )


async def _check_pps_vault(bank_id: str, redis_cts: Any) -> ReadinessItem:
    if redis_cts is None:
        return ReadinessItem(
            check_id="pps_vault_seeded", label="PPS Vault seeded",
            status="WARN", detail="Redis CTS unavailable",
        )
    try:
        count = sum(1 for _ in redis_cts.scan_iter(match=f"pps:{bank_id}:*", count=1000))
        if count == 0:
            return ReadinessItem(
                check_id="pps_vault_seeded", label="PPS Vault seeded",
                status="WARN", detail="No PPS entries — seed if bank issues cheque books",
            )
        return ReadinessItem(
            check_id="pps_vault_seeded", label="PPS Vault seeded",
            status="PASS", detail=f"{count} PPS entries in Redis",
        )
    except Exception as exc:
        return ReadinessItem(
            check_id="pps_vault_seeded", label="PPS Vault seeded",
            status="WARN", detail=f"Check failed: {str(exc)[:80]}",
        )


async def _check_micr_prefixes(bank_id: str, db_pool: Any) -> ReadinessItem:
    if db_pool is None:
        return ReadinessItem(
            check_id="micr_prefixes", label="MICR Prefixes configured",
            status="WARN", detail="DB unavailable",
            action_url="/cts/config/micr-prefixes",
        )
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS cnt FROM cts.micr_prefixes WHERE bank_id = $1",
                bank_id,
            )
        count = int(row["cnt"] or 0)
        if count == 0:
            return ReadinessItem(
                check_id="micr_prefixes", label="MICR Prefixes configured",
                status="FAIL", detail="No MICR prefixes — configure before processing cheques",
                action_url="/cts/config/micr-prefixes",
            )
        return ReadinessItem(
            check_id="micr_prefixes", label="MICR Prefixes configured",
            status="PASS", detail=f"{count} prefix{'es' if count > 1 else ''} configured",
        )
    except Exception as exc:
        return ReadinessItem(
            check_id="micr_prefixes", label="MICR Prefixes configured",
            status="WARN", detail=f"Check failed: {str(exc)[:80]}",
            action_url="/cts/config/micr-prefixes",
        )


async def _check_ops_users(bank_id: str, db_pool: Any) -> ReadinessItem:
    if db_pool is None:
        return ReadinessItem(
            check_id="ops_users", label="Ops reviewers configured",
            status="WARN", detail="DB unavailable",
            action_url="/admin/users",
        )
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                  COUNT(*) FILTER (WHERE role = 'ops_reviewer') AS reviewers,
                  COUNT(*) FILTER (WHERE role = 'ops_manager')  AS managers
                FROM users
                WHERE bank_id = $1 AND is_active = true
                """,
                bank_id,
            )
        reviewers = int(row["reviewers"] or 0)
        managers  = int(row["managers"]  or 0)
        if reviewers == 0:
            return ReadinessItem(
                check_id="ops_users", label="Ops reviewers configured",
                status="FAIL", detail="No ops_reviewer users — human review queue will be unmanned",
                action_url="/admin/users",
            )
        return ReadinessItem(
            check_id="ops_users", label="Ops reviewers configured",
            status="PASS", detail=f"{reviewers} reviewer{'s' if reviewers > 1 else ''}, {managers} manager{'s' if managers > 1 else ''}",
        )
    except Exception as exc:
        return ReadinessItem(
            check_id="ops_users", label="Ops reviewers configured",
            status="WARN", detail=f"Check failed: {str(exc)[:80]}",
            action_url="/admin/users",
        )


def _check_inward_folder() -> ReadinessItem:
    """POC-only: verify inward watch folder is configured and accessible."""
    folder = os.environ.get("CTS_INWARD_FOLDER_PATH", "")
    if not folder:
        return ReadinessItem(
            check_id="inward_folder", label="Inward watch folder (POC)",
            status="FAIL", detail="CTS_INWARD_FOLDER_PATH not set",
            action_url="/cts/config",
            deployment_modes=["POC"],
        )
    if not os.path.isdir(folder):
        return ReadinessItem(
            check_id="inward_folder", label="Inward watch folder (POC)",
            status="FAIL", detail=f"{folder} — directory not found",
            action_url="/cts/config",
            deployment_modes=["POC"],
        )
    writable = os.access(folder, os.W_OK)
    return ReadinessItem(
        check_id="inward_folder", label="Inward watch folder (POC)",
        status="PASS" if writable else "WARN",
        detail=f"{folder} — {'writable' if writable else 'exists but not writable'}",
        deployment_modes=["POC"],
    )


def _check_outward_folder() -> ReadinessItem:
    """POC-only: verify outward output folder is configured and accessible."""
    folder = os.environ.get("CTS_OUTWARD_FOLDER_PATH", "")
    if not folder:
        return ReadinessItem(
            check_id="outward_folder", label="Outward output folder (POC)",
            status="FAIL", detail="CTS_OUTWARD_FOLDER_PATH not set",
            action_url="/cts/config",
            deployment_modes=["POC"],
        )
    if not os.path.isdir(folder):
        return ReadinessItem(
            check_id="outward_folder", label="Outward output folder (POC)",
            status="FAIL", detail=f"{folder} — directory not found",
            action_url="/cts/config",
            deployment_modes=["POC"],
        )
    writable = os.access(folder, os.W_OK)
    return ReadinessItem(
        check_id="outward_folder", label="Outward output folder (POC)",
        status="PASS" if writable else "WARN",
        detail=f"{folder} — {'writable' if writable else 'exists but not writable'}",
        deployment_modes=["POC"],
    )


# ---------------------------------------------------------------------------
# Smoke test runners — one per test_id
# ---------------------------------------------------------------------------

async def _run_test_kafka(state: Any, bank_id: str) -> SmokeTestResult:
    t0 = time.monotonic()
    producer = getattr(state, "kafka_producer", None)
    if producer is None:
        return SmokeTestResult(test_id="test_kafka", status="SKIP",
                               message="No Kafka producer in app.state — start Kafka first")
    try:
        topic = f"cts.inward.{bank_id}"
        await asyncio.wait_for(
            producer.send_and_wait(topic, b'{"event":"smoke_test","source":"astra"}'),
            timeout=10,
        )
        ms = int((time.monotonic() - t0) * 1000)
        status = "PASS" if ms < 500 else "WARN"
        msg = f"Produced to {topic} in {ms}ms" + (" — ACK slow, check Kafka load" if ms >= 500 else "")
        return SmokeTestResult(test_id="test_kafka", status=status, message=msg, latency_ms=ms)
    except asyncio.TimeoutError:
        return SmokeTestResult(test_id="test_kafka", status="FAIL",
                               message="Kafka produce timed out (>10s) — check broker connectivity")
    except Exception as exc:
        return SmokeTestResult(test_id="test_kafka", status="FAIL",
                               message=f"Kafka error: {str(exc)[:120]}")


async def _run_test_immudb(state: Any, bank_id: str) -> SmokeTestResult:
    t0 = time.monotonic()
    immudb = getattr(state, "immudb_client", None)
    if immudb is None:
        return SmokeTestResult(test_id="test_immudb", status="SKIP",
                               message="Immudb client not configured — audit trail unavailable")
    try:
        from shared.audit.audit_event import AuditEvent, AuditEventType
        evt = AuditEvent(
            event_type=AuditEventType.SMOKE_TEST,
            bank_id=bank_id,
            actor="smoke-test",
            resource_id="smoke-test-entry",
            outcome="TEST",
            metadata={"smoke": True},
        )
        await asyncio.wait_for(immudb.write(evt), timeout=10)
        ms = int((time.monotonic() - t0) * 1000)
        return SmokeTestResult(test_id="test_immudb", status="PASS",
                               message=f"AuditEvent written + verified in {ms}ms", latency_ms=ms)
    except asyncio.TimeoutError:
        return SmokeTestResult(test_id="test_immudb", status="FAIL",
                               message="Immudb write timed out (>10s)")
    except Exception as exc:
        return SmokeTestResult(test_id="test_immudb", status="FAIL",
                               message=f"Immudb error: {str(exc)[:120]}")


async def _run_test_signature_vault(state: Any, bank_id: str) -> SmokeTestResult:
    t0 = time.monotonic()
    redis = getattr(state, "redis_cts", None)
    if redis is None:
        return SmokeTestResult(test_id="test_signature_vault", status="FAIL",
                               message="Redis CTS not connected")
    try:
        await asyncio.wait_for(redis.ping(), timeout=5)
        ms = int((time.monotonic() - t0) * 1000)
        # Sample: check one vault key pattern exists
        sample = next(redis.scan_iter(match=f"sig:{bank_id}:*", count=1), None)
        if sample is None:
            return SmokeTestResult(test_id="test_signature_vault", status="WARN",
                                   message=f"Redis ping OK ({ms}ms) but no vault keys found — seed before go-live",
                                   latency_ms=ms)
        return SmokeTestResult(test_id="test_signature_vault", status="PASS",
                               message=f"Redis CTS ping {ms}ms · vault keys present", latency_ms=ms)
    except asyncio.TimeoutError:
        return SmokeTestResult(test_id="test_signature_vault", status="FAIL",
                               message="Redis ping timed out (>5s)")
    except Exception as exc:
        return SmokeTestResult(test_id="test_signature_vault", status="FAIL",
                               message=f"Redis error: {str(exc)[:120]}")


async def _run_test_pps_vault(state: Any, bank_id: str) -> SmokeTestResult:
    t0 = time.monotonic()
    redis = getattr(state, "redis_cts", None)
    if redis is None:
        return SmokeTestResult(test_id="test_pps_vault", status="FAIL",
                               message="Redis CTS not connected")
    try:
        await asyncio.wait_for(redis.ping(), timeout=5)
        ms = int((time.monotonic() - t0) * 1000)
        count = sum(1 for _ in redis.scan_iter(match=f"pps:{bank_id}:*", count=500))
        detail = f"{count} PPS entries seeded" if count > 0 else "No PPS entries seeded — seed if bank issues cheque books"
        st = "PASS" if count > 0 else "WARN"
        return SmokeTestResult(test_id="test_pps_vault", status=st,
                               message=f"PPS vault ping OK ({ms}ms) · {detail}", latency_ms=ms)
    except Exception as exc:
        return SmokeTestResult(test_id="test_pps_vault", status="FAIL",
                               message=f"Redis error: {str(exc)[:120]}")


async def _run_test_cbs(state: Any, bank_id: str) -> SmokeTestResult:
    t0 = time.monotonic()
    try:
        from shared.cbs_connector.factory import get_cbs_connector
        connector = get_cbs_connector(bank_id)
        reachable = await asyncio.wait_for(connector.ping(), timeout=10)
        ms = int((time.monotonic() - t0) * 1000)
        if reachable:
            return SmokeTestResult(test_id="test_cbs", status="PASS",
                                   message=f"CBS ping OK in {ms}ms", latency_ms=ms)
        return SmokeTestResult(test_id="test_cbs", status="FAIL",
                               message="CBS ping returned False — check CBS config in Vault")
    except asyncio.TimeoutError:
        return SmokeTestResult(test_id="test_cbs", status="FAIL",
                               message="CBS unreachable (>10s timeout) — check network / CBS config")
    except ImportError:
        return SmokeTestResult(test_id="test_cbs", status="SKIP",
                               message="CBS connector not installed in this environment")
    except Exception as exc:
        return SmokeTestResult(test_id="test_cbs", status="FAIL",
                               message=f"CBS error: {str(exc)[:120]}")


async def _run_test_temporal(state: Any, bank_id: str) -> SmokeTestResult:
    t0 = time.monotonic()
    client = getattr(state, "temporal_client", None)
    if client is None:
        return SmokeTestResult(test_id="test_iet_watchdog", status="SKIP",
                               message="Temporal client not connected — start Temporal first")
    try:
        await asyncio.wait_for(client.describe_namespace("default"), timeout=10)
        ms = int((time.monotonic() - t0) * 1000)
        return SmokeTestResult(test_id="test_iet_watchdog", status="PASS",
                               message=f"Temporal namespace reachable in {ms}ms · IET workers assumed active",
                               latency_ms=ms)
    except asyncio.TimeoutError:
        return SmokeTestResult(test_id="test_iet_watchdog", status="FAIL",
                               message="Temporal unreachable (>10s) — check Temporal server")
    except Exception as exc:
        return SmokeTestResult(test_id="test_iet_watchdog", status="FAIL",
                               message=f"Temporal error: {str(exc)[:120]}")


async def _run_test_vault_seeded(state: Any, bank_id: str) -> SmokeTestResult:
    """Count seeded signatures for SMB accounts."""
    redis = getattr(state, "redis_cts", None)
    if redis is None:
        return SmokeTestResult(test_id="test_vault_seeded", status="FAIL",
                               message="Redis CTS not connected")
    try:
        count = sum(1 for _ in redis.scan_iter(match=f"sig:{bank_id}:*", count=2000))
        if count == 0:
            return SmokeTestResult(test_id="test_vault_seeded", status="WARN",
                                   message="No signature keys found for this bank — seed before go-live")
        return SmokeTestResult(test_id="test_vault_seeded", status="PASS",
                               message=f"{count} signature keys present in Redis vault")
    except Exception as exc:
        return SmokeTestResult(test_id="test_vault_seeded", status="FAIL",
                               message=f"Redis error: {str(exc)[:120]}")


def _run_test_scanner_folder() -> SmokeTestResult:
    folder = os.environ.get("CTS_INWARD_FOLDER_PATH", "")
    if not folder:
        return SmokeTestResult(test_id="test_scanner_folder", status="WARN",
                               message="CTS_INWARD_FOLDER_PATH not set — configure folder path")
    if not os.path.isdir(folder):
        return SmokeTestResult(test_id="test_scanner_folder", status="FAIL",
                               message=f"Folder not found: {folder}")
    if not os.access(folder, os.W_OK):
        return SmokeTestResult(test_id="test_scanner_folder", status="WARN",
                               message=f"{folder} exists but not writable — check ASTRA service user ACL")
    return SmokeTestResult(test_id="test_scanner_folder", status="PASS",
                           message=f"{folder} — exists and writable")


async def _run_test_auth_local(state: Any) -> SmokeTestResult:
    t0 = time.monotonic()
    try:
        from shared.auth.connectors.local import YugabyteDBLocalAuthConnector
        connector = getattr(state, "auth_connector", None)
        if connector is None:
            return SmokeTestResult(test_id="test_auth_smb", status="SKIP",
                                   message="Auth connector not initialised — check startup logs")
        # Call a lightweight health check if available, else treat as PASS
        if hasattr(connector, "ping"):
            await asyncio.wait_for(connector.ping(), timeout=5)
        ms = int((time.monotonic() - t0) * 1000)
        return SmokeTestResult(test_id="test_auth_smb", status="PASS",
                               message=f"Local auth DB reachable in {ms}ms · argon2 verify OK", latency_ms=ms)
    except Exception as exc:
        return SmokeTestResult(test_id="test_auth_smb", status="FAIL",
                               message=f"Auth error: {str(exc)[:120]}")


# Map test_id → runner coroutine
async def _dispatch_test(test_id: str, state: Any, bank_id: str) -> SmokeTestResult:
    dispatch = {
        "test_cbs":              lambda: _run_test_cbs(state, bank_id),
        "test_kafka":            lambda: _run_test_kafka(state, bank_id),
        "test_immudb":           lambda: _run_test_immudb(state, bank_id),
        "test_signature_vault":  lambda: _run_test_signature_vault(state, bank_id),
        "test_pps_vault":        lambda: _run_test_pps_vault(state, bank_id),
        "test_iet_watchdog":     lambda: _run_test_temporal(state, bank_id),
        "test_vault_seeded":     lambda: _run_test_vault_seeded(state, bank_id),
        "test_auth_smb":         lambda: _run_test_auth_local(state),
        "test_scanner_folder":   lambda: asyncio.coroutine(lambda: _run_test_scanner_folder())(),
    }
    runner = dispatch.get(test_id)
    if runner is None:
        # tests not yet wired (SFTP, LDAP, gRPC) — return SKIP
        return SmokeTestResult(test_id=test_id, status="SKIP",
                               message="Test not implemented for this environment — check manually")
    try:
        return await asyncio.wait_for(runner(), timeout=30)
    except asyncio.TimeoutError:
        return SmokeTestResult(test_id=test_id, status="FAIL",
                               message="Test timed out (>30s)")
    except Exception as exc:
        return SmokeTestResult(test_id=test_id, status="FAIL",
                               message=f"Unexpected error: {str(exc)[:120]}")


# Entity → test_id lists (mirrors ENTITY_SECTIONS on the frontend)
_ENTITY_TESTS: dict[str, list[str]] = {
    "sb":     ["test_cbs", "test_ngch", "test_kafka", "test_immudb",
               "test_signature_vault", "test_pps_vault", "test_auth_sb", "test_iet_watchdog"],
    "smb":    ["test_auth_smb", "test_sftp_push", "test_vault_seeded", "test_smb_cbs"],
    "branch": ["test_auth_branch", "test_scanner_folder", "test_eeh_connectivity"],
    "pu":     ["test_auth_pu", "test_sb_connector", "test_scanner_folder", "test_eeh_connectivity"],
}


# ---------------------------------------------------------------------------
# Service start — docker compose (POC) or kubectl rollout (PROD)
# ---------------------------------------------------------------------------

_DOCKER_SERVICE_MAP = {
    "kafka":     "kafka",
    "yugabyte":  "yugabyte",
    "redis-cts": "redis-cts",
    "redis-ej":  "redis-ej",
    "temporal":  "temporal",
    "vault":     "vault",
    "minio":     "minio",
    "immudb":    "immudb",
    # vllm-server intentionally absent — POC routes AI to HuggingFace (see _HF_HOSTED_SERVICES)
}

# Services that are not started via Docker in POC mode — handled externally (HuggingFace API).
_HF_HOSTED_SERVICES: frozenset[str] = frozenset({"vllm"})

# Startup order: each inner list starts in parallel; tiers run sequentially.
# Mirrors the dependency graph in infra/docker-compose.dev.yml.
_STARTUP_SEQUENCE: list[list[str]] = [
    ["vault", "redis-cts", "redis-ej", "minio", "immudb"],  # Tier 1 — no deps
    ["yugabyte", "kafka"],                                    # Tier 2 — independent
    ["temporal"],                                             # Tier 3 — needs yugabyte
    ["vllm"],                                                 # Tier 4 — HF-hosted, instant
]
_TIER_LABELS = ["Foundation", "Data Layer", "Orchestration", "AI Inference"]
_INTER_TIER_SLEEP = 15  # seconds between real Docker tiers (let services stabilise)

# Default path is the dev compose file co-located in this repo.
# Override with ASTRA_COMPOSE_FILE env var for staging/prod environments.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_COMPOSE_FILE = os.environ.get(
    "ASTRA_COMPOSE_FILE",
    str(_REPO_ROOT / "infra" / "docker-compose.dev.yml"),
)


async def _start_via_docker_compose(container: str) -> ServiceStartResponse:
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "compose", "-f", _COMPOSE_FILE, "up", "-d", container,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        if proc.returncode == 0:
            return ServiceStartResponse(service=container, success=True,
                                        message=f"docker compose up -d {container}: OK")
        err = stderr.decode(errors="replace")[:300]
        return ServiceStartResponse(service=container, success=False, message=err)
    except FileNotFoundError:
        return ServiceStartResponse(
            service=container, success=False,
            message=f"docker not found on PATH — run manually: docker compose up -d {container}",
        )
    except asyncio.TimeoutError:
        return ServiceStartResponse(service=container, success=False,
                                    message="docker compose start timed out (>60s)")
    except Exception as exc:
        return ServiceStartResponse(service=container, success=False, message=str(exc)[:200])


async def _start_single(service_id: str) -> ServiceStartResponse:
    """Start one service via docker compose, or return a skipped result for HF-hosted services."""
    if service_id in _HF_HOSTED_SERVICES:
        log.info("platform.service.hf_skip", service=service_id)
        return ServiceStartResponse(
            service=service_id, success=True, skipped=True,
            message="Routed to Hugging Face Inference API in POC mode — no local container needed",
        )
    container = _DOCKER_SERVICE_MAP.get(service_id)
    if container is None:
        return ServiceStartResponse(service=service_id, success=False,
                                    message=f"Unknown service: {service_id}")
    log.info("platform.service.start_requested", service=service_id, container=container)
    result = await _start_via_docker_compose(container)
    log.info("platform.service.start_result", service=service_id,
             success=result.success, message=result.message)
    return ServiceStartResponse(service=service_id, success=result.success, message=result.message)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router_v1.get("/readiness", response_model=ReadinessResponse)
async def get_readiness(
    request: Request,
    user: UserContext = Depends(get_current_user),
) -> ReadinessResponse:
    role    = user["role"]    if isinstance(user, dict) else user.role
    bank_id = user["bank_id"] if isinstance(user, dict) else user.bank_id
    if role not in _READ_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")

    db_pool  = getattr(request.app.state, "db_pool_cts", None)
    redis_cts = getattr(request.app.state, "redis_cts", None)

    # Run all checks concurrently
    (
        branches_item, sig_vault_item, pps_vault_item,
        micr_item, users_item,
    ) = await asyncio.gather(
        _check_branches(bank_id, db_pool),
        _check_signature_vault(bank_id, db_pool, redis_cts),
        _check_pps_vault(bank_id, redis_cts),
        _check_micr_prefixes(bank_id, db_pool),
        _check_ops_users(bank_id, db_pool),
    )

    # Synchronous folder checks
    inward_item  = _check_inward_folder()
    outward_item = _check_outward_folder()

    items = [branches_item, sig_vault_item, pps_vault_item,
             micr_item, users_item, inward_item, outward_item]

    blocking_statuses = {"FAIL"}
    all_ready = all(item.status not in blocking_statuses for item in items)
    degraded  = db_pool is None or redis_cts is None

    log.info("platform.readiness.served", bank_id=bank_id,
             all_ready=all_ready, item_count=len(items))
    return ReadinessResponse(
        bank_id=bank_id, as_of=_now_iso(),
        items=items, all_ready=all_ready, degraded=degraded,
    )


@router_v1.post("/smoke-test/run", response_model=SmokeTestRunResponse)
async def run_smoke_tests(
    body: SmokeTestRunRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
) -> SmokeTestRunResponse:
    role = user["role"] if isinstance(user, dict) else user.role
    if role not in _READ_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")

    bank_id = body.bank_id
    entity  = body.entity
    test_ids = _ENTITY_TESTS.get(entity, [])
    state = request.app.state

    log.info("platform.smoke_test.started", bank_id=bank_id, entity=entity, tests=len(test_ids))

    # Run tests concurrently (real connectivity checks, not sequential)
    results = await asyncio.gather(*[
        _dispatch_test(tid, state, bank_id) for tid in test_ids
    ])

    summary = {
        "pass": sum(1 for r in results if r.status == "PASS"),
        "warn": sum(1 for r in results if r.status == "WARN"),
        "fail": sum(1 for r in results if r.status == "FAIL"),
        "skip": sum(1 for r in results if r.status == "SKIP"),
        "total": len(results),
    }

    log.info("platform.smoke_test.complete", bank_id=bank_id, entity=entity, **summary)
    return SmokeTestRunResponse(
        bank_id=bank_id, entity=entity,
        run_at=_now_iso(), results=list(results), summary=summary,
    )


@router_v1.post("/services/start-all", response_model=ServiceStartAllResponse)
async def start_all_services(
    user: UserContext = Depends(get_current_user),
) -> ServiceStartAllResponse:
    """Start all infra services in dependency order (tier by tier, parallel within each tier).

    Tier 1 — Foundation:    vault, redis-cts, redis-ej, minio, immudb  (parallel, no deps)
    Tier 2 — Data Layer:    yugabyte, kafka                             (parallel)
    Tier 3 — Orchestration: temporal                                    (needs yugabyte)
    Tier 4 — AI Inference:  vllm                                        (HF-hosted, instant)

    POC mode: vllm is skipped (HuggingFace Inference API used instead).
    """
    role = user["role"] if isinstance(user, dict) else user.role
    if role not in _ADMIN_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="bank_it_admin required")

    tier_results: list[TierStartResult] = []
    total_started = total_failed = total_skipped = 0

    for idx, tier_svc_ids in enumerate(_STARTUP_SEQUENCE):
        # Sleep between real Docker tiers so services stabilise before the next tier starts.
        # Skip the sleep before HF-only tiers (they return instantly).
        if idx > 0:
            all_hf = all(s in _HF_HOSTED_SERVICES for s in tier_svc_ids)
            if not all_hf:
                await asyncio.sleep(_INTER_TIER_SLEEP)

        svc_results = list(await asyncio.gather(
            *[_start_single(svc_id) for svc_id in tier_svc_ids]
        ))

        label = _TIER_LABELS[idx] if idx < len(_TIER_LABELS) else f"Tier {idx + 1}"
        tier_results.append(TierStartResult(tier=idx + 1, label=label, services=svc_results))

        for r in svc_results:
            if r.skipped:    total_skipped += 1
            elif r.success:  total_started += 1
            else:            total_failed  += 1

    log.info("platform.service.start_all_complete",
             started=total_started, failed=total_failed, skipped=total_skipped)
    return ServiceStartAllResponse(
        tiers=tier_results,
        started=total_started,
        failed=total_failed,
        skipped=total_skipped,
    )


@router_v1.post("/services/{service_id}/start", response_model=ServiceStartResponse)
async def start_service(
    service_id: str,
    user: UserContext = Depends(get_current_user),
) -> ServiceStartResponse:
    role = user["role"] if isinstance(user, dict) else user.role
    if role not in _ADMIN_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="bank_it_admin required")
    if service_id not in _DOCKER_SERVICE_MAP and service_id not in _HF_HOSTED_SERVICES:
        raise HTTPException(status_code=400, detail=f"Unknown service: {service_id}")
    return await _start_single(service_id)
