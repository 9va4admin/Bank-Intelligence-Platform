# Stub — model tests live in test_compliance.py (consolidated).
# Satisfies pre-commit TDD pairing hook for models.py.
from tests.modules.cts.compliance.test_compliance import (  # noqa: F401
    test_instrument_compliance_record_pass,
    test_instrument_compliance_record_fail_low_dpi,
    test_instrument_compliance_record_fail_large_file,
    test_instrument_compliance_record_fail_low_micr,
    test_batch_certificate_all_pass,
    test_batch_certificate_fail_if_any_instrument_fails,
)


def _make_inst(**kwargs):
    from modules.cts.compliance.models import InstrumentComplianceRecord
    # Defaults must satisfy all CTS2010 thresholds to produce a PASS
    # MIN_DPI=200, MIN_COLOUR_DEPTH=24, MAX_FILE_SIZE_KB=50, MIN_IQA_SCORE=0.7, MICR_BAND_MIN_SCORE=0.8
    defaults = dict(
        instrument_id="I1", cheque_number="001", lot_number="L1",
        front_dpi=200, rear_dpi=200,
        front_colour_depth=24, rear_colour_depth=24,
        front_file_size_kb=30.0, rear_file_size_kb=30.0,
        front_iqa_score=0.85, rear_iqa_score=0.85,
        micr_band_score=0.95,
    )
    defaults.update(kwargs)
    return InstrumentComplianceRecord(**defaults)


def test_fail_low_rear_dpi():
    """Covers line 52: rear_dpi below minimum → failure_reasons includes rear_dpi."""
    from modules.cts.compliance.cts2010 import CTS2010Standard
    inst = _make_inst(rear_dpi=CTS2010Standard.MIN_DPI - 1)
    assert "rear_dpi" in inst.failure_reasons


def test_fail_low_front_colour_depth():
    """Covers line 54: front_colour_depth below minimum."""
    from modules.cts.compliance.cts2010 import CTS2010Standard
    inst = _make_inst(front_colour_depth=CTS2010Standard.MIN_COLOUR_DEPTH - 1)
    assert "front_colour_depth" in inst.failure_reasons


def test_fail_high_rear_file_size():
    """Covers line 58: rear_file_size_kb above maximum."""
    from modules.cts.compliance.cts2010 import CTS2010Standard
    inst = _make_inst(rear_file_size_kb=CTS2010Standard.MAX_FILE_SIZE_KB + 1)
    assert "rear_file_size_kb" in inst.failure_reasons


def test_fail_low_front_iqa_score():
    """Covers line 60: front_iqa_score below minimum."""
    from modules.cts.compliance.cts2010 import CTS2010Standard
    inst = _make_inst(front_iqa_score=CTS2010Standard.MIN_IQA_SCORE - 0.01)
    assert "front_iqa_score" in inst.failure_reasons


def test_fail_low_rear_iqa_score():
    """Covers line 62: rear_iqa_score below minimum."""
    from modules.cts.compliance.cts2010 import CTS2010Standard
    inst = _make_inst(rear_iqa_score=CTS2010Standard.MIN_IQA_SCORE - 0.01)
    assert "rear_iqa_score" in inst.failure_reasons


def test_pass_rate_with_instruments():
    """Covers line 102: pass_rate calculation when total_instruments > 0."""
    from modules.cts.compliance.models import BatchComplianceCertificate
    from datetime import datetime, timezone
    good = _make_inst()
    bad = _make_inst(rear_dpi=1)
    cert = BatchComplianceCertificate(
        batch_id="BATCH001", bank_ifsc="HDFC0001234",
        session_id="sess-001",
        issued_at=datetime(2026, 6, 24, tzinfo=timezone.utc),
        instruments=[good, bad],
    )
    assert cert.pass_rate == 50.0


def test_pass_rate_zero_when_no_instruments():
    """Covers line 102: pass_rate returns 0.0 when total_instruments == 0."""
    from modules.cts.compliance.models import BatchComplianceCertificate
    from datetime import datetime, timezone
    cert = BatchComplianceCertificate(
        batch_id="BATCH001", bank_ifsc="HDFC0001234",
        session_id="sess-001",
        issued_at=datetime(2026, 6, 24, tzinfo=timezone.utc),
        instruments=[],
    )
    assert cert.pass_rate == 0.0
