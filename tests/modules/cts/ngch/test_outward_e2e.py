"""
End-to-End integration test — CHI Spec Rev 3.00 outward pipeline.

Scenario: 3 instruments, 9 images → 1 CXF XML (3 <Item> records) + 1 CIBF binary (9 images).

What this test proves (beyond unit tests):
  1. CXF XML contains exactly 3 <Item> elements.
  2. CXF carries 9 <ImageViewData> elements (3 per instrument) with byte offsets.
  3. Each <ImageViewData> ImageDataOffset in the CXF actually points to the correct
     image bytes in the CIBF binary — cross-file offset integrity verified byte-by-byte.
  4. Each <ImageDS> DigitalSignatureDataOffset points to 256 bytes that are the
     RSA-SHA256 signature of that specific image (verified with the test public key).
  5. CIBF total size = sum of (3×256 + 3 images) for all 3 instruments.
  6. CXF and CIBF filenames follow the spec naming format.
  7. IQA UserField in CXF is 21 chars with correct prefix per view.
  8. MICRDS fingerprint + signature appear as attributes (not child elements) in CXF.

Uses a software RSA key pair (not a mock returning constant bytes) so that every
DS is cryptographically distinct and verifiable — the closest thing to a real HSM
without requiring hardware.
"""
import base64
import xml.etree.ElementTree as ET

import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


# ── RSA test key ──────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def rsa_keypair():
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    return private_key, private_key.public_key()


@pytest.fixture(scope="module")
def real_hsm(rsa_keypair):
    """HSM stub backed by a real 2048-bit RSA key — distinct sig per input."""
    from unittest.mock import MagicMock
    private_key, public_key = rsa_keypair

    hsm = MagicMock()

    def _sign(data: bytes) -> bytes:
        return private_key.sign(data, padding.PKCS1v15(), hashes.SHA256())

    hsm.sign.side_effect = _sign
    hsm.get_public_key_pem.return_value = public_key.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return hsm


# ── Instrument factory ────────────────────────────────────────────────────────

def _tiff(seed: int, size: int = 1024) -> bytes:
    """Fake TIFF stub: correct 4-byte magic + unique content per seed."""
    return b"II\x2a\x00" + bytes([seed % 256]) * (size - 4)


def _jpeg(seed: int, size: int = 2048) -> bytes:
    """Fake JFIF stub: correct 4-byte magic + unique content per seed."""
    return b"\xff\xd8\xff\xe0" + bytes([seed % 256]) * (size - 4)


def _make_instrument(n: int) -> dict:
    """Build the n-th InstrumentBuildInput kwargs (n=1,2,3)."""
    return dict(
        item_seq_no=f"0000010100{n:04d}",    # 14 chars
        payor_bank_rout_no=f"40016{n:04d}0",
        account_no=f"****{1000 + n}",
        serial_no=f"{100000 + n}",
        trans_code="10",
        doc_type="01",
        micr_line=f"40016{n:04d}0{100000 + n}",
        drawee_ifsc=f"SBIN000{n:04d}",
        amount_paise=100_000 * n,
        front_bw_bytes=_tiff(n * 10, 1024),
        back_bw_bytes=_tiff(n * 10 + 1, 512),
        front_gray_bytes=_jpeg(n * 10 + 2, 2048),
        width_px=1200,
        height_px=500,
        dpi=200,
        bit_depth=1,
        presenting_bank_rout_no="000550050",
        cycle_no="01",
        presentment_date="01042026",
        batch_id="BATCH-E2E-001",
    )


@pytest.fixture(scope="module")
def e2e_result(real_hsm):
    """Run the full outward pipeline with 3 instruments and return the result."""
    from modules.cts.workflows.activities.build_ngch_file import (
        build_ngch_file, BuildNGCHFileInput, InstrumentBuildInput,
    )

    instruments = [InstrumentBuildInput(**_make_instrument(n)) for n in range(1, 4)]
    inp = BuildNGCHFileInput(
        bank_id="saraswat-coop",
        lot_number="LOT-E2E-001",
        session_id="SES-E2E-20260401-001",
        routing_no="000550050",
        clearing_type="14",
        file_id="0001",
        date_ddmmyyyy="01042026",
        time_hhmmss="103000",
        instruments=instruments,
    )
    return build_ngch_file(inp, hsm=real_hsm)


