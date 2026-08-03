"""
DEM file-level PKI — NPCI DEM Spec v20 §3.b.

OUTWARD (bank → CCH):
  sign_and_encrypt_file(bytes, hsm, cch_key_bundle, bank_routing_no) → wrapped_bytes

  1. RSA-SHA256 sign the file using bank's HSM private key
  2. Build Trans.Signature.Data header block (signature header + original bytes)
  3. Generate random AES-256 key; AES-256-CBC encrypt the signed block
     IV = bytes(range(16)) per DEM spec §3.b.iii
  4. RSA-encrypt the AES key using CCH's RSA public key (from CCHKeyBundle)
  5. Build Trans.Encrypt.Data header block (encryption header + ciphertext)

INWARD (CCH → bank):
  verify_and_decrypt_file(wrapped_bytes, hsm, cch_key_bundle) → original_bytes

  1. Parse and strip Trans.Encrypt.Data header; extract wrapped AES key
  2. Decrypt AES key using bank's HSM private key (hsm.decrypt_rsa)
  3. AES-256-CBC decrypt the body
  4. Parse and strip Trans.Signature.Data header; extract signature + original bytes
  5. Verify RSA-SHA256 signature using CCH's RSA public key (from CCHKeyBundle)

Line separator: \\n (LF) only — never \\r\\n per DEM spec.
"""
from __future__ import annotations

import base64
import os
from typing import Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from modules.cts.dem.models import CCHKeyBundle, DEMEncryptionAlgo

# DEM spec §3.b.iii: IV is bytes 0x00 through 0x0F
_DEM_AES_IV = bytes(range(16))

# Header delimiters (LF only — DEM spec)
_SIG_BEGIN = "Trans.Signature.Data"
_SIG_END = "Trans.Signature.Data=="
_ENC_BEGIN = "Trans.Encrypt.Data"
_ENC_END = "Trans.Encrypt.Data=="


class DEMPKIError(Exception):
    """Raised on any DEM PKI failure — tampered data, wrong key, missing header."""


class DEMHSMProtocol(Protocol):
    """Minimal HSM interface required by DEM PKI operations.

    Production implementation uses FIPS 140-2 Level 3 HSM via PKCS#11.
    Test implementations may use in-memory keys (never in production).
    """

    def sign(self, data: bytes) -> bytes:
        """RSA-SHA256 sign data using the bank's DEM private key in HSM."""
        ...

    def decrypt_rsa(self, ciphertext: bytes) -> bytes:
        """RSA-PKCS1v15 decrypt ciphertext using the bank's DEM private key in HSM."""
        ...

    def get_key_alias(self) -> str:
        """Return the HSM key alias for the bank's DEM signing key."""
        ...


# ── Internal helpers ─────────────────────────────────────────────────────────


def _cch_public_key(bundle: CCHKeyBundle):
    """Reconstruct CCH's RSA public key from modulus and exponent in the bundle."""
    pub_numbers = RSAPublicNumbers(e=bundle.exponent, n=bundle.modulus)
    return pub_numbers.public_key(default_backend())


def _header_block(marker: str, fields: dict[str, str]) -> bytes:
    """Build a DEM header block with LF line separators.

    Format:
        {marker}\\n
        {Key}={Value}\\n
        ...
        {marker}==\\n
    """
    lines = [marker]
    for key, value in fields.items():
        lines.append(f"{key}={value}")
    lines.append(f"{marker}==")
    return ("\n".join(lines) + "\n").encode("ascii")


