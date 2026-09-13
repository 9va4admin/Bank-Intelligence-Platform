"""
Tests for CXFBuilder — CHI Spec Rev 3.00 compliant CXF XML.

Key spec requirements tested here:
  1. Root element is <FileHeader> (NOT <PresentmentExchangeFile>)
  2. All item data as XML ATTRIBUTES on <Item> (NOT child elements)
  3. ItemSeqNo must be exactly 14 chars
  4. <AddendA> element required per item
  5. <FileSummary> required at document level
  6. <ImageViewData> required per image view (with byte offsets from CIBF)
  7. <ImageDS> (CXF inline DS reference) required per image view
  8. <MICRDS> has MICRFingerPrint + SignatureData attributes
  9. IQA UserField is 21 chars ("BFB:" + 17 codes)
  10. ViewSideIndicator values: "Front BW", "Back BW", "Front Gray"
     (NOT "FrontBlackAndWhite" / "BackBlackAndWhite" / "FrontGrayscale")

RED phase: all tests must fail against the old cxf_builder.py which uses
wrong root element, child elements, 5-char ItemSeqNo, 20-char UserField, etc.
"""
import xml.etree.ElementTree as ET

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_item(**overrides) -> dict:
    """Minimal valid CXFItem kwargs."""
    defaults = dict(
        item_seq_no="00000101000001",           # 14 chars
        payor_bank_rout_no="000550050",
        account_no="****4521",
        serial_no="123456",
        trans_code="10",
        micr_line="000550050010000123456",
        micrds_fingerprint="PresentmentDate;PresentingBankRoutNo;CycleNo;ItemSeqNo;Amount;SerialNo;Transcode",
        micrds_signature="A" * 344,             # 344-char Base64 MICRDS
        iqa_user_field_front_bw="BFB:" + "0" * 17,   # 21 chars
        iqa_user_field_back_bw="BBB:" + "0" * 17,    # 21 chars
        iqa_user_field_front_gray="BFG:" + "0" * 17, # 21 chars
        amount_paise=10000,
        drawee_ifsc="ABCD0001234",
        doc_type="01",
        presenting_bank_rout_no="000550050",
        cycle_no="01",
        presentment_date="01042026",
        batch_id="BATCH001",
        # CIBF byte offsets for ImageViewData
        front_bw_ds_offset=0,
        front_bw_image_offset=256,
        front_bw_image_length=1024,
        back_bw_ds_offset=1280,
        back_bw_image_offset=1536,
        back_bw_image_length=512,
        front_gray_ds_offset=2048,
        front_gray_image_offset=2304,
        front_gray_image_length=2048,
    )
    defaults.update(overrides)
    return defaults


def _build_one(session_id: str = "SES001", **item_overrides) -> ET.Element:
    """Build CXF XML for one item and return the parsed root element (namespace stripped for findall)."""
    from modules.cts.ngch.cxf_builder import CXFBuilder, CXFItem, _CXF_NS

    item = CXFItem(**_make_item(**item_overrides))
    builder = CXFBuilder()
    xml_bytes = builder.build([item], session_id=session_id, cibf_filename="CIBF_000550050_01042026_103000_14_0001_01.img")
    # Strip namespace so plain findall(".//Item") works in tests
    xml_str = xml_bytes.decode("utf-8").replace(f' xmlns="{_CXF_NS}"', "")
    return ET.fromstring(xml_str)


# ---------------------------------------------------------------------------
# Root element
# ---------------------------------------------------------------------------

class TestCXFRootElement:
    def test_root_is_fileheader(self):
        """Root element must be FileHeader (CHI Spec Rev 3.00 § 4.1.1)."""
        root = _build_one()
        assert root.tag == "FileHeader" or root.tag.endswith("}FileHeader"), \
            f"Expected root <FileHeader>, got <{root.tag}>"

    def test_root_is_not_presentment_exchange_file(self):
        root = _build_one()
        assert "PresentmentExchangeFile" not in root.tag

    def test_root_has_xmlns_attribute(self):
        """Root must declare the CXF namespace."""
        from modules.cts.ngch.cxf_builder import CXFBuilder, CXFItem
        item = CXFItem(**_make_item())
        builder = CXFBuilder()
        xml_bytes = builder.build([item], session_id="S1", cibf_filename="CIBF_000550050_01042026_103000_14_0001_01.img")
        xml_str = xml_bytes.decode("utf-8")
        assert "xmlns" in xml_str


