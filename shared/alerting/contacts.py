"""Alert contacts: the outside addresses and phone numbers alerts may go to, verified by a code before they count for Go-Live.

The address is stored encrypted (pgcrypto, the bank's PII key) with a keyed hash for lookup; the code is stored only as a keyed hash, is single use, expires, and
allows a limited number of wrong tries. Lists show the address masked. The decrypted address is available only to send the code.
"""
from __future__ import annotations

import hmac
import re
import secrets
import uuid
from datetime import datetime
from typing import Any, Literal, Optional

import structlog
from pydantic import BaseModel, ConfigDict

from shared.utils.masking import mask_email, mask_phone
from shared.utils.pii_crypto import hash_account_number

log = structlog.get_logger()

Kind = Literal["email", "phone"]
_EMAIL = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
_PHONE = re.compile(r"^\+[1-9][0-9]{7,14}$")


class ContactInvalid(Exception):
    """The address was refused. `code` is invalid_kind | invalid_email | invalid_phone | duplicate."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class Contact(BaseModel):
    model_config = ConfigDict(frozen=True)
    contact_id: str
    kind: Kind
    address_masked: str
    label: str
    status: Literal["UNVERIFIED", "VERIFIED"]
    code_pending: bool = False
    verified_at: Optional[datetime] = None
    verified_by: Optional[str] = None
    created_by: str
    created_at: datetime


class VerifyResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    ok: bool
    reason: str          # ok | wrong_code | expired | too_many_attempts | already_verified | not_found


def _normalise(kind: str, address: str) -> str:
    text = (address or "").strip()
    if kind == "email":
        text = text.lower()
        if not _EMAIL.match(text):
            raise ContactInvalid("invalid_email")
    elif kind == "phone":
        if not _PHONE.match(text):
            raise ContactInvalid("invalid_phone")
    else:
        raise ContactInvalid("invalid_kind")
    return text


def _mask(kind: str, address: str) -> str:
    return mask_email(address) if kind == "email" else mask_phone(address)


def _canonical(address: str) -> str:
    text = address.strip()
    return text.lower() if "@" in text else text


_COLUMNS = "contact_id, kind, label, status, code_hash IS NOT NULL AS code_pending, verified_at, verified_by, created_by, created_at"


class ContactStore:
    def __init__(self, pool: Any, *, pii_key: str, pepper: str, code_ttl_minutes: int = 15, max_attempts: int = 5, code_length: int = 6) -> None:
        self._pool, self._key, self._pepper = pool, pii_key, pepper
        self._ttl, self._max_attempts, self._length = code_ttl_minutes, max_attempts, code_length

    def _hash(self, bank_id: str, value: str) -> str:
        return hash_account_number(value, bank_id, self._pepper)

    def _new_code(self) -> str:
        return str(secrets.randbelow(10 ** self._length)).zfill(self._length)

    @staticmethod
    def _to_contact(row: Any, address: Optional[str] = None) -> Contact:
        masked = _mask(row["kind"], address) if address else ""
        return Contact(contact_id=row["contact_id"], kind=row["kind"], address_masked=masked, label=row["label"], status=row["status"], code_pending=row["code_pending"],
                       verified_at=row["verified_at"], verified_by=row["verified_by"], created_by=row["created_by"], created_at=row["created_at"])

    async def add(self, bank_id: str, kind: str, address: str, label: str, created_by: str) -> tuple[Contact, str]:
        """Add an unverified contact and return it with the code to send. A repeated address is refused."""
        normal = _normalise(kind, address)
        contact_id, code = uuid.uuid4().hex, self._new_code()
        try:
            row = await self._pool.fetchrow(
                "INSERT INTO platform.alert_contacts (contact_id, bank_id, kind, address_enc, address_hash, label, code_hash, code_expires_at, created_by) "
                "VALUES ($1,$2,$3, pgp_sym_encrypt($4,$5)::bytea, $6,$7,$8, NOW() + make_interval(mins => $9), $10) "
                f"RETURNING {_COLUMNS}",
                contact_id, bank_id, kind, normal, self._key, self._hash(bank_id, normal), label.strip()[:80], self._hash(bank_id, f"{contact_id}:{code}"), self._ttl, created_by)
        except Exception as exc:  # noqa: BLE001
            if "ux_alert_contacts_address" in str(exc) or "duplicate key" in str(exc).lower():
                raise ContactInvalid("duplicate") from exc
            raise
        return self._to_contact(row, normal), code

    async def issue_code(self, bank_id: str, contact_id: str) -> Optional[str]:
        """A new code for a contact (the old one stops working and the wrong-try count starts again). None if there is no such unverified contact."""
        code = self._new_code()
        updated = await self._pool.fetchval(
            "UPDATE platform.alert_contacts SET code_hash=$3, code_expires_at = NOW() + make_interval(mins => $4), attempts=0 "
            "WHERE bank_id=$1 AND contact_id=$2 AND status='UNVERIFIED' RETURNING contact_id", bank_id, contact_id, self._hash(bank_id, f"{contact_id}:{code}"), self._ttl)
        return code if updated else None

    async def verify(self, bank_id: str, contact_id: str, code: str, by: str) -> VerifyResult:
        row = await self._pool.fetchrow("SELECT status, code_hash, attempts, code_expires_at < NOW() AS expired FROM platform.alert_contacts WHERE bank_id=$1 AND contact_id=$2",
                                        bank_id, contact_id)
        if row is None:
            return VerifyResult(ok=False, reason="not_found")
        if row["status"] == "VERIFIED":
            return VerifyResult(ok=False, reason="already_verified")
        if row["code_hash"] is None or row["expired"]:
            return VerifyResult(ok=False, reason="expired")
        if row["attempts"] >= self._max_attempts:
            return VerifyResult(ok=False, reason="too_many_attempts")
        if not hmac.compare_digest(row["code_hash"], self._hash(bank_id, f"{contact_id}:{(code or '').strip()}")):
            await self._pool.execute("UPDATE platform.alert_contacts SET attempts = attempts + 1 WHERE bank_id=$1 AND contact_id=$2", bank_id, contact_id)
            return VerifyResult(ok=False, reason="wrong_code")
        await self._pool.execute("UPDATE platform.alert_contacts SET status='VERIFIED', verified_at=NOW(), verified_by=$3, code_hash=NULL, code_expires_at=NULL, attempts=0 "
                                 "WHERE bank_id=$1 AND contact_id=$2", bank_id, contact_id, by)
        return VerifyResult(ok=True, reason="ok")

    async def list(self, bank_id: str, limit: int = 200) -> list[Contact]:
        rows = await self._pool.fetch(f"SELECT {_COLUMNS}, pgp_sym_decrypt(address_enc, $2) AS address FROM platform.alert_contacts WHERE bank_id=$1 ORDER BY created_at DESC LIMIT $3",
                                      bank_id, self._key, limit)
        return [self._to_contact(r, r["address"]) for r in rows]

    async def address(self, bank_id: str, contact_id: str) -> Optional[str]:
        """The decrypted address, only to send the code."""
        return await self._pool.fetchval("SELECT pgp_sym_decrypt(address_enc, $3) FROM platform.alert_contacts WHERE bank_id=$1 AND contact_id=$2", bank_id, contact_id, self._key)

    async def remove(self, bank_id: str, contact_id: str) -> bool:
        return bool(await self._pool.fetchval("DELETE FROM platform.alert_contacts WHERE bank_id=$1 AND contact_id=$2 RETURNING contact_id", bank_id, contact_id))

    async def unverified(self, bank_id: str, addresses: list[str]) -> list[str]:
        """Of these addresses, the ones that are not a verified contact (an e-mail address is compared lower-cased, as the store holds it)."""
        wanted = {self._hash(bank_id, _canonical(a)): _canonical(a) for a in addresses if a and a.strip()}
        if not wanted:
            return []
        rows = await self._pool.fetch("SELECT address_hash FROM platform.alert_contacts WHERE bank_id=$1 AND status='VERIFIED' AND address_hash = ANY($2::text[])", bank_id, list(wanted))
        verified = {r["address_hash"] for r in rows}
        return [address for h, address in wanted.items() if h not in verified]