def _parse_header(data: bytes, begin_marker: str, end_marker: str) -> tuple[dict[str, str], bytes]:
    """Split a DEM-wrapped blob into (header_fields, body).

    Returns:
        (fields_dict, body_bytes) where body_bytes is everything after the end marker.

    Raises:
        DEMPKIError if the expected markers are not found.
    """
    begin_b = begin_marker.encode("ascii")
    end_b = (end_marker + "\n").encode("ascii")

    if not data.startswith(begin_b):
        raise DEMPKIError(
            f"DEM header not found: expected '{begin_marker}' at start, "
            f"got {data[:40]!r}"
        )

    end_pos = data.find(end_b)
    if end_pos == -1:
        raise DEMPKIError(f"DEM end marker '{end_marker}' not found in data")

    header_bytes = data[: end_pos + len(end_b)]
    body = data[end_pos + len(end_b):]

    # Strip leading \n separator between header and body if present
    if body.startswith(b"\n"):
        body = body[1:]

    # Parse key=value pairs (skip the first line which is the begin marker)
    fields: dict[str, str] = {}
    for line in header_bytes.decode("ascii").splitlines()[1:]:
        if line == end_marker:
            break
        if "=" in line:
            k, _, v = line.partition("=")
            fields[k] = v

    return fields, body


def _aes_encrypt(key: bytes, plaintext: bytes) -> bytes:
    """AES-256-CBC encrypt with DEM-spec IV. Applies PKCS7 padding."""
    pad_len = 16 - (len(plaintext) % 16)
    padded = plaintext + bytes([pad_len] * pad_len)
    enc = Cipher(
        algorithms.AES(key), modes.CBC(_DEM_AES_IV), backend=default_backend()
    ).encryptor()
    return enc.update(padded) + enc.finalize()


def _aes_decrypt(key: bytes, ciphertext: bytes) -> bytes:
    """AES-256-CBC decrypt with DEM-spec IV. Strips PKCS7 padding."""
    dec = Cipher(
        algorithms.AES(key), modes.CBC(_DEM_AES_IV), backend=default_backend()
    ).decryptor()
    padded = dec.update(ciphertext) + dec.finalize()
    pad_len = padded[-1]
    return padded[:-pad_len]


# ── Public API ───────────────────────────────────────────────────────────────


def sign_and_encrypt_file(
    file_bytes: bytes,
    *,
    hsm: DEMHSMProtocol,
    cch_key_bundle: CCHKeyBundle,
    bank_routing_no: str,
    algo: DEMEncryptionAlgo = DEMEncryptionAlgo.AES,
) -> bytes:
    """Wrap file_bytes with DEM PKI for outward submission to CCH.

    Steps per DEM Spec v20 §3.b:
      1. Sign file_bytes with bank HSM → RSA-SHA256 signature
      2. Build Trans.Signature.Data header block
      3. AES-256-CBC encrypt the signed block (random key, DEM IV)
      4. RSA-encrypt AES key with CCH's public key
      5. Build Trans.Encrypt.Data header block

    Args:
        file_bytes: Raw CXF/CIBF/RRF content to protect.
        hsm: Bank's HSM interface for signing.
        cch_key_bundle: CCH's current RSA public key (from Reqtype=W exchange).
        bank_routing_no: Bank's 9-digit NPCI routing number.
        algo: Symmetric cipher (AES-256-CBC default; 3DES legacy).

    Returns:
        DEM-wrapped bytes ready for SFTP upload.
    """
    # Step 1 — Sign the original file bytes with bank HSM
    signature = hsm.sign(file_bytes)
    sig_b64 = base64.b64encode(signature).decode("ascii")

    # Step 2 — Build Trans.Signature.Data header block
    sig_header = _header_block(_SIG_BEGIN, {
        "Alias": hsm.get_key_alias(),
        "ThumbPrint": "",
        "Routing_Number": bank_routing_no,
        "Sign-Algo": "SHA256",
        "Data": sig_b64,
    })
    signed_block = sig_header + b"\n" + file_bytes

    # Step 3 — AES-256-CBC encrypt the signed block
    aes_key = os.urandom(32)
    if algo == DEMEncryptionAlgo.AES:
        ciphertext = _aes_encrypt(aes_key, signed_block)
    else:
        raise DEMPKIError(f"Unsupported DEM encryption algorithm: {algo}")

    # Step 4 — RSA-encrypt the AES key with CCH's public key
    cch_pub = _cch_public_key(cch_key_bundle)
    wrapped_key = cch_pub.encrypt(aes_key, asym_padding.PKCS1v15())
    key_b64 = base64.b64encode(wrapped_key).decode("ascii")

    # Step 5 — Build Trans.Encrypt.Data header block
    enc_header = _header_block(_ENC_BEGIN, {
        "Alias": hsm.get_key_alias(),
        "ThumbPrint": "",
        "Routing_Number": bank_routing_no,
        "Algo": algo.value,
        "Key": key_b64,
    })

    return enc_header + b"\n" + ciphertext


