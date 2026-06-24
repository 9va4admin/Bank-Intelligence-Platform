# Stub — all tests live in test_rrf_generator.py (consolidated file).
from tests.modules.cts.rrf.test_rrf_generator import *  # noqa: F401,F403


def test_to_xml_with_workflow_id():
    """Covers line 49: optional workflow_id element is added when present."""
    from modules.cts.rrf.generator import RRFGenerator
    from modules.cts.rrf.models import RRFDocument, ReturnItem, RBIReturnCode
    from datetime import datetime, timezone

    item = ReturnItem(
        instrument_id="INST001",
        micr_code="123456789012345",
        return_code=RBIReturnCode.SIGNATURE_DIFFERS,
        drawee_ifsc="HDFC0001234",
        presenting_ifsc="ICIC0005678",
        iet_deadline=datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc),
        returned_at=datetime(2026, 6, 24, 11, 55, 0, tzinfo=timezone.utc),
        decided_by="ops_reviewer",
        amount_range="₹[1L-5L]",
        bank_id="test-bank",
        workflow_id="cts-test-bank-INST001",  # non-None → triggers line 49
    )
    doc = RRFDocument(
        bank_ifsc="HDFC0001234",
        bank_id="test-bank",
        session_id="sess-001",
        clearing_zone="MUMBAI",
        generated_at=datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc),
        returns=[item],
    )
    xml = RRFGenerator.to_xml(doc)
    assert "cts-test-bank-INST001" in xml
    assert "TemporalWorkflowID" in xml
