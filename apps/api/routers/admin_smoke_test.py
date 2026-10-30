"""Admin smoke-test router — entity-scoped pre-live validation.

GET /v1/admin/smoke-test        → run all tests for the caller's entity_type
GET /v1/admin/smoke-test/{id}   → run a single named test

Every test returns a SmokeTestResult with status PASS / WARN / FAIL.
The summary all_clear=True only when zero FAIL results — WARN is advisory.

Entity scope:
  sb     → CBS, NGCH, Vault, Immudb, Kafka, Auth(SAML/LDAP), IET Watchdog
  smb    → Auth, SFTP push, Vault seeding check, SMB CBS (if configured)
  branch → Scanner drop-folder, Auth(LDAP), EEH session
  pu     → SB connector, EEH session, Auth(LDAP), Scanner drop-folder
"""
from __future__ import annotations

import time
from enum import Enum
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from shared.auth.connectors.base import ASTRAIdentity
from shared.messages import get_message

log = structlog.get_logger()

router = APIRouter(prefix="/v1/admin/smoke-test", tags=["Admin Smoke Test"])


# ── Models ────────────────────────────────────────────────────────────────────

class SmokeTestStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIP = "SKIP"


class SmokeTestResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    test_id: str
    name: str
    entity_scope: str           # sb | smb | branch | pu | shared
    status: SmokeTestStatus
    latency_ms: Optional[int]   # None when test could not even start
    message: str


class SmokeTestSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    total: int
    passed: int = 0
    fail: int = 0
    warn: int = 0
    all_clear: bool             # True iff fail == 0 (WARN is advisory, not blocking)

    # alias so tests can use data["summary"]["pass"]
    @property
    def pass_(self) -> int:
        return self.passed

    def model_post_init(self, _ctx) -> None:
        pass


class SmokeTestResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    entity_type: str
    entity_id: str
    bank_id: str
    run_at: float
    results: list[SmokeTestResult]
    summary: dict   # {"total", "pass", "fail", "warn", "all_clear"}


class EntityScopeMismatchError(Exception):
    """Raised when an entity tries to run a test outside their scope."""


# ── Entity → test-id mapping ──────────────────────────────────────────────────

_ENTITY_TESTS: dict[str, list[str]] = {
    "sb": [
        "test_cbs",
        "test_ngch",
        "test_signature_vault",
        "test_pps_vault",
        "test_immudb",
        "test_kafka",
        "test_auth_sb",
        "test_iet_watchdog",
    ],
    "smb": [
        "test_auth_smb",
        "test_sftp_push",
        "test_vault_seeded",
        "test_smb_cbs",         # only runs if SMB_CBS MCP connection exists
    ],
    "branch": [
        "test_scanner_folder",
        "test_auth_branch",
        "test_eeh_connectivity",
    ],
    "pu": [
        "test_sb_connector",
        "test_auth_pu",
        "test_eeh_connectivity",
        "test_scanner_folder",
    ],
}

_TEST_NAMES: dict[str, str] = {
    "test_cbs":              get_message("API_CBS_CONNECTIVITY"),
    "test_ngch":             get_message("API_NGCH_ADAPTER"),
    "test_signature_vault":  get_message("API_SIGNATURE_VAULT_REDIS"),
    "test_pps_vault":        get_message("API_PPS_VAULT_REDIS"),
    "test_immudb":           get_message("API_IMMUDB_AUDIT_TRAIL"),
    "test_kafka":            get_message("API_KAFKA_TOPICS"),
    "test_auth_sb":          get_message("API_SB_AUTH_CONNECTOR"),
    "test_iet_watchdog":     get_message("API_IET_WATCHDOG_SYNTHETIC_CHEQUE"),
    "test_auth_smb":         get_message("API_SMB_AUTH_CONNECTOR"),
    "test_sftp_push":        get_message("API_AGENCY_SFTP_PUSH"),
    "test_vault_seeded":     get_message("API_VAULT_SEEDING_CHECK"),
    "test_smb_cbs":          get_message("API_SMB_CBS_CONNECTIVITY"),
    "test_scanner_folder":   get_message("API_SCANNER_DROP_FOLDER"),
    "test_auth_branch":      get_message("API_BRANCH_AUTH_CONNECTOR"),
    "test_eeh_connectivity": get_message("API_EEH_IEH_SESSION"),
    "test_sb_connector":     get_message("API_AGENCY_SB_CONNECTOR"),
    "test_auth_pu":          get_message("API_PU_AUTH_CONNECTOR"),
}


