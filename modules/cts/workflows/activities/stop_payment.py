"""
Stop payment check activity — CBS lookup + Bloom filter pre-check.

Routing:
  Bloom filter hit       → HUMAN_REVIEW  (probabilistic — may be false positive, never auto-return)
  CBS confirms stopped   → STP_RETURN
  CBS unavailable        → HUMAN_REVIEW  (uncertainty = escalate, never auto-return)
  Not stopped            → PROCEED

The Bloom filter (CanceledLeafBloom) is populated every 15 minutes by DeltaVaultSyncWorkflow
with stop-payment serials fetched from CBS. A Bloom hit is a fast early exit that routes to
human review without making a CBS round-trip, but because Bloom filters have a non-zero
false-positive rate we never auto-return on a Bloom hit alone.
"""
from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict

from temporalio import activity

from shared.cbs_connector.exceptions import CBSUnavailableError

log = structlog.get_logger()


class StopPaymentActivityInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    account_number: str
    cheque_number: str
    bank_id: str
    instrument_id: str


class StopPaymentActivityResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str                    # "PROCEED" | "STP_RETURN" | "HUMAN_REVIEW"
    bank_id: str = ""
    instrument_id: str = ""
    stop_reason: Optional[str] = None
    bloom_hit: bool = False
    degraded: bool = False


@activity.defn
async def check_stop_payment(
    inp: StopPaymentActivityInput,
    cbs_connector,
    bloom_client=None,
) -> StopPaymentActivityResult:
    """
    Check whether a stop payment instruction exists for this cheque.

    Always returns a result — never raises. CBS failure degrades to HUMAN_REVIEW.
    """
    # Fast path: Bloom filter pre-check before CBS round-trip
    if bloom_client is not None:
        try:
            if bloom_client.check_serial(inp.cheque_number):
                log.info(
                    "stop_payment.bloom_hit",
                    instrument_id=inp.instrument_id,
                    bank_id=inp.bank_id,
                    cheque_suffix=inp.cheque_number[-4:],
                )
                return StopPaymentActivityResult(
                    outcome="HUMAN_REVIEW",
                    bank_id=inp.bank_id,
                    instrument_id=inp.instrument_id,
                    stop_reason="bloom_filter_hit",
                    bloom_hit=True,
                )
        except Exception as exc:
            # Bloom unavailable is non-fatal — fall through to CBS
            log.warning(
                "stop_payment.bloom_error",
                instrument_id=inp.instrument_id,
                bank_id=inp.bank_id,
                error=str(exc),
            )

    # Authoritative CBS lookup
    try:
        result = await cbs_connector.check_stop_payment(
            inp.account_number, inp.cheque_number, inp.bank_id
        )
    except CBSUnavailableError as exc:
        log.warning(
            "stop_payment.cbs_unavailable",
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            error=str(exc),
        )
        return StopPaymentActivityResult(
            outcome="HUMAN_REVIEW",
            bank_id=inp.bank_id,
            instrument_id=inp.instrument_id,
            stop_reason="cbs_unavailable",
            degraded=True,
        )
    except Exception as exc:
        log.error(
            "stop_payment.unexpected_error",
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            error=str(exc),
        )
        return StopPaymentActivityResult(
            outcome="HUMAN_REVIEW",
            bank_id=inp.bank_id,
            instrument_id=inp.instrument_id,
            stop_reason="unexpected_error",
            degraded=True,
        )

    if result.is_stopped:
        log.info(
            "stop_payment.confirmed_stopped",
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            cheque_suffix=inp.cheque_number[-4:],
            reason=result.reason,
        )
        return StopPaymentActivityResult(
            outcome="STP_RETURN",
            bank_id=inp.bank_id,
            instrument_id=inp.instrument_id,
            stop_reason=result.reason,
        )

    return StopPaymentActivityResult(
        outcome="PROCEED",
        bank_id=inp.bank_id,
        instrument_id=inp.instrument_id,
    )
