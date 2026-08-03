"""
PlatformHealthCheckWorkflow activities — alert engine for the ASTRA Ops Dashboard.

Three activities:
  check_iet_risk_for_alert    — query IET near-breach count from YugabyteDB
  check_human_review_for_alert — query human review queue depth + avg wait
  dispatch_platform_alert     — send alert via NotificationDispatcher → WhatsApp + email

All activities degrade gracefully when db_pool or dispatcher is None (never crash).
IET near-breach > 0 → always P0 (bypass debouncer).
Human review threshold breaches → P1/WARN.
"""
from __future__ import annotations

from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import activity

from shared.notifications.dispatcher import NotificationRequest

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Input / result models
# ---------------------------------------------------------------------------

class CheckIETInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str


class IETCheckResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str = ""
    near_breach_count: int = 0
    in_processing_count: int = 0
    needs_alert: bool = False
    alert_priority: str = "P0"
    degraded: bool = False


class CheckHRInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    max_depth: int          # alert when queue_depth > max_depth
    max_wait_minutes: float # alert when avg_wait > max_wait_minutes


class HRCheckResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str = ""
    queue_depth: int = 0
    avg_wait_minutes: float = 0.0
    needs_alert: bool = False
    alert_severity: str = "WARN"
    alert_reason: str = ""  # "QUEUE_DEPTH" | "WAIT_TIME"
    degraded: bool = False


class DispatchAlertInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    event_type: str    # "IET_BREACH_RISK" | "HUMAN_REVIEW_QUEUE_DEEP"
    severity: str      # "CRITICAL" | "WARN"
    priority: str      # "P0" | "P1" (P0 = never debounced)
    message: str


class DispatchAlertResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    sent: bool = False
    degraded: bool = False


class CheckVaultCoverageInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    min_coverage_pct: float  # alert when Redis coverage drops below this (e.g. 95.0)


class VaultCoverageCheckResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str = ""
    yugabyte_accounts: int = 0
    redis_sig_keys: int = 0
    coverage_pct: float = 100.0
    gap_accounts: int = 0
    needs_alert: bool = False
    alert_severity: str = "WARN"
    degraded: bool = False


# ---------------------------------------------------------------------------
# Activities
# ---------------------------------------------------------------------------

@activity.defn
async def check_iet_risk_for_alert(
    inp: CheckIETInput,
    db_pool=None,
) -> IETCheckResult:
    """
    Query YugabyteDB for cheques whose IET deadline is within 30 seconds.
    Any near-breach count > 0 means a P0 alert must fire.
    Degrades gracefully when db_pool is None — returns needs_alert=False, degraded=True.
    """
    if db_pool is None:
        log.warning("check_iet_risk_for_alert.degraded", bank_id=inp.bank_id, reason="db_pool_none")
        return IETCheckResult(bank_id=inp.bank_id, degraded=True)

    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) FILTER (
                        WHERE status = 'IN_PROCESSING'
                          AND iet_deadline < NOW() + INTERVAL '30 seconds'
                          AND iet_deadline > NOW()
                    ) AS near_breach,
                    COUNT(*) FILTER (WHERE status = 'IN_PROCESSING') AS in_processing
                FROM cts.cheque_instruments
                WHERE bank_id = $1
                """,
                inp.bank_id,
            )
        near_breach = int(row["near_breach"] or 0)
        in_processing = int(row["in_processing"] or 0)
        needs_alert = near_breach > 0
        log.info(
            "check_iet_risk_for_alert.done",
            bank_id=inp.bank_id,
            near_breach=near_breach,
            in_processing=in_processing,
            needs_alert=needs_alert,
        )
        return IETCheckResult(
            bank_id=inp.bank_id,
            near_breach_count=near_breach,
            in_processing_count=in_processing,
            needs_alert=needs_alert,
            alert_priority="P0",
            degraded=False,
        )
    except Exception as exc:
        log.warning("check_iet_risk_for_alert.error", bank_id=inp.bank_id, error=str(exc))
        return IETCheckResult(bank_id=inp.bank_id, degraded=True)


@activity.defn
async def check_human_review_for_alert(
    inp: CheckHRInput,
    db_pool=None,
) -> HRCheckResult:
    """
    Query YugabyteDB for human review queue depth and average wait time.
    Alerts (WARN) when either exceeds the configurable thresholds in inp.
    Degrades gracefully when db_pool is None.
    """
    if db_pool is None:
        log.warning("check_human_review_for_alert.degraded", bank_id=inp.bank_id, reason="db_pool_none")
        return HRCheckResult(bank_id=inp.bank_id, degraded=True)

    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) AS queue_depth,
                    COALESCE(
                        AVG(EXTRACT(EPOCH FROM (NOW() - review_queued_at)) / 60.0),
                        0
                    ) AS avg_wait
                FROM cts.cheque_instruments
                WHERE bank_id = $1
                  AND status = 'HUMAN_REVIEW'
                """,
                inp.bank_id,
            )
        queue_depth = int(row["queue_depth"] or 0)
        avg_wait = float(row["avg_wait"] or 0.0)

        needs_alert = False
        alert_reason = ""

        if queue_depth > inp.max_depth:
            needs_alert = True
            alert_reason = "QUEUE_DEPTH"
        elif avg_wait > inp.max_wait_minutes:
            needs_alert = True
            alert_reason = "WAIT_TIME"

        log.info(
            "check_human_review_for_alert.done",
            bank_id=inp.bank_id,
            queue_depth=queue_depth,
            avg_wait_minutes=round(avg_wait, 1),
            needs_alert=needs_alert,
        )
        return HRCheckResult(
            bank_id=inp.bank_id,
            queue_depth=queue_depth,
            avg_wait_minutes=avg_wait,
            needs_alert=needs_alert,
            alert_severity="WARN",
            alert_reason=alert_reason,
            degraded=False,
        )
    except Exception as exc:
        log.warning("check_human_review_for_alert.error", bank_id=inp.bank_id, error=str(exc))
        return HRCheckResult(bank_id=inp.bank_id, degraded=True)


