"""
EJ OEM fingerprint validation activity.

Note: OEM detection happens in the Go edge agent (branch-ej-agent).
This Python activity receives the fingerprint and validates it against known OEMs.
"""
import structlog
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()

_KNOWN_OEMS = frozenset([
    "NCR_SELFSERV",
    "DIEBOLD_NIXDORF",
    "WINCOR_NIXDORF",
    "HYOSUNG",
    "GRG_BANKING",
])


class EJFingerprintInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    oem_fingerprint: str
    atm_id: str
    bank_id: str
    raw_log_hash: str


class EJFingerprintResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str            # "VALIDATED" | "UNKNOWN_OEM"
    oem_fingerprint: str
    bank_id: str


async def validate_oem_fingerprint(inp: EJFingerprintInput) -> EJFingerprintResult:
    if inp.oem_fingerprint in _KNOWN_OEMS:
        return EJFingerprintResult(
            outcome="VALIDATED",
            oem_fingerprint=inp.oem_fingerprint,
            bank_id=inp.bank_id,
        )

    log.warning(
        "ej_fingerprint.unknown_oem",
        atm_id=inp.atm_id,
        oem_fingerprint=inp.oem_fingerprint,
    )
    return EJFingerprintResult(
        outcome="UNKNOWN_OEM",
        oem_fingerprint=inp.oem_fingerprint,
        bank_id=inp.bank_id,
    )
