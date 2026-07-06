"""
Tests for CXF Builder — CXF XML per CTS Spec Rev 3.0.

CXF (Cheque Exchange Format) is the outward clearing file format submitted
to NGCH by the presentee bank. Each CXF submission covers one lot of cheques.

CTS Spec Rev 3.0 requirements (§CXF):
  - Namespace: urn:schemas-ncr-com:ECPIX:CXF:FileStructure:010005
  - <MICRDS> element: RSA-SHA256 over MICR line, Base64-encoded, 344 chars
  - <ImageViewAnalysis><UserField>: IQA result, "BFG:" + 16 chars
  - Mandatory fields: PresentingBankRoutNo, BatchID, CycleNo, ItemSeqNo, Amount

The CXFBuilder takes a list of CXFItem (one per cheque) and returns UTF-8 bytes.

RED phase: all tests must fail before cxf_builder.py is created.
"""
import xml.etree.ElementTree as ET
import pytest


def _make_cxf_item(**kwargs):
    """Create a minimal CXFItem dict; override any field with kwargs."""
    defaults = {
        "item_seq_no": "00001",
        "micr_line": "000012340050000012100000000005000123456789",
        "micrds": "A" * 344,   # fake 344-char base64 signature
        "iqa_user_field": "BFG:0000000000000000",
        "amount_paise": 5_000_000,
        "drawee_ifsc": "SBIN0000123",
        "drawee_account": "SB12345678901",
        "presenting_bank_rout_no": "000550050",
        "cycle_no": "01",
        "presentment_date": "07062026",
        "batch_id": "BCH0001",
    }
    defaults.update(kwargs)
    return defaults


_CXF_NS = "urn:schemas-ncr-com:ECPIX:CXF:FileStructure:010005"


def _parse_cxf(xml_bytes: bytes) -> ET.Element:
    """Parse CXF XML and return root element."""
    return ET.fromstring(xml_bytes)


def _find(root: ET.Element, *path: str) -> ET.Element | None:
    """Find element by path, trying with and without CXF namespace."""
    for element in [root]:
        for part in path:
            ns_tag = f"{{{_CXF_NS}}}{part}"
            child = element.find(ns_tag)
            if child is None:
                child = element.find(part)
            if child is None:
                return None
            element = child
    return element


class TestCXFXMLStructure:
    """CXF XML must be valid XML with correct namespace."""

    def test_build_returns_bytes(self):
        from modules.cts.ngch.cxf_builder import CXFBuilder, CXFItem

        builder = CXFBuilder()
        item = CXFItem(**_make_cxf_item())
        result = builder.build([item], session_id="SES0001")
        assert isinstance(result, bytes)

    def test_build_is_valid_xml(self):
        from modules.cts.ngch.cxf_builder import CXFBuilder, CXFItem

        builder = CXFBuilder()
        item = CXFItem(**_make_cxf_item())
        xml_bytes = builder.build([item], session_id="SES0001")
        # Must not raise
        root = ET.fromstring(xml_bytes)
        assert root is not None

    def test_root_element_has_cxf_namespace(self):
        """Root must have xmlns=urn:schemas-ncr-com:ECPIX:CXF:FileStructure:010005."""
        from modules.cts.ngch.cxf_builder import CXFBuilder, CXFItem

        builder = CXFBuilder()
        xml_bytes = builder.build([CXFItem(**_make_cxf_item())], session_id="SES0001")
        xml_str = xml_bytes.decode("utf-8")
        assert "urn:schemas-ncr-com:ECPIX:CXF:FileStructure:010005" in xml_str

    def test_xml_declaration_is_utf8(self):
        from modules.cts.ngch.cxf_builder import CXFBuilder, CXFItem

        builder = CXFBuilder()
        xml_bytes = builder.build([CXFItem(**_make_cxf_item())], session_id="SES0001")
        assert xml_bytes.startswith(b"<?xml")
        assert b"UTF-8" in xml_bytes[:50] or b"utf-8" in xml_bytes[:50]


