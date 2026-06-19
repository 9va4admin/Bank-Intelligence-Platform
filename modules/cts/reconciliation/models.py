"""
CTS Automated Reconciliation — data models.

Reconciliation compares NGCH-filed instrument records against CBS posting
confirmations to detect mismatches, pending settlements, and amounts discrepancies
per clearing session.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class ReconciliationStatus(str, Enum):
    MATCHED          = 'MATCHED'           # NGCH confirmed + CBS posted, amounts agree
    NGCH_ONLY        = 'NGCH_ONLY'         # Filed to NGCH, no matching CBS posting
    CBS_ONLY         = 'CBS_ONLY'          # CBS posted, no matching NGCH record
    PENDING          = 'PENDING'           # NGCH filed + CBS pending (settlement in progress)
    AMOUNT_MISMATCH  = 'AMOUNT_MISMATCH'   # Both present but amount ranges differ


@dataclass
class ReconciliationItem:
    instrument_id:           str
    session_id:              str
    bank_id:                 str
    cheque_number:           str
    account_suffix:          str               # last 4 digits only — never full account number
    ngch_status:             str               # e.g. CONFIRMED, FILED, RETURNED
    cbs_status:              str               # e.g. POSTED, PENDING, REVERSED
    ngch_amount_range:       str               # bucketed range: ₹[<1L] / ₹[1L-5L] / etc.
    cbs_amount_range:        str
    reconciliation_status:   ReconciliationStatus
    occurred_at:             datetime
    detail:                  Optional[str] = None

    def __post_init__(self) -> None:
        if len(self.account_suffix) > 4:
            raise ValueError(
                f"account_suffix must be at most 4 characters (got {len(self.account_suffix)}). "
                "Store only the last 4 digits — never the full account number."
            )


@dataclass
class SessionReconciliationReport:
    session_id:    str
    bank_id:       str
    bank_ifsc:     str
    session_date:  datetime
    items:         list[ReconciliationItem] = field(default_factory=list)

    @property
    def total_items(self) -> int:
        return len(self.items)

    @property
    def matched_count(self) -> int:
        return sum(1 for i in self.items if i.reconciliation_status == ReconciliationStatus.MATCHED)

    @property
    def pending_count(self) -> int:
        return sum(1 for i in self.items if i.reconciliation_status == ReconciliationStatus.PENDING)

    @property
    def unmatched_count(self) -> int:
        return sum(
            1 for i in self.items
            if i.reconciliation_status not in (
                ReconciliationStatus.MATCHED,
                ReconciliationStatus.PENDING,
            )
        )

    @property
    def match_rate(self) -> float:
        if self.total_items == 0:
            return 0.0
        return round((self.matched_count / self.total_items) * 100, 2)
