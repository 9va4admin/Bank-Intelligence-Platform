"""
CXFParser tests — parse inward CXF XML received from NGCH.

The drawee bank receives the CXF that the presentee bank submitted (passed
through by NGCH). CXFParser extracts instrument metadata + CIBF byte offsets
needed to slice individual cheque images out of the accompanying CIBF binary.

RED phase: all tests must fail before cxf_parser.py is created.
"""
from __future__ import annotations

import base64
import textwrap

import pytest

# ---------------------------------------------------------------------------
# Helpers to build minimal valid CXF XML (same format CXFBuilder produces)
# ---------------------------------------------------------------------------

_NS = "urn:schemas-ncr-com:ECPIX:CXF:FileStructure:010005"
_FAKE_DS = "A" * 344          # 344-char Base64 placeholder for MICRDS
_FAKE_IQA_FBW  = "BFB:" + "A" * 17   # 21 chars
_FAKE_IQA_BBW  = "BBB:" + "A" * 17
_FAKE_IQA_FGRY = "BFG:" + "A" * 17


def _make_item_xml(
    item_seq_no="000550050000011",   # intentional: 15 chars — validator should raise
    payor_bank_rout_no="012345678",
    serial_no="000042",
    trans_code="51",
    micr_line="000042510123456780000010000050012345678",
    drawee_ifsc="SBIN0000123",
    amount_paise=10000000,
    doc_type="01",
    micrds_fp="MICRLine;Amount;SerialNo",
    micrds_sig=_FAKE_DS,
    addenda_rout="000550050",
    addenda_date="13092026",
    fwd_ds_off=0,
    fwd_img_off=256,
    fwd_img_len=50000,
    bwd_ds_off=50256,
    bwd_img_off=50512,
    bwd_img_len=45000,
    fgd_ds_off=95512,
    fgd_img_off=95768,
    fgd_img_len=120000,
    iqa_fbw=_FAKE_IQA_FBW,
    iqa_bbw=_FAKE_IQA_BBW,
    iqa_fgry=_FAKE_IQA_FGRY,
) -> str:
    return textwrap.dedent(f"""\
        <Item ItemSeqNo="{item_seq_no}" PayorBankRoutNo="{payor_bank_rout_no}"
              SerialNo="{serial_no}" TransCode="{trans_code}"
              MICRLine="{micr_line}" DraweeIFSC="{drawee_ifsc}"
              Amount="{amount_paise}" DocType="{doc_type}">
          <MICRDS MICRFingerPrint="{micrds_fp}" SignatureData="{micrds_sig}"/>
          <AddendA TruncatingRoutNo="{addenda_rout}" TruncatingBusDate="{addenda_date}"/>
          <ImageViewDetail ViewSideIndicator="Front BW">
            <ImageDS DigitalSignatureDataOffset="{fwd_ds_off}"/>
            <ImageViewData ImageDataOffset="{fwd_img_off}" ImageDataLength="{fwd_img_len}"/>
            <ImageViewAnalysis UserField="{iqa_fbw}"/>
          </ImageViewDetail>
          <ImageViewDetail ViewSideIndicator="Back BW">
            <ImageDS DigitalSignatureDataOffset="{bwd_ds_off}"/>
            <ImageViewData ImageDataOffset="{bwd_img_off}" ImageDataLength="{bwd_img_len}"/>
            <ImageViewAnalysis UserField="{iqa_bbw}"/>
          </ImageViewDetail>
          <ImageViewDetail ViewSideIndicator="Front Gray">
            <ImageDS DigitalSignatureDataOffset="{fgd_ds_off}"/>
            <ImageViewData ImageDataOffset="{fgd_img_off}" ImageDataLength="{fgd_img_len}"/>
            <ImageViewAnalysis UserField="{iqa_fgry}"/>
          </ImageViewDetail>
        </Item>""")


