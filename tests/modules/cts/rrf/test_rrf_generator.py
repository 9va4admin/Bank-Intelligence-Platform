"""
Tests for RRF (Return Reason File) generator.
RBI/NPCI CTS standard — XML format filed to NGCH for returned instruments.
RED phase: all tests must fail before implementation exists.
"""
import pytest
from datetime import datetime, timezone
from xml.etree import ElementTree as ET


# ── Tests for RBIReturnCode ─────────────────────────────────────────────────

def test_return_code_has_standard_rbi_codes():
    from modules.cts.rrf.models import RBIReturnCode
    assert RBIReturnCode.FUNDS_INSUFFICIENT.code == '01'
    assert RBIReturnCode.SIGNATURE_DIFFERS.code == '06'
    assert RBIReturnCode.ALTERATION_REQUIRES_AUTH.code == '07'
    assert RBIReturnCode.PAYMENT_STOPPED.code == '08'
    assert RBIReturnCode.WORDS_FIGURES_DIFFER.code == '16'
    assert RBIReturnCode.IMAGE_POOR_QUALITY.code == '20'


def test_return_code_has_description():
    from modules.cts.rrf.models import RBIReturnCode
    assert 'Insufficient' in RBIReturnCode.FUNDS_INSUFFICIENT.description
    assert 'Signature' in RBIReturnCode.SIGNATURE_DIFFERS.description


def test_return_code_from_ui_reason_maps_correctly():
    from modules.cts.rrf.models import RBIReturnCode
    code = RBIReturnCode.from_ui_reason('Signature mismatch confirmed')
    assert code == RBIReturnCode.SIGNATURE_DIFFERS

    code = RBIReturnCode.from_ui_reason('Insufficient funds')
    assert code == RBIReturnCode.FUNDS_INSUFFICIENT

    code = RBIReturnCode.from_ui_reason('Words and figures differ')
    assert code == RBIReturnCode.WORDS_FIGURES_DIFFER

    code = RBIReturnCode.from_ui_reason('Amount alteration detected')
    assert code == RBIReturnCode.ALTERATION_REQUIRES_AUTH


def test_return_code_from_unknown_ui_reason_returns_refer_drawer():
    from modules.cts.rrf.models import RBIReturnCode
    code = RBIReturnCode.from_ui_reason('Some unknown reason')
    assert code == RBIReturnCode.REFER_TO_DRAWER


# ── Tests for ReturnItem model ───────────────────────────────────────────────

def test_return_item_model_validates_required_fields():
    from modules.cts.rrf.models import ReturnItem, RBIReturnCode
    item = ReturnItem(
        instrument_id='CHQ-2026-001847',
        micr_code='400160001847',
        return_code=RBIReturnCode.FUNDS_INSUFFICIENT,
        drawee_ifsc='SVCB0000001',
        presenting_ifsc='HDFC0001234',
        iet_deadline=datetime(2026, 6, 19, 16, 0, 0, tzinfo=timezone.utc),
        returned_at=datetime(2026, 6, 19, 14, 28, 0, tzinfo=timezone.utc),
        decided_by='ops_reviewer',
        amount_range='₹[1L-5L]',
        bank_id='saraswat-mah',
    )
    assert item.instrument_id == 'CHQ-2026-001847'
    assert item.return_code.code == '01'


def test_return_item_filed_within_iet_true_when_before_deadline():
    from modules.cts.rrf.models import ReturnItem, RBIReturnCode
    item = ReturnItem(
        instrument_id='CHQ-2026-001847',
        micr_code='400160001847',
        return_code=RBIReturnCode.FUNDS_INSUFFICIENT,
        drawee_ifsc='SVCB0000001',
        presenting_ifsc='HDFC0001234',
        iet_deadline=datetime(2026, 6, 19, 16, 0, 0, tzinfo=timezone.utc),
        returned_at=datetime(2026, 6, 19, 14, 28, 0, tzinfo=timezone.utc),
        decided_by='ops_reviewer',
        amount_range='₹[1L-5L]',
        bank_id='saraswat-mah',
    )
    assert item.filed_within_iet is True


def test_return_item_filed_within_iet_false_when_after_deadline():
    from modules.cts.rrf.models import ReturnItem, RBIReturnCode
    item = ReturnItem(
        instrument_id='CHQ-2026-001847',
        micr_code='400160001847',
        return_code=RBIReturnCode.FUNDS_INSUFFICIENT,
        drawee_ifsc='SVCB0000001',
        presenting_ifsc='HDFC0001234',
        iet_deadline=datetime(2026, 6, 19, 13, 0, 0, tzinfo=timezone.utc),
        returned_at=datetime(2026, 6, 19, 14, 28, 0, tzinfo=timezone.utc),
        decided_by='ops_reviewer',
        amount_range='₹[1L-5L]',
        bank_id='saraswat-mah',
    )
    assert item.filed_within_iet is False


# ── Tests for RRFDocument model ──────────────────────────────────────────────

