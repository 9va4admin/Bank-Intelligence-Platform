"""
classify_bucket and sip_hold_check — which review bucket an inward cheque belongs to, and whether a system decision
must be held for a reviewer.

Both are best-effort by design: a failed lookup degrades to what is known (and is reported in `degraded`) and a failed
hold check means "do not hold". Neither can fail the workflow or change the cheque's decision.

The rules live in modules/cts/buckets.py; every threshold arrives in `cfg` (the bank's Layer 3 config, bare key names).
"""
from __future__ import annotations

from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict, Field

from modules.cts.buckets import BucketFacts, matched_buckets, resolve_bucket
from shared.observability.otel_setup import get_tracer
from shared.utils.pii_crypto import hash_account_number

log = structlog.get_logger()
tracer = get_tracer(__name__)

SQL_LISTS = "SELECT bucket FROM cts.bucket_account_lists WHERE bank_id = $1 AND account_hash = $2"
SQL_RECENT = (
    "SELECT count(*) FROM cts.cheque_instruments WHERE bank_id = $1 AND account_hash = $2 "
    "AND direction = 'INWARD' AND received_at >= now() - ($3::int * interval '1 day')"
)
_SIP_BUCKETS = ("SIP_SUCCESS", "SIP_REJECT")


class ClassifyBucketInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    instrument_id: str
    account_number: str
    presented_amount: Optional[float] = None
    needs_human: bool
    system_decision: Optional[str] = None            # "CONFIRM" | "RETURN" when the system decided
    cfg: dict[str, Any] = Field(default_factory=dict)


class ClassifyBucketResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    bucket: str
    matched: list[str] = Field(default_factory=list)     # every class bucket the cheque fits, in priority order
    degraded: list[str] = Field(default_factory=list)    # facts that could not be fetched


async def classify_bucket(
    inp: ClassifyBucketInput, cbs_connector: Any = None, db_conn: Any = None, pepper: Optional[str] = None,
) -> ClassifyBucketResult:
    with tracer.start_as_current_span("activity.classify_bucket") as span:
        span.set_attribute("bank_id", inp.bank_id)
        if not inp.needs_human:
            facts = BucketFacts(needs_human=False, system_decision=inp.system_decision, amount=inp.presented_amount)
            return ClassifyBucketResult(bucket=resolve_bucket(facts, inp.cfg))

        degraded: list[str] = []
        account_type: Optional[str] = None
        if cbs_connector is not None:
            try:
                info = await cbs_connector.get_account_info(inp.account_number, inp.bank_id)
                account_type = getattr(info, "account_type", None)
            except Exception as exc:  # noqa: BLE001 - never let a CBS fault change routing of a cheque
                log.warning("classify_bucket.cbs_unavailable", bank_id=inp.bank_id, error=str(exc))
                degraded.append("account_type")
        else:
            degraded.append("account_type")

        listed: frozenset = frozenset()
        recent: Optional[int] = None
        if db_conn is not None and pepper:
            account_hash = hash_account_number(inp.account_number, inp.bank_id, pepper)
            try:
                listed = frozenset(r["bucket"] for r in await db_conn.fetch(SQL_LISTS, inp.bank_id, account_hash))
            except Exception as exc:  # noqa: BLE001
                log.warning("classify_bucket.lists_unavailable", bank_id=inp.bank_id, error=str(exc))
                degraded.append("account_lists")
            try:
                days = int(inp.cfg.get("bucket_frequent_window_days", 30))
                recent = int(await db_conn.fetchval(SQL_RECENT, inp.bank_id, account_hash, days))
            except Exception as exc:  # noqa: BLE001
                log.warning("classify_bucket.history_unavailable", bank_id=inp.bank_id, error=str(exc))
                degraded.append("recent_cheques")
        else:
            degraded += ["account_lists", "recent_cheques"]

        facts = BucketFacts(needs_human=True, amount=inp.presented_amount, account_type=account_type,
                            listed_in=listed, recent_cheques=recent)
        result = ClassifyBucketResult(bucket=resolve_bucket(facts, inp.cfg), matched=matched_buckets(facts, inp.cfg),
                                      degraded=degraded)
        log.info("classify_bucket.done", bank_id=inp.bank_id, instrument_id=inp.instrument_id, bucket=result.bucket,
                 degraded=degraded)
        return result


class SipHoldInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    bucket: str
    cfg: dict[str, Any] = Field(default_factory=dict)


class SipHoldResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    hold: bool
    reason: Optional[str] = None


async def sip_hold_check(inp: SipHoldInput, db_pool: Any = None, redis_client: Any = None) -> SipHoldResult:
    """Hold a system decision for review only when routing is on, the bucket is a SIP bucket, and at least one
    reviewer connected to it is logged in right now. Anything else (including any failure) means: file immediately."""
    with tracer.start_as_current_span("activity.sip_hold_check") as span:
        span.set_attribute("bank_id", inp.bank_id)
        if not inp.cfg.get("bucket_routing_enabled", False):
            return SipHoldResult(hold=False, reason="ROUTING_OFF")
        if inp.bucket not in _SIP_BUCKETS:
            return SipHoldResult(hold=False, reason="NOT_A_SIP_BUCKET")
        try:
            from modules.cts.allocation.lock_service import LockService
            from modules.cts.allocation.subscriptions import SubscriptionStore
            subscribers = set(await SubscriptionStore(db_pool, redis=None).get_subscribers(inp.bank_id, inp.bucket))
            if not subscribers:
                return SipHoldResult(hold=False, reason="NO_SUBSCRIBERS")
            if redis_client is None:
                return SipHoldResult(hold=True, reason="SUBSCRIBERS_PRESENCE_UNKNOWN")
            active = set(await LockService(redis_client).get_active_reviewers(inp.bank_id))
            if not subscribers & active:
                return SipHoldResult(hold=False, reason="NO_ACTIVE_SUBSCRIBER")
            return SipHoldResult(hold=True)
        except Exception as exc:  # noqa: BLE001 - a fault must never delay a filing
            log.warning("sip_hold_check.failed", bank_id=inp.bank_id, error=str(exc))
            return SipHoldResult(hold=False, reason="CHECK_FAILED")
