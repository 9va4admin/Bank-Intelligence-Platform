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


class _ExceptionMeta:
    __slots__ = ('code', 'label', 'severity')

    def __init__(self, code: str, label: str, severity: str):
        self.code = code
        self.label = label
        self.severity = severity


class ExceptionType(Enum):
    IQA_FAIL              = _ExceptionMeta('IQA_FAIL',              'Image Quality Failure',           'HIGH')
    IET_NEAR_BREACH       = _ExceptionMeta('IET_NEAR_BREACH',       'IET Near-Breach (< 30s margin)',  'CRITICAL')
    VAULT_MISS            = _ExceptionMeta('VAULT_MISS',            'Signature / PPS Vault Miss',      'HIGH')
    NGCH_REJECT           = _ExceptionMeta('NGCH_REJECT',           'NGCH Filing Rejected / Retried',  'CRITICAL')
    HUMAN_REVIEW          = _ExceptionMeta('HUMAN_REVIEW',          'Escalated to Human Review',       'MEDIUM')
    WORDS_FIGURES_MISMATCH = _ExceptionMeta('WORDS_FIGURES_MISMATCH', 'Words / Figures Amount Differ', 'HIGH')
    ALTERATION_DETECTED   = _ExceptionMeta('ALTERATION_DETECTED',   'Possible Alteration Detected',    'HIGH')
    OCR_LOW_CONFIDENCE    = _ExceptionMeta('OCR_LOW_CONFIDENCE',    'OCR Confidence Below Threshold',  'MEDIUM')
    SIGNATURE_LOW_CONF    = _ExceptionMeta('SIGNATURE_LOW_CONF',    'Signature Match Low Confidence',  'HIGH')
    FRAUD_HIGH_SCORE      = _ExceptionMeta('FRAUD_HIGH_SCORE',      'Fraud Score Above Threshold',     'HIGH')

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
