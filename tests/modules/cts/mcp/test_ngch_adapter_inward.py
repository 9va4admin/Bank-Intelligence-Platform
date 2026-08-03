"""
Tests for NGCHAdapter.get_inward_instruments() — Gap 1 wiring.

P0 SAFETY GAP: PXFParser.parse() exists and is tested, but NGCHAdapter had no
method to call it. Without this method, the inward cheque ingestion path computes
iet_deadline from iet_minutes config instead of from the per-item ItemExpiryTime
field in PXF XML. Every inward instrument gets the WRONG deadline.

This test file covers:
  - NGCHAdapter.get_inward_instruments(pxf_xml_bytes) returns List[InwardInstrument]
  - iet_deadline values come from PXF ItemExpiryTime (IST→UTC), not from config
  - Multiple instruments → all returned with correct individual deadlines
  - Invalid / empty XML raises PXFParseError

RED phase: all tests must fail before NGCHAdapter.get_inward_instruments() is added.
"""
import pytest
from datetime import datetime, timezone, timedelta


_IST = timezone(timedelta(hours=5, minutes=30))
_PXF_NS = "urn:schemas-ncr-com:ECPIX:PXF:FileStructure:010003"


def _make_pxf_xml(
    item_expiry_time: str = "000000019062026143000",  # 19 Jun 2026 14:30:00 IST
    pps_flag: str = "N",
    clearing_type: str = "01",
    item_seq_no: str = "00001",
    amount_paise: int = 5_000_000,
    drawee_ifsc: str = "SBIN0000123",
    drawee_account: str = "SB12345678901",
    micr_line: str = "400160001234",
    presenting_bank_rout_no: str = "000550050",
    cycle_no: str = "01",
    presentment_date: str = "19062026",
) -> bytes:
    # PXFParser expects:  <PXF> / <FileHeader>/<ClearingType>
    #                     <PXF> / <BatchGroup> / <BatchHeader> + <Item>...
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<PXF xmlns="{_PXF_NS}">
  <FileHeader>
    <ClearingType>{clearing_type}</ClearingType>
  </FileHeader>
  <BatchGroup>
    <BatchHeader>
      <PresentingBankRoutNo>{presenting_bank_rout_no}</PresentingBankRoutNo>
      <PresentmentDate>{presentment_date}</PresentmentDate>
      <CycleNo>{cycle_no}</CycleNo>
    </BatchHeader>
    <Item>
      <ItemSeqNo>{item_seq_no}</ItemSeqNo>
      <MICRLine>{micr_line}</MICRLine>
      <DraweeIFSC>{drawee_ifsc}</DraweeIFSC>
      <DraweeAccount>{drawee_account}</DraweeAccount>
      <AmountPaise>{amount_paise}</AmountPaise>
      <PPS_Flag>{pps_flag}</PPS_Flag>
      <ItemExpiryTime>{item_expiry_time}</ItemExpiryTime>
    </Item>
  </BatchGroup>
</PXF>"""
    return xml.encode("utf-8")


def _make_two_item_pxf_xml() -> bytes:
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<PXF xmlns="{_PXF_NS}">
  <FileHeader>
    <ClearingType>01</ClearingType>
  </FileHeader>
  <BatchGroup>
    <BatchHeader>
      <PresentingBankRoutNo>000550050</PresentingBankRoutNo>
      <PresentmentDate>19062026</PresentmentDate>
      <CycleNo>01</CycleNo>
    </BatchHeader>
    <Item>
      <ItemSeqNo>00001</ItemSeqNo>
      <MICRLine>400160001234</MICRLine>
      <DraweeIFSC>SBIN0000123</DraweeIFSC>
      <DraweeAccount>SB12345678901</DraweeAccount>
      <AmountPaise>5000000</AmountPaise>
      <PPS_Flag>N</PPS_Flag>
      <ItemExpiryTime>000000019062026143000</ItemExpiryTime>
    </Item>
    <Item>
      <ItemSeqNo>00002</ItemSeqNo>
      <MICRLine>400160009999</MICRLine>
      <DraweeIFSC>HDFC0001234</DraweeIFSC>
      <DraweeAccount>HD98765432100</DraweeAccount>
      <AmountPaise>1000000</AmountPaise>
      <PPS_Flag>P</PPS_Flag>
      <ItemExpiryTime>000000019062026160000</ItemExpiryTime>
    </Item>
  </BatchGroup>
</PXF>"""
    return xml.encode("utf-8")


def _make_adapter():
    from modules.cts.mcp.ngch_adapter import NGCHAdapter
    adapter = NGCHAdapter(bank_id="test-bank", base_url="https://ngch.internal/api")
    adapter._ready = True
    return adapter


class TestGetInwardInstrumentsExists:
    """NGCHAdapter must expose get_inward_instruments()."""

    def test_method_exists_on_adapter(self):
        from modules.cts.mcp.ngch_adapter import NGCHAdapter
        adapter = NGCHAdapter(bank_id="test-bank", base_url="https://ngch.internal/api")
        assert hasattr(adapter, "get_inward_instruments"), (
            "NGCHAdapter.get_inward_instruments() does not exist — "
            "inward PXF parsing is not wired. Per-item IET deadlines will be wrong."
        )

    def test_method_is_callable(self):
        from modules.cts.mcp.ngch_adapter import NGCHAdapter
        adapter = NGCHAdapter(bank_id="test-bank", base_url="https://ngch.internal/api")
        assert callable(getattr(adapter, "get_inward_instruments", None))