# ---------------------------------------------------------------------------
# FileSummary
# ---------------------------------------------------------------------------

class TestFileSummary:
    def test_file_summary_present(self):
        root = _build_one()
        # FileSummary may be at root level or as a child — must exist somewhere
        found = (
            root.find("FileSummary") is not None
            or root.find(".//FileSummary") is not None
        )
        assert found, "<FileSummary> element missing from CXF"

    def test_file_summary_has_total_items(self):
        root = _build_one()
        fs = root.find("FileSummary") or root.find(".//FileSummary")
        assert fs is not None
        # Must have TotalItemCount (as attribute or child text)
        has_count = (
            fs.get("TotalItemCount") is not None
            or fs.find("TotalItemCount") is not None
            or fs.get("ItemCount") is not None
        )
        assert has_count, "<FileSummary> missing TotalItemCount/ItemCount"


# ---------------------------------------------------------------------------
# Item attributes (NOT child elements)
# ---------------------------------------------------------------------------

class TestItemAttributes:
    def test_item_seq_no_is_attribute(self):
        """ItemSeqNo must be an XML attribute on <Item>, not a child element."""
        root = _build_one()
        item_el = root.find(".//Item")
        assert item_el is not None, "<Item> element not found"
        assert item_el.get("ItemSeqNo") is not None, \
            "ItemSeqNo must be an XML attribute on <Item>"

    def test_amount_is_attribute(self):
        root = _build_one()
        item_el = root.find(".//Item")
        assert item_el.get("Amount") is not None or item_el.get("AmountPaise") is not None, \
            "Amount must be an XML attribute on <Item>"

    def test_drawee_ifsc_is_attribute(self):
        root = _build_one()
        item_el = root.find(".//Item")
        assert item_el.get("DraweeIFSC") is not None or item_el.get("DraweeIfsc") is not None, \
            "DraweeIFSC must be an XML attribute on <Item>"

    def test_micr_line_is_attribute(self):
        root = _build_one()
        item_el = root.find(".//Item")
        assert item_el.get("MICRLine") is not None or item_el.get("MicrLine") is not None, \
            "MICRLine must be an XML attribute on <Item>"

    def test_item_has_no_plain_text_children_for_fields(self):
        """Item fields must NOT be child text elements."""
        root = _build_one()
        item_el = root.find(".//Item")
        # Fields that must be attributes, not child elements:
        wrong_children = {"ItemSeqNo", "AmountPaise", "DraweeIFSC", "MICRLine"}
        for child in item_el:
            assert child.tag not in wrong_children, \
                f"Field <{child.tag}> must be an attribute, not a child element"


# ---------------------------------------------------------------------------
# ItemSeqNo — 14 chars
# ---------------------------------------------------------------------------

class TestItemSeqNo:
    def test_item_seq_no_is_14_chars(self):
        """ItemSeqNo must be exactly 14 chars per spec."""
        root = _build_one()
        item_el = root.find(".//Item")
        seq_no = item_el.get("ItemSeqNo")
        assert seq_no is not None
        assert len(seq_no) == 14, f"ItemSeqNo must be 14 chars, got {len(seq_no)}: {seq_no!r}"

    def test_item_seq_no_validation_rejects_5_chars(self):
        """Old code used 5-char ItemSeqNo — must now be rejected."""
        from modules.cts.ngch.cxf_builder import CXFItem, CXFValidationError
        with pytest.raises((CXFValidationError, ValueError)):
            CXFItem(**_make_item(item_seq_no="00001"))

    def test_item_seq_no_validation_accepts_14_chars(self):
        from modules.cts.ngch.cxf_builder import CXFItem
        item = CXFItem(**_make_item(item_seq_no="00000101000001"))
        assert item.item_seq_no == "00000101000001"


# ---------------------------------------------------------------------------
# AddendA element
# ---------------------------------------------------------------------------

