"""
PlatformHealthCheckWorkflow — ASTRA alert engine (push side of Ops Dashboard).

60-second cadence loop. Checks:
  1. IET near-breach risk (any > 0 → P0 alert)
  2. Human review queue depth + avg wait (threshold → WARN alert)

On breach → dispatch_platform_alert → dispatcher.py → WhatsApp + email.

Workflow ID: cts-platform-health-{bank_id}  (singleton per bank, always running)
Start at bank onboarding via BankOnboardingWorkflow.

Thresholds passed in via PlatformHealthInput (sourced from config_service by the
caller) — never hardcoded, per .claude/rules/cts.md.

run_with_mocks() drives the same branch logic without Temporal machinery so tests
can exercise it synchronously at full speed.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import workflow

from modules.cts.workflows.activities.platform_health_activities import (
    CheckHRInput,
    CheckIETInput,
    CheckVaultCoverageInput,
    DispatchAlertInput,
    check_human_review_for_alert,
    check_iet_risk_for_alert,
    check_vault_redis_coverage_for_alert,
    dispatch_platform_alert,
)

log = structlog.get_logger()

_HEALTH_CHECK_INTERVAL_S = 60  # structural constant — not bank-configurable
_ACTIVITY_TIMEOUT = timedelta(seconds=30)


# ---------------------------------------------------------------------------
# Input / result models
# ---------------------------------------------------------------------------

class PlatformHealthInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    max_hr_depth: int = 50              # human review queue depth threshold
    max_hr_wait_minutes: float = 45.0   # human review avg-wait threshold
    min_vault_coverage_pct: float = 95.0  # vault Redis coverage alert threshold


class HealthCheckRunResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    checks_run: int = 0
    alerts_sent: int = 0


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------

@workflow.defn
class PlatformHealthCheckWorkflow:
    """
    Singleton platform health loop — one per bank, started at onboarding.
    Each 60s tick runs two checks; fires P0/P1 alerts on breach.
    """

    @workflow.run
    async def run(self, inp: PlatformHealthInput) -> None:
        while True:
            # ── 1. IET near-breach risk ───────────────────────────────────
            iet_result = await workflow.execute_activity(
                check_iet_risk_for_alert,
                CheckIETInput(bank_id=inp.bank_id),
                start_to_close_timeout=_ACTIVITY_TIMEOUT,
            )
            if iet_result.needs_alert:
                await workflow.execute_activity(
                    dispatch_platform_alert,
                    DispatchAlertInput(
                        bank_id=inp.bank_id,
                        event_type="IET_BREACH_RISK",
                        severity="CRITICAL",
                        priority="P0",
                        message=(
                            f"IET breach risk: {iet_result.near_breach_count} "
                            f"cheques within 30s of deadline"
                        ),
                    ),
                    start_to_close_timeout=_ACTIVITY_TIMEOUT,
                )

            # ── 2. Human review queue ─────────────────────────────────────
            hr_result = await workflow.execute_activity(
                check_human_review_for_alert,
                CheckHRInput(
                    bank_id=inp.bank_id,
                    max_depth=inp.max_hr_depth,
                    max_wait_minutes=inp.max_hr_wait_minutes,
                ),
                start_to_close_timeout=_ACTIVITY_TIMEOUT,
            )
            if hr_result.needs_alert:
                await workflow.execute_activity(
                    dispatch_platform_alert,
                    DispatchAlertInput(
                        bank_id=inp.bank_id,
                        event_type="HUMAN_REVIEW_QUEUE_DEEP",
                        severity=hr_result.alert_severity,
                        priority="P1",
                        message=(
                            f"Human review queue: depth={hr_result.queue_depth}, "
                            f"avg_wait={hr_result.avg_wait_minutes:.1f}min "
                            f"({hr_result.alert_reason})"
                        ),
                    ),
                    start_to_close_timeout=_ACTIVITY_TIMEOUT,
                )

            # ── 3. Vault Redis coverage ───────────────────────────────────
            cov_result = await workflow.execute_activity(
                check_vault_redis_coverage_for_alert,
                CheckVaultCoverageInput(
                    bank_id=inp.bank_id,
                    min_coverage_pct=inp.min_vault_coverage_pct,
                ),
                start_to_close_timeout=_ACTIVITY_TIMEOUT,
            )
            if cov_result.needs_alert:
                await workflow.execute_activity(
                    dispatch_platform_alert,
                    DispatchAlertInput(
                        bank_id=inp.bank_id,
                        event_type="VAULT_REDIS_COLD_DETECTED",
                        severity="WARN",
                        priority="P1",
                        message=(
                            f"Vault Redis coverage low: {cov_result.coverage_pct:.1f}% "
                            f"({cov_result.redis_sig_keys}/{cov_result.yugabyte_accounts} accounts). "
                            f"Gap: {cov_result.gap_accounts} accounts. "
                            f"POST /v1/admin/vault/warm-redis to recover."
                        ),
                    ),
                    start_to_close_timeout=_ACTIVITY_TIMEOUT,
                )

            await workflow.sleep(timedelta(seconds=_HEALTH_CHECK_INTERVAL_S))

    # -----------------------------------------------------------------------
    # Testable orchestration — same branch logic, no Temporal machinery
    # -----------------------------------------------------------------------

    async def run_with_mocks(
        self,
        inp: PlatformHealthInput,
        mock_results: dict[str, Any],
    ) -> HealthCheckRunResult:
        """
        Executes one health check tick using pre-built mock results.

        mock_results schema:
          "iet_risk":      dict matching IETCheckResult fields
          "human_review":  dict matching HRCheckResult fields
          "vault_coverage": dict matching VaultCoverageCheckResult fields (optional — defaults to no alert)
          "dispatched":    list — run_with_mocks appends alert dicts here instead of
                           calling dispatch_platform_alert

        Returns HealthCheckRunResult(checks_run=3).
        """
        checks_run = 0
        alerts_sent = 0
        dispatched: list[dict] = mock_results["dispatched"]

        # ── IET check ────────────────────────────────────────────────────
        iet_data = mock_results["iet_risk"]
        checks_run += 1
        if iet_data.get("needs_alert"):
            near_breach = iet_data.get("near_breach_count", 0)
            dispatched.append({
                "event_type": "IET_BREACH_RISK",
                "severity": "CRITICAL",
                "priority": iet_data.get("alert_priority", "P0"),
                "bank_id": inp.bank_id,
                "message": f"IET breach risk: {near_breach} cheques within 30s of deadline",
            })
            alerts_sent += 1

        # ── Human review check ────────────────────────────────────────────
        hr_data = mock_results["human_review"]
        checks_run += 1
        if hr_data.get("needs_alert"):
            dispatched.append({
                "event_type": "HUMAN_REVIEW_QUEUE_DEEP",
                "severity": hr_data.get("alert_severity", "WARN"),
                "priority": "P1",
                "bank_id": inp.bank_id,
                "message": (
                    f"Human review queue: depth={hr_data.get('queue_depth', 0)}, "
                    f"reason={hr_data.get('alert_reason', 'UNKNOWN')}"
                ),
            })
            alerts_sent += 1

        # ── Vault Redis coverage check ────────────────────────────────────
        cov_data = mock_results.get("vault_coverage", {"needs_alert": False, "degraded": False})
        checks_run += 1
        if cov_data.get("needs_alert"):
            dispatched.append({
                "event_type": "VAULT_REDIS_COLD_DETECTED",
                "severity": "WARN",
                "priority": "P1",
                "bank_id": inp.bank_id,
                "message": (
                    f"Vault Redis coverage low: {cov_data.get('coverage_pct', 0.0):.1f}% "
                    f"(gap: {cov_data.get('gap_accounts', 0)} accounts)"
                ),
            })
            alerts_sent += 1

        return HealthCheckRunResult(checks_run=checks_run, alerts_sent=alerts_sent)
