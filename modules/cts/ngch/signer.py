"""
NGCHSigner — MICRDS and ImageDS signatures per CTS Spec Rev 3.0.

MICRDS: RSA-SHA256 over MICR line (UTF-8 bytes) → Base64-encoded string (344 chars)
ImageDS: RSA-SHA256 over raw image bytes → 256-byte raw binary

All RSA signing is delegated to an HSM interface (FIPS 140-2 Level 3).
No private key material touches Python memory; the HSM performs the operation.

HSM interface contract (duck-typed):
  hsm.sign(data: bytes) -> bytes       # RSA-SHA256, raw signature bytes
  hsm.get_public_key_pem() -> bytes    # Public key in PEM format (for verification)
"""
import base64

import structlog

log = structlog.get_logger()


class NGCHSigner:
    """Signs MICR lines (MICRDS) and image blobs (ImageDS) via HSM.

    Args:
        hsm: HSM interface implementing sign(data: bytes) -> bytes.
             Must use RSA-SHA256 PKCS#1v15 padding.
             Must be FIPS 140-2 Level 3 compliant in production.
    """

    def __init__(self, *, hsm) -> None:
        self._hsm = hsm

    def sign_micr(self, micr_line: str) -> str:
        """Sign a MICR line and return Base64-encoded MICRDS (344 chars).

        The MICR line is encoded as UTF-8 before signing.
        Result is standard Base64 (no URL-safe variant) — exactly 344 chars
        for a 2048-bit RSA key.

        Args:
            micr_line: The MICR line string as extracted from the cheque.

        Returns:
            Base64-encoded RSA-SHA256 signature (344 characters).
        """
        raw_sig = self._hsm.sign(micr_line.encode("utf-8"))
        encoded = base64.b64encode(raw_sig).decode("ascii")
        log.debug("ngch_signer.micrds_signed", sig_len=len(encoded))
        return encoded

    def sign_image(self, image_bytes: bytes) -> bytes:
        """Sign raw image bytes and return 256-byte raw ImageDS.

        The signature is embedded at the spec-defined byte offset inside
        the CIBF by CIBFAssembler — do not Base64-encode this value.

        Args:
            image_bytes: Raw binary content of the cheque image (TIFF or JPEG).

        Returns:
            256-byte raw RSA-SHA256 signature (2048-bit key).
        """
        raw_sig = self._hsm.sign(image_bytes)
        log.debug("ngch_signer.imageds_signed", sig_len=len(raw_sig))
        return raw_sig