class TestAddendA:
    def test_addenda_present_per_item(self):
        """<AddendA> must appear for every <Item> (CHI Spec Rev 3.00)."""
        root = _build_one()
        item_el = root.find(".//Item")
        addenda = item_el.find("AddendA") or item_el.find(".//AddendA")
        assert addenda is not None, "<AddendA> element missing from <Item>"

    def test_addenda_has_required_fields(self):
        """AddendA must carry BofdRoutNo, BofdBusDate, or similar."""
        root = _build_one()
        item_el = root.find(".//Item")
        addenda = item_el.find("AddendA") or item_el.find(".//AddendA")
        assert addenda is not None
        # Must have at least one attribute or child
        has_content = len(addenda.attrib) > 0 or len(list(addenda)) > 0
        assert has_content, "<AddendA> is empty — must carry BOFD/truncation data"


# ---------------------------------------------------------------------------
# MICRDS — fingerprint + signature attributes
# ---------------------------------------------------------------------------

class TestMICRDS:
    def test_micrds_element_present(self):
        root = _build_one()
        micrds = root.find(".//MICRDS")
        assert micrds is not None, "<MICRDS> element not found"

    def test_micrds_has_fingerprint_attribute(self):
        root = _build_one()
        micrds = root.find(".//MICRDS")
        fp = micrds.get("MICRFingerPrint")
        assert fp is not None, "<MICRDS> missing MICRFingerPrint attribute"
        assert ";" in fp

    def test_micrds_has_signature_data_attribute(self):
        root = _build_one()
        micrds = root.find(".//MICRDS")
        sig = micrds.get("SignatureData")
        assert sig is not None, "<MICRDS> missing SignatureData attribute"
        assert len(sig) == 344


# ---------------------------------------------------------------------------
# ImageViewData — byte offsets from CIBF
# ---------------------------------------------------------------------------

class TestImageViewData:
    def _get_view_data_list(self, root):
        return root.findall(".//ImageViewData")

    def test_three_image_view_data_per_item(self):
        """One <ImageViewData> per image view (Front BW, Back BW, Front Gray)."""
        root = _build_one()
        ivd_list = self._get_view_data_list(root)
        assert len(ivd_list) == 3, f"Expected 3 ImageViewData, got {len(ivd_list)}"

    def test_image_data_offset_present(self):
        root = _build_one()
        for ivd in self._get_view_data_list(root):
            assert ivd.get("ImageDataOffset") is not None, \
                "<ImageViewData> missing ImageDataOffset attribute"

    def test_image_data_length_present(self):
        root = _build_one()
        for ivd in self._get_view_data_list(root):
            assert ivd.get("ImageDataLength") is not None, \
                "<ImageViewData> missing ImageDataLength attribute"

    def test_image_data_offset_matches_cibf(self):
        """Offsets in CXF must match values from CIBF assembler result."""
        root = _build_one(
            front_bw_image_offset=256,
            back_bw_image_offset=1536,
            front_gray_image_offset=2304,
        )
        ivd_list = self._get_view_data_list(root)
        offsets = [int(ivd.get("ImageDataOffset")) for ivd in ivd_list]
        assert 256 in offsets
        assert 1536 in offsets
        assert 2304 in offsets


# ---------------------------------------------------------------------------
# ImageDS in CXF
# ---------------------------------------------------------------------------

class TestImageDSInCXF:
    def test_image_ds_element_present(self):
        """<ImageDS> must appear per image view in CXF (CHI Spec Rev 3.00)."""
        root = _build_one()
        ids_list = root.findall(".//ImageDS")
        assert len(ids_list) >= 1, "<ImageDS> element missing from CXF"

    def test_image_ds_has_offset_attribute(self):
        root = _build_one()
        for ids in root.findall(".//ImageDS"):
            offset = ids.get("DigitalSignatureDataOffset")
            assert offset is not None, "<ImageDS> missing DigitalSignatureDataOffset"


# ---------------------------------------------------------------------------
# ViewSideIndicator values (NOT old ViewType values)
# ---------------------------------------------------------------------------

