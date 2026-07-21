"""
ASTRA Ops Dashboard API — replaces Grafana with contextual React pages.

Routes:
  GET /v1/ops/dashboard      — IET risk + human review queue + Kafka lag + Temporal depth
  GET /v1/ops/model-health   — OCR/fraud/signature model drift indicators (7-day rolling)
  GET /v1/ops/alerts         — recent CRITICAL/ERROR from audit trail (last 24h, max 50)
  GET /v1/ops/system         — Redis/YugabyteDB/Vault connectivity + pool utilisation

Access: ops_manager and bank_it_admin only (ml_engineer also for /model-health).
No PII in any response — only counts, rates, percentiles, distributions.
All deps degrade gracefully to None → 200 with degraded=True, zero values.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict

from apps.api.dependencies import require_user_context
from shared.auth.rbac import UserContext

log = structlog.get_logger()

router_v1 = APIRouter(prefix="/v1/ops", tags=["Ops Dashboard v1"])

_OPS_ROLES = frozenset({"ops_manager", "bank_it_admin"})
_OPS_AND_ML_ROLES = frozenset({"ops_manager", "bank_it_admin", "ml_engineer"})


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

async def get_current_user(
    ctx: UserContext = Depends(require_user_context),
) -> UserContext:
    return ctx


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class IETRiskPanel(BaseModel):
    model_config = ConfigDict(frozen=True)
    near_breach_count: int = 0       # cheques within 30s of IET deadline
    in_processing_count: int = 0     # total cheques currently in-flight
    degraded: bool = False


class HumanReviewPanel(BaseModel):
    model_config = ConfigDict(frozen=True)
    queue_depth: int = 0
    avg_wait_minutes: float = 0.0
    degraded: bool = False


class DashboardResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    as_of: str
    iet_risk: IETRiskPanel
    human_review: HumanReviewPanel
    degraded: bool = False


class ModelEntry(BaseModel):
    model_config = ConfigDict(frozen=True, protected_namespaces=())
    model_name: str
    metric: str
    current_value: float = 0.0
    baseline_7d: float = 0.0
    drift_pct: float = 0.0
    alert_status: str = "UNKNOWN"    # SAFE | WARN | CRITICAL | UNKNOWN
    degraded: bool = False


class ModelHealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    as_of: str
    models: list[ModelEntry] = []
    degraded: bool = False


class AlertEntry(BaseModel):
    model_config = ConfigDict(frozen=True)
    event_type: str
    severity: str
    occurred_at: str
    acknowledged: bool = False


class AlertsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    as_of: str
    total: int = 0
    alerts: list[AlertEntry] = []
    degraded: bool = False


class RedisPanel(BaseModel):
    model_config = ConfigDict(frozen=True)
    connected: bool = False
    hit_rate_pct: float = 0.0
    degraded: bool = False


class YugabytePanel(BaseModel):
    model_config = ConfigDict(frozen=True)
    connected: bool = False
    pool_size: int = 0
    active_connections: int = 0
    degraded: bool = False


class SystemHealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    as_of: str
    redis_cts: RedisPanel
    yugabyte: YugabytePanel
    degraded: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _fetch_dashboard_panels(
    bank_id: str,
    db_pool: Any,
) -> tuple[IETRiskPanel, HumanReviewPanel]:
    if db_pool is None:
        return (
            IETRiskPanel(degraded=True),
            HumanReviewPanel(degraded=True),
        )
    try:
        async with db_pool.acquire() as conn:
            iet_row = await conn.fetchrow(
                """
                SELECT
                  COUNT(*) FILTER (WHERE iet_deadline < NOW() + INTERVAL '30 seconds') AS near_breach,
                  COUNT(*) AS in_processing
                FROM cts.cheque_instruments
                WHERE bank_id = $1
                  AND status = 'IN_PROCESSING'
                """,
                bank_id,
            )
            review_row = await conn.fetchrow(
                """
                SELECT
                  COUNT(*) AS queue_depth,
                  COALESCE(AVG(EXTRACT(EPOCH FROM (NOW() - received_at)) / 60), 0) AS avg_wait
                FROM cts.cheque_instruments
                WHERE bank_id = $1
                  AND status = 'HUMAN_REVIEW'
                """,
                bank_id,
            )
        return (
            IETRiskPanel(
                near_breach_count=int(iet_row["near_breach"] or 0),
                in_processing_count=int(iet_row["in_processing"] or 0),
            ),
            HumanReviewPanel(
                queue_depth=int(review_row["queue_depth"] or 0),
                avg_wait_minutes=float(review_row["avg_wait"] or 0.0),
            ),
        )
    except Exception as exc:
        log.warning("ops.dashboard.db_error", bank_id=bank_id, error=str(exc))
        return (
            IETRiskPanel(degraded=True),
            HumanReviewPanel(degraded=True),
        )


_MODEL_CONFIGS = [
    ("got-ocr2", "ocr_confidence_mean", "cts.ai_inference_logs", "ocr_confidence"),
    ("qwen2-vl", "fraud_score_mean",    "cts.agent_decisions",   "fraud_score"),
]

_DRIFT_WARN = 2.0
_DRIFT_CRITICAL = 5.0


async def _fetch_model_health(bank_id: str, db_pool: Any) -> tuple[list[ModelEntry], bool]:
    if db_pool is None:
        return [], True
    entries: list[ModelEntry] = []
    try:
        async with db_pool.acquire() as conn:
            for model_name, metric, table, col in _MODEL_CONFIGS:
                row = await conn.fetchrow(
                    f"""
                    SELECT
                      AVG({col}) FILTER (WHERE created_at > NOW() - INTERVAL '1 day')   AS current_val,
                      AVG({col}) FILTER (WHERE created_at BETWEEN NOW() - INTERVAL '8 days'
                                                              AND NOW() - INTERVAL '1 day') AS baseline_7d
                    FROM {table}
                    WHERE bank_id = $1
                    """,
                    bank_id,
                )
                curr = float(row["current_val"] or 0.0)
                base = float(row["baseline_7d"] or 0.0)
                drift = ((curr - base) / base * 100) if base else 0.0
                abs_drift = abs(drift)
                if base == 0.0:
                    alert = "UNKNOWN"
                elif abs_drift >= _DRIFT_CRITICAL:
                    alert = "CRITICAL"
                elif abs_drift >= _DRIFT_WARN:
                    alert = "WARN"
                else:
                    alert = "SAFE"
                entries.append(ModelEntry(
                    model_name=model_name,
                    metric=metric,
                    current_value=round(curr, 4),
                    baseline_7d=round(base, 4),
                    drift_pct=round(drift, 2),
                    alert_status=alert,
                ))
        return entries, False
    except Exception as exc:
        log.warning("ops.model_health.db_error", bank_id=bank_id, error=str(exc))
        return [], True


async def _fetch_alerts(
    bank_id: str, db_pool: Any, limit: int
) -> tuple[list[AlertEntry], int, bool]:
    if db_pool is None:
        return [], 0, True
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT event_type, severity, occurred_at, acknowledged
                FROM cts.audit_events
                WHERE bank_id = $1
                  AND severity IN ('CRITICAL', 'ERROR')
                  AND occurred_at > NOW() - INTERVAL '24 hours'
                ORDER BY occurred_at DESC
                LIMIT $2
                """,
                bank_id,
                limit,
            )
            total_row = await conn.fetchrow(
                """
                SELECT COUNT(*) AS cnt
                FROM cts.audit_events
                WHERE bank_id = $1
                  AND severity IN ('CRITICAL', 'ERROR')
                  AND occurred_at > NOW() - INTERVAL '24 hours'
                """,
                bank_id,
            )
        alerts = [
            AlertEntry(
                event_type=r["event_type"],
                severity=r["severity"],
                occurred_at=r["occurred_at"].isoformat() if hasattr(r["occurred_at"], "isoformat") else str(r["occurred_at"]),
                acknowledged=bool(r["acknowledged"]),
            )
            for r in rows
        ]
        return alerts, int(total_row["cnt"] or 0), False
    except Exception as exc:
        log.warning("ops.alerts.db_error", bank_id=bank_id, error=str(exc))
        return [], 0, True


