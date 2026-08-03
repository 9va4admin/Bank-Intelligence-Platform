"""
OPA client — evaluates CTS Layer 4 business policy rules via OPA decision API.

Policy file: infra/opa/policies/cts_routing.rego
OPA endpoint: POST /v1/data/astra/cts/routing

Input shape passed to OPA:
  { "input": { instrument_id, bank_id, cheque_type, amount, account_status,
               is_first_clearing_day, has_government_flag, has_court_order_flag } }

Expected OPA response:
  { "result": { "decision": "PROCEED" | "HUMAN_REVIEW" | "AUTO_RETURN",
                "reason": "..." } }

Failure mode: OPA unavailable → safe default PROCEED.
The downstream decision.py gates (fraud score, CBS, signature) still apply.
Never raises — callers can assume a result is always returned.
"""
from __future__ import annotations

from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()

_OPA_CTS_PATH = "/v1/data/astra/cts/routing"
_SAFE_DEFAULT = "PROCEED"
_SAFE_DEFAULT_REASON = "opa_unavailable"


class OPAInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    bank_id: str
    cheque_type: str                    # "STANDARD" | "GOVERNMENT" | "COURT_ORDER" | etc.
    amount: float
    account_status: str                 # as returned by CBS
    is_first_clearing_day: bool
    has_government_flag: bool
    has_court_order_flag: bool


class OPAResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    decision: str                       # "PROCEED" | "HUMAN_REVIEW" | "AUTO_RETURN"
    reason: str


class OPAClient:
    """
    Thin async client for OPA policy evaluation.
    Pass an httpx.AsyncClient (or equivalent mock) as http_client.
    """

    def __init__(self, opa_url: str, http_client: Any) -> None:
        self._base_url = opa_url.rstrip("/")
        self._http = http_client

    async def decide(self, inp: OPAInput) -> OPAResult:
        """
        Evaluate CTS routing policy for a single instrument.
        Always returns an OPAResult — never raises.
        """
        url = f"{self._base_url}{_OPA_CTS_PATH}"
        body = {
            "input": {
                "instrument_id": inp.instrument_id,
                "bank_id": inp.bank_id,
                "cheque_type": inp.cheque_type,
                "amount": inp.amount,
                "account_status": inp.account_status,
                "is_first_clearing_day": inp.is_first_clearing_day,
                "has_government_flag": inp.has_government_flag,
                "has_court_order_flag": inp.has_court_order_flag,
            }
        }

        try:
            response = await self._http.post(url, json=body)
        except Exception as exc:
            log.warning(
                "opa_client.unavailable",
                bank_id=inp.bank_id,
                instrument_id=inp.instrument_id,
                error=str(exc),
            )
            return OPAResult(decision=_SAFE_DEFAULT, reason=_SAFE_DEFAULT_REASON)

        if response.status_code != 200:
            log.warning(
                "opa_client.http_error",
                bank_id=inp.bank_id,
                status_code=response.status_code,
            )
            return OPAResult(decision=_SAFE_DEFAULT, reason=f"opa_http_{response.status_code}")

        try:
            data = response.json()
            result = data["result"]
            return OPAResult(
                decision=result["decision"],
                reason=result.get("reason", ""),
            )
        except Exception as exc:
            log.warning(
                "opa_client.parse_error",
                bank_id=inp.bank_id,
                error=str(exc),
            )
            return OPAResult(decision=_SAFE_DEFAULT, reason="opa_parse_error")