class TestViewSideIndicator:
    def test_view_side_indicator_front_bw(self):
        """ViewSideIndicator must be 'Front BW' (not 'FrontBlackAndWhite')."""
        root = _build_one()
        xml_str = ET.tostring(root, encoding="unicode")
        assert "Front BW" in xml_str, \
            "Expected ViewSideIndicator='Front BW' in CXF XML"

    def test_view_side_indicator_back_bw(self):
        root = _build_one()
        xml_str = ET.tostring(root, encoding="unicode")
        assert "Back BW" in xml_str, \
            "Expected ViewSideIndicator='Back BW' in CXF XML"

    def test_view_side_indicator_front_gray(self):
        root = _build_one()
        xml_str = ET.tostring(root, encoding="unicode")
        assert "Front Gray" in xml_str, \
            "Expected ViewSideIndicator='Front Gray' in CXF XML"

    def test_old_view_type_not_used(self):
        """Old ViewType values (FrontBlackAndWhite etc.) must NOT appear."""
        root = _build_one()
        xml_str = ET.tostring(root, encoding="unicode")
        assert "FrontBlackAndWhite" not in xml_str
        assert "BackBlackAndWhite" not in xml_str
        assert "FrontGrayscale" not in xml_str


# ---------------------------------------------------------------------------
# IQA UserField — 21 chars
# ---------------------------------------------------------------------------

class TestIQAUserField:
    def test_user_field_is_21_chars_front_bw(self):
        from modules.cts.ngch.cxf_builder import CXFItem, CXFValidationError
        with pytest.raises((CXFValidationError, ValueError)):
            CXFItem(**_make_item(iqa_user_field_front_bw="BFB:" + "0" * 16))  # 20 chars — old, wrong

    def test_user_field_accepts_21_chars(self):
        from modules.cts.ngch.cxf_builder import CXFItem
        item = CXFItem(**_make_item(iqa_user_field_front_bw="BFB:" + "0" * 17))
        assert len(item.iqa_user_field_front_bw) == 21

    def test_user_field_in_xml_is_21_chars(self):
        root = _build_one()
        xml_str = ET.tostring(root, encoding="unicode")
        # Extract UserField values — all must be 21 chars
        for elem in root.findall(".//ImageViewAnalysis"):
            uf = elem.get("UserField") or (elem.find("UserField").text if elem.find("UserField") is not None else None)
            if uf:
                assert len(uf) == 21, f"UserField must be 21 chars, got {len(uf)}: {uf!r}"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestCXFItemValidation:
    def test_micrds_signature_must_be_344_chars(self):
        from modules.cts.ngch.cxf_builder import CXFItem, CXFValidationError
        with pytest.raises((CXFValidationError, ValueError)):
            CXFItem(**_make_item(micrds_signature="X" * 100))

    def test_empty_items_raises(self):
        from modules.cts.ngch.cxf_builder import CXFBuilder, CXFValidationError
        builder = CXFBuilder()
        with pytest.raises((CXFValidationError, ValueError)):
            builder.build([], session_id="S1", cibf_filename="CIBF_000550050_01042026_103000_14_0001_01.img")

    def test_valid_item_builds_without_error(self):
        from modules.cts.ngch.cxf_builder import CXFBuilder, CXFItem
        item = CXFItem(**_make_item())
        builder = CXFBuilder()
        result = builder.build([item], session_id="S1", cibf_filename="CIBF_000550050_01042026_103000_14_0001_01.img")
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_build_returns_utf8_xml(self):
        from modules.cts.ngch.cxf_builder import CXFBuilder, CXFItem
        item = CXFItem(**_make_item())
        builder = CXFBuilder()
        result = builder.build([item], session_id="S1", cibf_filename="CIBF_000550050_01042026_103000_14_0001_01.img")
        xml_str = result.decode("utf-8")
        assert xml_str.startswith("<?xml")

    def test_multiple_items_all_present(self):
        from modules.cts.ngch.cxf_builder import CXFBuilder, CXFItem, _CXF_NS
        items = [
            CXFItem(**_make_item(item_seq_no=f"0000010100{i:04d}")) for i in range(1, 4)
        ]
        builder = CXFBuilder()
        result = builder.build(items, session_id="S1", cibf_filename="CIBF_000550050_01042026_103000_14_0001_01.img")
        xml_str = result.decode("utf-8").replace(f' xmlns="{_CXF_NS}"', "")
        root = ET.fromstring(xml_str)
        assert len(root.findall(".//Item")) == 3
