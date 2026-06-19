"""
CTS-2010 Compliance Certificate — data models.

An InstrumentComplianceRecord validates a single cheque image against CTS-2010 thresholds.
A BatchComplianceCertificate aggregates records for a full lot/batch before NGCH submission.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from modules.cts.compliance.cts2010 import CTS2010Standard


class ComplianceResult(str, Enum):
    PASS = 'PASS'
    FAIL = 'FAIL'


@dataclass
class InstrumentComplianceRecord:
    instrument_id:      str
    cheque_number:      str
    lot_number:         str

    # Front image metrics
    front_dpi:           int
    front_colour_depth:  int
    front_file_size_kb:  float
    front_iqa_score:     float

    # Rear image metrics
    rear_dpi:            int
    rear_colour_depth:   int
    rear_file_size_kb:   float
    rear_iqa_score:      float

    # MICR
    micr_band_score:     float

    def __post_init__(self) -> None:
        self._failure_reasons: list[str] = []
        self._evaluate()

    def _evaluate(self) -> None:
        s = CTS2010Standard
        if self.front_dpi < s.MIN_DPI:
            self._failure_reasons.append('front_dpi')
        if self.rear_dpi < s.MIN_DPI:
            self._failure_reasons.append('rear_dpi')
        if self.front_colour_depth < s.MIN_COLOUR_DEPTH:
            self._failure_reasons.append('front_colour_depth')
        if self.front_file_size_kb > s.MAX_FILE_SIZE_KB:
            self._failure_reasons.append('front_file_size_kb')
        if self.rear_file_size_kb > s.MAX_FILE_SIZE_KB:
            self._failure_reasons.append('rear_file_size_kb')
        if self.front_iqa_score < s.MIN_IQA_SCORE:
            self._failure_reasons.append('front_iqa_score')
        if self.rear_iqa_score < s.MIN_IQA_SCORE:
            self._failure_reasons.append('rear_iqa_score')
        if self.micr_band_score < s.MICR_BAND_MIN_SCORE:
            self._failure_reasons.append('micr_band_score')

    @property
    def failure_reasons(self) -> list[str]:
        return list(self._failure_reasons)

    @property
    def is_compliant(self) -> bool:
        return len(self._failure_reasons) == 0

    @property
    def result(self) -> ComplianceResult:
        return ComplianceResult.PASS if self.is_compliant else ComplianceResult.FAIL


@dataclass
class BatchComplianceCertificate:
    batch_id:    str
    session_id:  str
    bank_ifsc:   str
    issued_at:   datetime
    instruments: list[InstrumentComplianceRecord] = field(default_factory=list)

    @property
    def total_instruments(self) -> int:
        return len(self.instruments)

    @property
    def passed_count(self) -> int:
        return sum(1 for i in self.instruments if i.is_compliant)

    @property
    def failed_count(self) -> int:
        return self.total_instruments - self.passed_count

    @property
    def pass_rate(self) -> float:
        if self.total_instruments == 0:
            return 0.0
        return round((self.passed_count / self.total_instruments) * 100, 2)

    @property
    def overall_result(self) -> ComplianceResult:
        return ComplianceResult.PASS if self.failed_count == 0 else ComplianceResult.FAIL