def verify_and_decrypt_file(
    wrapped_bytes: bytes,
    *,
    hsm: DEMHSMProtocol,
    cch_key_bundle: CCHKeyBundle,
) -> bytes:
    """Unwrap and verify a DEM-protected inward file from CCH.

    Steps per DEM Spec v20 §3.b:
      1. Parse Trans.Encrypt.Data header; extract wrapped AES key
      2. Decrypt AES key using bank HSM (hsm.decrypt_rsa)
      3. AES-256-CBC decrypt the body
      4. Parse Trans.Signature.Data header; extract signature and original bytes
      5. Verify RSA-SHA256 signature using CCH's public key

    Args:
        wrapped_bytes: Raw bytes received from CCH via SFTP (PXF, RF, RES, etc.)
        hsm: Bank's HSM interface for decrypting the AES key.
        cch_key_bundle: CCH's current RSA public key (used to verify CCH's signature).

    Returns:
        Original file bytes after verification.

    Raises:
        DEMPKIError on any failure: missing header, decryption error, signature mismatch.
    """
    # Step 1 — Parse Trans.Encrypt.Data header
    try:
        enc_fields, ciphertext = _parse_header(wrapped_bytes, _ENC_BEGIN, _ENC_END)
    except DEMPKIError:
        raise
    except Exception as exc:
        raise DEMPKIError(f"Failed to parse Trans.Encrypt.Data header: {exc}") from exc

    key_b64 = enc_fields.get("Key", "")
    if not key_b64:
        raise DEMPKIError("Trans.Encrypt.Data header missing 'Key' field")

    # Step 2 — Decrypt AES key with bank HSM
    try:
        wrapped_key = base64.b64decode(key_b64)
        aes_key = hsm.decrypt_rsa(wrapped_key)
    except Exception as exc:
        raise DEMPKIError(f"Failed to decrypt AES key via HSM: {exc}") from exc

    # Step 3 — AES-256-CBC decrypt the body
    try:
        signed_block = _aes_decrypt(aes_key, ciphertext)
    except Exception as exc:
        raise DEMPKIError(f"AES decryption failed (tampered ciphertext?): {exc}") from exc

    # Step 4 — Parse Trans.Signature.Data header
    try:
        sig_fields, original_bytes = _parse_header(signed_block, _SIG_BEGIN, _SIG_END)
    except DEMPKIError:
        raise DEMPKIError("Trans.Signature.Data header missing or malformed after decryption")
    except Exception as exc:
        raise DEMPKIError(f"Failed to parse Trans.Signature.Data header: {exc}") from exc

    sig_b64 = sig_fields.get("Data", "")
    if not sig_b64:
        raise DEMPKIError("Trans.Signature.Data header missing 'Data' (signature) field")

    # Step 5 — Verify CCH's RSA-SHA256 signature over the original file bytes
    try:
        signature = base64.b64decode(sig_b64)
        cch_pub = _cch_public_key(cch_key_bundle)
        cch_pub.verify(signature, original_bytes, asym_padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature:
        raise DEMPKIError("CCH signature verification failed — file may be tampered")
    except DEMPKIError:
        raise
    except Exception as exc:
        raise DEMPKIError(f"Signature verification error: {exc}") from exc

    return original_bytes
