"""
Tests for CTS Discrepancy / Exception Report.
RED phase — all tests must fail before implementation.

Report covers per-session exceptions:
  - IQA failures (image quality)
  - IET near-breach (< 30s margin)
  - Vault misses (signature / PPS)
  - NGCH rejections / retries
  - Human review escalations
  - Words/figures mismatch
"""
import pytest
from datetime import datetime, timezone


# ── Exception item models ──────────────────────────────────────────────────

def test_exception_item_requires_minimum_fields():
    from modules.cts.reports.models import ExceptionItem, ExceptionType
    item = ExceptionItem(
        instrument_id='CHQ-2026-001847',
        exception_type=ExceptionType.IQA_FAIL,
        session_id='SES-0619-001',
        bank_id='saraswat-mah',
        occurred_at=datetime(2026, 6, 19, 10, 15, 0, tzinfo=timezone.utc),
        detail='Image JPEG quality below 200 DPI threshold',
        resolved=False,
    )
    assert item.instrument_id == 'CHQ-2026-001847'
    assert item.exception_type.code == 'IQA_FAIL'
    assert item.resolved is False


def test_exception_type_enum_has_required_types():
    from modules.cts.reports.models import ExceptionType
    assert ExceptionType.IQA_FAIL.code == 'IQA_FAIL'
    assert ExceptionType.IET_NEAR_BREACH.code == 'IET_NEAR_BREACH'
    assert ExceptionType.VAULT_MISS.code == 'VAULT_MISS'
    assert ExceptionType.NGCH_REJECT.code == 'NGCH_REJECT'
    assert ExceptionType.HUMAN_REVIEW.code == 'HUMAN_REVIEW'
    assert ExceptionType.WORDS_FIGURES_MISMATCH.code == 'WORDS_FIGURES_MISMATCH'


def test_exception_type_has_label_and_severity():
    from modules.cts.reports.models import ExceptionType
    assert ExceptionType.IET_NEAR_BREACH.severity == 'CRITICAL'
    assert ExceptionType.IQA_FAIL.severity == 'HIGH'
    assert ExceptionType.HUMAN_REVIEW.severity == 'MEDIUM'


def test_exception_item_iet_near_breach_stores_margin():
    from modules.cts.reports.models import ExceptionItem, ExceptionType
    item = ExceptionItem(
        instrument_id='CHQ-2026-001999',
        exception_type=ExceptionType.IET_NEAR_BREACH,
        session_id='SES-0619-001',
        bank_id='saraswat-mah',
        occurred_at=datetime(2026, 6, 19, 13, 29, 35, tzinfo=timezone.utc),
        detail='Filed with 25s to IET deadline',
        resolved=True,
        margin_seconds=25,
    )
    assert item.margin_seconds == 25


# ── DiscrepancyReport model ────────────────────────────────────────────────

def test_discrepancy_report_totals():
    from modules.cts.reports.models import DiscrepancyReport, ExceptionItem, ExceptionType
    items = [
        ExceptionItem(
            instrument_id=f'CHQ-2026-00{i:04d}',
            exception_type=ExceptionType.IQA_FAIL,
            session_id='SES-0619-001',
            bank_id='saraswat-mah',
            occurred_at=datetime(2026, 6, 19, 10, i, tzinfo=timezone.utc),
            detail='IQA fail',
            resolved=(i % 2 == 0),
        )
        for i in range(4)
    ]
    report = DiscrepancyReport(
        session_id='SES-0619-001',
        bank_id='saraswat-mah',
        bank_ifsc='SVCB0000001',
        clearing_date=datetime(2026, 6, 19, tzinfo=timezone.utc),
        generated_at=datetime(2026, 6, 19, 14, 30, tzinfo=timezone.utc),
        total_instruments_processed=45,
        exceptions=items,
    )
    assert report.total_exceptions == 4
    assert report.unresolved_count == 2
    assert report.has_critical is False


def test_discrepancy_report_detects_critical():
    from modules.cts.reports.models import DiscrepancyReport, ExceptionItem, ExceptionType
    items = [
        ExceptionItem(
            instrument_id='CHQ-2026-001999',
            exception_type=ExceptionType.IET_NEAR_BREACH,
            session_id='SES-0619-001',
            bank_id='saraswat-mah',
            occurred_at=datetime(2026, 6, 19, 13, 29, tzinfo=timezone.utc),
            detail='Filed with 25s to IET',
            resolved=True,
            margin_seconds=25,
        )
    ]
    report = DiscrepancyReport(
        session_id='SES-0619-001',
        bank_id='saraswat-mah',
        bank_ifsc='SVCB0000001',
        clearing_date=datetime(2026, 6, 19, tzinfo=timezone.utc),
        generated_at=datetime(2026, 6, 19, 14, 30, tzinfo=timezone.utc),
        total_instruments_processed=45,
        exceptions=items,
    )
    assert report.has_critical is True


