"""
Tests for CTS outward session report — builder, HTML template, PDF renderer.
RED phase: all must fail before implementation exists.
"""
import pytest
from datetime import date, datetime, timezone
from dataclasses import dataclass
from typing import Optional


# ── Shared fixture data ───────────────────────────────────────────────────────

@pytest.fixture
def sample_session():
    from modules.cts.reports.session_report_builder import SessionReportData, InstrumentRow
    return SessionReportData(
        report_id="RPT-001",
        session_id="SES-2026-0811-001",
        bank_id="federal-bank",
        branch_id="BR-FED-0001",
        branch_ifsc="FDRL0001234",
        branch_name="Federal Bank - MG Road Branch",
        clearing_date=date(2026, 8, 11),
        session_type="MORNING",
        generated_at=datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc),
        instrument_count=4,
        lot_count=1,
        accepted_count=2,
        rejected_count=1,
        held_count=1,
        compliance_pass_count=3,
        compliance_fail_count=1,
        instruments=[
            InstrumentRow(
                instrument_id="CHQ-OUT-00001",
                cheque_number="100001",
                lot_number="LOT-001",
                payee_display="R***",
                amount_range="₹[<1L]",
                payee_status="PROCEED",
                compliance_result="PASS",
                compliance_violations=[],
                outcome="ACCEPTED",
                scanned_at=datetime(2026, 8, 11, 9, 10, 0, tzinfo=timezone.utc),
            ),
            InstrumentRow(
                instrument_id="CHQ-OUT-00002",
                cheque_number="100002",
                lot_number="LOT-001",
                payee_display="S***",
                amount_range="₹[1L-5L]",
                payee_status="ACCOUNT_INACTIVE",
                compliance_result="PASS",
                compliance_violations=[],
                outcome="MISMATCH_HELD",
                scanned_at=datetime(2026, 8, 11, 9, 15, 0, tzinfo=timezone.utc),
            ),
            InstrumentRow(
                instrument_id="CHQ-OUT-00003",
                cheque_number="100003",
                lot_number="LOT-001",
                payee_display="P***",
                amount_range="₹[<1L]",
                payee_status="PROCEED",
                compliance_result="FAIL",
                compliance_violations=["front_colour_depth", "front_file_size_kb"],
                outcome="CTS_REJECTED",
                scanned_at=datetime(2026, 8, 11, 9, 20, 0, tzinfo=timezone.utc),
            ),
            InstrumentRow(
                instrument_id="CHQ-OUT-00004",
                cheque_number="100004",
                lot_number="LOT-001",
                payee_display="N***",
                amount_range="₹[<1L]",
                payee_status="PROCEED",
                compliance_result="PASS",
                compliance_violations=[],
                outcome="ACCEPTED",
                scanned_at=datetime(2026, 8, 11, 9, 25, 0, tzinfo=timezone.utc),
            ),
        ],
    )


# ── SessionReportData model ───────────────────────────────────────────────────

def test_session_report_data_exists():
    from modules.cts.reports.session_report_builder import SessionReportData
    assert SessionReportData is not None


def test_instrument_row_exists():
    from modules.cts.reports.session_report_builder import InstrumentRow
    assert InstrumentRow is not None


def test_session_report_data_fields(sample_session):
    assert sample_session.session_id == "SES-2026-0811-001"
    assert sample_session.bank_id == "federal-bank"
    assert sample_session.branch_ifsc == "FDRL0001234"
    assert sample_session.instrument_count == 4
    assert sample_session.accepted_count == 2
    assert sample_session.rejected_count == 1
    assert sample_session.held_count == 1


def test_instrument_row_fields(sample_session):
    row = sample_session.instruments[0]
    assert row.instrument_id == "CHQ-OUT-00001"
    assert row.payee_status == "PROCEED"
    assert row.compliance_result == "PASS"
    assert row.outcome == "ACCEPTED"


# ── HTML template ─────────────────────────────────────────────────────────────

def test_html_template_returns_string(sample_session):
    from modules.cts.reports.html_template import render_html
    html = render_html(sample_session)
    assert isinstance(html, str)
    assert len(html) > 500


def test_html_contains_session_id(sample_session):
    from modules.cts.reports.html_template import render_html
    html = render_html(sample_session)
    assert "SES-2026-0811-001" in html


def test_html_contains_branch_ifsc(sample_session):
    from modules.cts.reports.html_template import render_html
    html = render_html(sample_session)
    assert "FDRL0001234" in html


def test_html_contains_all_instrument_ids(sample_session):
    from modules.cts.reports.html_template import render_html
    html = render_html(sample_session)
    for row in sample_session.instruments:
        assert row.instrument_id in html


def test_html_shows_summary_counts(sample_session):
    from modules.cts.reports.html_template import render_html
    html = render_html(sample_session)
    assert "ACCEPTED" in html
    assert "CTS_REJECTED" in html or "REJECTED" in html
    assert "MISMATCH_HELD" in html or "HELD" in html


def test_html_compliance_violations_shown(sample_session):
    from modules.cts.reports.html_template import render_html
    html = render_html(sample_session)
    assert "front_colour_depth" in html


def test_html_no_raw_pii(sample_session):
    from modules.cts.reports.html_template import render_html
    html = render_html(sample_session)
    # Payee display must be masked (e.g. R***) — full names must not appear
    assert "account_number" not in html.lower()
    # Amounts must be ranges, not exact values
    assert "₹[<1L]" in html or "1L" in html


def test_html_is_valid_structure(sample_session):
    from modules.cts.reports.html_template import render_html
    html = render_html(sample_session)
    assert "<!DOCTYPE html>" in html or "<!doctype html>" in html.lower()
    assert "<html" in html
    assert "</html>" in html
    assert "<table" in html   # instruments must be in a table


# ── PDF renderer ──────────────────────────────────────────────────────────────

def test_pdf_renderer_returns_bytes(sample_session):
    from modules.cts.reports.html_template import render_html
    from modules.cts.reports.pdf_renderer import render_pdf
    html = render_html(sample_session)
    pdf_bytes = render_pdf(html)
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 1000


def test_pdf_starts_with_pdf_magic(sample_session):
    from modules.cts.reports.html_template import render_html
    from modules.cts.reports.pdf_renderer import render_pdf
    html = render_html(sample_session)
    pdf_bytes = render_pdf(html)
    assert pdf_bytes[:4] == b"%PDF"


# ── MinIO path builder ────────────────────────────────────────────────────────

def test_minio_path_html(sample_session):
    from modules.cts.reports.session_report_builder import minio_path
    path = minio_path(sample_session, "html")
    assert "federal-bank" in path
    assert "FDRL0001234" in path
    assert "SES-2026-0811-001" in path
    assert path.endswith("report.html")


def test_minio_path_pdf(sample_session):
    from modules.cts.reports.session_report_builder import minio_path
    path = minio_path(sample_session, "pdf")
    assert path.endswith("report.pdf")


def test_minio_path_includes_year_month(sample_session):
    from modules.cts.reports.session_report_builder import minio_path
    path = minio_path(sample_session, "html")
    assert "2026" in path
    assert "08" in path