# ── Dependency ────────────────────────────────────────────────────────────────

async def get_current_entity_context() -> ASTRAIdentity:
    """Resolved from JWT in production — overridden in tests."""
    raise NotImplementedError("wire real RBAC dependency in production main.py")


# ── Core test runner (stub — real checks injected per test_id) ────────────────

async def run_all_tests(
    entity_type: str,
    entity_id: str,
    bank_id: str,
) -> list[SmokeTestResult]:
    """Run all tests for the given entity type. Each test is independently timed."""
    test_ids = _ENTITY_TESTS.get(entity_type, [])
    results: list[SmokeTestResult] = []
    for test_id in test_ids:
        result = await run_single_test(
            test_id=test_id,
            entity_type=entity_type,
            entity_id=entity_id,
            bank_id=bank_id,
        )
        results.append(result)
    return results


async def run_single_test(
    test_id: str,
    entity_type: str,
    entity_id: str,
    bank_id: str,
) -> SmokeTestResult:
    """Run one named test. Raises EntityScopeMismatchError if entity not allowed."""
    allowed = _ENTITY_TESTS.get(entity_type, [])
    if test_id not in allowed:
        raise EntityScopeMismatchError(
            get_message("API_TEST_IS_NOT_IN_SCOPE", test_id=test_id, entity_type=entity_type, allowed=allowed)
        )

    runner = _TEST_RUNNERS.get(test_id)
    if runner is None:
        return SmokeTestResult(
            test_id=test_id,
            name=_TEST_NAMES.get(test_id, test_id),
            entity_scope=entity_type,
            status=SmokeTestStatus.SKIP,
            latency_ms=None,
            message=get_message("API_TEST_RUNNER_NOT_YET_IMPLEMENTED"),
        )

    t0 = time.monotonic()
    try:
        status, message = await runner(entity_id=entity_id, bank_id=bank_id)
        latency_ms = int((time.monotonic() - t0) * 1000)
    except Exception as exc:
        latency_ms = int((time.monotonic() - t0) * 1000)
        status = SmokeTestStatus.FAIL
        message = get_message("API_TEST_RAISED_EXCEPTION", name=type(exc).__name__, exc=exc)

    return SmokeTestResult(
        test_id=test_id,
        name=_TEST_NAMES.get(test_id, test_id),
        entity_scope=entity_type,
        status=status,
        latency_ms=latency_ms,
        message=message,
    )


# ── Individual test runners ────────────────────────────────────────────────────
# Each runner: async fn(entity_id, bank_id) → (SmokeTestStatus, message str)
# Stubs return SKIP — wired to real checks in production config.

async def _run_test_cbs(entity_id: str, bank_id: str):
    return SmokeTestStatus.SKIP, get_message("API_CBS_CONNECTIVITY_CHECK_WIRE_REAL")


async def _run_test_ngch(entity_id: str, bank_id: str):
    return SmokeTestStatus.SKIP, get_message("API_NGCH_ADAPTER_CHECK_WIRE_REAL")


async def _run_test_signature_vault(entity_id: str, bank_id: str):
    return SmokeTestStatus.SKIP, get_message("API_SIGNATURE_VAULT_CHECK_WIRE_REAL")


async def _run_test_pps_vault(entity_id: str, bank_id: str):
    return SmokeTestStatus.SKIP, get_message("API_PPS_VAULT_CHECK_WIRE_REAL")


async def _run_test_immudb(entity_id: str, bank_id: str):
    return SmokeTestStatus.SKIP, get_message("API_IMMUDB_CHECK_WIRE_REAL_IMMUDB")


async def _run_test_kafka(entity_id: str, bank_id: str):
    return SmokeTestStatus.SKIP, get_message("API_KAFKA_CHECK_WIRE_REAL_KAFKA")


async def _run_test_auth(entity_id: str, bank_id: str):
    return SmokeTestStatus.SKIP, get_message("API_AUTH_CONNECTOR_CHECK_WIRE_AUTHCONNEC")