def _make_cxf_xml(
    session_id="SES0001",
    presenting_bank_rout_no="000550050",
    cibf_filename="CIBF_000550050_13092026_120000_14_0001.img",
    item_count=1,
    total_amount_paise=10000000,
    batch_id="BCH0001",
    presentment_date="13092026",
    cycle_no="01",
    items_xml: str = "",
    item_seq_no="00055005000001",  # 14 chars — valid
) -> bytes:
    if not items_xml:
        items_xml = _make_item_xml(item_seq_no=item_seq_no)
    xml = textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <FileHeader xmlns="{_NS}"
                    SessionID="{session_id}"
                    PresentingBankRoutNo="{presenting_bank_rout_no}"
                    CIBFFileName="{cibf_filename}">
          <FileSummary TotalItemCount="{item_count}" TotalAmountPaise="{total_amount_paise}"/>
          <Batch BatchID="{batch_id}"
                 PresentingBankRoutNo="{presenting_bank_rout_no}"
                 PresentmentDate="{presentment_date}"
                 CycleNo="{cycle_no}">
            {items_xml}
          </Batch>
        </FileHeader>""")
    return xml.encode("utf-8")


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------

class TestCXFParserFileHeader:
    def test_session_id_extracted(self):
        from modules.cts.ngch.cxf_parser import CXFParser
        result = CXFParser().parse(_make_cxf_xml(session_id="MY-SESSION-99"))
        assert result.session_id == "MY-SESSION-99"

    def test_cibf_filename_extracted(self):
        from modules.cts.ngch.cxf_parser import CXFParser
        fname = "CIBF_000550050_13092026_120000_14_0001.img"
        result = CXFParser().parse(_make_cxf_xml(cibf_filename=fname))
        assert result.cibf_filename == fname

    def test_presenting_bank_rout_no_extracted(self):
        from modules.cts.ngch.cxf_parser import CXFParser
        result = CXFParser().parse(_make_cxf_xml(presenting_bank_rout_no="000550050"))
        assert result.presenting_bank_rout_no == "000550050"

    def test_total_item_count_extracted(self):
        from modules.cts.ngch.cxf_parser import CXFParser
        result = CXFParser().parse(_make_cxf_xml(item_count=5))
        assert result.total_item_count == 5

    def test_total_amount_paise_extracted(self):
        from modules.cts.ngch.cxf_parser import CXFParser
        result = CXFParser().parse(_make_cxf_xml(total_amount_paise=99999999))
        assert result.total_amount_paise == 99999999


class TestCXFParserItemCount:
    def test_single_item_parsed(self):
        from modules.cts.ngch.cxf_parser import CXFParser
        result = CXFParser().parse(_make_cxf_xml())
        assert len(result.items) == 1

    def test_two_items_parsed(self):
        from modules.cts.ngch.cxf_parser import CXFParser
        item1 = _make_item_xml(item_seq_no="00055005000001",
                               fwd_ds_off=0, fwd_img_off=256, fwd_img_len=10000,
                               bwd_ds_off=10256, bwd_img_off=10512, bwd_img_len=9000,
                               fgd_ds_off=19512, fgd_img_off=19768, fgd_img_len=20000)
        item2 = _make_item_xml(item_seq_no="00055005000002",
                               fwd_ds_off=39768, fwd_img_off=40024, fwd_img_len=10000,
                               bwd_ds_off=50024, bwd_img_off=50280, bwd_img_len=9000,
                               fgd_ds_off=59280, fgd_img_off=59536, fgd_img_len=20000)
        xml = _make_cxf_xml(item_count=2, items_xml=item1 + "\n" + item2)
        result = CXFParser().parse(xml)
        assert len(result.items) == 2

    def test_empty_xml_raises(self):
        from modules.cts.ngch.cxf_parser import CXFParser, CXFParseError
        with pytest.raises(CXFParseError):
            CXFParser().parse(b"")

    def test_malformed_xml_raises(self):
        from modules.cts.ngch.cxf_parser import CXFParser, CXFParseError
        with pytest.raises(CXFParseError):
            CXFParser().parse(b"<not valid xml")


class TestCXFParserItemFields:
    def _parsed_item(self, **kwargs):
        from modules.cts.ngch.cxf_parser import CXFParser
        return CXFParser().parse(_make_cxf_xml(**kwargs)).items[0]

    def test_item_seq_no_extracted(self):
        item = self._parsed_item(item_seq_no="00055005000001")
        assert item.item_seq_no == "00055005000001"

    def test_payor_bank_rout_no_extracted(self):
        item = self._parsed_item()
        assert item.payor_bank_rout_no == "012345678"

    def test_serial_no_extracted(self):
        item = self._parsed_item()
        assert item.serial_no == "000042"

    def test_trans_code_extracted(self):
        item = self._parsed_item()
        assert item.trans_code == "51"

    def test_amount_paise_is_int(self):
        item = self._parsed_item()
        assert isinstance(item.amount_paise, int)
        assert item.amount_paise == 10000000

    def test_drawee_ifsc_extracted(self):
        item = self._parsed_item()
        assert item.drawee_ifsc == "SBIN0000123"

    def test_micrds_fingerprint_extracted(self):
        item = self._parsed_item()
        assert item.micrds_fingerprint == "MICRLine;Amount;SerialNo"

    def test_micrds_signature_extracted(self):
        item = self._parsed_item()
        assert item.micrds_signature == _FAKE_DS
        assert len(item.micrds_signature) == 344


class TestCXFParserByteOffsets:
    def _parsed_item(self):
        from modules.cts.ngch.cxf_parser import CXFParser
        xml = _make_cxf_xml(item_seq_no="00055005000001")
        return CXFParser().parse(xml).items[0]

    def test_front_bw_ds_offset(self):
        assert self._parsed_item().front_bw_ds_offset == 0

    def test_front_bw_image_offset(self):
        assert self._parsed_item().front_bw_image_offset == 256

    def test_front_bw_image_length(self):
        assert self._parsed_item().front_bw_image_length == 50000

    def test_back_bw_ds_offset(self):
        assert self._parsed_item().back_bw_ds_offset == 50256

    def test_back_bw_image_offset(self):
        assert self._parsed_item().back_bw_image_offset == 50512

    def test_back_bw_image_length(self):
        assert self._parsed_item().back_bw_image_length == 45000

    def test_front_gray_ds_offset(self):
        assert self._parsed_item().front_gray_ds_offset == 95512

    def test_front_gray_image_offset(self):
        assert self._parsed_item().front_gray_image_offset == 95768

    def test_front_gray_image_length(self):
        assert self._parsed_item().front_gray_image_length == 120000


class TestCXFParserIQAFields:
    def _parsed_item(self):
        from modules.cts.ngch.cxf_parser import CXFParser
        return CXFParser().parse(_make_cxf_xml()).items[0]

    def test_iqa_front_bw_extracted(self):
        item = self._parsed_item()
        assert item.iqa_user_field_front_bw == _FAKE_IQA_FBW
        assert item.iqa_user_field_front_bw.startswith("BFB:")

    def test_iqa_back_bw_extracted(self):
        item = self._parsed_item()
        assert item.iqa_user_field_back_bw == _FAKE_IQA_BBW
        assert item.iqa_user_field_back_bw.startswith("BBB:")

    def test_iqa_front_gray_extracted(self):
        item = self._parsed_item()
        assert item.iqa_user_field_front_gray == _FAKE_IQA_FGRY
        assert item.iqa_user_field_front_gray.startswith("BFG:")


class TestCXFParserWrongNamespace:
    def test_wrong_namespace_still_parses(self):
        """Tolerant parsing: accept CXF even if namespace is missing or wrong."""
        from modules.cts.ngch.cxf_parser import CXFParser
        xml = _make_cxf_xml().decode("utf-8").replace(_NS, "urn:wrong-ns")
        result = CXFParser().parse(xml.encode("utf-8"))
        assert len(result.items) == 1

    def test_no_namespace_still_parses(self):
        from modules.cts.ngch.cxf_parser import CXFParser
        xml = _make_cxf_xml().decode("utf-8").replace(f' xmlns="{_NS}"', "")
        result = CXFParser().parse(xml.encode("utf-8"))
        assert len(result.items) == 1