def test_rrf_document_total_returns_matches_items():
    from modules.cts.rrf.models import RRFDocument, ReturnItem, RBIReturnCode
    items = [
        ReturnItem(
            instrument_id=f'CHQ-2026-00{i}',
            micr_code=f'40016000{i:04d}',
            return_code=RBIReturnCode.FUNDS_INSUFFICIENT,
            drawee_ifsc='SVCB0000001',
            presenting_ifsc='HDFC0001234',
            iet_deadline=datetime(2026, 6, 19, 16, 0, tzinfo=timezone.utc),
            returned_at=datetime(2026, 6, 19, 14, 0, tzinfo=timezone.utc),
            decided_by='ops_reviewer',
            amount_range='₹[<1L]',
            bank_id='saraswat-mah',
        )
        for i in range(3)
    ]
    doc = RRFDocument(
        bank_ifsc='SVCB0000001',
        bank_id='saraswat-mah',
        session_id='SES-0619-001',
        clearing_zone='MUMBAI',
        generated_at=datetime(2026, 6, 19, 14, 30, tzinfo=timezone.utc),
        returns=items,
    )
    assert doc.total_returns == 3


# ── Tests for RRFGenerator ───────────────────────────────────────────────────

def test_generator_produces_valid_xml_string():
    from modules.cts.rrf.generator import RRFGenerator
    from modules.cts.rrf.models import RRFDocument, ReturnItem, RBIReturnCode
    item = ReturnItem(
        instrument_id='CHQ-2026-001847',
        micr_code='400160001847',
        return_code=RBIReturnCode.SIGNATURE_DIFFERS,
        drawee_ifsc='SVCB0000001',
        presenting_ifsc='HDFC0001234',
        iet_deadline=datetime(2026, 6, 19, 16, 0, tzinfo=timezone.utc),
        returned_at=datetime(2026, 6, 19, 14, 28, tzinfo=timezone.utc),
        decided_by='ops_reviewer',
        amount_range='₹[1L-5L]',
        bank_id='saraswat-mah',
    )
    doc = RRFDocument(
        bank_ifsc='SVCB0000001',
        bank_id='saraswat-mah',
        session_id='SES-0619-001',
        clearing_zone='MUMBAI',
        generated_at=datetime(2026, 6, 19, 14, 30, tzinfo=timezone.utc),
        returns=[item],
    )
    xml_str = RRFGenerator.to_xml(doc)
    assert isinstance(xml_str, str)
    assert '<?xml' in xml_str


def test_generator_xml_has_correct_root_element():
    from modules.cts.rrf.generator import RRFGenerator
    from modules.cts.rrf.models import RRFDocument, ReturnItem, RBIReturnCode
    item = ReturnItem(
        instrument_id='CHQ-2026-001847',
        micr_code='400160001847',
        return_code=RBIReturnCode.FUNDS_INSUFFICIENT,
        drawee_ifsc='SVCB0000001',
        presenting_ifsc='HDFC0001234',
        iet_deadline=datetime(2026, 6, 19, 16, 0, tzinfo=timezone.utc),
        returned_at=datetime(2026, 6, 19, 14, 28, tzinfo=timezone.utc),
        decided_by='ops_reviewer',
        amount_range='₹[<1L]',
        bank_id='saraswat-mah',
    )
    doc = RRFDocument(
        bank_ifsc='SVCB0000001',
        bank_id='saraswat-mah',
        session_id='SES-0619-001',
        clearing_zone='MUMBAI',
        generated_at=datetime(2026, 6, 19, 14, 30, tzinfo=timezone.utc),
        returns=[item],
    )
    xml_str = RRFGenerator.to_xml(doc)
    root = ET.fromstring(xml_str)
    assert root.tag == 'ReturnReasonFile'


def test_generator_xml_header_contains_bank_and_session():
    from modules.cts.rrf.generator import RRFGenerator
    from modules.cts.rrf.models import RRFDocument, ReturnItem, RBIReturnCode
    item = ReturnItem(
        instrument_id='CHQ-2026-001847',
        micr_code='400160001847',
        return_code=RBIReturnCode.FUNDS_INSUFFICIENT,
        drawee_ifsc='SVCB0000001',
        presenting_ifsc='HDFC0001234',
        iet_deadline=datetime(2026, 6, 19, 16, 0, tzinfo=timezone.utc),
        returned_at=datetime(2026, 6, 19, 14, 28, tzinfo=timezone.utc),
        decided_by='ops_reviewer',
        amount_range='₹[<1L]',
        bank_id='saraswat-mah',
    )
    doc = RRFDocument(
        bank_ifsc='SVCB0000001',
        bank_id='saraswat-mah',
        session_id='SES-0619-001',
        clearing_zone='MUMBAI',
        generated_at=datetime(2026, 6, 19, 14, 30, tzinfo=timezone.utc),
        returns=[item],
    )
    xml_str = RRFGenerator.to_xml(doc)
    root = ET.fromstring(xml_str)
    header = root.find('Header')
    assert header is not None
    assert header.find('BankIFSC').text == 'SVCB0000001'
    assert header.find('SessionID').text == 'SES-0619-001'
    assert header.find('TotalReturns').text == '1'
    assert header.find('ClearingZone').text == 'MUMBAI'


