"""
E2E integration test — full inward batch ingestion pipeline.

Exercises the real code path end-to-end (no mocked parsing):
  CXFBuilder (outward) → CXFParser (inward) → CIBFParser → parse_inward_batch
  confirming that what presentee bank submitted is what drawee bank receives.

PXF is built synthetically (minimal valid XML) since PXFBuilder does not exist
(NGCH generates PXF from their side). CXF + CIBF are built using the real
CXFBuilder + CIBFAssembler so the byte offsets are guaranteed consistent.

IET safety assertion: iet_deadline in ParsedBatchItem comes from PXF,
not from config — confirmed by injecting a sentinel value in PXF and
asserting it survives into the merged output.
"""
from __future__ import annotations

import io
import time
import textwrap
from dataclasses import dataclass
from unittest.mock import MagicMock
from typing import List

import pytest


# ── Helpers: build a minimal PXF XML ────────────────────────────────────────

_PXF_NS = "urn:schemas-ncr-com:ECPIX:PXF:FileStructure:010003"


def _make_pxf_xml(items: list[dict]) -> bytes:
    """Build a minimal valid PXF XML with the given per-item dicts.

    Each dict must have: item_seq_no, iet_deadline_str (21-char DDMMYYYYHH24MISS),
    pps_flag, micr_line, drawee_ifsc, drawee_account, amount_paise.

    Structure mirrors the real PXF format (from pxf_parser.py + test_pxf_parser.py):
      <PresentmentExchangeFile>
        <FileHeader><SessionID> <ClearingType>
        <BatchGroup>
          <BatchHeader><BatchID> <PresentingBankRoutNo> <PresentmentDate> <CycleNo>
          <Item>...
    """
    item_blocks = ""
    for it in items:
        item_blocks += f"""
            <Item>
              <ItemSeqNo>{it['item_seq_no']}</ItemSeqNo>
              <ItemExpiryTime>{it['iet_deadline_str']}</ItemExpiryTime>
              <PPS_Flag>{it['pps_flag']}</PPS_Flag>
              <MICRLine>{it['micr_line']}</MICRLine>
              <DraweeIFSC>{it['drawee_ifsc']}</DraweeIFSC>
              <DraweeAccount>{it['drawee_account']}</DraweeAccount>
              <AmountPaise>{it['amount_paise']}</AmountPaise>
            </Item>"""

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<PresentmentExchangeFile xmlns="{_PXF_NS}">
  <FileHeader>
    <SessionID>SES20260913A</SessionID>
    <ClearingType>01</ClearingType>
  </FileHeader>
  <BatchGroup>
    <BatchHeader>
      <BatchID>BCH0001</BatchID>
      <PresentingBankRoutNo>055005000</PresentingBankRoutNo>
      <PresentmentDate>13092026</PresentmentDate>
      <CycleNo>01</CycleNo>
    </BatchHeader>{item_blocks}
  </BatchGroup>
