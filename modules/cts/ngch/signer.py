"""
NGCHSigner — MICRDS and ImageDS signatures per CHI Spec Rev 3.00.

MICRDS (Appendix 4.1.3.4):
  - MICRFingerPrint attribute = semicolon-delimited field NAMES
    "PresentmentDate;PresentingBankRoutNo;CycleNo;ItemSeqNo;Amount;SerialNo;Transcode"
  - Data signed = corresponding field VALUES concatenated with ";" as separator
    "01042026;000550050;01;00000101123456;10000;123456;10;"
  - RSA-SHA256 over UTF-8 bytes of the concatenated values
  - Base64-encoded result = 344 chars

ImageDS (Appendix 4.1.3.7):
  - RSA-SHA256 over raw image bytes → 256-byte raw binary
  - Called once per image view (3× per instrument: front BW, back BW, front gray)

All RSA signing is delegated to an HSM interface (FIPS 140-2 Level 3).
No private key material touches Python memory.

HSM interface contract (duck-typed):
  hsm.sign(data: bytes) -> bytes       # RSA-SHA256 PKCS#1v15, raw 256-byte output
  hsm.get_public_key_pem() -> bytes
"""
import base64
from dataclasses import dataclass

import structlog

log = structlog.get_logger()

# Field names in the MICR fingerprint (order matches spec Appendix 4.1.3.4 sample)
_MICR_FINGERPRINT = (
    "PresentmentDate;PresentingBankRoutNo;CycleNo;ItemSeqNo;Amount;SerialNo;Transcode"
)
_MICR_FIELD_ORDER = [
    "presentment_date",
    "presenting_bank_rout_no",
    "cycle_no",
    "item_seq_no",
    "amount",
    "serial_no",
    "trans_code",
]


@dataclass(frozen=True)
class MICRDSResult:
    """Result of signing MICR field values.

    fingerprint:    Semicolon-delimited field NAMES (for CXF MICRFingerPrint attribute).
    signature_b64:  344-char Base64 RSA-SHA256 over concatenated field VALUES.
    """
    fingerprint: str
    signature_b64: str


class NGCHSigner:
    """Signs MICR fields (MICRDS) and image blobs (ImageDS) via HSM.

    Args:
        hsm: HSM interface implementing sign(data: bytes) -> bytes.
             Must use RSA-SHA256 PKCS#1v15 padding.
             Must be FIPS 140-2 Level 3 compliant in production.
    """

    def __init__(self, *, hsm) -> None:
        self._hsm = hsm

    def sign_micr(
        self,
        *,
        presentment_date: str,
        presenting_bank_rout_no: str,
        cycle_no: str,
        item_seq_no: str,
        amount: int,
        serial_no: str,
        trans_code: str,
    ) -> MICRDSResult:
        """Sign MICR field values and return MICRDSResult.

        The fingerprint string (field names) is fixed per spec.
        The data signed is the corresponding field values joined with ";".
        The Base64-encoded RSA-SHA256 signature is exactly 344 chars.

        Args:
            presentment_date:        DDMMYYYY format
            presenting_bank_rout_no: 9-digit NPCI routing number of presenting bank
            cycle_no:                2-char cycle number ("01"-"12")
            item_seq_no:             14-char item sequence number
            amount:                  cheque amount in paise (integer)
            serial_no:               cheque serial number (MICR-extracted)
            trans_code:              MICR transaction code (e.g. "10")

        Returns:
            MICRDSResult with fingerprint string and 344-char base64 signature.
        """
        data_to_sign = (
            f"{presentment_date};"
            f"{presenting_bank_rout_no};"
            f"{cycle_no};"
            f"{item_seq_no};"
            f"{amount};"
            f"{serial_no};"
            f"{trans_code};"
        )
        raw_sig = self._hsm.sign(data_to_sign.encode("utf-8"))
        sig_b64 = base64.b64encode(raw_sig).decode("ascii")
        log.debug("ngch_signer.micrds_signed", sig_len=len(sig_b64))
        return MICRDSResult(fingerprint=_MICR_FINGERPRINT, signature_b64=sig_b64)

    def sign_image(self, image_bytes: bytes) -> bytes:
        """Sign raw image bytes and return 256-byte raw ImageDS.

        Must be called once per image view (3× per instrument).
        The raw signature bytes are prepended before the image in the CIBF binary.

        Args:
            image_bytes: Raw binary content of the cheque image (TIFF or JPEG).

        Returns:
            256-byte raw RSA-SHA256 signature (2048-bit key).
        """
        raw_sig = self._hsm.sign(image_bytes)
        log.debug("ngch_signer.imageds_signed", sig_len=len(raw_sig))
        return raw_sig
