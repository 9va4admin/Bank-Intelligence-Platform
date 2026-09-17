"""
Tests for NGCHSigner — MICRDS and ImageDS signing per CHI Spec Rev 3.00.

CHI Spec Rev 3.00 Appendix 4.1.3.4 (MICRDS) and 4.1.3.7 (ImageDS):

  MICRDS — sign MICR field VALUES (not raw MICR line):
    - MICRFingerPrint attribute = semicolon-delimited field names
      e.g. "PresentmentDate;PresentingBankRoutNo;CycleNo;ItemSeqNo;Amount;SerialNo;Transcode"
    - The actual data signed = corresponding field values concatenated with ";"
      e.g. "01042026;000550050;01;00000101123456;10000;123456;10;"
    - Result: Base64(RSA-SHA256) = 344 chars + the fingerprint string
    - sign_micr() returns MICRDSResult(fingerprint, signature_b64)

  ImageDS — RSA-SHA256 over raw image bytes → 256 bytes raw binary
    - sign_image(image_bytes) returns 256-byte raw bytes
    - Must be called 3× per instrument (once per image view)

RED phase: new fingerprint-based interface tests must fail against old signer.
"""
import base64

import pytest


@pytest.fixture(scope="module")
def rsa_key_pair():
    """Generate a 2048-bit RSA key pair for test signing (software only)."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.backends import default_backend

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    public_key = private_key.public_key()
    return private_key, public_key


@pytest.fixture
def mock_hsm(rsa_key_pair):
    """Minimal HSM stub that signs with the test RSA key."""
    from unittest.mock import MagicMock
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    private_key, public_key = rsa_key_pair

    hsm = MagicMock()

    def _sign(data: bytes) -> bytes:
        return private_key.sign(data, padding.PKCS1v15(), hashes.SHA256())

    def _get_public_key_pem() -> bytes:
        return public_key.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )

    hsm.sign.side_effect = _sign
    hsm.get_public_key_pem.side_effect = _get_public_key_pem
    return hsm


def _micr_input():
    """Minimal valid MICRSignInput kwargs."""
    return dict(
        presentment_date="01042026",
        presenting_bank_rout_no="000550050",
        cycle_no="01",
        item_seq_no="00000101123456",
        amount=10000,
        serial_no="123456",
        trans_code="10",
    )


class TestMICRDSResult:
    """sign_micr returns MICRDSResult with fingerprint + signature_b64."""

    def test_sign_micr_returns_micrds_result(self, mock_hsm):
        from modules.cts.ngch.signer import NGCHSigner

        signer = NGCHSigner(hsm=mock_hsm)
        result = signer.sign_micr(**_micr_input())
        assert result is not None

    def test_micrds_result_has_fingerprint(self, mock_hsm):
        from modules.cts.ngch.signer import NGCHSigner

        signer = NGCHSigner(hsm=mock_hsm)
        result = signer.sign_micr(**_micr_input())
        assert hasattr(result, "fingerprint")

    def test_micrds_result_has_signature_b64(self, mock_hsm):
        from modules.cts.ngch.signer import NGCHSigner

        signer = NGCHSigner(hsm=mock_hsm)
        result = signer.sign_micr(**_micr_input())
        assert hasattr(result, "signature_b64")

    def test_micrds_signature_b64_is_344_chars(self, mock_hsm):
        """2048-bit RSA produces 256 raw bytes → Base64 → exactly 344 chars."""
        from modules.cts.ngch.signer import NGCHSigner

        signer = NGCHSigner(hsm=mock_hsm)
        result = signer.sign_micr(**_micr_input())
        assert len(result.signature_b64) == 344

    def test_micrds_signature_is_valid_base64(self, mock_hsm):
        from modules.cts.ngch.signer import NGCHSigner

        signer = NGCHSigner(hsm=mock_hsm)
        result = signer.sign_micr(**_micr_input())
        decoded = base64.b64decode(result.signature_b64)
        assert len(decoded) == 256

    def test_micrds_fingerprint_contains_field_names(self, mock_hsm):
        """Fingerprint must be semicolon-delimited field names."""
        from modules.cts.ngch.signer import NGCHSigner

        signer = NGCHSigner(hsm=mock_hsm)
        result = signer.sign_micr(**_micr_input())
        fp = result.fingerprint
        # Must contain the field names that were signed
        assert "SerialNo" in fp or "PresentmentDate" in fp or "Amount" in fp

    def test_micrds_fingerprint_is_semicolon_delimited(self, mock_hsm):
        from modules.cts.ngch.signer import NGCHSigner

        signer = NGCHSigner(hsm=mock_hsm)
        result = signer.sign_micr(**_micr_input())
        assert ";" in result.fingerprint

    def test_micrds_signs_field_values_not_raw_micr(self, mock_hsm):
        """HSM must be called with semicolon-delimited field values, not raw MICR line."""
        from modules.cts.ngch.signer import NGCHSigner

        signer = NGCHSigner(hsm=mock_hsm)
        inp = _micr_input()
        signer.sign_micr(**inp)

        # The HSM sign call must receive field values, not a raw MICR line string
        call_args = mock_hsm.sign.call_args[0][0]   # first positional arg = bytes
        call_data = call_args.decode("utf-8")
        # Field values should appear (amount "10000" and serial_no "123456")
        assert "10000" in call_data or "123456" in call_data

    def test_micrds_different_field_values_different_signature(self, mock_hsm):
        from modules.cts.ngch.signer import NGCHSigner

        signer = NGCHSigner(hsm=mock_hsm)
        r1 = signer.sign_micr(**_micr_input())
        r2 = signer.sign_micr(**{**_micr_input(), "amount": 99999, "serial_no": "999999"})
        assert r1.signature_b64 != r2.signature_b64

    def test_micrds_delegated_to_hsm(self, mock_hsm):
        from modules.cts.ngch.signer import NGCHSigner

        signer = NGCHSigner(hsm=mock_hsm)
        signer.sign_micr(**_micr_input())
        assert mock_hsm.sign.called


class TestImageDS:
    """ImageDS — RSA-SHA256 over image bytes → 256 raw bytes (unchanged)."""

    def test_imageds_returns_bytes(self, mock_hsm):
        from modules.cts.ngch.signer import NGCHSigner

        signer = NGCHSigner(hsm=mock_hsm)
        result = signer.sign_image(b"\xff\xd8\xff" + b"\x00" * 100)
        assert isinstance(result, bytes)

    def test_imageds_length_is_256_bytes(self, mock_hsm):
        from modules.cts.ngch.signer import NGCHSigner

        signer = NGCHSigner(hsm=mock_hsm)
        result = signer.sign_image(b"\xff\xd8\xff" + b"\x00" * 100)
        assert len(result) == 256

    def test_imageds_same_input_same_output(self, mock_hsm):
        from modules.cts.ngch.signer import NGCHSigner

        signer = NGCHSigner(hsm=mock_hsm)
        data = b"\xff\xd8\xff" + b"\x00" * 100
        r1 = signer.sign_image(data)
        r2 = signer.sign_image(data)
        assert r1 == r2

    def test_imageds_different_images_different_signature(self, mock_hsm):
        from modules.cts.ngch.signer import NGCHSigner

        signer = NGCHSigner(hsm=mock_hsm)
        r1 = signer.sign_image(b"\xff\xd8\xff" + b"\x01" * 50)
        r2 = signer.sign_image(b"\xff\xd8\xff" + b"\x02" * 50)
        assert r1 != r2

    def test_imageds_passes_raw_image_bytes_to_hsm(self, mock_hsm):
        from modules.cts.ngch.signer import NGCHSigner

        signer = NGCHSigner(hsm=mock_hsm)
        image_data = b"\xff\xd8\xff" + b"\xAB" * 80
        signer.sign_image(image_data)
        mock_hsm.sign.assert_called_once_with(image_data)

    def test_imageds_called_per_image_view(self, mock_hsm):
        """sign_image must work correctly when called 3× per instrument."""
        from modules.cts.ngch.signer import NGCHSigner

        signer = NGCHSigner(hsm=mock_hsm)
        front_bw = b"II\x2a\x00" + b"\x01" * 100
        back_bw = b"II\x2a\x00" + b"\x02" * 100
        front_gray = b"\xff\xd8\xff\xe0" + b"\x03" * 100

        ds_fb = signer.sign_image(front_bw)
        ds_bb = signer.sign_image(back_bw)
        ds_fg = signer.sign_image(front_gray)

        assert len(ds_fb) == 256
        assert len(ds_bb) == 256
        assert len(ds_fg) == 256
        # All 3 signatures are distinct for different images
        assert ds_fb != ds_bb != ds_fg


class TestNGCHSignerInit:
    """Signer must require HSM; no software fallback in production."""

    def test_signer_requires_hsm_arg(self):
        from modules.cts.ngch.signer import NGCHSigner

        with pytest.raises(TypeError):
            NGCHSigner()

    def test_signer_stores_hsm(self, mock_hsm):
        from modules.cts.ngch.signer import NGCHSigner

        signer = NGCHSigner(hsm=mock_hsm)
        assert signer._hsm is mock_hsm