def test_generator_xml_return_item_has_all_required_fields():
    from modules.cts.rrf.generator import RRFGenerator
    from modules.cts.rrf.models import RRFDocument, ReturnItem, RBIReturnCode
    item = ReturnItem(
        instrument_id='CHQ-2026-001847',
        micr_code='400160001847',
        return_code=RBIReturnCode.SIGNATURE_DIFFERS,
        drawee_ifsc='SVCB0000001',
        presenting_ifsc='HDFC0001234',
        iet_deadline=datetime(2026, 6, 19, 16, 0, tzinfo=timezone.utc),
        returned_at=datetime(2026, 6, 19, 14, 28, tzinfo=timezone.utc),
        decided_by='ops_reviewer',
        amount_range='₹[1L-5L]',
        bank_id='saraswat-mah',
    )
    doc = RRFDocument(
        bank_ifsc='SVCB0000001',
        bank_id='saraswat-mah',
        session_id='SES-0619-001',
        clearing_zone='MUMBAI',
        generated_at=datetime(2026, 6, 19, 14, 30, tzinfo=timezone.utc),
        returns=[item],
    )
    xml_str = RRFGenerator.to_xml(doc)
    root = ET.fromstring(xml_str)
    ret = root.find('Returns/ReturnItem')
    assert ret is not None
    assert ret.find('InstrumentID').text == 'CHQ-2026-001847'
    assert ret.find('MICRCode').text == '400160001847'
    assert ret.find('ReturnReasonCode').text == '06'
    assert ret.find('DraweeIFSC').text == 'SVCB0000001'
    assert ret.find('PresentingIFSC').text == 'HDFC0001234'
    assert ret.find('FiledWithinIET').text == 'true'
    assert ret.find('DecidedBy').text == 'ops_reviewer'


def test_generator_xml_multiple_items():
    from modules.cts.rrf.generator import RRFGenerator
    from modules.cts.rrf.models import RRFDocument, ReturnItem, RBIReturnCode
    items = [
        ReturnItem(
            instrument_id=f'CHQ-2026-00{i:04d}',
            micr_code=f'40016000{i:04d}',
            return_code=RBIReturnCode.FUNDS_INSUFFICIENT,
            drawee_ifsc='SVCB0000001',
            presenting_ifsc='HDFC0001234',
            iet_deadline=datetime(2026, 6, 19, 16, 0, tzinfo=timezone.utc),
            returned_at=datetime(2026, 6, 19, 14, 0, tzinfo=timezone.utc),
            decided_by='ops_reviewer',
            amount_range='₹[<1L]',
            bank_id='saraswat-mah',
        )
        for i in range(5)
    ]
    doc = RRFDocument(
        bank_ifsc='SVCB0000001',
        bank_id='saraswat-mah',
        session_id='SES-0619-001',
        clearing_zone='MUMBAI',
        generated_at=datetime(2026, 6, 19, 14, 30, tzinfo=timezone.utc),
        returns=items,
    )
    xml_str = RRFGenerator.to_xml(doc)
    root = ET.fromstring(xml_str)
    assert len(root.findall('Returns/ReturnItem')) == 5
    assert root.find('Header/TotalReturns').text == '5'


def test_generator_filename_follows_ngch_convention():
    from modules.cts.rrf.generator import RRFGenerator
    from modules.cts.rrf.models import RRFDocument, RBIReturnCode
    doc = RRFDocument(
        bank_ifsc='SVCB0000001',
        bank_id='saraswat-mah',
        session_id='SES-0619-001',
        clearing_zone='MUMBAI',
        generated_at=datetime(2026, 6, 19, 14, 30, tzinfo=timezone.utc),
        returns=[],
    )
    fname = RRFGenerator.filename(doc)
    # NGCH convention: RRF_{IFSC}_{YYYYMMDD}_{SessionID}.xml
    assert fname.startswith('RRF_SVCB0000001_')
    assert fname.endswith('.xml')
    assert '20260619' in fname
    assert 'SES-0619-001' in fname


def test_generator_rejects_empty_returns_list():
    from modules.cts.rrf.generator import RRFGenerator
    from modules.cts.rrf.models import RRFDocument
    doc = RRFDocument(
        bank_ifsc='SVCB0000001',
        bank_id='saraswat-mah',
        session_id='SES-0619-001',
        clearing_zone='MUMBAI',
        generated_at=datetime(2026, 6, 19, 14, 30, tzinfo=timezone.utc),
        returns=[],
    )
    with pytest.raises(ValueError, match='No return items'):
        RRFGenerator.to_xml(doc, allow_empty=False)
