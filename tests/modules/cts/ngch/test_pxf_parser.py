"""
Tests for PXF Parser — full inward instrument parser per CTS Spec Rev 3.0.

PXF (Presentment Exchange File) is the inward clearing file NGCH sends to
the drawee bank. It contains per-item data including:
  - ItemExpiryTime (per-item IET deadline — parsed via pxf_iet_parser)
  - PPS_Flag       (P/D/Y/Z/N/R/U — positive pay status from CCH)
  - ClearingType   (01=normal, 14=On Realization)
  - UDK components (PresentmentDate+PresentingBankRoutNo+CycleNo+ItemSeqNo)
  - MICR line, drawee IFSC, drawee account, amount

The parsed InwardInstrument feeds directly into ChequeWorkflowInput.
iet_deadline is set from ItemExpiryTime (not from config iet_minutes).

PPS_Flag meanings (from CTS Spec Rev 3.0):
  P = Positive Pay match confirmed by CCH
  D = Drawee to verify (instrument not in PPS database at CCH)
  Y = PPS registered but date/amount not checked (drawee must verify)
  Z = PPS inactive/cancelled — treat as stop payment
  N = No PPS instruction exists
  R = Refer to drawee for confirmation
  U = Unknown / unable to determine

RED phase: all tests must fail before pxf_parser.py is created.
"""
import textwrap
import pytest


