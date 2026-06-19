"""
Tests for CTS Automated Reconciliation Engine.
RED phase — all tests must fail before implementation.

Reconciliation compares NGCH-filed items against CBS posting confirmations
to detect mismatches, pending items, and settlement position per clearing session.
"""
import pytest
from datetime import datetime, timezone


# ── Models ──────────────────────────────────────────────────────────────────

def test_recon_status_enum_values():
    from modules.cts.reconciliation.models import ReconciliationStatus
    assert ReconciliationStatus.MATCHED
    assert ReconciliationStatus.NGCH_ONLY       # filed to NGCH, no CBS posting
    assert ReconciliationStatus.CBS_ONLY        # CBS posted, no NGCH record
    assert ReconciliationStatus.PENDING         # NGCH filed, CBS not yet posted
    assert ReconciliationStatus.AMOUNT_MISMATCH # amounts differ between NGCH and CBS


def test_recon_item_fields():
    from modules.cts.reconciliation.models import ReconciliationItem, ReconciliationStatus
    item = ReconciliationItem(
        instrument_id='CHQ-IN-00001',
        session_id='SES-0619-001',
        bank_id='SVCB',
        cheque_number='100001',
        account_suffix='4521',
        ngch_status='CONFIRMED',
        cbs_status='POSTED',
        ngch_amount_range='₹[1L-5L]',
        cbs_amount_range='₹[1L-5L]',
        reconciliation_status=ReconciliationStatus.MATCHED,
        occurred_at=datetime(2026, 6, 19, 10, 30, tzinfo=timezone.utc),
    )
    assert item.instrument_id == 'CHQ-IN-00001'
    assert item.account_suffix == '4521'
    assert item.reconciliation_status == ReconciliationStatus.MATCHED


def test_recon_item_account_suffix_max_four_chars():
    from modules.cts.reconciliation.models import ReconciliationItem, ReconciliationStatus
    with pytest.raises(ValueError, match='account_suffix'):
        ReconciliationItem(
            instrument_id='CHQ-IN-00001',
            session_id='SES-0619-001',
            bank_id='SVCB',
            cheque_number='100001',
            account_suffix='12345',      # 5 chars — invalid
            ngch_status='CONFIRMED',
            cbs_status='POSTED',
            ngch_amount_range='₹[1L-5L]',
            cbs_amount_range='₹[1L-5L]',
            reconciliation_status=ReconciliationStatus.MATCHED,
            occurred_at=datetime(2026, 6, 19, 10, 30, tzinfo=timezone.utc),
        )


def test_session_recon_report_fields():
    from modules.cts.reconciliation.models import SessionReconciliationReport
    report = SessionReconciliationReport(
        session_id='SES-0619-001',
        bank_id='SVCB',
        bank_ifsc='SVCB0000001',
        session_date=datetime(2026, 6, 19, tzinfo=timezone.utc),
        items=[],
    )
    assert report.session_id == 'SES-0619-001'
    assert report.total_items == 0
    assert report.matched_count == 0
    assert report.unmatched_count == 0
    assert report.pending_count == 0


def test_session_recon_report_totals():
    from modules.cts.reconciliation.models import (
        SessionReconciliationReport, ReconciliationItem, ReconciliationStatus
    )
    ts = datetime(2026, 6, 19, 10, 30, tzinfo=timezone.utc)
    def make(iid, status):
        return ReconciliationItem(
            instrument_id=iid, session_id='SES-0619-001', bank_id='SVCB',
            cheque_number='100001', account_suffix='4521',
            ngch_status='CONFIRMED', cbs_status='POSTED',
            ngch_amount_range='₹[<1L]', cbs_amount_range='₹[<1L]',
            reconciliation_status=status, occurred_at=ts,
        )

    items = [
        make('CHQ-001', ReconciliationStatus.MATCHED),
        make('CHQ-002', ReconciliationStatus.MATCHED),
        make('CHQ-003', ReconciliationStatus.PENDING),
        make('CHQ-004', ReconciliationStatus.NGCH_ONLY),
        make('CHQ-005', ReconciliationStatus.AMOUNT_MISMATCH),
    ]
    report = SessionReconciliationReport(
        session_id='SES-0619-001', bank_id='SVCB', bank_ifsc='SVCB0000001',
        session_date=datetime(2026, 6, 19, tzinfo=timezone.utc), items=items,
    )
    assert report.total_items == 5
    assert report.matched_count == 2
    assert report.pending_count == 1
    assert report.unmatched_count == 2   # NGCH_ONLY + AMOUNT_MISMATCH
    assert report.match_rate == pytest.approx(40.0)


def test_report_match_rate_zero_items():
    from modules.cts.reconciliation.models import SessionReconciliationReport
    report = SessionReconciliationReport(
        session_id='SES-0619-001', bank_id='SVCB', bank_ifsc='SVCB0000001',
        session_date=datetime(2026, 6, 19, tzinfo=timezone.utc), items=[],
    )
    assert report.match_rate == 0.0


# ── Engine ──────────────────────────────────────────────────────────────────

