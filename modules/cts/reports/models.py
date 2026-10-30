"""
CTS Discrepancy / Exception Report domain models.
Covers per-session exceptions: IQA failures, IET near-breaches, vault misses,
NGCH rejections, human review escalations, words/figures mismatches.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from shared.messages import get_message


class _ExceptionMeta:
    __slots__ = ('code', 'label', 'severity')

    def __init__(self, code: str, label: str, severity: str):
        self.code = code
        self.label = label
        self.severity = severity


class ExceptionType(Enum):
    IQA_FAIL              = _ExceptionMeta('IQA_FAIL',              get_message("UI_EXCEPTIONS_IMAGE_QUALITY_FAILURE"),           'HIGH')
    IET_NEAR_BREACH       = _ExceptionMeta('IET_NEAR_BREACH',       get_message("UI_EXCEPTIONS_IET_NEAR_BREACH_30S_MARGIN"),  'CRITICAL')
    VAULT_MISS            = _ExceptionMeta('VAULT_MISS',            get_message("UI_EXCEPTIONS_SIGNATURE_PPS_VAULT_MISS"),      'HIGH')
    NGCH_REJECT           = _ExceptionMeta('NGCH_REJECT',           get_message("UI_EXCEPTIONS_NGCH_FILING_REJECTED_RETRIED"),  'CRITICAL')
    HUMAN_REVIEW          = _ExceptionMeta('HUMAN_REVIEW',          get_message("UI_EXCEPTIONS_ESCALATED_TO_HUMAN_REVIEW"),       'MEDIUM')
    WORDS_FIGURES_MISMATCH = _ExceptionMeta('WORDS_FIGURES_MISMATCH', get_message("UI_EXCEPTIONS_WORDS_FIGURES_AMOUNT_DIFFER"), 'HIGH')
    ALTERATION_DETECTED   = _ExceptionMeta('ALTERATION_DETECTED',   get_message("UI_EXCEPTIONS_POSSIBLE_ALTERATION_DETECTED"),    'HIGH')
    OCR_LOW_CONFIDENCE    = _ExceptionMeta('OCR_LOW_CONFIDENCE',    get_message("UI_EXCEPTIONS_OCR_CONFIDENCE_BELOW_THRESHOLD"),  'MEDIUM')
    SIGNATURE_LOW_CONF    = _ExceptionMeta('SIGNATURE_LOW_CONF',    get_message("UI_EXCEPTIONS_SIGNATURE_MATCH_LOW_CONFIDENCE"),  'HIGH')
    FRAUD_HIGH_SCORE      = _ExceptionMeta('FRAUD_HIGH_SCORE',      get_message("UI_EXCEPTIONS_FRAUD_SCORE_ABOVE_THRESHOLD"),     'HIGH')

    @property
    def code(self) -> str:
        return self.value.code

    @property
    def label(self) -> str:
        return self.value.label

    @property
    def severity(self) -> str:
        return self.value.severity


@dataclass
class ExceptionItem:
    instrument_id: str
    exception_type: ExceptionType
    session_id: str
    bank_id: str
    occurred_at: datetime
    detail: str
    resolved: bool
    margin_seconds: Optional[int] = None  # for IET_NEAR_BREACH


@dataclass
class DiscrepancyReport:
    session_id: str
    bank_id: str
    bank_ifsc: str
    clearing_date: datetime
    generated_at: datetime
    total_instruments_processed: int
    exceptions: list[ExceptionItem] = field(default_factory=list)

    @property
    def total_exceptions(self) -> int:
        return len(self.exceptions)

    @property
    def unresolved_count(self) -> int:
        return sum(1 for e in self.exceptions if not e.resolved)

    @property
    def has_critical(self) -> bool:
        return any(e.exception_type.severity == 'CRITICAL' for e in self.exceptions)

    def counts_by_type(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for item in self.exceptions:
            key = item.exception_type.code
            result[key] = result.get(key, 0) + 1
        return result
