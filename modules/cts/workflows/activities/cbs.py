"""
CBS activity — check account status and balance via CBS connector.

Graceful degradation: CBS unreachable → CBS_UNAVAILABLE outcome.
Account status routing:
  ACTIVE   → PROCEED (let processing continue)
  FROZEN   → RETURN  (OPA Layer 4 rule: return immediately)
  CLOSED   → RETURN
  NPA      → RETURN
  DORMANT  → HUMAN_REVIEW (ambiguous — escalate)
"""
from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict

from shared.cbs_connector.base import AccountStatus
from shared.cbs_connector.exceptions import AccountNotFoundError, CBSUnavailableError

log = structlog.get_logger()

_RETURN_STATUSES = {AccountStatus.FROZEN, AccountStatus.CLOSED, AccountStatus.NPA}
_HUMAN_REVIEW_STATUSES = {AccountStatus.DORMANT}


class CBSActivityInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    account_number: str
    bank_id: str
    instrument_id: str


class CBSActivityResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str               # "PROCEED" | "RETURN" | "HUMAN_REVIEW" | "CBS_UNAVAILABLE"
    account_status: Optional[str] = None
    available_balance: Optional[float] = None
    degraded: bool = False


async def check_account_status(
    inp: CBSActivityInput,
    cbs_connector=None,
) -> CBSActivityResult:
    """
    Check account status only — FROZEN/CLOSED/NPA → RETURN, DORMANT → HUMAN_REVIEW.
    Separated from check_cbs_balance so drawee workflow checks status independently.
    Degrades gracefully: CBS unavailable → CBS_UNAVAILABLE (caller routes to HUMAN_REVIEW).
    """
    try:
        account_info = await cbs_connector.get_account_info(
            inp.account_number, inp.bank_id
        )
    except AccountNotFoundError:
        log.info(
            "cbs_activity.account_status.not_found",
            account_last4=inp.account_number[-4:],
            bank_id=inp.bank_id,
        )
        return CBSActivityResult(outcome="RETURN", account_status="NOT_FOUND")
    except CBSUnavailableError as exc:
        log.warning(
            "cbs_activity.account_status.cbs_unavailable",
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            error=str(exc),
        )
        return CBSActivityResult(outcome="CBS_UNAVAILABLE", degraded=True)
    except Exception as exc:
        log.error(
            "cbs_activity.account_status.unexpected_error",
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            error=str(exc),
        )
        return CBSActivityResult(outcome="CBS_UNAVAILABLE", degraded=True)

    status = account_info.status

    if status in _RETURN_STATUSES:
        return CBSActivityResult(
            outcome="RETURN",
            account_status=status.value,
        )

    if status in _HUMAN_REVIEW_STATUSES:
        return CBSActivityResult(
            outcome="HUMAN_REVIEW",
            account_status=status.value,
        )

    return CBSActivityResult(
        outcome="PROCEED",
        account_status=status.value,
    )


async def check_cbs_balance(
    inp: CBSActivityInput,
    cbs_connector=None,
) -> CBSActivityResult:
    """
    Fetch account status and balance from CBS.
    Never raises — degrades gracefully to CBS_UNAVAILABLE on connector failure.
    """
    try:
        account_info = await cbs_connector.get_account_info(
            inp.account_number, inp.bank_id
        )
    except AccountNotFoundError:
        log.info(
            "cbs_activity.account_not_found",
            account_last4=inp.account_number[-4:],
            bank_id=inp.bank_id,
        )
        return CBSActivityResult(outcome="RETURN", account_status="NOT_FOUND")
    except CBSUnavailableError as exc:
        log.warning(
            "cbs_activity.cbs_unavailable",
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            error=str(exc),
        )
        return CBSActivityResult(outcome="CBS_UNAVAILABLE", degraded=True)
    except Exception as exc:
        log.error(
            "cbs_activity.unexpected_error",
            instrument_id=inp.instrument_id,
            bank_id=inp.bank_id,
            error=str(exc),
        )
        return CBSActivityResult(outcome="CBS_UNAVAILABLE", degraded=True)

    status = account_info.status

    if status in _RETURN_STATUSES:
        return CBSActivityResult(
            outcome="RETURN",
            account_status=status.value,
            available_balance=account_info.available_balance,
        )

    if status in _HUMAN_REVIEW_STATUSES:
        return CBSActivityResult(
            outcome="HUMAN_REVIEW",
            account_status=status.value,
            available_balance=account_info.available_balance,
        )

    return CBSActivityResult(
        outcome="PROCEED",
        account_status=status.value,
        available_balance=account_info.available_balance,
    )
