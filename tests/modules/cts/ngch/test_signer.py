"""
Tests for NGCHSigner — MICRDS and ImageDS signing per CTS Spec Rev 3.0.

CTS Spec Rev 3.0 signing requirements:
  MICRDS: RSA-SHA256 over MICR line bytes → Base64-encoded → exactly 344 chars
  ImageDS: RSA-SHA256 over image bytes → 256 bytes raw binary

All private key operations must use the HSM interface (injected dependency).
Tests use a software RSA key as a stand-in for the HSM (test only — never prod).

RED phase: all tests must fail before signer.py is created.
"""
import base64
import hashlib

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


class TestMICRDS:
    """MICRDS — RSA-SHA256 over MICR line, Base64-encoded, 344 chars."""

    def test_micrds_returns_string(self, mock_hsm):
        from modules.cts.ngch.signer import NGCHSigner

        signer = NGCHSigner(hsm=mock_hsm)
        micr = "000012340050000012100000000005000123456789"
        result = signer.sign_micr(micr)
        assert isinstance(result, str)

    def test_micrds_length_is_344_chars(self, mock_hsm):
        """2048-bit RSA produces 256 raw bytes → Base64 → exactly 344 chars."""
        from modules.cts.ngch.signer import NGCHSigner

        signer = NGCHSigner(hsm=mock_hsm)
        micr = "000012340050000012100000000005000123456789"
        result = signer.sign_micr(micr)
        assert len(result) == 344

    def test_micrds_is_valid_base64(self, mock_hsm):
        from modules.cts.ngch.signer import NGCHSigner

        signer = NGCHSigner(hsm=mock_hsm)
        micr = "000012340050000012100000000005000123456789"
        result = signer.sign_micr(micr)
        # Must decode without error
        decoded = base64.b64decode(result)
        assert len(decoded) == 256  # 2048-bit RSA = 256 bytes

    def test_micrds_same_input_same_output(self, mock_hsm):
        """RSA-PKCS1v15 with SHA256 is deterministic for the same key + input."""
        from modules.cts.ngch.signer import NGCHSigner

        signer = NGCHSigner(hsm=mock_hsm)
        micr = "000012340050000012100000000005000123456789"
        r1 = signer.sign_micr(micr)
        r2 = signer.sign_micr(micr)
        assert r1 == r2

    def test_micrds_different_inputs_different_output(self, mock_hsm):
        from modules.cts.ngch.signer import NGCHSigner

        signer = NGCHSigner(hsm=mock_hsm)
        r1 = signer.sign_micr("000012340050000012100000000005000123456789")
        r2 = signer.sign_micr("000099990050000099900000000099900999999999")
        assert r1 != r2

    def test_micrds_signs_utf8_bytes_of_micr_line(self, mock_hsm, rsa_key_pair):
        """Verify that the HSM is called with the UTF-8 bytes of the MICR line."""
        from modules.cts.ngch.signer import NGCHSigner
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        signer = NGCHSigner(hsm=mock_hsm)
        micr = "000012340050000012100000000005000123456789"
        signer.sign_micr(micr)

        # HSM should have been called with the MICR line as bytes
        mock_hsm.sign.assert_called_once_with(micr.encode("utf-8"))

    def test_micrds_delegated_to_hsm(self, mock_hsm):
        """Signer must call hsm.sign(), not use a software key directly."""
        from modules.cts.ngch.signer import NGCHSigner

        signer = NGCHSigner(hsm=mock_hsm)
        signer.sign_micr("000012340050000012100000000005000123456789")
        assert mock_hsm.sign.called


class TestImageDS:
    """ImageDS — RSA-SHA256 over image bytes → 256 raw bytes."""

    def test_imageds_returns_bytes(self, mock_hsm):
        from modules.cts.ngch.signer import NGCHSigner

        signer = NGCHSigner(hsm=mock_hsm)
        image_data = b"\xff\xd8\xff" + b"\x00" * 100  # fake JPEG header + data
        result = signer.sign_image(image_data)
        assert isinstance(result, bytes)

    def test_imageds_length_is_256_bytes(self, mock_hsm):
        """2048-bit RSA signature = 256 bytes raw."""
        from modules.cts.ngch.signer import NGCHSigner

        signer = NGCHSigner(hsm=mock_hsm)
        image_data = b"\xff\xd8\xff" + b"\x00" * 100
        result = signer.sign_image(image_data)
        assert len(result) == 256

    def test_imageds_same_input_same_output(self, mock_hsm):
        """Deterministic for same image content + same key."""
        from modules.cts.ngch.signer import NGCHSigner

        signer = NGCHSigner(hsm=mock_hsm)
        image_data = b"\xff\xd8\xff" + b"\x00" * 100
        r1 = signer.sign_image(image_data)
        r2 = signer.sign_image(image_data)
        assert r1 == r2

    def test_imageds_different_images_different_signature(self, mock_hsm):
        from modules.cts.ngch.signer import NGCHSigner

        signer = NGCHSigner(hsm=mock_hsm)
        r1 = signer.sign_image(b"\xff\xd8\xff" + b"\x01" * 50)
        r2 = signer.sign_image(b"\xff\xd8\xff" + b"\x02" * 50)
        assert r1 != r2

    def test_imageds_passes_raw_image_bytes_to_hsm(self, mock_hsm):
        """HSM receives the raw image bytes, NOT a hash of them."""
        from modules.cts.ngch.signer import NGCHSigner

        signer = NGCHSigner(hsm=mock_hsm)
        image_data = b"\xff\xd8\xff" + b"\xAB" * 80
        signer.sign_image(image_data)
        mock_hsm.sign.assert_called_once_with(image_data)

    def test_imageds_delegated_to_hsm(self, mock_hsm):
        from modules.cts.ngch.signer import NGCHSigner

        signer = NGCHSigner(hsm=mock_hsm)
        signer.sign_image(b"\x00" * 100)
        assert mock_hsm.sign.called


class TestNGCHSignerInit:
    """Signer must require HSM; no software fallback in production."""

    def test_signer_requires_hsm_arg(self):
        from modules.cts.ngch.signer import NGCHSigner

        with pytest.raises(TypeError):
            NGCHSigner()  # missing required hsm

    def test_signer_stores_hsm(self, mock_hsm):
        from modules.cts.ngch.signer import NGCHSigner

        signer = NGCHSigner(hsm=mock_hsm)
        assert signer._hsm is mock_hsm