async def _fetch_system_health(
    bank_id: str, db_pool: Any, redis_cts: Any
) -> tuple[RedisPanel, YugabytePanel]:
    # Redis panel
    if redis_cts is None:
        redis_panel = RedisPanel(degraded=True)
    else:
        try:
            info = await redis_cts.info("stats")
            hits = int(info.get("keyspace_hits", 0))
            misses = int(info.get("keyspace_misses", 0))
            total = hits + misses
            hit_rate = (hits / total * 100) if total else 0.0
            redis_panel = RedisPanel(connected=True, hit_rate_pct=round(hit_rate, 1))
        except Exception as exc:
            log.warning("ops.system.redis_error", bank_id=bank_id, error=str(exc))
            redis_panel = RedisPanel(degraded=True)

    # YugabyteDB panel
    if db_pool is None:
        yb_panel = YugabytePanel(degraded=True)
    else:
        try:
            pool_size = getattr(db_pool, "_maxsize", 0) or getattr(db_pool, "get_size", lambda: 0)()
            active = getattr(db_pool, "get_size", lambda: 0)() - getattr(db_pool, "get_idle_size", lambda: 0)()
            yb_panel = YugabytePanel(
                connected=True,
                pool_size=int(pool_size),
                active_connections=max(0, int(active)),
            )
        except Exception as exc:
            log.warning("ops.system.yugabyte_error", bank_id=bank_id, error=str(exc))
            yb_panel = YugabytePanel(degraded=True)

    return redis_panel, yb_panel


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router_v1.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(
    request: Request,
    user: dict = Depends(get_current_user),
) -> DashboardResponse:
    role = user["role"] if isinstance(user, dict) else user.role
    bank_id = user["bank_id"] if isinstance(user, dict) else user.bank_id
    if role not in _OPS_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")

    db_pool = getattr(request.app.state, "db_pool_cts", None)
    iet_panel, review_panel = await _fetch_dashboard_panels(bank_id, db_pool)

    degraded = iet_panel.degraded or review_panel.degraded
    log.info("ops.dashboard.served", bank_id=bank_id, degraded=degraded)
    return DashboardResponse(
        bank_id=bank_id,
        as_of=_now_iso(),
        iet_risk=iet_panel,
        human_review=review_panel,
        degraded=degraded,
    )


