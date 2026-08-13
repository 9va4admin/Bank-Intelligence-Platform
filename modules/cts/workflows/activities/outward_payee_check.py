"""Outward payee name check activity for CTS outward clearing.

In outward processing, the cheque is being deposited by a customer at OUR branch.
The cheque has a payee name written on it (may be in any Indic script, with
salutations). The depositor has an account with us, and their name is in CBS.

This activity:
  1. Takes the OCR-extracted payee name from the deposit slip, cheque reverse, or kiosk.
  2. Takes the CBS-stored account holder name (from the account the customer is depositing into).
  3. Runs payee_names_match() — salutation strip → transliterate → Jaro-Winkler.
  4. Returns a decision: MATCH | FUZZY | MISMATCH | UNDECIDABLE.

FUZZY → routed to branch supervisor for manual confirmation before lot admission.
MISMATCH → cheque rejected at counter (not admitted to lot).
UNDECIDABLE → routed to supervisor (safe default).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from temporalio import activity

from shared.config.config_service import config_service
from modules.cts.preprocessing.payee_normalizer import payee_names_match

PayeeDecision = Literal["MATCH", "FUZZY", "MISMATCH", "UNDECIDABLE"]
OutwardSource = Literal["deposit_slip", "kiosk", "cheque_reverse"]


@dataclass(frozen=True)
class OutwardPayeeCheckInput:
    ocr_payee_name: str
    cbs_account_holder_name: str
    script: str | None
    source: OutwardSource
    instrument_id: str
    bank_id: str


@dataclass(frozen=True)
class OutwardPayeeCheckResult:
    decision: PayeeDecision
    score: float | None
    normalized_ocr: str
    normalized_cbs: str
    instrument_id: str
    source: OutwardSource


@activity.defn
async def check_outward_payee(input: OutwardPayeeCheckInput) -> OutwardPayeeCheckResult:
    """Verify that the payee name on the cheque matches the depositor's CBS name.

    Threshold sourced from config_service — never hardcoded.
    Operates on OUTWARD side only (we are the presenting bank).
    """
    cts_cfg = await config_service.get_cts_config(input.bank_id)
    threshold: float = cts_cfg.get("payee_match_threshold", 0.82)

    match_result = payee_names_match(
        ocr_name=input.ocr_payee_name,
        cbs_name=input.cbs_account_holder_name,
        threshold=threshold,
        script=input.script,
    )

    return OutwardPayeeCheckResult(
        decision=match_result.decision,
        score=match_result.score,
        normalized_ocr=match_result.normalized_ocr,
        normalized_cbs=match_result.normalized_cbs,
        instrument_id=input.instrument_id,
        source=input.source,
    )