def test_discrepancy_report_counts_by_type():
    from modules.cts.reports.models import DiscrepancyReport, ExceptionItem, ExceptionType
    items = [
        ExceptionItem(
            instrument_id=f'CHQ-IQA-{i:03d}',
            exception_type=ExceptionType.IQA_FAIL,
            session_id='SES-0619-001',
            bank_id='saraswat-mah',
            occurred_at=datetime(2026, 6, 19, 10, i, tzinfo=timezone.utc),
            detail='IQA',
            resolved=False,
        )
        for i in range(3)
    ] + [
        ExceptionItem(
            instrument_id='CHQ-VAULT-001',
            exception_type=ExceptionType.VAULT_MISS,
            session_id='SES-0619-001',
            bank_id='saraswat-mah',
            occurred_at=datetime(2026, 6, 19, 11, 0, tzinfo=timezone.utc),
            detail='Signature vault miss',
            resolved=False,
        )
    ]
    report = DiscrepancyReport(
        session_id='SES-0619-001',
        bank_id='saraswat-mah',
        bank_ifsc='SVCB0000001',
        clearing_date=datetime(2026, 6, 19, tzinfo=timezone.utc),
        generated_at=datetime(2026, 6, 19, 14, 30, tzinfo=timezone.utc),
        total_instruments_processed=50,
        exceptions=items,
    )
    by_type = report.counts_by_type()
    assert by_type['IQA_FAIL'] == 3
    assert by_type['VAULT_MISS'] == 1
    assert by_type.get('NGCH_REJECT', 0) == 0


# ── CSV export ─────────────────────────────────────────────────────────────

def test_csv_export_produces_string():
    from modules.cts.reports.models import DiscrepancyReport, ExceptionItem, ExceptionType
    from modules.cts.reports.exporter import DiscrepancyExporter
    items = [
        ExceptionItem(
            instrument_id='CHQ-2026-001847',
            exception_type=ExceptionType.IQA_FAIL,
            session_id='SES-0619-001',
            bank_id='saraswat-mah',
            occurred_at=datetime(2026, 6, 19, 10, 15, tzinfo=timezone.utc),
            detail='DPI below threshold',
            resolved=False,
        )
    ]
    report = DiscrepancyReport(
        session_id='SES-0619-001',
        bank_id='saraswat-mah',
        bank_ifsc='SVCB0000001',
        clearing_date=datetime(2026, 6, 19, tzinfo=timezone.utc),
        generated_at=datetime(2026, 6, 19, 14, 30, tzinfo=timezone.utc),
        total_instruments_processed=45,
        exceptions=items,
    )
    csv_str = DiscrepancyExporter.to_csv(report)
    assert isinstance(csv_str, str)
    assert 'CHQ-2026-001847' in csv_str


def test_csv_export_has_header_row():
    from modules.cts.reports.models import DiscrepancyReport, ExceptionItem, ExceptionType
    from modules.cts.reports.exporter import DiscrepancyExporter
    report = DiscrepancyReport(
        session_id='SES-0619-001',
        bank_id='saraswat-mah',
        bank_ifsc='SVCB0000001',
        clearing_date=datetime(2026, 6, 19, tzinfo=timezone.utc),
        generated_at=datetime(2026, 6, 19, 14, 30, tzinfo=timezone.utc),
        total_instruments_processed=0,
        exceptions=[],
    )
    csv_str = DiscrepancyExporter.to_csv(report)
    assert 'InstrumentID' in csv_str
    assert 'ExceptionType' in csv_str
    assert 'Severity' in csv_str
    assert 'Resolved' in csv_str


def test_csv_export_includes_summary_block():
    from modules.cts.reports.models import DiscrepancyReport, ExceptionItem, ExceptionType
    from modules.cts.reports.exporter import DiscrepancyExporter
    report = DiscrepancyReport(
        session_id='SES-0619-001',
        bank_id='saraswat-mah',
        bank_ifsc='SVCB0000001',
        clearing_date=datetime(2026, 6, 19, tzinfo=timezone.utc),
        generated_at=datetime(2026, 6, 19, 14, 30, tzinfo=timezone.utc),
        total_instruments_processed=45,
        exceptions=[],
    )
    csv_str = DiscrepancyExporter.to_csv(report)
    assert 'SES-0619-001' in csv_str
    assert 'SVCB0000001' in csv_str


# ── Filename convention ────────────────────────────────────────────────────

def test_exporter_filename_convention():
    from modules.cts.reports.models import DiscrepancyReport
    from modules.cts.reports.exporter import DiscrepancyExporter
    report = DiscrepancyReport(
        session_id='SES-0619-001',
        bank_id='saraswat-mah',
        bank_ifsc='SVCB0000001',
        clearing_date=datetime(2026, 6, 19, tzinfo=timezone.utc),
        generated_at=datetime(2026, 6, 19, 14, 30, tzinfo=timezone.utc),
        total_instruments_processed=45,
        exceptions=[],
    )
    fname = DiscrepancyExporter.filename(report)
    assert fname.startswith('DISC_')
    assert 'SVCB0000001' in fname
    assert '20260619' in fname
    assert fname.endswith('.csv')