def _make_pxf_xml(
    item_expiry_time="000000007062026160000",
    pps_flag="P",
    clearing_type="01",
    item_seq_no="00001",
    cycle_no="01",
    presentment_date="07062026",
    presenting_bank_rout_no="000550050",
    micr_line="000012340050000012100000000005000123456789",
    drawee_ifsc="SBIN0000123",
    drawee_account="SB12345678901",
    amount_paise=5000000,
    batch_id="BCH0001",
    session_id="SES0001",
) -> bytes:
    """Minimal valid PXF XML for testing."""
    xml = textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <PresentmentExchangeFile xmlns="urn:schemas-ncr-com:ECPIX:PXF:FileStructure:010003">
          <FileHeader>
            <SessionID>{session_id}</SessionID>
            <ClearingType>{clearing_type}</ClearingType>
          </FileHeader>
          <BatchGroup>
            <BatchHeader>
              <BatchID>{batch_id}</BatchID>
              <PresentingBankRoutNo>{presenting_bank_rout_no}</PresentingBankRoutNo>
              <PresentmentDate>{presentment_date}</PresentmentDate>
              <CycleNo>{cycle_no}</CycleNo>
            </BatchHeader>
            <Item>
              <ItemSeqNo>{item_seq_no}</ItemSeqNo>
              <ItemExpiryTime>{item_expiry_time}</ItemExpiryTime>
              <PPS_Flag>{pps_flag}</PPS_Flag>
              <MICRLine>{micr_line}</MICRLine>
              <DraweeIFSC>{drawee_ifsc}</DraweeIFSC>
              <DraweeAccount>{drawee_account}</DraweeAccount>
              <AmountPaise>{amount_paise}</AmountPaise>
            </Item>
          </BatchGroup>
        </PresentmentExchangeFile>
    """).encode("utf-8")
    return xml


def _make_two_item_pxf_xml() -> bytes:
    """PXF with two items having different IET deadlines."""
    return textwrap.dedent("""\
        <?xml version="1.0" encoding="UTF-8"?>
        <PresentmentExchangeFile xmlns="urn:schemas-ncr-com:ECPIX:PXF:FileStructure:010003">
          <FileHeader>
            <SessionID>SES0001</SessionID>
            <ClearingType>01</ClearingType>
          </FileHeader>
          <BatchGroup>
            <BatchHeader>
              <BatchID>BCH0001</BatchID>
              <PresentingBankRoutNo>000550050</PresentingBankRoutNo>
              <PresentmentDate>07062026</PresentmentDate>
              <CycleNo>01</CycleNo>
            </BatchHeader>
            <Item>
              <ItemSeqNo>00001</ItemSeqNo>
              <ItemExpiryTime>000000007062026150000</ItemExpiryTime>
              <PPS_Flag>P</PPS_Flag>
              <MICRLine>000012340050000012100000000005000123456789</MICRLine>
              <DraweeIFSC>SBIN0000123</DraweeIFSC>
              <DraweeAccount>SB12345678901</DraweeAccount>
              <AmountPaise>5000000</AmountPaise>
            </Item>
            <Item>
              <ItemSeqNo>00002</ItemSeqNo>
              <ItemExpiryTime>000000007062026160000</ItemExpiryTime>
              <PPS_Flag>N</PPS_Flag>
              <MICRLine>000099990050000099900000000099900999999999</MICRLine>
              <DraweeIFSC>SBIN0000456</DraweeIFSC>
              <DraweeAccount>SB99999999901</DraweeAccount>
              <AmountPaise>1000000</AmountPaise>
            </Item>
          </BatchGroup>
        </PresentmentExchangeFile>
    """).encode("utf-8")


class TestPXFParserBasic:
    """Core parsing contract."""

    def test_parse_returns_list_of_instruments(self):
        from modules.cts.ngch.pxf_parser import PXFParser

        parser = PXFParser()
        instruments = parser.parse(_make_pxf_xml())
        assert isinstance(instruments, list)
        assert len(instruments) == 1

    def test_instrument_has_required_fields(self):
        from modules.cts.ngch.pxf_parser import PXFParser

        parser = PXFParser()
        instruments = parser.parse(_make_pxf_xml())
        inst = instruments[0]
        assert hasattr(inst, "iet_deadline")
        assert hasattr(inst, "pps_flag")
        assert hasattr(inst, "clearing_type")
        assert hasattr(inst, "udk")
        assert hasattr(inst, "micr_line")
        assert hasattr(inst, "drawee_ifsc")
        assert hasattr(inst, "drawee_account")
        assert hasattr(inst, "amount_paise")
        assert hasattr(inst, "item_seq_no")

    def test_two_items_returns_two_instruments(self):
        from modules.cts.ngch.pxf_parser import PXFParser

        parser = PXFParser()
        instruments = parser.parse(_make_two_item_pxf_xml())
        assert len(instruments) == 2


class TestIETDeadlineExtraction:
    """IET deadline must come from ItemExpiryTime, not config."""

    def test_iet_deadline_is_float(self):
        from modules.cts.ngch.pxf_parser import PXFParser

        parser = PXFParser()
        inst = parser.parse(_make_pxf_xml(item_expiry_time="000000007062026160000"))[0]
        assert isinstance(inst.iet_deadline, float)

    def test_iet_deadline_matches_item_expiry_time(self):
        """Parser must use the per-item ItemExpiryTime, not a default."""
        from modules.cts.ngch.pxf_parser import PXFParser
        from modules.cts.ngch.pxf_iet_parser import iet_to_unix_timestamp

        expected = iet_to_unix_timestamp("000000007062026160000")
        parser = PXFParser()
        inst = parser.parse(_make_pxf_xml(item_expiry_time="000000007062026160000"))[0]
        assert abs(inst.iet_deadline - expected) < 1.0

    def test_two_items_have_different_iet_deadlines(self):
        from modules.cts.ngch.pxf_parser import PXFParser

        parser = PXFParser()
        instruments = parser.parse(_make_two_item_pxf_xml())
        assert instruments[0].iet_deadline != instruments[1].iet_deadline

    def test_later_item_expiry_time_has_larger_deadline(self):
        from modules.cts.ngch.pxf_parser import PXFParser

        parser = PXFParser()
        instruments = parser.parse(_make_two_item_pxf_xml())
        # Item 00001 has 15:00 IST, item 00002 has 16:00 IST
        assert instruments[1].iet_deadline > instruments[0].iet_deadline


class TestPPSFlagParsing:
    """All 7 PPS_Flag values must be parsed and preserved."""

    @pytest.mark.parametrize("flag", ["P", "D", "Y", "Z", "N", "R", "U"])
    def test_pps_flag_value_preserved(self, flag):
        from modules.cts.ngch.pxf_parser import PXFParser

        parser = PXFParser()
        inst = parser.parse(_make_pxf_xml(pps_flag=flag))[0]
        assert inst.pps_flag == flag

    def test_pps_flag_p_means_positive_pay_confirmed(self):
        from modules.cts.ngch.pxf_parser import PXFParser, PPSFlagMeaning

        parser = PXFParser()
        inst = parser.parse(_make_pxf_xml(pps_flag="P"))[0]
        assert inst.pps_flag_meaning == PPSFlagMeaning.CONFIRMED

    def test_pps_flag_z_means_cancelled(self):
        from modules.cts.ngch.pxf_parser import PXFParser, PPSFlagMeaning

        parser = PXFParser()
        inst = parser.parse(_make_pxf_xml(pps_flag="Z"))[0]
        assert inst.pps_flag_meaning == PPSFlagMeaning.CANCELLED

    def test_pps_flag_n_means_no_pps(self):
        from modules.cts.ngch.pxf_parser import PXFParser, PPSFlagMeaning

        parser = PXFParser()
        inst = parser.parse(_make_pxf_xml(pps_flag="N"))[0]
        assert inst.pps_flag_meaning == PPSFlagMeaning.NO_PPS


class TestClearingType:
    """ClearingType must be parsed and mapped to enum."""

    def test_clearing_type_01_is_normal(self):
        from modules.cts.ngch.pxf_parser import PXFParser, ClearingType

        parser = PXFParser()
        inst = parser.parse(_make_pxf_xml(clearing_type="01"))[0]
        assert inst.clearing_type == ClearingType.NORMAL

    def test_clearing_type_14_is_on_realization(self):
        from modules.cts.ngch.pxf_parser import PXFParser, ClearingType

        parser = PXFParser()
        inst = parser.parse(_make_pxf_xml(clearing_type="14"))[0]
        assert inst.clearing_type == ClearingType.ON_REALIZATION

    def test_on_realization_flag_accessible(self):
        from modules.cts.ngch.pxf_parser import PXFParser

        parser = PXFParser()
        inst_normal = parser.parse(_make_pxf_xml(clearing_type="01"))[0]
        inst_or = parser.parse(_make_pxf_xml(clearing_type="14"))[0]
        assert not inst_normal.is_on_realization
        assert inst_or.is_on_realization


class TestUDKConstruction:
    """UDK = PresentmentDate(8) + PresentingBankRoutNo(9) + CycleNo(2) + ItemSeqNo(5)."""

    def test_udk_is_24_chars(self):
        from modules.cts.ngch.pxf_parser import PXFParser

        parser = PXFParser()
        inst = parser.parse(_make_pxf_xml())[0]
        assert len(inst.udk) == 24

    def test_udk_components_in_correct_order(self):
        """PresentmentDate(8) + PresentingBankRoutNo(9) + CycleNo(2) + ItemSeqNo(5)."""
        from modules.cts.ngch.pxf_parser import PXFParser

        parser = PXFParser()
        inst = parser.parse(_make_pxf_xml(
            presentment_date="07062026",
            presenting_bank_rout_no="000550050",
            cycle_no="01",
            item_seq_no="00001",
        ))[0]
        assert inst.udk == "07062026" + "000550050" + "01" + "00001"

    def test_udk_different_for_different_items(self):
        from modules.cts.ngch.pxf_parser import PXFParser

        parser = PXFParser()
        instruments = parser.parse(_make_two_item_pxf_xml())
        assert instruments[0].udk != instruments[1].udk


class TestFieldExtraction:
    """Other mandatory fields are extracted correctly."""

    def test_micr_line_preserved(self):
        from modules.cts.ngch.pxf_parser import PXFParser

        micr = "000012340050000012100000000005000123456789"
        parser = PXFParser()
        inst = parser.parse(_make_pxf_xml(micr_line=micr))[0]
        assert inst.micr_line == micr

    def test_drawee_ifsc_preserved(self):
        from modules.cts.ngch.pxf_parser import PXFParser

        parser = PXFParser()
        inst = parser.parse(_make_pxf_xml(drawee_ifsc="HDFC0001234"))[0]
        assert inst.drawee_ifsc == "HDFC0001234"

    def test_drawee_account_preserved(self):
        from modules.cts.ngch.pxf_parser import PXFParser

        parser = PXFParser()
        inst = parser.parse(_make_pxf_xml(drawee_account="ACC9999999901"))[0]
        assert inst.drawee_account == "ACC9999999901"

    def test_amount_paise_is_int(self):
        from modules.cts.ngch.pxf_parser import PXFParser

        parser = PXFParser()
        inst = parser.parse(_make_pxf_xml(amount_paise=5000000))[0]
        assert inst.amount_paise == 5_000_000

    def test_item_seq_no_preserved(self):
        from modules.cts.ngch.pxf_parser import PXFParser

        parser = PXFParser()
        inst = parser.parse(_make_pxf_xml(item_seq_no="00042"))[0]
        assert inst.item_seq_no == "00042"


class TestPXFParserErrors:
    """Error handling for malformed PXF."""

    def test_empty_xml_raises(self):
        from modules.cts.ngch.pxf_parser import PXFParser, PXFParseError

        parser = PXFParser()
        with pytest.raises(PXFParseError):
            parser.parse(b"")

    def test_invalid_xml_raises(self):
        from modules.cts.ngch.pxf_parser import PXFParser, PXFParseError

        parser = PXFParser()
        with pytest.raises(PXFParseError):
            parser.parse(b"not xml at all")

    def test_bad_item_expiry_time_raises(self):
        from modules.cts.ngch.pxf_parser import PXFParser, PXFParseError

        parser = PXFParser()
        # ItemExpiryTime with wrong length — must raise PXFParseError (wrapping IETParseError)
        with pytest.raises(PXFParseError):
            parser.parse(_make_pxf_xml(item_expiry_time="BAD_IET"))
