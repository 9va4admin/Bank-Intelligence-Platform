"""
PII cryptographic utilities — THE single source of truth for all hashing and
encryption of personally identifiable information in ASTRA.

Rules:
  - Every vault, connector, workflow, and processor MUST import from here.
  - No inline hmac.new() / hashlib.sha256() anywhere else in the codebase.
  - No copy-pasted hash logic in any module.

Two operations:

1. hash_account_number(account_number, bank_id, pepper) → str
   HMAC-SHA256 keyed with bank-specific pepper from Vault.
   Used as: Redis key suffix + DB account_hash column.
   One-way: account numbers are NEVER recoverable from the hash.
   bank_id is included in the message to prevent cross-bank hash collisions.

2. encrypt_pii / decrypt_pii
   pgcrypto symmetric encryption (pgp_sym_encrypt / pgp_sym_decrypt) executed
   inside YugabyteDB via asyncpg.  Key comes from Vault transit engine via
   config_service — never a literal string.
   Used for: payee_name, holder_name, any reversible PII field stored in DB.

Do NOT use:
  - hashlib.sha256(account_number) — no pepper, wrong hash
  - hmac.new(...) anywhere outside this file
  - Any cloud KMS — data localisation violation
"""
from __future__ import annotations

import hashlib
import hmac
from typing import Optional


# ---------------------------------------------------------------------------
# 1. Canonical account-number hash  (sync, no DB)
# ---------------------------------------------------------------------------

def hash_account_number(account_number: str, bank_id: str, pepper: str) -> str:
    """
    HMAC-SHA256(pepper, "{bank_id}:{account_number}").

    Args:
        account_number: raw account number string (never stored after this call)
        bank_id:        prevents cross-bank collision if two banks share a pepper
        pepper:         bank-specific secret from Vault:
                        secret/astra/{bank_id}/pii_hash_pepper

    Returns 64-character lowercase hex digest.
    """
    if not pepper:
        raise ValueError(
            "pepper must not be empty — fetch it from Vault via config_service"
        )
    message = f"{bank_id}:{account_number}".encode()
    return hmac.new(pepper.encode(), message, hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# 2. Reversible PII encryption via YugabyteDB pgcrypto  (async, needs conn)
# ---------------------------------------------------------------------------

async def encrypt_pii(plaintext: str, key: str, conn) -> bytes:
    """
    Encrypt a PII string using PostgreSQL pgp_sym_encrypt (pgcrypto).

    Args:
        plaintext: the raw PII value (payee name, holder name, etc.)
        key:       symmetric key string fetched from Vault transit engine
        conn:      asyncpg connection (already inside a transaction is fine)

    Returns bytes suitable for storage in a BYTEA column.
    """
    if not plaintext:
        return b""
    if not key:
        raise ValueError(
            "encryption key must not be empty — fetch from Vault via config_service"
        )
    row = await conn.fetchrow(
        "SELECT pgp_sym_encrypt($1, $2)::bytea AS enc",
        plaintext,
        key,
    )
    return bytes(row["enc"])


async def decrypt_pii(ciphertext: Optional[bytes], key: str, conn) -> str:
    """
    Decrypt a pgp_sym_encrypt ciphertext back to plaintext.

    Args:
        ciphertext: bytes from a BYTEA column (may be None → returns "")
        key:        the same symmetric key used during encryption
        conn:       asyncpg connection

    Returns the original plaintext string, or "" if ciphertext is None/empty.
    """
    if not ciphertext:
        return ""
    if not key:
        raise ValueError(
            "encryption key must not be empty — fetch from Vault via config_service"
        )
    row = await conn.fetchrow(
        "SELECT pgp_sym_decrypt($1::bytea, $2) AS dec",
        ciphertext,
        key,
    )
    return row["dec"] or ""