async def _run_test_iet_watchdog(entity_id: str, bank_id: str):
    return SmokeTestStatus.SKIP, get_message("API_IET_WATCHDOG_SEND_SYNTHETIC_CHEQUE")


async def _run_test_sftp_push(entity_id: str, bank_id: str):
    return SmokeTestStatus.SKIP, get_message("API_SFTP_PUSH_CHECK_WIRE_AGENCY")


async def _run_test_vault_seeded(entity_id: str, bank_id: str):
    return SmokeTestStatus.SKIP, get_message("API_VAULT_SEEDING_CHECK_QUERY_REDIS")


async def _run_test_smb_cbs(entity_id: str, bank_id: str):
    return SmokeTestStatus.SKIP, get_message("API_SMB_CBS_CHECK_ONLY_RUNS")


async def _run_test_scanner_folder(entity_id: str, bank_id: str):
    return SmokeTestStatus.SKIP, get_message("API_SCANNER_DROP_FOLDER_CHECK_VERIFY")


async def _run_test_eeh(entity_id: str, bank_id: str):
    return SmokeTestStatus.SKIP, get_message("API_EEH_IEH_GRPC_PING_WIRE")


async def _run_test_sb_connector(entity_id: str, bank_id: str):
    return SmokeTestStatus.SKIP, get_message("API_SB_CONNECTOR_CHECK_WIRE_REAL")


_TEST_RUNNERS = {
    "test_cbs":              _run_test_cbs,
    "test_ngch":             _run_test_ngch,
    "test_signature_vault":  _run_test_signature_vault,
    "test_pps_vault":        _run_test_pps_vault,
    "test_immudb":           _run_test_immudb,
    "test_kafka":            _run_test_kafka,
    "test_auth_sb":          _run_test_auth,
    "test_auth_smb":         _run_test_auth,
    "test_auth_branch":      _run_test_auth,
    "test_auth_pu":          _run_test_auth,
    "test_iet_watchdog":     _run_test_iet_watchdog,
    "test_sftp_push":        _run_test_sftp_push,
    "test_vault_seeded":     _run_test_vault_seeded,
    "test_smb_cbs":          _run_test_smb_cbs,
    "test_scanner_folder":   _run_test_scanner_folder,
    "test_eeh_connectivity": _run_test_eeh,
    "test_sb_connector":     _run_test_sb_connector,
}


# ── Routes ────────────────────────────────────────────────────────────────────

def _build_summary(results: list[SmokeTestResult]) -> dict:
    fail = sum(1 for r in results if r.status == SmokeTestStatus.FAIL)
    warn = sum(1 for r in results if r.status == SmokeTestStatus.WARN)
    passed = sum(1 for r in results if r.status == SmokeTestStatus.PASS)
    return {
        "total": len(results),
        "pass": passed,
        "fail": fail,
        "warn": warn,
        "all_clear": fail == 0,
    }


@router.get("", response_model=SmokeTestResponse)
async def get_smoke_test_all(
    identity: ASTRAIdentity = Depends(get_current_entity_context),
):
    """Run all smoke tests for the caller's entity type."""
    results = await run_all_tests(
        entity_type=identity.entity_type,
        entity_id=identity.entity_id,
        bank_id=identity.bank_id,
    )
    log.info(
        "smoke_test.all_run",
        entity_type=identity.entity_type,
        bank_id=identity.bank_id,
        total=len(results),
        fail=sum(1 for r in results if r.status == SmokeTestStatus.FAIL),
    )
    return SmokeTestResponse(
        entity_type=identity.entity_type,
        entity_id=identity.entity_id,
        bank_id=identity.bank_id,
        run_at=time.time(),
        results=results,
        summary=_build_summary(results),
    )


@router.get("/{test_id}", response_model=SmokeTestResult)
async def get_smoke_test_single(
    test_id: str,
    identity: ASTRAIdentity = Depends(get_current_entity_context),
):
    """Run a single named smoke test. 403 if test not in scope for caller's entity."""
    try:
        result = await run_single_test(
            test_id=test_id,
            entity_type=identity.entity_type,
            entity_id=identity.entity_id,
            bank_id=identity.bank_id,
        )
    except EntityScopeMismatchError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return result