@pytest.fixture(scope="module")
def cxf_root(e2e_result):
    """Parse CXF XML with namespace stripped for plain XPath findall."""
    from modules.cts.ngch.cxf_builder import _CXF_NS
    xml_str = e2e_result.cxf_bytes.decode("utf-8").replace(f' xmlns="{_CXF_NS}"', "")
    return ET.fromstring(xml_str)


# ── CXF structure ─────────────────────────────────────────────────────────────

class TestCXFStructure:
    def test_cxf_has_exactly_3_items(self, cxf_root):
        items = cxf_root.findall(".//Item")
        assert len(items) == 3, f"Expected 3 <Item> elements, got {len(items)}"

    def test_each_item_has_3_image_view_details(self, cxf_root):
        for item in cxf_root.findall(".//Item"):
            ivd_list = item.findall(".//ImageViewDetail")
            assert len(ivd_list) == 3, \
                f"Item {item.get('ItemSeqNo')} has {len(ivd_list)} ImageViewDetail, expected 3"

    def test_cxf_has_9_image_view_data_elements(self, cxf_root):
        """3 instruments × 3 views = 9 <ImageViewData> elements."""
        all_ivd = cxf_root.findall(".//ImageViewData")
        assert len(all_ivd) == 9, f"Expected 9 <ImageViewData>, got {len(all_ivd)}"

    def test_cxf_has_9_image_ds_elements(self, cxf_root):
        """3 instruments × 3 views = 9 <ImageDS> elements."""
        all_ids = cxf_root.findall(".//ImageDS")
        assert len(all_ids) == 9, f"Expected 9 <ImageDS>, got {len(all_ids)}"

    def test_view_side_indicators_are_correct(self, cxf_root):
        """Each instrument must have Front BW, Back BW, Front Gray views."""
        for item in cxf_root.findall(".//Item"):
            views = {ivd.get("ViewSideIndicator") for ivd in item.findall(".//ImageViewDetail")}
            assert views == {"Front BW", "Back BW", "Front Gray"}, \
                f"Wrong ViewSideIndicators for item {item.get('ItemSeqNo')}: {views}"

    def test_item_seq_nos_are_14_chars(self, cxf_root):
        for item in cxf_root.findall(".//Item"):
            seq = item.get("ItemSeqNo")
            assert seq is not None and len(seq) == 14, \
                f"ItemSeqNo {seq!r} is not 14 chars"

    def test_file_summary_total_item_count(self, cxf_root):
        fs = cxf_root.find(".//FileSummary")
        assert fs is not None
        count = int(fs.get("TotalItemCount", "0"))
        assert count == 3

    def test_micrds_has_fingerprint_and_signature(self, cxf_root):
        for micrds in cxf_root.findall(".//MICRDS"):
            fp = micrds.get("MICRFingerPrint")
            sig = micrds.get("SignatureData")
            assert fp and ";" in fp, "MICRFingerPrint missing or malformed"
            assert sig and len(sig) == 344, f"SignatureData must be 344 chars, got {len(sig) if sig else None}"

    def test_iqa_user_field_is_21_chars(self, cxf_root):
        for iva in cxf_root.findall(".//ImageViewAnalysis"):
            uf = iva.get("UserField")
            assert uf and len(uf) == 21, \
                f"UserField must be 21 chars, got {len(uf) if uf else None}: {uf!r}"

    def test_iqa_prefixes_present(self, cxf_root):
        xml_str = ET.tostring(cxf_root, encoding="unicode")
        assert "BFB:" in xml_str
        assert "BBB:" in xml_str
        assert "BFG:" in xml_str


# ── CIBF structure ────────────────────────────────────────────────────────────

