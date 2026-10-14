"""
Tests for modules/cts/lot/lot_store.py — CHI Spec Rev 3.00

LotStore.build_ngch_file() must now call the CHI Spec Rev 3.00 compliant
builder and produce spec-compliant CXF XML + CIBF binary files.
"""
import hashlib
import io
import xml.etree.ElementTree as ET
from unittest.mock import AsyncMock, MagicMock

import pytest

_CXF_NS = "urn:schemas-ncr-com:ECPIX:CXF:FileStructure:010005"

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _fake_tiff(seed: int = 0) -> bytes:
    """Minimal TIFF magic bytes — satisfies IQA T17 image-format check."""
    return b"\x49\x49\x2A\x00" + seed.to_bytes(4, "little") + b"\x00" * 100


def _fake_jfif(seed: int = 0) -> bytes:
    """Minimal JFIF/JPEG magic bytes."""
    return b"\xFF\xD8\xFF\xE0" + seed.to_bytes(4, "big") + b"\x00" * 100


def _mock_hsm() -> MagicMock:
    """HSM that always returns 256 zero bytes for signing (not cryptographic)."""
    hsm = MagicMock()
    hsm.sign.return_value = b"\x00" * 256
    return hsm


def _instr_row(num: int) -> dict:
    return {
        "instrument_id": f"INST-{num:03d}",
        "cheque_number": f"{100000 + num}",
        "micr_code": f"40005300{num}",
        "drawee_ifsc": "SVCB0000001",
        "presenting_ifsc": "SVCB0000002",
        "presenting_bank_rout_no": "000550050",
        "payor_bank_rout_no": f"40005300{num}",
        "trans_code": "01",
        "doc_type": "01",
        "amount_paise": 5_000_000 + num * 1_000_000,
        "cheque_date": "2026-09-01",
        "account_last4": f"{4521 + num}",
        "image_front_bw_key": f"cts/test-bank/INST-{num:03d}/front_bw.tif",
        "image_back_bw_key": f"cts/test-bank/INST-{num:03d}/back_bw.tif",
        "image_front_gray_key": f"cts/test-bank/INST-{num:03d}/front_gray.jpg",
        "width_px": 1728,
        "height_px": 816,
        "dpi": 200,
        "bit_depth": 1,
        "cycle_no": "AM",
    }


def _mock_db(n_instruments: int = 2):
    conn = AsyncMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)

    pool = AsyncMock()
    pool.acquire = MagicMock(return_value=conn)

    instr_rows = [_instr_row(i) for i in range(1, n_instruments + 1)]
    conn.fetch = AsyncMock(return_value=instr_rows)
    return pool, conn


def _mock_minio(n_instruments: int = 2):
    """MinIO client mock that serves fake image bytes and records put calls."""
    minio = MagicMock()

    # get_object returns an object whose .read() gives fake image bytes
    def _get_object(bucket, key):
        resp = MagicMock()
        if "gray" in key:
            resp.read.return_value = _fake_jfif(seed=hash(key) & 0xFF)
        else:
            resp.read.return_value = _fake_tiff(seed=hash(key) & 0xFF)
        return resp

    minio.get_object = MagicMock(side_effect=_get_object)
    minio.put_object = MagicMock()
    return minio


def _call_build(store, n: int = 2, **kwargs):
    """Convenience: call store.build_ngch_file() with defaults."""
    defaults = dict(
        lot_number="LOT_SVCB0000002_20260901_AM_01",
        bank_id="test-bank",
        bank_ifsc="SVCB0000002",
        session_id="SES-ABC001",
        clearing_date="2026-09-01",
        routing_no="000550050",
        clearing_type="14",
        file_id="0001",
        date_ddmmyyyy="01092026",
        time_hhmmss="103000",
        hsm=_mock_hsm(),
    )
    defaults.update(kwargs)
    return store.build_ngch_file(**defaults)


# ---------------------------------------------------------------------------
# Import helper — build LotStore
# ---------------------------------------------------------------------------

def _store(n_instruments: int = 2):
    from modules.cts.lot.lot_store import LotStore
    pool, _ = _mock_db(n_instruments)
    minio = _mock_minio(n_instruments)
    return LotStore(db_pool=pool, minio_client=minio, bucket="astra-cts"), minio


# ---------------------------------------------------------------------------
# Suite: return values
# ---------------------------------------------------------------------------

