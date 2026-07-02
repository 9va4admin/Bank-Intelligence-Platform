"""
Demo pipeline data models.

All state for a demo session is stored in memory (DemoSession).
No database or Kafka required — demo mode is self-contained.
"""
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class PresentmentStep(str, Enum):
    FILE_DETECTED   = "file_detected"
    IMAGE_LOAD      = "image_load"
    OCR_MICR        = "ocr_micr"
    CTS_COMPLIANCE  = "cts_compliance"
    VISION_LLM      = "vision_llm"
    DATA_EXTRACTION = "data_extraction"
    LOT_ASSIGNMENT  = "lot_assignment"
    DECISION        = "decision"


class DraweeStep(str, Enum):
    FILE_RECEIPT   = "file_receipt"
    OCR_REEXTRACT  = "ocr_reextract"
    RBI_CHECKLIST  = "rbi_checklist"
    SIGNATURE_VAULT = "signature_vault"
    ACCOUNT_STATUS = "account_status"
    STOP_PAYMENT   = "stop_payment"
    PPS_CHECK      = "pps_check"
    FRAUD_SCORE    = "fraud_score"
    VISION_LLM     = "vision_llm"
    DECISION       = "decision"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED  = "passed"
    FAILED  = "failed"
    SKIPPED = "skipped"


class StepResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    step:        str
    status:      StepStatus
    duration_ms: int = 0
    detail:      Optional[str] = None
    data:        Optional[Dict[str, Any]] = None


class ItemStatus(str, Enum):
    QUEUED     = "queued"
    PROCESSING = "processing"
    SUCCESS    = "success"
    FAILED     = "failed"


class DemoItem(BaseModel):
    model_config = ConfigDict(frozen=False)

    item_id:      str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    filename:     str
    status:       ItemStatus = ItemStatus.QUEUED
    steps:        List[StepResult] = Field(default_factory=list)
    decision:     Optional[str] = None
    reject_reason: Optional[str] = None
    extracted:    Optional[Dict[str, Any]] = None
    drawee_bank:  Optional[str] = None
    total_ms:     int = 0
    started_at:   Optional[float] = None
    completed_at: Optional[float] = None


class SessionPhase(str, Enum):
    IDLE             = "idle"
    PRESENTMENT      = "presentment"
    NPCI_SIMULATION  = "npci_simulation"
    DRAWEE           = "drawee"
    COMPLETE         = "complete"


class DemoSession(BaseModel):
    model_config = ConfigDict(frozen=False)

    session_id:   str = Field(default_factory=lambda: str(uuid.uuid4()))
    bank_id:      str = "demo-bank"
    phase:        SessionPhase = SessionPhase.IDLE
    items:        List[DemoItem] = Field(default_factory=list)
    drawee_items: List[DemoItem] = Field(default_factory=list)
    npci_output:  Optional[Dict[str, List[str]]] = None  # bank_name → [item_ids]
    created_at:   float = Field(default_factory=time.time)