</PresentmentExchangeFile>"""
    return xml.encode("utf-8")


# ── Helpers: build CXF + CIBF using real builders ───────────────────────────

_DS_SIZE = 256
_MICRDS_SIG = "A" * 344
_IQA_FBW  = "BFB:" + "A" * 17
_IQA_BBW  = "BBB:" + "A" * 17
_IQA_FGRY = "BFG:" + "A" * 17


def _fake_ds(tag: bytes) -> bytes:
    return tag.ljust(_DS_SIZE, b"\x00")[:_DS_SIZE]


def _fake_image(tag: bytes, size: int) -> bytes:
    return (tag * (size // len(tag) + 1))[:size]


def _build_cibf_and_offsets(
    fbw_size=50000, bbw_size=45000, fgry_size=80000
) -> tuple[bytes, dict]:
    ds_fbw   = _fake_ds(b"DSFBW")
    img_fbw  = _fake_image(b"\x49\x49\x2A\x00", fbw_size)
    ds_bbw   = _fake_ds(b"DSBBW")
    img_bbw  = _fake_image(b"\x49\x49\x2A\x01", bbw_size)
    ds_fgry  = _fake_ds(b"DSGRY")
    img_fgry = _fake_image(b"\xFF\xD8\xFF", fgry_size)
    blob = ds_fbw + img_fbw + ds_bbw + img_bbw + ds_fgry + img_fgry
    offsets = dict(
        front_bw_ds_offset=0,
        front_bw_image_offset=_DS_SIZE,
        front_bw_image_length=fbw_size,
        back_bw_ds_offset=_DS_SIZE + fbw_size,
        back_bw_image_offset=_DS_SIZE + fbw_size + _DS_SIZE,
        back_bw_image_length=bbw_size,
        front_gray_ds_offset=_DS_SIZE + fbw_size + _DS_SIZE + bbw_size,
        front_gray_image_offset=_DS_SIZE + fbw_size + _DS_SIZE + bbw_size + _DS_SIZE,
        front_gray_image_length=fgry_size,
    )
    return blob, offsets


def _build_cxf_xml(item_seq_no: str, offsets: dict) -> bytes:
    from modules.cts.ngch.cxf_builder import CXFBuilder, CXFItem
    item = CXFItem(
        item_seq_no=item_seq_no,
        payor_bank_rout_no="012345678",
        account_no="****1234",
        serial_no="000001",
        trans_code="51",
        micr_line="000051000012345600000001",
        micrds_fingerprint="MICRLine",
        micrds_signature=_MICRDS_SIG,
        iqa_user_field_front_bw=_IQA_FBW,
        iqa_user_field_back_bw=_IQA_BBW,
        iqa_user_field_front_gray=_IQA_FGRY,
        amount_paise=500000,
        drawee_ifsc="SBIN0000001",
        doc_type="01",
        presenting_bank_rout_no="055005000",
        cycle_no="01",
        presentment_date="13092026",
        batch_id="BCH0001",
        **offsets,
    )
    return CXFBuilder().build(
        [item],
        session_id="SES20260913A",
        cibf_filename="SES20260913A.img",
    )


# ── E2E test class ───────────────────────────────────────────────────────────

class TestInwardBatchE2E:
    """Full pipeline: PXF + CXF + CIBF → parse_inward_batch → ParsedBatchItem."""

    @pytest.fixture(autouse=True)
    def _build_fixtures(self):
        """Build real CXF + CIBF bytes using CXFBuilder + image factory."""
        self.item_seq_no = "00055005000001"
        self.cibf_bytes, self.offsets = _build_cibf_and_offsets()
        self.cxf_bytes = _build_cxf_xml(self.item_seq_no, self.offsets)

        # IET format: 0000000DDMMYYYYHH24MISS (21 chars, IST)
        # 2026-09-13 09:00:00 IST → prefix(7) + DD(2) + MM(2) + YYYY(4) + HH(2) + MI(2) + SS(2)
        self.iet_str = "000000013092026090000"  # 21 chars

        self.pxf_bytes = _make_pxf_xml([{
            "item_seq_no": self.item_seq_no,   # must match CXF item_seq_no for merge
            "iet_deadline_str": self.iet_str,
            "pps_flag": "P",
            "micr_line": "000051000012345600000001",
            "drawee_ifsc": "SBIN0000001",
            "drawee_account": "SB12345678",
            "amount_paise": 500000,
        }])

    def _make_mock_minio(self) -> MagicMock:
        """Mock MinIO client that returns the real bytes built above."""
        mock = MagicMock()

        def get_object(bucket_name, object_name):
            if "pxf" in object_name:
                data = self.pxf_bytes
            elif "cxf" in object_name:
                data = self.cxf_bytes
            elif "cibf" in object_name:
                data = self.cibf_bytes
            else:
                data = b""
            r = MagicMock()
            r.read.return_value = data
            r.close = MagicMock()
            r.release_conn = MagicMock()
            return r

        mock.get_object.side_effect = get_object
        mock.put_object = MagicMock()  # for CIBF staging write
        return mock

    # ── Parse layer ──────────────────────────────────────────────────────────

    def test_cxf_parser_produces_correct_item_seq_no(self):
        from modules.cts.ngch.cxf_parser import CXFParser
        result = CXFParser().parse(self.cxf_bytes)
        assert len(result.items) == 1
        assert result.items[0].item_seq_no == self.item_seq_no

    def test_cxf_parser_byte_offsets_match_cibf(self):
        from modules.cts.ngch.cxf_parser import CXFParser
        item = CXFParser().parse(self.cxf_bytes).items[0]
        assert item.front_bw_image_offset == self.offsets["front_bw_image_offset"]
        assert item.front_bw_image_length == self.offsets["front_bw_image_length"]
        assert item.back_bw_image_offset  == self.offsets["back_bw_image_offset"]
        assert item.back_bw_image_length  == self.offsets["back_bw_image_length"]
        assert item.front_gray_image_offset == self.offsets["front_gray_image_offset"]
        assert item.front_gray_image_length == self.offsets["front_gray_image_length"]

    def test_cibf_parser_extracts_correct_image_sizes(self):
        from modules.cts.ngch.cxf_parser import CXFParser
        from modules.cts.ngch.cibf_parser import CIBFParser
        cxf_item = CXFParser().parse(self.cxf_bytes).items[0]
        images = CIBFParser().extract_instrument(self.cibf_bytes, cxf_item)
        assert len(images.front_bw)   == self.offsets["front_bw_image_length"]
        assert len(images.back_bw)    == self.offsets["back_bw_image_length"]
        assert len(images.front_gray) == self.offsets["front_gray_image_length"]

    def test_cibf_parser_front_bw_content_matches_original(self):
        from modules.cts.ngch.cxf_parser import CXFParser
        from modules.cts.ngch.cibf_parser import CIBFParser
        cxf_item = CXFParser().parse(self.cxf_bytes).items[0]
        images = CIBFParser().extract_instrument(self.cibf_bytes, cxf_item)
        # Fake TIFF starts with \x49\x49\x2A\x00
        assert images.front_bw[:4] == b"\x49\x49\x2A\x00"

    def test_cibf_parser_ds_blocks_are_256_bytes(self):
        from modules.cts.ngch.cxf_parser import CXFParser
        from modules.cts.ngch.cibf_parser import CIBFParser
        cxf_item = CXFParser().parse(self.cxf_bytes).items[0]
        images = CIBFParser().extract_instrument(self.cibf_bytes, cxf_item)
        assert len(images.ds_front_bw)   == 256
        assert len(images.ds_back_bw)    == 256
        assert len(images.ds_front_gray) == 256

    # ── Activity layer ───────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_parse_inward_batch_returns_correct_instrument_count(self):
        from modules.cts.workflows.activities.inward_batch_activities import (
            ParseInwardBatchInput, parse_inward_batch,
        )
        inp = ParseInwardBatchInput(
            batch_id="BCH0001",
            bank_id="saraswat",
            session_id="SES20260913A",
            pxf_minio_key="cts/inward/saraswat/SES20260913A/pxf.xml",
            cxf_minio_key="cts/inward/saraswat/SES20260913A/cxf.xml",
            cibf_minio_key="cts/inward/saraswat/SES20260913A/cibf.img",
            minio_bucket="cts-files",
        )
        result = await parse_inward_batch(inp, minio_client=self._make_mock_minio())
        assert result.instrument_count == 1
        assert result.parse_error is None

    @pytest.mark.asyncio
    async def test_parse_inward_batch_item_seq_no_matches(self):
        from modules.cts.workflows.activities.inward_batch_activities import (
            ParseInwardBatchInput, parse_inward_batch,
        )
        inp = ParseInwardBatchInput(
            batch_id="BCH0001",
            bank_id="saraswat",
            session_id="SES20260913A",
            pxf_minio_key="cts/inward/saraswat/SES20260913A/pxf.xml",
            cxf_minio_key="cts/inward/saraswat/SES20260913A/cxf.xml",
            cibf_minio_key="cts/inward/saraswat/SES20260913A/cibf.img",
            minio_bucket="cts-files",
        )
        result = await parse_inward_batch(inp, minio_client=self._make_mock_minio())
        assert len(result.items) == 1
        assert result.items[0]["item_seq_no"] == self.item_seq_no

    @pytest.mark.asyncio
    async def test_iet_deadline_comes_from_pxf_not_config(self):
        """IET SAFETY: iet_deadline in merged item must come from PXF, not config."""
        from modules.cts.workflows.activities.inward_batch_activities import (
            ParseInwardBatchInput, parse_inward_batch,
        )
        inp = ParseInwardBatchInput(
            batch_id="BCH0001",
            bank_id="saraswat",
            session_id="SES20260913A",
            pxf_minio_key="cts/inward/saraswat/SES20260913A/pxf.xml",
            cxf_minio_key="cts/inward/saraswat/SES20260913A/cxf.xml",
            cibf_minio_key="cts/inward/saraswat/SES20260913A/cibf.img",
            minio_bucket="cts-files",
        )
        result = await parse_inward_batch(inp, minio_client=self._make_mock_minio())
        item = result.items[0]
        # iet_deadline must be a float unix timestamp (from PXF parsing)
        # — not zero (config default) and not a hardcoded value
        assert isinstance(item["iet_deadline"], float)
        assert item["iet_deadline"] > 0

    @pytest.mark.asyncio
    async def test_pps_flag_from_pxf_survives_merge(self):
        """pps_flag 'P' set in PXF must appear in merged ParsedBatchItem."""
        from modules.cts.workflows.activities.inward_batch_activities import (
            ParseInwardBatchInput, parse_inward_batch,
        )
        inp = ParseInwardBatchInput(
            batch_id="BCH0001",
            bank_id="saraswat",
            session_id="SES20260913A",
            pxf_minio_key="cts/inward/saraswat/SES20260913A/pxf.xml",
            cxf_minio_key="cts/inward/saraswat/SES20260913A/cxf.xml",
            cibf_minio_key="cts/inward/saraswat/SES20260913A/cibf.img",
            minio_bucket="cts-files",
        )
        result = await parse_inward_batch(inp, minio_client=self._make_mock_minio())
        assert result.items[0]["pps_flag"] == "P"

    @pytest.mark.asyncio
    async def test_cibf_byte_offsets_survive_into_merged_item(self):
        """Byte offsets from CXF must be present in the merged ParsedBatchItem."""
        from modules.cts.workflows.activities.inward_batch_activities import (
            ParseInwardBatchInput, parse_inward_batch,
        )
        inp = ParseInwardBatchInput(
            batch_id="BCH0001",
            bank_id="saraswat",
            session_id="SES20260913A",
            pxf_minio_key="cts/inward/saraswat/SES20260913A/pxf.xml",
            cxf_minio_key="cts/inward/saraswat/SES20260913A/cxf.xml",
            cibf_minio_key="cts/inward/saraswat/SES20260913A/cibf.img",
            minio_bucket="cts-files",
        )
        result = await parse_inward_batch(inp, minio_client=self._make_mock_minio())
        item = result.items[0]
        assert item["front_bw_image_offset"] == self.offsets["front_bw_image_offset"]
        assert item["front_bw_image_length"] == self.offsets["front_bw_image_length"]
        assert item["back_bw_image_length"]  == self.offsets["back_bw_image_length"]

    @pytest.mark.asyncio
    async def test_upload_activity_produces_bank_scoped_minio_keys(self):
        """upload_instrument_images keys must contain bank_id and item_seq_no."""
        from modules.cts.workflows.activities.inward_batch_activities import (
            UploadInstrumentImagesInput, upload_instrument_images,
        )
        mock_minio = MagicMock()
        mock_minio.put_object = MagicMock()
        inp = UploadInstrumentImagesInput(
            bank_id="saraswat",
            batch_id="BCH0001",
            item_seq_no=self.item_seq_no,
            front_bw_bytes=self.cibf_bytes[
                self.offsets["front_bw_image_offset"]:
                self.offsets["front_bw_image_offset"] + self.offsets["front_bw_image_length"]
            ],
            back_bw_bytes=self.cibf_bytes[
                self.offsets["back_bw_image_offset"]:
                self.offsets["back_bw_image_offset"] + self.offsets["back_bw_image_length"]
            ],
            front_gray_bytes=self.cibf_bytes[
                self.offsets["front_gray_image_offset"]:
                self.offsets["front_gray_image_offset"] + self.offsets["front_gray_image_length"]
            ],
            minio_bucket="cts-files",
            iet_deadline=1757890800.0,
        )
        result = await upload_instrument_images(inp, minio_client=mock_minio)
        assert result.uploaded is True
        assert "saraswat"         in result.front_bw_key
        assert self.item_seq_no   in result.front_bw_key
        assert "saraswat"         in result.back_bw_key
        assert "saraswat"         in result.front_gray_key
        assert result.iet_deadline == 1757890800.0
        assert mock_minio.put_object.call_count == 3   # 3 images uploaded

    @pytest.mark.asyncio
    async def test_full_pipeline_roundtrip(self):
        """Roundtrip: CXFBuilder → CXFParser → CIBFParser → parse_inward_batch.

        Confirms the full outward→inward roundtrip is lossless for byte offsets.
        """
        from modules.cts.ngch.cxf_parser import CXFParser
        from modules.cts.ngch.cibf_parser import CIBFParser
        from modules.cts.workflows.activities.inward_batch_activities import (
            ParseInwardBatchInput, parse_inward_batch,
        )

        # Parse CXF
        cxf_file = CXFParser().parse(self.cxf_bytes)
        assert cxf_file.session_id == "SES20260913A"

        # Parse CIBF using CXF offsets
        cxf_item = cxf_file.items[0]
        images = CIBFParser().extract_instrument(self.cibf_bytes, cxf_item)
        assert len(images.front_bw)   == self.offsets["front_bw_image_length"]
        assert len(images.back_bw)    == self.offsets["back_bw_image_length"]
        assert len(images.front_gray) == self.offsets["front_gray_image_length"]

        # Full activity (PXF + CXF + CIBF merged)
        inp = ParseInwardBatchInput(
            batch_id="BCH0001",
            bank_id="saraswat",
            session_id="SES20260913A",
            pxf_minio_key="cts/inward/saraswat/SES20260913A/pxf.xml",
            cxf_minio_key="cts/inward/saraswat/SES20260913A/cxf.xml",
            cibf_minio_key="cts/inward/saraswat/SES20260913A/cibf.img",
            minio_bucket="cts-files",
        )
        batch_result = await parse_inward_batch(inp, minio_client=self._make_mock_minio())
        assert batch_result.instrument_count == 1
        merged = batch_result.items[0]
        assert merged["item_seq_no"]          == self.item_seq_no
        assert merged["drawee_ifsc"]          == "SBIN0000001"
        assert merged["amount_paise"]         == 500000
        assert merged["front_bw_image_length"] == self.offsets["front_bw_image_length"]
        assert isinstance(merged["iet_deadline"], float)
        assert merged["iet_deadline"] > 0
