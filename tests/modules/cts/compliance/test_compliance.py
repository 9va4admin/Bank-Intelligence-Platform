"""
Tests for CTS-2010 Compliance Certificate Generator.
RED phase — all tests must fail before implementation.

CTS-2010 (RBI standard) mandates specific image quality thresholds for cheque images
presented through the Cheque Truncation System. A compliance certificate is generated
per batch/lot attesting that all instruments met or exceeded these standards.
"""
import pytest
from datetime import datetime, timezone


# ── CTS-2010 Standard Thresholds (immutable — defined by RBI) ────────────────

def test_cts2010_standard_constants():
    from modules.cts.compliance.cts2010 import CTS2010Standard
    assert CTS2010Standard.MIN_DPI              == 200
    assert CTS2010Standard.MIN_COLOUR_DEPTH     == 24      # bits (RGB)
    assert CTS2010Standard.GRAYSCALE_DEPTH      == 8       # bits
    assert CTS2010Standard.MAX_FILE_SIZE_KB     == 50      # per image
    assert CTS2010Standard.MIN_IQA_SCORE        == 0.70    # overall quality score
    assert CTS2010Standard.MICR_BAND_MIN_SCORE  == 0.80    # MICR line quality
    assert CTS2010Standard.FRONT_IMAGE_REQUIRED is True
    assert CTS2010Standard.REAR_IMAGE_REQUIRED  is True


# ── Instrument Compliance Record ─────────────────────────────────────────────

def test_instrument_compliance_record_pass():
    from modules.cts.compliance.models import InstrumentComplianceRecord, ComplianceResult
    record = InstrumentComplianceRecord(
        instrument_id='CHQ-OUT-00001',
        cheque_number='100001',
        lot_number='LOT_SVCB0000001_20260619_SES-0619-001_01',
        front_dpi=300,
        front_colour_depth=24,
        front_file_size_kb=38.2,
        front_iqa_score=0.94,
        rear_dpi=300,
        rear_colour_depth=24,
        rear_file_size_kb=22.5,
        rear_iqa_score=0.91,
        micr_band_score=0.96,
    )
    assert record.result == ComplianceResult.PASS
    assert record.is_compliant is True


def test_instrument_compliance_record_fail_low_dpi():
    from modules.cts.compliance.models import InstrumentComplianceRecord, ComplianceResult
    record = InstrumentComplianceRecord(
        instrument_id='CHQ-OUT-00002',
        cheque_number='100002',
        lot_number='LOT_SVCB0000001_20260619_SES-0619-001_01',
        front_dpi=150,          # below CTS-2010 minimum of 200 dpi
        front_colour_depth=24,
        front_file_size_kb=38.2,
        front_iqa_score=0.94,
        rear_dpi=200,
        rear_colour_depth=24,
        rear_file_size_kb=22.5,
        rear_iqa_score=0.91,
        micr_band_score=0.96,
    )
    assert record.result == ComplianceResult.FAIL
    assert record.is_compliant is False
    assert 'front_dpi' in record.failure_reasons


def test_instrument_compliance_record_fail_large_file():
    from modules.cts.compliance.models import InstrumentComplianceRecord, ComplianceResult
    record = InstrumentComplianceRecord(
        instrument_id='CHQ-OUT-00003',
        cheque_number='100003',
        lot_number='LOT_SVCB0000001_20260619_SES-0619-001_01',
        front_dpi=300,
        front_colour_depth=24,
        front_file_size_kb=55.0,    # exceeds 50KB max
        front_iqa_score=0.94,
        rear_dpi=300,
        rear_colour_depth=24,
        rear_file_size_kb=22.5,
        rear_iqa_score=0.91,
        micr_band_score=0.96,
    )
    assert record.result == ComplianceResult.FAIL
    assert 'front_file_size_kb' in record.failure_reasons


def test_instrument_compliance_record_fail_low_micr():
    from modules.cts.compliance.models import InstrumentComplianceRecord, ComplianceResult
    record = InstrumentComplianceRecord(
        instrument_id='CHQ-OUT-00004',
        cheque_number='100004',
        lot_number='LOT_SVCB0000001_20260619_SES-0619-001_01',
        front_dpi=300,
        front_colour_depth=24,
        front_file_size_kb=38.2,
        front_iqa_score=0.94,
        rear_dpi=300,
        rear_colour_depth=24,
        rear_file_size_kb=22.5,
        rear_iqa_score=0.91,
        micr_band_score=0.65,    # below MICR minimum 0.80
    )
    assert record.result == ComplianceResult.FAIL
    assert 'micr_band_score' in record.failure_reasons


# ── Batch Compliance Certificate ─────────────────────────────────────────────

