from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from typing import Optional


class PrincipalTag(Enum):
    DIRECT = "DIRECT"          # Bank is a direct NGCH member
    SUB_MEMBER = "SUB_MEMBER"  # Routes clearing via sponsor bank


class ClearingBucket(Enum):
    STP_PASS = "STP_PASS"            # Auto-confirmed, filed to NGCH
    STP_RETURN = "STP_RETURN"        # Auto-returned, defect detected
    EYEBALL = "EYEBALL"              # Queued for human review
    FRAUD_HOLD = "FRAUD_HOLD"        # Fraud score above threshold
    IET_EMERGENCY = "IET_EMERGENCY"  # IET watchdog fired emergency filing


@dataclass(frozen=True)
class SubMemberBank:
    sub_member_id: str
    bank_name: str
    sponsor_bank_id: str       # Direct NGCH member acting as sponsor
    micr_prefix: str           # 3–6 digit MICR routing prefix
    ifsc_prefix: str
    branch_manager_email: str  # Tier 1 + Tier 2 notification recipient
    ops_head_email: str        # Tier 2 CC
    gm_email: str              # Tier 3 escalation
    return_rate_threshold: float   # Warn above this (e.g. 0.15 = 15%)
    soft_hold_threshold: float     # Activate soft-hold above this (e.g. 0.25 = 25%)


@dataclass
class SubMemberBatchLedger:
    sub_member_id: str
    session_date: str           # YYYY-MM-DD
    clearing_session: str       # MORNING | AFTERNOON | SPECIAL

    total_received: int = 0
    stp_pass: int = 0
    stp_return: int = 0
    eyeball: int = 0
    fraud_hold: int = 0
    iet_emergency: int = 0
    soft_hold_active: bool = False

    @property
    def total_returns(self) -> int:
        return self.stp_return

    @property
    def return_rate(self) -> float:
        if self.total_received == 0:
            return 0.0
        return self.stp_return / self.total_received

    @property
    def stp_rate(self) -> float:
        if self.total_received == 0:
            return 0.0
        return self.stp_pass / self.total_received


@dataclass
class SubMemberReturn:
    instrument_id: str
    sub_member_id: str
    return_reason: str
    bucket: ClearingBucket
    amount_range: str          # Bucketed range: ₹[1L-5L], never exact amount
    cheque_number_suffix: str  # Last 4 digits only — PII rule
    returned_at: datetime

    def __post_init__(self):
        if len(self.cheque_number_suffix) > 4:
            raise ValueError(
                f"cheque_number_suffix must be ≤ 4 characters (PII rule): "
                f"got {len(self.cheque_number_suffix)} chars"
            )