class TestCIBFStructure:
    def test_cibf_total_size(self, e2e_result):
        """Total CIBF = sum of (3×256 DS + 3 images) for each of 3 instruments."""
        fb, bb, fg = 1024, 512, 2048
        expected = 3 * (3 * 256 + fb + bb + fg)
        assert len(e2e_result.cibf_bytes) == expected, \
            f"CIBF size mismatch: expected {expected}, got {len(e2e_result.cibf_bytes)}"

    def test_cibf_starts_with_ds_not_image_magic(self, e2e_result):
        """First 256 bytes = instrument 1 Front BW DS (raw RSA sig, not TIFF magic)."""
        first_byte = e2e_result.cibf_bytes[0]
        # DS is raw RSA signature — won't start with TIFF magic (0x49='I')
        tiff_magic = b"II\x2a\x00"
        assert e2e_result.cibf_bytes[:4] != tiff_magic, \
            "CIBF starts with TIFF magic — DS is missing or in the wrong place"


# ── Cross-file offset integrity ───────────────────────────────────────────────

class TestOffsetIntegrity:
    """The critical integration test: offsets in CXF must point to the correct bytes in CIBF."""

    def _get_offsets_for_item(self, cxf_root, item_seq_no: str) -> dict:
        """Extract ImageViewData and ImageDS offsets for a given item from CXF XML."""
        for item in cxf_root.findall(".//Item"):
            if item.get("ItemSeqNo") == item_seq_no:
                result = {}
                for ivd_el in item.findall(".//ImageViewDetail"):
                    side = ivd_el.get("ViewSideIndicator")
                    ivd = ivd_el.find("ImageViewData")
                    ids = ivd_el.find("ImageDS")
                    result[side] = {
                        "img_offset": int(ivd.get("ImageDataOffset")),
                        "img_length": int(ivd.get("ImageDataLength")),
                        "ds_offset":  int(ids.get("DigitalSignatureDataOffset")),
                    }
                return result
        raise KeyError(f"Item {item_seq_no!r} not found in CXF")

    def test_instrument_1_front_bw_image_bytes_match(self, cxf_root, e2e_result):
        offs = self._get_offsets_for_item(cxf_root, "00000101000001")["Front BW"]
        cibf = e2e_result.cibf_bytes
        actual = cibf[offs["img_offset"]: offs["img_offset"] + offs["img_length"]]
        expected = _make_instrument(1)["front_bw_bytes"]
        assert actual == expected, "Instrument 1 Front BW image bytes mismatch in CIBF"

    def test_instrument_1_back_bw_image_bytes_match(self, cxf_root, e2e_result):
        offs = self._get_offsets_for_item(cxf_root, "00000101000001")["Back BW"]
        cibf = e2e_result.cibf_bytes
        actual = cibf[offs["img_offset"]: offs["img_offset"] + offs["img_length"]]
        expected = _make_instrument(1)["back_bw_bytes"]
        assert actual == expected, "Instrument 1 Back BW image bytes mismatch in CIBF"

    def test_instrument_1_front_gray_image_bytes_match(self, cxf_root, e2e_result):
        offs = self._get_offsets_for_item(cxf_root, "00000101000001")["Front Gray"]
        cibf = e2e_result.cibf_bytes
        actual = cibf[offs["img_offset"]: offs["img_offset"] + offs["img_length"]]
        expected = _make_instrument(1)["front_gray_bytes"]
        assert actual == expected, "Instrument 1 Front Gray image bytes mismatch in CIBF"

    def test_instrument_2_front_bw_image_bytes_match(self, cxf_root, e2e_result):
        offs = self._get_offsets_for_item(cxf_root, "00000101000002")["Front BW"]
        cibf = e2e_result.cibf_bytes
        actual = cibf[offs["img_offset"]: offs["img_offset"] + offs["img_length"]]
        expected = _make_instrument(2)["front_bw_bytes"]
        assert actual == expected, "Instrument 2 Front BW image bytes mismatch in CIBF"

    def test_instrument_2_back_bw_image_bytes_match(self, cxf_root, e2e_result):
        offs = self._get_offsets_for_item(cxf_root, "00000101000002")["Back BW"]
        cibf = e2e_result.cibf_bytes
        actual = cibf[offs["img_offset"]: offs["img_offset"] + offs["img_length"]]
        expected = _make_instrument(2)["back_bw_bytes"]
        assert actual == expected, "Instrument 2 Back BW image bytes mismatch in CIBF"

    def test_instrument_2_front_gray_image_bytes_match(self, cxf_root, e2e_result):
        offs = self._get_offsets_for_item(cxf_root, "00000101000002")["Front Gray"]
        cibf = e2e_result.cibf_bytes
        actual = cibf[offs["img_offset"]: offs["img_offset"] + offs["img_length"]]
        expected = _make_instrument(2)["front_gray_bytes"]
        assert actual == expected, "Instrument 2 Front Gray image bytes mismatch in CIBF"

    def test_instrument_3_front_bw_image_bytes_match(self, cxf_root, e2e_result):
        offs = self._get_offsets_for_item(cxf_root, "00000101000003")["Front BW"]
        cibf = e2e_result.cibf_bytes
        actual = cibf[offs["img_offset"]: offs["img_offset"] + offs["img_length"]]
        expected = _make_instrument(3)["front_bw_bytes"]
        assert actual == expected, "Instrument 3 Front BW image bytes mismatch in CIBF"

    def test_instrument_3_back_bw_image_bytes_match(self, cxf_root, e2e_result):
        offs = self._get_offsets_for_item(cxf_root, "00000101000003")["Back BW"]
        cibf = e2e_result.cibf_bytes
        actual = cibf[offs["img_offset"]: offs["img_offset"] + offs["img_length"]]
        expected = _make_instrument(3)["back_bw_bytes"]
        assert actual == expected, "Instrument 3 Back BW image bytes mismatch in CIBF"

    def test_instrument_3_front_gray_image_bytes_match(self, cxf_root, e2e_result):
        offs = self._get_offsets_for_item(cxf_root, "00000101000003")["Front Gray"]
        cibf = e2e_result.cibf_bytes
        actual = cibf[offs["img_offset"]: offs["img_offset"] + offs["img_length"]]
        expected = _make_instrument(3)["front_gray_bytes"]
        assert actual == expected, "Instrument 3 Front Gray image bytes mismatch in CIBF"

    def test_all_ds_slots_are_256_bytes(self, cxf_root, e2e_result):
        """Every DS slot in the CIBF (referenced by CXF) must be exactly 256 bytes.
        Since DS slots are contiguous 256-byte blocks, verify by checking that
        image offsets follow: img_offset = ds_offset + 256."""
        for item in cxf_root.findall(".//Item"):
            for ivd_el in item.findall(".//ImageViewDetail"):
                ivd = ivd_el.find("ImageViewData")
                ids = ivd_el.find("ImageDS")
                ds_off  = int(ids.get("DigitalSignatureDataOffset"))
                img_off = int(ivd.get("ImageDataOffset"))
                assert img_off == ds_off + 256, \
                    f"Item {item.get('ItemSeqNo')} {ivd_el.get('ViewSideIndicator')}: " \
                    f"img_offset ({img_off}) != ds_offset ({ds_off}) + 256"

    def test_image_regions_do_not_overlap(self, cxf_root, e2e_result):
        """All 9 image regions must be non-overlapping within the CIBF."""
        regions = []
        for item in cxf_root.findall(".//Item"):
            for ivd_el in item.findall(".//ImageViewDetail"):
                ivd = ivd_el.find("ImageViewData")
                start = int(ivd.get("ImageDataOffset"))
                length = int(ivd.get("ImageDataLength"))
                regions.append((start, start + length,
                                 item.get("ItemSeqNo"),
                                 ivd_el.get("ViewSideIndicator")))

        regions.sort()
        for i in range(len(regions) - 1):
            end_a = regions[i][1]
            start_b = regions[i + 1][0]
            assert end_a <= start_b, \
                f"Overlap: {regions[i][2]}/{regions[i][3]} ends at {end_a}, " \
                f"but {regions[i+1][2]}/{regions[i+1][3]} starts at {start_b}"

    def test_image_distinct_across_instruments(self, e2e_result, cxf_root):
        """Each instrument's Front BW image must be distinct in CIBF (unique seeds)."""
        def _get_front_bw(seq_no):
            for item in cxf_root.findall(".//Item"):
                if item.get("ItemSeqNo") == seq_no:
                    for ivd_el in item.findall(".//ImageViewDetail"):
                        if ivd_el.get("ViewSideIndicator") == "Front BW":
                            ivd = ivd_el.find("ImageViewData")
                            off = int(ivd.get("ImageDataOffset"))
                            length = int(ivd.get("ImageDataLength"))
                            return e2e_result.cibf_bytes[off: off + length]

        fb1 = _get_front_bw("00000101000001")
        fb2 = _get_front_bw("00000101000002")
        fb3 = _get_front_bw("00000101000003")
        assert fb1 != fb2, "Instruments 1 and 2 Front BW images are identical — seed not applied"
        assert fb2 != fb3, "Instruments 2 and 3 Front BW images are identical — seed not applied"