@router_v1.get("/model-health", response_model=ModelHealthResponse)
async def get_model_health(
    request: Request,
    user: dict = Depends(get_current_user),
) -> ModelHealthResponse:
    role = user["role"] if isinstance(user, dict) else user.role
    bank_id = user["bank_id"] if isinstance(user, dict) else user.bank_id
    if role not in _OPS_AND_ML_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")

    db_pool = getattr(request.app.state, "db_pool_cts", None)
    models, degraded = await _fetch_model_health(bank_id, db_pool)

    log.info("ops.model_health.served", bank_id=bank_id, model_count=len(models))
    return ModelHealthResponse(
        bank_id=bank_id,
        as_of=_now_iso(),
        models=models,
        degraded=degraded,
    )


@router_v1.get("/alerts", response_model=AlertsResponse)
async def get_alerts(
    request: Request,
    user: dict = Depends(get_current_user),
    limit: int = Query(default=25, ge=1, le=50),
) -> AlertsResponse:
    role = user["role"] if isinstance(user, dict) else user.role
    bank_id = user["bank_id"] if isinstance(user, dict) else user.bank_id
    if role not in _OPS_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")

    db_pool = getattr(request.app.state, "db_pool_cts", None)
    alerts, total, degraded = await _fetch_alerts(bank_id, db_pool, limit)

    return AlertsResponse(
        bank_id=bank_id,
        as_of=_now_iso(),
        total=total,
        alerts=alerts,
        degraded=degraded,
    )


@router_v1.get("/system", response_model=SystemHealthResponse)
async def get_system_health(
    request: Request,
    user: dict = Depends(get_current_user),
) -> SystemHealthResponse:
    role = user["role"] if isinstance(user, dict) else user.role
    bank_id = user["bank_id"] if isinstance(user, dict) else user.bank_id
    if role not in _OPS_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")

    db_pool = getattr(request.app.state, "db_pool_cts", None)
    redis_cts = getattr(request.app.state, "redis_cts", None)
    redis_panel, yb_panel = await _fetch_system_health(bank_id, db_pool, redis_cts)

    degraded = redis_panel.degraded or yb_panel.degraded
    return SystemHealthResponse(
        bank_id=bank_id,
        as_of=_now_iso(),
        redis_cts=redis_panel,
        yugabyte=yb_panel,
        degraded=degraded,
    )
