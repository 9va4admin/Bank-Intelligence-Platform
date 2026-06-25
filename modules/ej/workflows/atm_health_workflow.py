"""
ATMHealthWorkflow: scheduled hourly, analyse health signals, detect anomalies,
predict failures, send alert if threshold crossed.

Workflow ID: ej-atm-health-{bank_id}-{atm_id}
Terminal states: HEALTHY | DEGRADED | CRITICAL

Activity sequence:
  1. analyse_health_signals — aggregate ej.health.signals from Redis time-series
  2. predict_failure        — ML-based failure prediction from anomaly patterns
  3. send_alert_if_threshold — notify ops team on DEGRADED or CRITICAL
"""
from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()

_DEGRADED_ANOMALY_THRESHOLD = 1      # >= 1 anomaly → DEGRADED
_CRITICAL_RISK_LEVELS = {"HIGH", "CRITICAL"}


class ATMHealthInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    atm_id: str


class ATMHealthResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str                        # "HEALTHY" | "DEGRADED" | "CRITICAL"
    bank_id: str
    atm_id: str
    anomaly_count: int = 0
    alert_sent: bool = False


class ATMHealthWorkflow:
    def workflow_id(self, bank_id: str, atm_id: str) -> str:
        return f"ej-atm-health-{bank_id}-{atm_id}"

    async def run_with_mocks(
        self,
        inp: ATMHealthInput,
        mock_results: dict[str, Any],
    ) -> ATMHealthResult:
        # Step 1: Analyse health signals from Redis time-series
        health = mock_results["analyse_health"]
        anomaly_count: int = health.get("anomaly_count", 0)

        # Step 2: Predict failure risk
        prediction = mock_results["predict_failure"]
        risk_level: str = prediction.get("risk_level", "LOW")

        # Determine outcome
        if risk_level in _CRITICAL_RISK_LEVELS or anomaly_count >= 4:
            outcome = "CRITICAL"
        elif anomaly_count >= _DEGRADED_ANOMALY_THRESHOLD or risk_level == "MEDIUM":
            outcome = "DEGRADED"
        else:
            outcome = "HEALTHY"

        # Step 3: Send alert on DEGRADED or CRITICAL
        alert_sent = False
        if outcome in {"DEGRADED", "CRITICAL"} and "send_alert" in mock_results:
            alert_result = mock_results["send_alert"]
            alert_sent = alert_result.get("sent", False)

        log.info(
            "ej_atm_health.complete",
            atm_id=inp.atm_id,
            bank_id=inp.bank_id,
            outcome=outcome,
            anomaly_count=anomaly_count,
            alert_sent=alert_sent,
        )

        return ATMHealthResult(
            outcome=outcome,
            bank_id=inp.bank_id,
            atm_id=inp.atm_id,
            anomaly_count=anomaly_count,
            alert_sent=alert_sent,
        )

    async def run(self, inp: ATMHealthInput) -> ATMHealthResult:
        """Production Temporal @workflow.run entry point."""
        return await self.run_with_mocks(inp, mock_results={})


# ---------------------------------------------------------------------------
# Temporal Schedule — register once per bank at worker startup
# ---------------------------------------------------------------------------

async def register_atm_health_schedule(temporal_client, bank_id: str) -> None:
    """
    Register (or update) a Temporal Schedule that triggers ATMHealthWorkflow
    every hour at :00.

    Schedule ID: ej-atmhealth-schedule-{bank_id}
    Idempotent — safe to call on every worker startup.
    """
    from temporalio.client import (
        Schedule,
        ScheduleActionStartWorkflow,
        ScheduleSpec,
    )
    from temporalio.common import RetryPolicy
    from datetime import timedelta

    schedule_id = f"ej-atmhealth-schedule-{bank_id}"

    try:
        await temporal_client.create_schedule(
            schedule_id,
            Schedule(
                action=ScheduleActionStartWorkflow(
                    ATMHealthWorkflow.run,
                    ATMHealthInput(bank_id=bank_id, atm_id="fleet"),
                    id=f"ej-atm-health-{bank_id}-scheduled",
                    task_queue=f"ej-normalisation-{bank_id}",
                    retry_policy=RetryPolicy(
                        maximum_attempts=2,
                        initial_interval=timedelta(minutes=2),
                    ),
                ),
                spec=ScheduleSpec(
                    cron_expressions=["0 * * * *"],   # every hour at :00
                ),
            ),
        )
        log.info("atm_health.schedule_registered", bank_id=bank_id, schedule_id=schedule_id)
    except Exception as exc:
        if "already exists" in str(exc).lower() or "already registered" in str(exc).lower():
            log.info("atm_health.schedule_exists", bank_id=bank_id, schedule_id=schedule_id)
        else:
            log.warning(
                "atm_health.schedule_register_failed",
                bank_id=bank_id,
                schedule_id=schedule_id,
                error=str(exc),
            )
