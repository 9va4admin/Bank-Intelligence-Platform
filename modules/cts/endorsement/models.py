"""
CTS Endorsement Models.

EndorsementTemplate: bank identity + endorsement text stamped on cheque reverse.
EndorsementRecord:   per-instrument audit record of what was stamped and when.

PII rule: account_suffix stores only last 4 digits — enforced in __post_init__.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class EndorsementTemplate:
    bank_name:        str
    branch_name:      str
    bank_ifsc:        str
    endorsement_text: str  # e.g. "Payee's Account Credited. Received for Collection."


@dataclass
class EndorsementRecord:
    instrument_id:     str
    account_suffix:    str   # ≤4 chars — enforced below (PII rule)
    presentation_date: datetime
    applied_at:        datetime
    template:          EndorsementTemplate

    def __post_init__(self) -> None:
        if len(self.account_suffix) > 4:
            raise ValueError(
                f"account_suffix must be ≤ 4 characters (PII rule); "
                f"got {len(self.account_suffix)} chars"
            )