def test_engine_reconcile_all_matched():
    from modules.cts.reconciliation.engine import ReconciliationEngine
    from modules.cts.reconciliation.models import ReconciliationStatus

    ngch_items = [
        {'instrument_id': 'CHQ-001', 'status': 'CONFIRMED', 'amount_range': '₹[<1L]'},
        {'instrument_id': 'CHQ-002', 'status': 'CONFIRMED', 'amount_range': '₹[1L-5L]'},
    ]
    cbs_items = [
        {'instrument_id': 'CHQ-001', 'status': 'POSTED',   'amount_range': '₹[<1L]'},
        {'instrument_id': 'CHQ-002', 'status': 'POSTED',   'amount_range': '₹[1L-5L]'},
    ]
    engine = ReconciliationEngine()
    report = engine.reconcile(
        session_id='SES-0619-001',
        bank_id='SVCB',
        bank_ifsc='SVCB0000001',
        session_date=datetime(2026, 6, 19, tzinfo=timezone.utc),
        ngch_items=ngch_items,
        cbs_items=cbs_items,
    )
    assert report.matched_count == 2
    assert report.unmatched_count == 0


def test_engine_reconcile_ngch_only():
    from modules.cts.reconciliation.engine import ReconciliationEngine
    from modules.cts.reconciliation.models import ReconciliationStatus

    ngch_items = [{'instrument_id': 'CHQ-001', 'status': 'CONFIRMED', 'amount_range': '₹[<1L]'}]
    cbs_items  = []
    engine = ReconciliationEngine()
    report = engine.reconcile(
        session_id='SES-0619-001', bank_id='SVCB', bank_ifsc='SVCB0000001',
        session_date=datetime(2026, 6, 19, tzinfo=timezone.utc),
        ngch_items=ngch_items, cbs_items=cbs_items,
    )
    assert report.unmatched_count == 1
    assert report.items[0].reconciliation_status == ReconciliationStatus.NGCH_ONLY


def test_engine_reconcile_cbs_only():
    from modules.cts.reconciliation.engine import ReconciliationEngine
    from modules.cts.reconciliation.models import ReconciliationStatus

    ngch_items = []
    cbs_items  = [{'instrument_id': 'CHQ-001', 'status': 'POSTED', 'amount_range': '₹[<1L]'}]
    engine = ReconciliationEngine()
    report = engine.reconcile(
        session_id='SES-0619-001', bank_id='SVCB', bank_ifsc='SVCB0000001',
        session_date=datetime(2026, 6, 19, tzinfo=timezone.utc),
        ngch_items=ngch_items, cbs_items=cbs_items,
    )
    assert report.unmatched_count == 1
    assert report.items[0].reconciliation_status == ReconciliationStatus.CBS_ONLY


def test_engine_reconcile_amount_mismatch():
    from modules.cts.reconciliation.engine import ReconciliationEngine
    from modules.cts.reconciliation.models import ReconciliationStatus

    ngch_items = [{'instrument_id': 'CHQ-001', 'status': 'CONFIRMED', 'amount_range': '₹[<1L]'}]
    cbs_items  = [{'instrument_id': 'CHQ-001', 'status': 'POSTED',    'amount_range': '₹[1L-5L]'}]
    engine = ReconciliationEngine()
    report = engine.reconcile(
        session_id='SES-0619-001', bank_id='SVCB', bank_ifsc='SVCB0000001',
        session_date=datetime(2026, 6, 19, tzinfo=timezone.utc),
        ngch_items=ngch_items, cbs_items=cbs_items,
    )
    assert report.unmatched_count == 1
    assert report.items[0].reconciliation_status == ReconciliationStatus.AMOUNT_MISMATCH


def test_engine_reconcile_ngch_filed_cbs_pending():
    from modules.cts.reconciliation.engine import ReconciliationEngine
    from modules.cts.reconciliation.models import ReconciliationStatus

    ngch_items = [{'instrument_id': 'CHQ-001', 'status': 'FILED', 'amount_range': '₹[<1L]'}]
    cbs_items  = [{'instrument_id': 'CHQ-001', 'status': 'PENDING', 'amount_range': '₹[<1L]'}]
    engine = ReconciliationEngine()
    report = engine.reconcile(
        session_id='SES-0619-001', bank_id='SVCB', bank_ifsc='SVCB0000001',
        session_date=datetime(2026, 6, 19, tzinfo=timezone.utc),
        ngch_items=ngch_items, cbs_items=cbs_items,
    )
    assert report.pending_count == 1
    assert report.items[0].reconciliation_status == ReconciliationStatus.PENDING


# ── CSV Export ──────────────────────────────────────────────────────────────

def test_reconciliation_csv_export():
    from modules.cts.reconciliation.engine import ReconciliationEngine
    from modules.cts.reconciliation.exporter import ReconciliationExporter

    engine = ReconciliationEngine()
    report = engine.reconcile(
        session_id='SES-0619-001', bank_id='SVCB', bank_ifsc='SVCB0000001',
        session_date=datetime(2026, 6, 19, tzinfo=timezone.utc),
        ngch_items=[{'instrument_id': 'CHQ-001', 'status': 'CONFIRMED', 'amount_range': '₹[<1L]'}],
        cbs_items=[{'instrument_id': 'CHQ-001', 'status': 'POSTED', 'amount_range': '₹[<1L]'}],
    )
    csv_str = ReconciliationExporter.to_csv(report)
    assert 'InstrumentID' in csv_str
    assert 'CHQ-001' in csv_str
    assert 'MATCHED' in csv_str


def test_reconciliation_csv_filename():
    from modules.cts.reconciliation.models import SessionReconciliationReport
    from modules.cts.reconciliation.exporter import ReconciliationExporter

    report = SessionReconciliationReport(
        session_id='SES-0619-001', bank_id='SVCB', bank_ifsc='SVCB0000001',
        session_date=datetime(2026, 6, 19, tzinfo=timezone.utc), items=[],
    )
    fname = ReconciliationExporter.filename(report)
    assert fname == 'RECON_SVCB0000001_20260619_SES-0619-001.csv'
