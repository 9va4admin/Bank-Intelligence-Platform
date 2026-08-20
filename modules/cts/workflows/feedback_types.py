"""Lightweight message types for the CTS OCR feedback loop.

Kept in a separate module with NO @workflow.defn or @activity.defn
decorators so they can be safely imported from inside workflow run()
methods (e.g. ChequeProcessingWorkflow) without triggering global
Temporal workflow registrations that would confuse test environments.

All types use Pydantic BaseModel so pydantic_data_converter can
deserialize them correctly when used as Temporal workflow inputs.
"""
from __future__ import annotations

from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict


class PayeeSignalMessage(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    bank_id: str
    ocr_payee: str
    name_match_score: float
    script: Optional[str] = None
    workflow_decision: str
    human_approved: Optional[bool] = None
    image_path: str
    cbs_degraded: bool = False
    cbs_display_initial: Optional[str] = None


class MicrSignalMessage(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    bank_id: str
    ngch_outcome: str
    micr_fields: Dict[str, Any] = {}
    image_path: str = ""


class FeedbackAccumulatorInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    corpus_type: str = "payee"   # "payee" | "micr"
    event_count: int = 0         # for continue-as-new carry-over


class ModelRetrainInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    corpus_type: str


class FeedbackEmitInput(BaseModel):
    """Payload for FeedbackEmitWorkflow — one instance per processed cheque."""
    model_config = ConfigDict(frozen=True)
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