@activity.defn
async def dispatch_platform_alert(
    inp: DispatchAlertInput,
    dispatcher=None,
) -> DispatchAlertResult:
    """
    Send an alert via NotificationDispatcher (email + WhatsApp).
    P0 alerts bypass the debouncer — safe to fire even during notification storms.
    Degrades gracefully when dispatcher is None (no notification infra available).
    """
    if dispatcher is None:
        log.warning(
            "dispatch_platform_alert.degraded",
            bank_id=inp.bank_id,
            event_type=inp.event_type,
            reason="dispatcher_none",
        )
        return DispatchAlertResult(sent=False, degraded=True)

    try:
        request = NotificationRequest(
            channel="email",
            recipient=f"ops-alerts@{inp.bank_id}.internal",
            template_id="PLATFORM_HEALTH_ALERT",
            context={
                "bank_id": inp.bank_id,
                "event_type": inp.event_type,
                "severity": inp.severity,
                "message": inp.message,
            },
            priority=inp.priority,
            event_category="PLATFORM_HEALTH",
        )
        await dispatcher.send(request)
        log.info(
            "dispatch_platform_alert.sent",
            bank_id=inp.bank_id,
            event_type=inp.event_type,
            severity=inp.severity,
            priority=inp.priority,
        )
        return DispatchAlertResult(sent=True, degraded=False)
    except Exception as exc:
        log.warning(
            "dispatch_platform_alert.error",
            bank_id=inp.bank_id,
            event_type=inp.event_type,
            error=str(exc),
        )
        return DispatchAlertResult(sent=False, degraded=False)


@activity.defn
async def check_vault_redis_coverage_for_alert(
    inp: CheckVaultCoverageInput,
    db_pool=None,
    redis_client=None,
) -> VaultCoverageCheckResult:
    """
    Compare signature embedding count in YugabyteDB vs Redis.
    A Redis cold restart leaves Redis empty while YugabyteDB retains all embeddings.
    Fires a WARN/P1 alert when coverage_pct < inp.min_coverage_pct.
    Degrades gracefully when db_pool or redis_client is None.
    """
    if db_pool is None or redis_client is None:
        log.warning(
            "check_vault_redis_coverage_for_alert.degraded",
            bank_id=inp.bank_id,
            reason="db_pool_none" if db_pool is None else "redis_client_none",
        )
        return VaultCoverageCheckResult(bank_id=inp.bank_id, degraded=True)

    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(DISTINCT account_hash) AS accounts "
                "FROM cts.signature_embeddings WHERE bank_id = $1",
                inp.bank_id,
            )
        yugabyte_accounts = int(row["accounts"] or 0)

        redis_sig_keys = sum(
            1 for _ in redis_client.scan_iter(match=f"sig:{inp.bank_id}:*", count=1000)
        )

        if yugabyte_accounts > 0:
            coverage_pct = min(100.0, redis_sig_keys / yugabyte_accounts * 100)
        else:
            coverage_pct = 100.0  # no accounts in DB → nothing to warm → healthy

        gap_accounts = max(0, yugabyte_accounts - redis_sig_keys)
        needs_alert = coverage_pct < inp.min_coverage_pct

        log.info(
            "check_vault_redis_coverage_for_alert.done",
            bank_id=inp.bank_id,
            yugabyte_accounts=yugabyte_accounts,
            redis_sig_keys=redis_sig_keys,
            coverage_pct=round(coverage_pct, 1),
            gap_accounts=gap_accounts,
            needs_alert=needs_alert,
        )
        return VaultCoverageCheckResult(
            bank_id=inp.bank_id,
            yugabyte_accounts=yugabyte_accounts,
            redis_sig_keys=redis_sig_keys,
            coverage_pct=coverage_pct,
            gap_accounts=gap_accounts,
            needs_alert=needs_alert,
            alert_severity="WARN",
            degraded=False,
        )
    except Exception as exc:
        log.warning(
            "check_vault_redis_coverage_for_alert.error",
            bank_id=inp.bank_id,
            error=str(exc),
        )
        return VaultCoverageCheckResult(bank_id=inp.bank_id, degraded=True)