class TestCXFFileHeader:
    """FileHeader elements must be present and correct."""

    def test_session_id_present(self):
        from modules.cts.ngch.cxf_builder import CXFBuilder, CXFItem

        builder = CXFBuilder()
        xml_bytes = builder.build([CXFItem(**_make_cxf_item())], session_id="SESS42")
        root = ET.fromstring(xml_bytes)
        fh = _find(root, "FileHeader")
        assert fh is not None
        sid = _find(fh, "SessionID") if fh is not None else None
        assert sid is not None
        assert sid.text == "SESS42"

    def test_presenting_bank_rout_no_in_header(self):
        from modules.cts.ngch.cxf_builder import CXFBuilder, CXFItem

        builder = CXFBuilder()
        xml_bytes = builder.build(
            [CXFItem(**_make_cxf_item(presenting_bank_rout_no="000550050"))],
            session_id="S01",
        )
        assert b"000550050" in xml_bytes


class TestCXFItemElements:
    """Per-item mandatory elements."""

    def test_micrds_element_present(self):
        from modules.cts.ngch.cxf_builder import CXFBuilder, CXFItem

        builder = CXFBuilder()
        micrds = "B" * 344
        xml_bytes = builder.build(
            [CXFItem(**_make_cxf_item(micrds=micrds))], session_id="S01"
        )
        assert micrds.encode() in xml_bytes

    def test_micrds_length_enforced(self):
        """CXFItem must reject MICRDS that is not 344 chars."""
        from modules.cts.ngch.cxf_builder import CXFItem, CXFValidationError

        with pytest.raises((CXFValidationError, ValueError)):
            CXFItem(**_make_cxf_item(micrds="SHORT"))

    def test_iqa_user_field_present(self):
        from modules.cts.ngch.cxf_builder import CXFBuilder, CXFItem

        builder = CXFBuilder()
        xml_bytes = builder.build(
            [CXFItem(**_make_cxf_item(iqa_user_field="BFG:0000000000000000"))],
            session_id="S01",
        )
        assert b"BFG:0000000000000000" in xml_bytes

    def test_iqa_user_field_format_enforced(self):
        """IQA UserField must start with 'BFG:' and be 20 chars."""
        from modules.cts.ngch.cxf_builder import CXFItem, CXFValidationError

        with pytest.raises((CXFValidationError, ValueError)):
            CXFItem(**_make_cxf_item(iqa_user_field="WRONG:FORMAT"))

    def test_amount_in_output(self):
        from modules.cts.ngch.cxf_builder import CXFBuilder, CXFItem

        builder = CXFBuilder()
        xml_bytes = builder.build(
            [CXFItem(**_make_cxf_item(amount_paise=7_500_000))], session_id="S01"
        )
        assert b"7500000" in xml_bytes

    def test_item_seq_no_in_output(self):
        from modules.cts.ngch.cxf_builder import CXFBuilder, CXFItem

        builder = CXFBuilder()
        xml_bytes = builder.build(
            [CXFItem(**_make_cxf_item(item_seq_no="00042"))], session_id="S01"
        )
        assert b"00042" in xml_bytes

    def test_drawee_ifsc_in_output(self):
        from modules.cts.ngch.cxf_builder import CXFBuilder, CXFItem

        builder = CXFBuilder()
        xml_bytes = builder.build(
            [CXFItem(**_make_cxf_item(drawee_ifsc="HDFC0001234"))], session_id="S01"
        )
        assert b"HDFC0001234" in xml_bytes

    def test_micr_line_in_output(self):
        from modules.cts.ngch.cxf_builder import CXFBuilder, CXFItem

        micr = "000012340050000012100000000005000123456789"
        builder = CXFBuilder()
        xml_bytes = builder.build([CXFItem(**_make_cxf_item(micr_line=micr))], session_id="S01")
        assert micr.encode() in xml_bytes


class TestCXFMultiItem:
    """Multiple items in one CXF file."""

    def test_two_items_both_present(self):
        from modules.cts.ngch.cxf_builder import CXFBuilder, CXFItem

        builder = CXFBuilder()
        items = [
            CXFItem(**_make_cxf_item(item_seq_no="00001", micrds="A" * 344)),
            CXFItem(**_make_cxf_item(item_seq_no="00002", micrds="B" * 344)),
        ]
        xml_bytes = builder.build(items, session_id="S01")
        assert b"00001" in xml_bytes
        assert b"00002" in xml_bytes

    def test_empty_item_list_raises(self):
        from modules.cts.ngch.cxf_builder import CXFBuilder, CXFValidationError

        builder = CXFBuilder()
        with pytest.raises((CXFValidationError, ValueError)):
            builder.build([], session_id="S01")