class TestReturnValues:
    @pytest.mark.asyncio
    async def test_returns_cxf_path_and_checksum(self):
        store, _ = _store()
        cxf_path, checksum = await _call_build(store)
        assert cxf_path.startswith("cts/ngch/test-bank/")
        assert len(checksum) == 64
        assert all(c in "0123456789abcdef" for c in checksum)

    @pytest.mark.asyncio
    async def test_cxf_path_contains_chi_spec_filename(self):
        """CXF object key must embed the CHI Spec filename."""
        store, _ = _store()
        cxf_path, _ = await _call_build(store)
        # CHI Spec: CXF_{RoutingNo}_{DDMMYYYY}_{HHMMSS}_{ClearingType}_{FileID}.XML
        assert "CXF_000550050_01092026_103000_14_0001.XML" in cxf_path

    @pytest.mark.asyncio
    async def test_checksum_matches_cxf_bytes(self):
        """SHA-256 in return value must match actual CXF bytes uploaded."""
        store, minio = _store()
        _, checksum = await _call_build(store)

        # First put_object call is the CXF upload
        calls = minio.put_object.call_args_list
        cxf_call = calls[0]
        # positional: bucket, key, data_io, length, content_type
        uploaded_bytes = cxf_call[0][2].read() if cxf_call[0] else cxf_call[1]["data"].read()
        assert hashlib.sha256(uploaded_bytes).hexdigest() == checksum


# ---------------------------------------------------------------------------
# Suite: MinIO upload behaviour
# ---------------------------------------------------------------------------

class TestMinIOUploads:
    @pytest.mark.asyncio
    async def test_put_object_called_twice_cxf_and_cibf(self):
        """Two MinIO uploads: CXF (XML) and CIBF (binary)."""
        store, minio = _store()
        await _call_build(store)
        assert minio.put_object.call_count == 2

    @pytest.mark.asyncio
    async def test_cxf_upload_content_type_is_xml(self):
        store, minio = _store()
        await _call_build(store)
        cxf_call = minio.put_object.call_args_list[0]
        ct = cxf_call.kwargs.get("content_type") or cxf_call[0][4]
        assert ct == "application/xml"

    @pytest.mark.asyncio
    async def test_cibf_upload_content_type_is_octet_stream(self):
        store, minio = _store()
        await _call_build(store)
        cibf_call = minio.put_object.call_args_list[1]
        ct = cibf_call.kwargs.get("content_type") or cibf_call[0][4]
        assert ct == "application/octet-stream"

    @pytest.mark.asyncio
    async def test_cibf_key_contains_chi_spec_filename(self):
        store, minio = _store()
        await _call_build(store)
        cibf_call = minio.put_object.call_args_list[1]
        key = cibf_call[0][1]
        assert "CIBF_000550050_01092026_103000_14_0001_01.img" in key


# ---------------------------------------------------------------------------
# Suite: CXF XML content — CHI Spec Rev 3.00
# ---------------------------------------------------------------------------

