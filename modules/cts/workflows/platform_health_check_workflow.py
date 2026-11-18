"""
PlatformHealthCheckWorkflow — ASTRA alert engine (push side of Ops Dashboard).

60-second cadence loop. Checks:
  0. Infrastructure: every configured dependency (Yugabyte, Redis, Temporal, Kafka, MinIO, Immudb, Vault, the AI services, CBS, NGCH ...) is
     probed, with latency; a component is DOWN/SLOW only after consecutive bad probes, and an outage is announced once and then reminded about
     (modules/cts/health/state_machine.py). The states are queryable for the Ops Dashboard (`component_states`).
  1. IET near-breach risk (any > 0 → P0 alert)
  2. Human review queue depth + avg wait (threshold → WARN alert)
  3-5. Vault coverage, scanner fleet, stuck workflows
A condition that persists is mailed once per repeat interval, not every minute. One failing check never stops the loop, and the loop restarts itself
(continue-as-new) carrying its state, so the singleton can run for years.

On breach → dispatch_platform_alert → dispatcher.py → WhatsApp + email.

Workflow ID: cts-platform-health-{bank_id}  (singleton per bank, always running)
Start at bank onboarding via BankOnboardingWorkflow.

Thresholds passed in via PlatformHealthInput (sourced from config_service by the
caller) — never hardcoded, per .claude/rules/cts.md.

run_with_mocks() drives the same branch logic without Temporal machinery so tests
can exercise it synchronously at full speed.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.workflow import ParentClosePolicy
from temporalio.exceptions import ActivityError, CancelledError

from modules.cts.workflows.alert_escalation_workflow import AlertEscalationInput, AlertEscalationWorkflow
from modules.cts.workflows.escalation_control import escalation_workflow_id
from modules.cts.health.state_machine import ComponentState, Event, human_duration
from modules.cts.workflows.activities.platform_health_activities import (
    CheckHRInput,
    CheckIETInput,
    CheckScannerFleetInput,
    CheckVaultCoverageInput,
    DispatchAlertInput,
    ProbeComponentsInput,
    StuckWorkflowSweepInput,
    check_human_review_for_alert,
    check_iet_risk_for_alert,
    check_scanner_fleet_for_alert,
    check_vault_redis_coverage_for_alert,
    dispatch_platform_alert,
    ProcessOutboxInput,
    RunRetentionInput,
    probe_components,
    process_alert_outbox,
    record_alert_incident,
    run_alert_retention,
    sweep_stuck_workflows,
)
with workflow.unsafe.imports_passed_through():       # the workflow sandbox restricts imports; the message registry is read-only wording
    from shared.messages import get_message

log = structlog.get_logger()

_HEALTH_CHECK_INTERVAL_S = 60  # structural constant — not bank-configurable
# Workflow patch ids (Temporal versioning). Never rename or remove one while a monitor started before it may still be running.
_PATCH_INCIDENTS = "alerting-incidents-v1"
_PATCH_OUTBOX = "alerting-outbox-v1"
_PATCH_RETENTION = "alerting-retention-v1"
_PATCH_ESCALATION = "alerting-escalation-v1"
_ACTIVITY_TIMEOUT = timedelta(seconds=30)
# The default policy retries forever, so one broken check would hold the whole tick (and the infrastructure probes with it). Two attempts, then
# the tick moves on and the failure is logged.
_CHECK_RETRY = RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=1))


# ---------------------------------------------------------------------------
# Input / result models
# ---------------------------------------------------------------------------

class PlatformHealthInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    max_hr_depth: int = 50              # human review queue depth threshold
    max_hr_wait_minutes: float = 45.0   # human review avg-wait threshold
    min_vault_coverage_pct: float = 95.0  # vault Redis coverage alert threshold
    repeat_alert_seconds: float = 1800.0   # the same standing condition is mailed again no sooner than this
    iet_repeat_seconds: float = 300.0      # IET near-breach is time-critical: repeat sooner
    max_ticks_before_restart: int = 1000   # continue-as-new after this many ticks (history stays small)
    prune_every_ticks: int = 1440          # old alert history is pruned on the first tick and then every this many ticks (1440 = daily at 60 s)
    # carried across continue-as-new:
    states: dict[str, ComponentState] = {}
    last_sent: dict[str, float] = {}
    tick: int = 0


class HealthCheckRunResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    checks_run: int = 0
    alerts_sent: int = 0


def alerts_for_events(bank_id: str, events: list[Event]) -> list[DispatchAlertInput]:
    """State-machine events -> the alert mails: DOWN/REMINDER/SLOW use the alert template, recoveries the recovery template."""
    out: list[DispatchAlertInput] = []
    for e in events:
        recovery = e.kind in ("RECOVERED", "SLOW_CLEARED")
        out.append(DispatchAlertInput(
            bank_id=bank_id, event_type=f"COMPONENT_{e.kind}", component=e.component, message=e.message,
            severity="INFO" if recovery else ("CRITICAL" if e.severity == "P0" else "WARN"), priority=e.severity,
            template="PLATFORM_HEALTH_RECOVERED" if recovery else "PLATFORM_HEALTH_ALERT",
            down_for=human_duration(e.down_for_seconds) if e.down_for_seconds is not None else "",
        ))
    return out


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------

@workflow.defn
class PlatformHealthCheckWorkflow:
    """
    Singleton platform health loop — one per bank, started at onboarding.
    Each 60s tick runs two checks; fires P0/P1 alerts on breach.
    """

    def __init__(self) -> None:
        self._states: dict[str, ComponentState] = {}
        self._last_sent: dict[str, float] = {}
        self._tick = 0
        self._last_tick_at: Optional[float] = None
        self._restart_requested = False

    @workflow.signal
    def request_restart(self) -> None:
        """Roll over (continue-as-new) at the end of the current tick, carrying the state. Sent by the worker on start-up so a monitor that was already
        running adopts upgraded code at once instead of keeping its old code path until its next scheduled restart."""
        self._restart_requested = True

    @workflow.query
    def component_states(self) -> dict:
        """For the Ops Dashboard: every component's state, how many ticks have run, and when the last one finished (a stale value means the
        monitor itself has stopped)."""
        return {"states": {k: v.model_dump() for k, v in self._states.items()}, "tick": self._tick, "last_tick_at": self._last_tick_at}

    async def _send(self, inp: PlatformHealthInput, alert: DispatchAlertInput, now: float, interval: float) -> None:
        """Send unless this same condition was mailed less than `interval` seconds ago."""
        last = self._last_sent.get(alert.event_type)
        if last is not None and now - last < interval:
            return
        self._last_sent[alert.event_type] = now
        await self._notify(alert)

    async def _manage_escalation(self, *, inp_bank_id: str, recorded) -> None:
        """A new incident gets its escalation workflow; a resolved one has its escalation stopped. Neither may ever hold up an alert."""
        if not recorded.incident_id:
            return
        escalation_id = escalation_workflow_id(inp_bank_id, recorded.incident_id)
        try:
            if recorded.created:
                await workflow.start_child_workflow(AlertEscalationWorkflow.run, AlertEscalationInput(bank_id=inp_bank_id, incident_id=recorded.incident_id,
                                                                                                    started_at=workflow.now().timestamp()),
                                                    id=escalation_id, parent_close_policy=ParentClosePolicy.ABANDON)
            elif recorded.resolved:
                await workflow.get_external_workflow_handle(escalation_id).signal(AlertEscalationWorkflow.stop, "resolved")
        except Exception:  # noqa: BLE001  - the escalation also ends by itself when the database says the incident is closed
            pass

    async def _notify(self, alert: DispatchAlertInput) -> None:
        """Open, update or resolve the incident this alert belongs to, then send it carrying the incident id. An incident store that is down
        or slow must never keep an alert from going out, so a failed record only means the alert has no incident id."""
        alert = alert.model_copy(update={"occasion": f"t{self._tick}", "occurred_at": workflow.now().timestamp()})      # one notification per tick per alert; an activity retry repeats it, so nothing is sent twice
        # Patch markers keep a monitor that was already running before an upgrade replayable: its recorded history has none of these steps.
        if workflow.patched(_PATCH_INCIDENTS):
            try:
                recorded = await workflow.execute_activity(record_alert_incident, alert, start_to_close_timeout=_ACTIVITY_TIMEOUT, retry_policy=_CHECK_RETRY)
                if recorded.incident_id:
                    alert = alert.model_copy(update={"incident_id": recorded.incident_id})
                if workflow.patched(_PATCH_ESCALATION):
                    await self._manage_escalation(inp_bank_id=alert.bank_id, recorded=recorded)
            except ActivityError:
                pass
        await workflow.execute_activity(dispatch_platform_alert, alert, start_to_close_timeout=_ACTIVITY_TIMEOUT, retry_policy=_CHECK_RETRY)

    async def _tick_once(self, inp: PlatformHealthInput, now: float) -> None:
        # ── 0. Infrastructure components ──────────────────────────────
        probed = await workflow.execute_activity(
            probe_components,
            ProbeComponentsInput(bank_id=inp.bank_id, states=self._states),
            start_to_close_timeout=timedelta(seconds=45),
            retry_policy=_CHECK_RETRY,
        )
        self._states = probed.states
        for alert in alerts_for_events(inp.bank_id, probed.events):      # the state machine already limits how often these happen
            await self._notify(alert)

        # ── 1. IET near-breach risk ───────────────────────────────────
        iet_result = await workflow.execute_activity(
            check_iet_risk_for_alert, CheckIETInput(bank_id=inp.bank_id), start_to_close_timeout=_ACTIVITY_TIMEOUT, retry_policy=_CHECK_RETRY)
        if iet_result.needs_alert:
            await self._send(inp, DispatchAlertInput(
                bank_id=inp.bank_id, event_type="IET_BREACH_RISK", severity="CRITICAL", priority="P0",
                message=get_message("CTS_IET_BREACH_RISK_CHEQUES_WITHIN", near_breach_count=iet_result.near_breach_count),
            ), now, inp.iet_repeat_seconds)

        # ── 2. Human review queue ─────────────────────────────────────
        hr_result = await workflow.execute_activity(
            check_human_review_for_alert,
            CheckHRInput(bank_id=inp.bank_id, max_depth=inp.max_hr_depth, max_wait_minutes=inp.max_hr_wait_minutes),
            start_to_close_timeout=_ACTIVITY_TIMEOUT, retry_policy=_CHECK_RETRY)
        if hr_result.needs_alert:
            await self._send(inp, DispatchAlertInput(
                bank_id=inp.bank_id, event_type="HUMAN_REVIEW_QUEUE_DEEP", severity=hr_result.alert_severity, priority="P1",
                message=(f"Human review queue: depth={hr_result.queue_depth}, avg_wait={hr_result.avg_wait_minutes:.1f}min ({hr_result.alert_reason})"),
            ), now, inp.repeat_alert_seconds)

        # ── 3. Vault Redis coverage ───────────────────────────────────
        cov_result = await workflow.execute_activity(
            check_vault_redis_coverage_for_alert,
            CheckVaultCoverageInput(bank_id=inp.bank_id, min_coverage_pct=inp.min_vault_coverage_pct),
            start_to_close_timeout=_ACTIVITY_TIMEOUT, retry_policy=_CHECK_RETRY)
        if cov_result.needs_alert:
            await self._send(inp, DispatchAlertInput(
                bank_id=inp.bank_id, event_type="VAULT_REDIS_COLD_DETECTED", severity="WARN", priority="P1",
                message=(f"Vault Redis coverage low: {cov_result.coverage_pct:.1f}% "
                         f"({cov_result.redis_sig_keys}/{cov_result.yugabyte_accounts} accounts). Gap: {cov_result.gap_accounts} accounts. "
                         f"POST /v1/admin/vault/warm-redis to recover."),
            ), now, inp.repeat_alert_seconds)

        # ── 4. Scanner fleet OFFLINE check ───────────────────────────
        fleet_result = await workflow.execute_activity(
            check_scanner_fleet_for_alert, CheckScannerFleetInput(bank_id=inp.bank_id), start_to_close_timeout=_ACTIVITY_TIMEOUT, retry_policy=_CHECK_RETRY)
        if fleet_result.needs_alert:
            branch_list = ", ".join(fleet_result.offline_branches[:5])
            if fleet_result.offline_count > 5:
                branch_list += f" (+{fleet_result.offline_count - 5} more)"
            await self._send(inp, DispatchAlertInput(
                bank_id=inp.bank_id, event_type="SCANNER_BRANCH_OFFLINE", severity="WARN", priority="P1",
                message=get_message("CTS_BRANCH_SCANNER_S_OFFLINE_DURING", offline_count=fleet_result.offline_count, branch_list=branch_list),
            ), now, inp.repeat_alert_seconds)

        # ── 5. Stuck workflow sweep ───────────────────────────────────
        sweep_result = await workflow.execute_activity(
            sweep_stuck_workflows, StuckWorkflowSweepInput(bank_id=inp.bank_id), start_to_close_timeout=_ACTIVITY_TIMEOUT, retry_policy=_CHECK_RETRY)
        if sweep_result.found > 0 and not sweep_result.degraded:
            await self._send(inp, DispatchAlertInput(
                bank_id=inp.bank_id, event_type="STUCK_WORKFLOWS_TERMINATED", severity="WARN", priority="P1",
                message=get_message("CTS_AUTO_TERMINATED_STUCK_CTS_WORKFLOWS", terminated=sweep_result.terminated, found=sweep_result.found),
            ), now, inp.repeat_alert_seconds)

        # ── 6. Alert outbox: retry what failed to send, recover what a dead sender left behind ─────
        if workflow.patched(_PATCH_OUTBOX):
            await workflow.execute_activity(
                process_alert_outbox, ProcessOutboxInput(bank_id=inp.bank_id), start_to_close_timeout=timedelta(seconds=45), retry_policy=_CHECK_RETRY)

        # ── 7. Retention: prune old alert history ────────────────────────────────────────────────
        if workflow.patched(_PATCH_RETENTION) and inp.prune_every_ticks > 0 and (self._tick - 1) % inp.prune_every_ticks == 0:
            await workflow.execute_activity(
                run_alert_retention, RunRetentionInput(bank_id=inp.bank_id), start_to_close_timeout=timedelta(seconds=120), retry_policy=_CHECK_RETRY)

    @workflow.run
    async def run(self, inp: PlatformHealthInput) -> None:
        self._states = {k: ComponentState.model_validate(v) if isinstance(v, dict) else v for k, v in inp.states.items()}
        self._last_sent = dict(inp.last_sent)
        self._tick = inp.tick
        ticks_this_run = 0
        while True:
            now = workflow.now().timestamp()
            try:
                await self._tick_once(inp, now)
            except CancelledError:
                raise
            except Exception as exc:       # one failing check must never end the monitor: log and carry on to the next tick
                workflow.logger.error("platform_health.tick_failed: %s", exc)
            self._tick += 1
            ticks_this_run += 1
            self._last_tick_at = now

            # temporalio has no workflow.sleep() (confirmed against the installed SDK, 1.7.1 — see .claude/rules/temporal.md's "Deterministic Sleep"
            # section, 2026-09-23). No signal interrupts this loop, so a pure wait_condition timeout is the deterministic-sleep idiom here.
            try:
                await workflow.wait_condition(lambda: False, timeout=timedelta(seconds=_HEALTH_CHECK_INTERVAL_S))
            except asyncio.TimeoutError:
                pass

            if ticks_this_run >= inp.max_ticks_before_restart or self._restart_requested:
                workflow.continue_as_new(inp.model_copy(update={"states": dict(self._states), "last_sent": dict(self._last_sent), "tick": self._tick}))

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
          "scanner_fleet": dict matching ScannerFleetCheckResult fields (optional — defaults to no alert)
          "stuck_sweep":   dict matching StuckWorkflowSweepResult fields (optional — defaults to no alert)
          "dispatched":    list — run_with_mocks appends alert dicts here instead of
                           calling dispatch_platform_alert

        Returns HealthCheckRunResult(checks_run=5).
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
                "message": get_message("CTS_IET_BREACH_RISK_CHEQUES_WITHIN_2", near_breach=near_breach),
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
                    get_message("CTS_HUMAN_REVIEW_QUEUE_DEPTH_REASON", hr_data=hr_data.get('queue_depth', 0), hr_data2=hr_data.get('alert_reason', 'UNKNOWN'))
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

        # ── Scanner fleet OFFLINE check ───────────────────────────────────
        fleet_data = mock_results.get("scanner_fleet", {"needs_alert": False, "degraded": False, "skipped_outside_hours": False})
        checks_run += 1
        if fleet_data.get("needs_alert"):
            offline_branches = fleet_data.get("offline_branches", [])
            branch_list = ", ".join(offline_branches[:5])
            if len(offline_branches) > 5:
                branch_list += f" (+{len(offline_branches) - 5} more)"
            dispatched.append({
                "event_type": "SCANNER_BRANCH_OFFLINE",
                "severity": fleet_data.get("alert_severity", "WARN"),
                "priority": "P1",
                "bank_id": inp.bank_id,
                "message": (
                    get_message("CTS_BRANCH_SCANNER_S_OFFLINE_DURING_2", fleet_data=fleet_data.get('offline_count', len(offline_branches)), branch_list=branch_list)
                ),
            })
            alerts_sent += 1

        # ── Stuck workflow sweep check ────────────────────────────────────
        sweep_data = mock_results.get("stuck_sweep", {"found": 0, "terminated": 0, "degraded": False})
        checks_run += 1
        if sweep_data.get("found", 0) > 0 and not sweep_data.get("degraded", False):
            dispatched.append({
                "event_type": "STUCK_WORKFLOWS_TERMINATED",
                "severity": "WARN",
                "priority": "P1",
                "bank_id": inp.bank_id,
                "message": (
                    get_message("CTS_AUTO_TERMINATED_STUCK_CTS_WORKFLOWS_2", sweep_data=sweep_data.get('terminated', 0), sweep_data2=sweep_data.get('found', 0))
                ),
            })
            alerts_sent += 1

        return HealthCheckRunResult(checks_run=checks_run, alerts_sent=alerts_sent)
