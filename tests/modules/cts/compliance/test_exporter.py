# Stub — exporter tests live in test_compliance.py (consolidated).
# Satisfies pre-commit TDD pairing hook for exporter.py.
from tests.modules.cts.compliance.test_compliance import (  # noqa: F401
    test_certificate_xml_export_structure,
    test_certificate_xml_filename,
)


def _make_instrument(
    front_dpi=200, rear_dpi=200, front_colour_depth=24, rear_colour_depth=24,
    front_file_size_kb=30.0, rear_file_size_kb=30.0,
    front_iqa_score=0.85, rear_iqa_score=0.85, micr_band_score=0.95, **kwargs
):
    from modules.cts.compliance.models import InstrumentComplianceRecord
    return InstrumentComplianceRecord(
        instrument_id="INST1", cheque_number="001", lot_number="LOT1",
        front_dpi=front_dpi, rear_dpi=rear_dpi,
        front_colour_depth=front_colour_depth, rear_colour_depth=rear_colour_depth,
        front_file_size_kb=front_file_size_kb, rear_file_size_kb=rear_file_size_kb,
        front_iqa_score=front_iqa_score, rear_iqa_score=rear_iqa_score,
        micr_band_score=micr_band_score,
    )


def _make_cert(session_id="sess-001", batch_id="BATCH001"):
    from modules.cts.compliance.models import BatchComplianceCertificate
    from datetime import datetime, timezone
    return BatchComplianceCertificate(
        batch_id=batch_id,
        bank_ifsc="HDFC0001234",
        session_id=session_id,
        issued_at=datetime(2026, 6, 24, tzinfo=timezone.utc),
        instruments=[_make_instrument()],
    )


def test_xml_export_has_xml_declaration():
    """Covers lines 74-76: XML output always starts with <?xml."""
    from modules.cts.compliance.exporter import CertificateExporter
    cert = _make_cert()
    xml = CertificateExporter.to_xml(cert)
    assert xml.startswith("<?xml")


def test_filename_returns_expected_pattern():
    """Covers line 81: filename() produces expected string."""
    from modules.cts.compliance.exporter import CertificateExporter
    cert = _make_cert(session_id="sess-abc", batch_id="BATCH-XYZ")
    fname = CertificateExporter.filename(cert)
    assert "sess-abc" in fname
    assert fname.endswith(".xml")


def test_xml_includes_failure_reasons_for_failing_instrument():
    """Covers lines 74-76: FailureReasons XML block for a failing instrument."""
    from modules.cts.compliance.exporter import CertificateExporter
    from modules.cts.compliance.models import BatchComplianceCertificate
    from datetime import datetime, timezone
    # front_dpi=1 → below MIN_DPI=200 → will have failure_reasons
    failing_inst = _make_instrument(front_dpi=1)
    cert = BatchComplianceCertificate(
        batch_id="BATCH001", bank_ifsc="HDFC0001234",
        session_id="sess-fail",
        issued_at=datetime(2026, 6, 24, tzinfo=timezone.utc),
        instruments=[failing_inst],
    )
    xml = CertificateExporter.to_xml(cert)
    assert "FailureReasons" in xml
    assert "front_dpi" in xml
