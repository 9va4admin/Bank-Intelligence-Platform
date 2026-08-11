"""
CTS Outward Session Report — data model and MinIO path builder.

SessionReportData is assembled from cts.outward_scan_events + cts.clearing_sessions
by the GenerateSessionReportActivity. It is then passed to html_template.render_html()
and pdf_renderer.render_pdf() to produce the two stored artifacts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


@dataclass
class InstrumentRow:
    instrument_id:        str
    cheque_number:        str
    lot_number:           str
    payee_display:        str          # masked: first initial + *** only
    amount_range:         str          # bucketed: ₹[<1L] / ₹[1L-5L] etc.
    payee_status:         str          # PROCEED | NOT_FOUND | ACCOUNT_INACTIVE | NAME_MISMATCH
    compliance_result:    str          # PASS | FAIL
    compliance_violations: list[str]  # e.g. ['front_colour_depth', 'front_file_size_kb']
    outcome:              str          # ACCEPTED | CTS_REJECTED | MISMATCH_HELD
    scanned_at:           datetime


@dataclass
class SessionReportData:
    report_id:             str
    session_id:            str
    bank_id:               str
    branch_id:             str
    branch_ifsc:           str
    branch_name:           str
    clearing_date:         date
    session_type:          str          # MORNING | AFTERNOON | EVENING
    generated_at:          datetime
    instrument_count:      int
    lot_count:             int
    accepted_count:        int
    rejected_count:        int
    held_count:            int
    compliance_pass_count: int
    compliance_fail_count: int
    instruments:           list[InstrumentRow] = field(default_factory=list)
    npci_ack_ref:          Optional[str] = None


def minio_path(report: SessionReportData, fmt: str) -> str:
    """
    Canonical MinIO object path for a session report artifact.

    Pattern: cts/reports/{bank_id}/{branch_ifsc}/{yyyy}/{mm}/{session_id}/report.{fmt}
    Stored under WORM COMPLIANCE bucket — path is the permanent address.
    """
    yyyy = report.clearing_date.strftime("%Y")
    mm   = report.clearing_date.strftime("%m")
    return (
        f"cts/reports/{report.bank_id}/{report.branch_ifsc}"
        f"/{yyyy}/{mm}/{report.session_id}/report.{fmt}"
    )
