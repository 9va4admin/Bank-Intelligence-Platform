"""
EJ canonical schema validation activity.
"""
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()

_REQUIRED_FIELDS = {"transaction_type", "status", "timestamp"}


class EJValidateInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    canonical_record: dict[str, Any]
    canonical_hash: str
    bank_id: str
    atm_id: str
    raw_log_hash: str


class EJValidateResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str                    # "VALID" | "INVALID"
    bank_id: str
    validation_errors: list[str]


async def validate_ej_canonical(inp: EJValidateInput) -> EJValidateResult:
    errors: list[str] = []

    for field in _REQUIRED_FIELDS:
        if field not in inp.canonical_record or inp.canonical_record[field] is None:
            errors.append(f"missing_required_field:{field}")

    if errors:
        log.warning("ej_validate.invalid", atm_id=inp.atm_id, errors=errors)
        return EJValidateResult(outcome="INVALID", bank_id=inp.bank_id, validation_errors=errors)

    return EJValidateResult(outcome="VALID", bank_id=inp.bank_id, validation_errors=[])