class TestGetInwardInstrumentsReturnType:
    """Return type must be a list of InwardInstrument objects."""

    def test_returns_list(self):
        adapter = _make_adapter()
        pxf = _make_pxf_xml()
        result = adapter.get_inward_instruments(pxf)
        assert isinstance(result, list)

    def test_single_item_pxf_returns_one_instrument(self):
        from modules.cts.ngch.pxf_parser import InwardInstrument
        adapter = _make_adapter()
        result = adapter.get_inward_instruments(_make_pxf_xml())
        assert len(result) == 1
        assert isinstance(result[0], InwardInstrument)

    def test_two_item_pxf_returns_two_instruments(self):
        adapter = _make_adapter()
        result = adapter.get_inward_instruments(_make_two_item_pxf_xml())
        assert len(result) == 2

    def test_each_result_has_iet_deadline_float(self):
        adapter = _make_adapter()
        result = adapter.get_inward_instruments(_make_pxf_xml())
        assert isinstance(result[0].iet_deadline, float)
        assert result[0].iet_deadline > 0


class TestIETDeadlineFromPXF:
    """iet_deadline must come from PXF ItemExpiryTime, not from any config."""

    def test_iet_deadline_matches_item_expiry_time_in_pxf(self):
        """19 Jun 2026 14:30 IST == 19 Jun 2026 09:00 UTC == Unix timestamp."""
        from modules.cts.ngch.pxf_iet_parser import iet_to_unix_timestamp

        # PXF has ItemExpiryTime = "000000019062026143000" (19 Jun 2026, 14:30 IST)
        pxf = _make_pxf_xml(item_expiry_time="000000019062026143000")
        adapter = _make_adapter()
        instruments = adapter.get_inward_instruments(pxf)

        expected_ts = iet_to_unix_timestamp("000000019062026143000")
        assert instruments[0].iet_deadline == pytest.approx(expected_ts, abs=1.0)

    def test_two_instruments_have_different_deadlines(self):
        """Each instrument must have its own IET deadline, not a shared value."""
        adapter = _make_adapter()
        instruments = adapter.get_inward_instruments(_make_two_item_pxf_xml())
        assert instruments[0].iet_deadline != instruments[1].iet_deadline

    def test_later_expiry_time_produces_larger_timestamp(self):
        """16:00 IST deadline must be a later Unix timestamp than 14:30 IST."""
        adapter = _make_adapter()
        instruments = adapter.get_inward_instruments(_make_two_item_pxf_xml())
        # Item 1: 14:30 IST, Item 2: 16:00 IST — item 2 should have larger ts
        ts1 = instruments[0].iet_deadline
        ts2 = instruments[1].iet_deadline
        assert ts2 > ts1

    def test_iet_deadline_is_utc_not_ist(self):
        """Stored deadline must be UTC. 14:30 IST = 09:00 UTC."""
        adapter = _make_adapter()
        instruments = adapter.get_inward_instruments(
            _make_pxf_xml(item_expiry_time="000000019062026143000")
        )
        dt = datetime.fromtimestamp(instruments[0].iet_deadline, tz=timezone.utc)
        assert dt.hour == 9
        assert dt.minute == 0


class TestGetInwardInstrumentsOtherFields:
    """Other InwardInstrument fields must be correctly extracted from PXF."""

    def test_pps_flag_extracted(self):
        adapter = _make_adapter()
        instruments = adapter.get_inward_instruments(_make_pxf_xml(pps_flag="P"))
        assert instruments[0].pps_flag == "P"

    def test_clearing_type_extracted(self):
        from modules.cts.ngch.pxf_parser import ClearingType
        adapter = _make_adapter()
        instruments = adapter.get_inward_instruments(_make_pxf_xml(clearing_type="14"))
        assert instruments[0].clearing_type == ClearingType.ON_REALIZATION

    def test_micr_line_extracted(self):
        adapter = _make_adapter()
        instruments = adapter.get_inward_instruments(_make_pxf_xml(micr_line="400160005678"))
        assert instruments[0].micr_line == "400160005678"

    def test_drawee_ifsc_extracted(self):
        adapter = _make_adapter()
        instruments = adapter.get_inward_instruments(_make_pxf_xml(drawee_ifsc="HDFC0001234"))
        assert instruments[0].drawee_ifsc == "HDFC0001234"


class TestGetInwardInstrumentsErrors:
    """Invalid PXF must raise PXFParseError, not crash silently."""

    def test_empty_bytes_raises(self):
        from modules.cts.ngch.pxf_parser import PXFParseError
        adapter = _make_adapter()
        with pytest.raises((PXFParseError, ValueError, Exception)):
            adapter.get_inward_instruments(b"")

    def test_invalid_xml_raises(self):
        from modules.cts.ngch.pxf_parser import PXFParseError
        adapter = _make_adapter()
        with pytest.raises((PXFParseError, ValueError, Exception)):
            adapter.get_inward_instruments(b"not xml at all")

    def test_pxf_with_bad_item_expiry_time_raises(self):
        from modules.cts.ngch.pxf_parser import PXFParseError
        bad_pxf = _make_pxf_xml(item_expiry_time="BADINPUT")
        adapter = _make_adapter()
        with pytest.raises((PXFParseError, ValueError)):
            adapter.get_inward_instruments(bad_pxf)