class TestCXFContent:
    def _parse_cxf(self, minio: MagicMock) -> ET.Element:
        cxf_bytes = minio.put_object.call_args_list[0][0][2].read()
        xml_str = cxf_bytes.decode("utf-8").replace(f' xmlns="{_CXF_NS}"', "")
        return ET.fromstring(xml_str)

    @pytest.mark.asyncio
    async def test_root_element_is_FileHeader(self):
        """CHI Spec root is <FileHeader>, NOT <CXF> or <PresentmentExchangeFile>."""
        store, minio = _store()
        await _call_build(store)
        root = self._parse_cxf(minio)
        assert root.tag == "FileHeader"

    @pytest.mark.asyncio
    async def test_item_count_in_FileSummary(self):
        """CHI Spec stores count in <FileSummary TotalItemCount=...>."""
        store, minio = _store(n_instruments=2)
        await _call_build(store)
        root = self._parse_cxf(minio)
        summary = root.find(".//FileSummary")
        assert summary is not None
        assert summary.get("TotalItemCount") == "2"

    @pytest.mark.asyncio
    async def test_items_are_attributes_not_child_elements(self):
        """CHI Spec encodes all item fields as XML attributes on <Item>, not child text."""
        store, minio = _store()
        await _call_build(store)
        root = self._parse_cxf(minio)
        items = root.findall(".//Item")
        assert len(items) == 2
        # Every item must have ItemSeqNo as an attribute (not as child)
        for item in items:
            assert item.get("ItemSeqNo") is not None, "ItemSeqNo must be an attribute"
            # Must NOT be a child element
            seq_children = [c for c in item if c.tag == "ItemSeqNo"]
            assert len(seq_children) == 0, "ItemSeqNo must NOT be a child element"

    @pytest.mark.asyncio
    async def test_three_image_views_per_item(self):
        """Each <Item> must have 3 <ImageViewDetail> children."""
        store, minio = _store()
        await _call_build(store)
        root = self._parse_cxf(minio)
        for item in root.findall(".//Item"):
            views = item.findall("ImageViewDetail")
            assert len(views) == 3, f"Expected 3 ImageViewDetail, got {len(views)}"

    @pytest.mark.asyncio
    async def test_micrds_present_on_each_item(self):
        """Each <Item> must have a <MICRDS> child with MICR fingerprint and signature."""
        store, minio = _store()
        await _call_build(store)
        root = self._parse_cxf(minio)
        for item in root.findall(".//Item"):
            micrds = item.find("MICRDS")
            assert micrds is not None
            assert micrds.get("MICRFingerPrint") is not None
            assert micrds.get("SignatureData") is not None

    @pytest.mark.asyncio
    async def test_item_seq_no_is_14_chars(self):
        """ItemSeqNo must be exactly 14 characters per CHI Spec."""
        store, minio = _store()
        await _call_build(store)
        root = self._parse_cxf(minio)
        for item in root.findall(".//Item"):
            seq = item.get("ItemSeqNo", "")
            assert len(seq) == 14, f"ItemSeqNo length {len(seq)} != 14: '{seq}'"


# ---------------------------------------------------------------------------
# Suite: CIBF binary content
# ---------------------------------------------------------------------------

class TestCIBFContent:
    @pytest.mark.asyncio
    async def test_cibf_is_nonempty_bytes(self):
        store, minio = _store()
        await _call_build(store)
        cibf_call = minio.put_object.call_args_list[1]
        cibf_bytes = cibf_call[0][2].read()
        assert len(cibf_bytes) > 0

    @pytest.mark.asyncio
    async def test_cibf_length_accounts_for_ds_and_images(self):
        """CIBF must be at least n_instruments × 3 × 256 bytes (DS headers only)."""
        n = 2
        store, minio = _store(n_instruments=n)
        await _call_build(store)
        cibf_call = minio.put_object.call_args_list[1]
        cibf_bytes = cibf_call[0][2].read()
        min_expected = n * 3 * 256
        assert len(cibf_bytes) >= min_expected


# ---------------------------------------------------------------------------
# Suite: empty lot
# ---------------------------------------------------------------------------

class TestEmptyLot:
    @pytest.mark.asyncio
    async def test_empty_lot_uploads_one_file(self):
        """Empty lot: we do NOT call the CHI Spec builder (no instruments).
        A single stub CXF is uploaded and returned."""
        conn = AsyncMock()
        conn.__aenter__ = AsyncMock(return_value=conn)
        conn.__aexit__ = AsyncMock(return_value=False)
        conn.fetch = AsyncMock(return_value=[])
        pool = AsyncMock()
        pool.acquire = MagicMock(return_value=conn)

        from modules.cts.lot.lot_store import LotStore
        minio = MagicMock()
        minio.put_object = MagicMock()
        minio.get_object = MagicMock()
        store = LotStore(db_pool=pool, minio_client=minio, bucket="astra-cts")

        path, checksum = await _call_build(store, n=0, hsm=None)
        assert "test-bank" in path
        assert len(checksum) == 64

    @pytest.mark.asyncio
    async def test_empty_lot_minio_called_once(self):
        """Empty lot only uploads one stub file — no CIBF needed."""
        conn = AsyncMock()
        conn.__aenter__ = AsyncMock(return_value=conn)
        conn.__aexit__ = AsyncMock(return_value=False)
        conn.fetch = AsyncMock(return_value=[])
        pool = AsyncMock()
        pool.acquire = MagicMock(return_value=conn)

        from modules.cts.lot.lot_store import LotStore
        minio = MagicMock()
        minio.put_object = MagicMock()
        minio.get_object = MagicMock()
        store = LotStore(db_pool=pool, minio_client=minio, bucket="astra-cts")

        await _call_build(store, n=0, hsm=None)
        assert minio.put_object.call_count == 1
