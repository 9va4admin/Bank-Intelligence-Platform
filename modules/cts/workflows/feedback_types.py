"""Lightweight message types for the CTS OCR feedback loop.

Kept in a separate module with NO @workflow.defn or @activity.defn
decorators so they can be safely imported from inside workflow run()
methods (e.g. ChequeProcessingWorkflow) without triggering global
Temporal workflow registrations that would confuse test environments.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PayeeSignalMessage:
    instrument_id: str
    bank_id: str
    ocr_payee: str
    name_match_score: float
    script: Optional[str]
    workflow_decision: str
    human_approved: Optional[bool]
    image_path: str
    cbs_degraded: bool = False
    cbs_display_initial: Optional[str] = None


@dataclass
class MicrSignalMessage:
    instrument_id: str
    bank_id: str
    ngch_outcome: str
    micr_fields: dict = field(default_factory=dict)
    image_path: str = ""


@dataclass
class FeedbackAccumulatorInput:
    bank_id: str
    corpus_type: str = "payee"   # "payee" | "micr"
    event_count: int = 0         # for continue-as-new carry-over


@dataclass
class ModelRetrainInput:
    bank_id: str
    corpus_type: str


@dataclass
class FeedbackEmitInput:
    """Payload for FeedbackEmitWorkflow — one instance per processed cheque."""
    instrument_id: str
    bank_id: str
    ocr_payee: str
    name_match_score: float
    workflow_decision: str
    image_path: str
    account_suffix: str          # last 4 digits only — never full account number
    cbs_degraded: bool = False
    ngch_filed_ok: bool = False  # True only when file_to_ngch succeeded
    script: Optional[str] = None
    human_approved: Optional[bool] = None
    cbs_display_initial: Optional[str] = None