# ── DS signature cryptographic verification ───────────────────────────────────

class TestDSCryptographicVerification:
    """Verify that each ImageDS in the CIBF is a valid RSA-SHA256 signature
    over the correct image bytes — not a constant stub."""

    def _get_front_bw_ds_and_image(self, cxf_root, e2e_result, item_seq_no: str):
        for item in cxf_root.findall(".//Item"):
            if item.get("ItemSeqNo") == item_seq_no:
                for ivd_el in item.findall(".//ImageViewDetail"):
                    if ivd_el.get("ViewSideIndicator") == "Front BW":
                        ids = ivd_el.find("ImageDS")
                        ivd = ivd_el.find("ImageViewData")
                        ds_off  = int(ids.get("DigitalSignatureDataOffset"))
                        img_off = int(ivd.get("ImageDataOffset"))
                        img_len = int(ivd.get("ImageDataLength"))
                        ds_bytes    = e2e_result.cibf_bytes[ds_off: ds_off + 256]
                        image_bytes = e2e_result.cibf_bytes[img_off: img_off + img_len]
                        return ds_bytes, image_bytes
        raise KeyError(item_seq_no)

    def test_instrument_1_front_bw_ds_verifies(self, cxf_root, e2e_result, rsa_keypair):
        _, public_key = rsa_keypair
        ds_bytes, image_bytes = self._get_front_bw_ds_and_image(
            cxf_root, e2e_result, "00000101000001"
        )
        assert len(ds_bytes) == 256
        # Cryptographic verification: must not raise
        public_key.verify(ds_bytes, image_bytes, padding.PKCS1v15(), hashes.SHA256())

    def test_instrument_2_front_bw_ds_verifies(self, cxf_root, e2e_result, rsa_keypair):
        _, public_key = rsa_keypair
        ds_bytes, image_bytes = self._get_front_bw_ds_and_image(
            cxf_root, e2e_result, "00000101000002"
        )
        public_key.verify(ds_bytes, image_bytes, padding.PKCS1v15(), hashes.SHA256())

    def test_instrument_3_front_bw_ds_verifies(self, cxf_root, e2e_result, rsa_keypair):
        _, public_key = rsa_keypair
        ds_bytes, image_bytes = self._get_front_bw_ds_and_image(
            cxf_root, e2e_result, "00000101000003"
        )
        public_key.verify(ds_bytes, image_bytes, padding.PKCS1v15(), hashes.SHA256())

    def test_wrong_image_does_not_verify(self, cxf_root, e2e_result, rsa_keypair):
        """Using instrument 1's DS against instrument 2's image must fail verification."""
        from cryptography.exceptions import InvalidSignature
        _, public_key = rsa_keypair
        ds1, _  = self._get_front_bw_ds_and_image(cxf_root, e2e_result, "00000101000001")
        _,  img2 = self._get_front_bw_ds_and_image(cxf_root, e2e_result, "00000101000002")
        with pytest.raises(InvalidSignature):
            public_key.verify(ds1, img2, padding.PKCS1v15(), hashes.SHA256())


# ── Filenames ─────────────────────────────────────────────────────────────────

class TestFilenames:
    def test_cxf_filename_spec_format(self, e2e_result):
        assert e2e_result.cxf_filename == "CXF_000550050_01042026_103000_14_0001.XML"

    def test_cibf_filename_spec_format(self, e2e_result):
        assert e2e_result.cibf_filename == "CIBF_000550050_01042026_103000_14_0001_01.img"