def test_batch_certificate_all_pass():
    from modules.cts.compliance.models import (
        InstrumentComplianceRecord, BatchComplianceCertificate, ComplianceResult
    )
    def make_pass(iid):
        return InstrumentComplianceRecord(
            instrument_id=iid, cheque_number='100001',
            lot_number='LOT_SVCB0000001_20260619_SES-0619-001_01',
            front_dpi=300, front_colour_depth=24, front_file_size_kb=38.2, front_iqa_score=0.94,
            rear_dpi=300,  rear_colour_depth=24,  rear_file_size_kb=22.5,  rear_iqa_score=0.91,
            micr_band_score=0.96,
        )

    instruments = [make_pass(f'CHQ-00{i}') for i in range(5)]
    cert = BatchComplianceCertificate(
        batch_id='LOT_SVCB0000001_20260619_SES-0619-001_01',
        session_id='SES-0619-001',
        bank_ifsc='SVCB0000001',
        issued_at=datetime(2026, 6, 19, 12, 0, tzinfo=timezone.utc),
        instruments=instruments,
    )
    assert cert.total_instruments == 5
    assert cert.passed_count      == 5
    assert cert.failed_count      == 0
    assert cert.pass_rate         == 100.0
    assert cert.overall_result    == ComplianceResult.PASS


def test_batch_certificate_fail_if_any_instrument_fails():
    from modules.cts.compliance.models import (
        InstrumentComplianceRecord, BatchComplianceCertificate, ComplianceResult
    )
    def make_pass(iid):
        return InstrumentComplianceRecord(
            instrument_id=iid, cheque_number='100001',
            lot_number='LOT_SVCB0000001_20260619_SES-0619-001_01',
            front_dpi=300, front_colour_depth=24, front_file_size_kb=38.2, front_iqa_score=0.94,
            rear_dpi=300,  rear_colour_depth=24,  rear_file_size_kb=22.5,  rear_iqa_score=0.91,
            micr_band_score=0.96,
        )
    fail_item = InstrumentComplianceRecord(
        instrument_id='CHQ-FAIL',  cheque_number='100099',
        lot_number='LOT_SVCB0000001_20260619_SES-0619-001_01',
        front_dpi=150,             # FAIL
        front_colour_depth=24, front_file_size_kb=38.2, front_iqa_score=0.94,
        rear_dpi=300,  rear_colour_depth=24, rear_file_size_kb=22.5, rear_iqa_score=0.91,
        micr_band_score=0.96,
    )
    instruments = [make_pass(f'CHQ-00{i}') for i in range(4)] + [fail_item]
    cert = BatchComplianceCertificate(
        batch_id='LOT_SVCB0000001_20260619_SES-0619-001_01',
        session_id='SES-0619-001',
        bank_ifsc='SVCB0000001',
        issued_at=datetime(2026, 6, 19, 12, 0, tzinfo=timezone.utc),
        instruments=instruments,
    )
    assert cert.failed_count   == 1
    assert cert.pass_rate      == 80.0
    assert cert.overall_result == ComplianceResult.FAIL


# ── Certificate Export ────────────────────────────────────────────────────────

def test_certificate_xml_export_structure():
    from modules.cts.compliance.models import InstrumentComplianceRecord, BatchComplianceCertificate
    from modules.cts.compliance.exporter import CertificateExporter

    instruments = [InstrumentComplianceRecord(
        instrument_id='CHQ-001', cheque_number='100001',
        lot_number='LOT_SVCB0000001_20260619_SES-0619-001_01',
        front_dpi=300, front_colour_depth=24, front_file_size_kb=38.2, front_iqa_score=0.94,
        rear_dpi=300,  rear_colour_depth=24,  rear_file_size_kb=22.5,  rear_iqa_score=0.91,
        micr_band_score=0.96,
    )]
    cert = BatchComplianceCertificate(
        batch_id='LOT_SVCB0000001_20260619_SES-0619-001_01',
        session_id='SES-0619-001',
        bank_ifsc='SVCB0000001',
        issued_at=datetime(2026, 6, 19, 12, 0, tzinfo=timezone.utc),
        instruments=instruments,
    )
    xml_str = CertificateExporter.to_xml(cert)
    assert '<?xml' in xml_str
    assert 'CTS2010ComplianceCertificate' in xml_str
    assert 'SVCB0000001' in xml_str
    assert 'CHQ-001' in xml_str
    assert 'PASS' in xml_str


def test_certificate_xml_filename():
    from modules.cts.compliance.models import BatchComplianceCertificate
    from modules.cts.compliance.exporter import CertificateExporter

    cert = BatchComplianceCertificate(
        batch_id='LOT_SVCB0000001_20260619_SES-0619-001_01',
        session_id='SES-0619-001',
        bank_ifsc='SVCB0000001',
        issued_at=datetime(2026, 6, 19, 12, 0, tzinfo=timezone.utc),
        instruments=[],
    )
    fname = CertificateExporter.filename(cert)
    assert fname == 'CTS2010_CERT_SVCB0000001_20260619_SES-0619-001_LOT01.xml'
