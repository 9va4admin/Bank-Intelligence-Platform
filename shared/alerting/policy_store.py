"""Stored routing policies (platform.alert_routing_policies): versioned, maker-checker, encrypted, audited.

propose -> PENDING (refused with reasons if the policy is invalid) -> approve by a DIFFERENT person -> ACTIVE (the previous ACTIVE becomes SUPERSEDED history)
or reject -> REJECTED. One ACTIVE policy per bank and scope. Every step writes an ALERT_ROUTING_POLICY_CHANGED audit event naming the actor; the event carries
no addresses. The policy body is encrypted with the bank's PII key because it can name external email addresses.
"""
from __future__ import annotations

import asyncio
import random
import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from shared.alerting.incidents import MAX_LIST, _is_conflict
from shared.alerting.routing_policy import LEVELS, IncidentFacts, Policy, validate_policy
from shared.audit.audit_event import AuditEventType


class PolicyInvalid(Exception):
    def __init__(self, codes: list[str]) -> None:
        super().__init__(", ".join(codes))
        self.codes = codes


class SameUserError(Exception):
    """The person who proposed a policy cannot be the one who approves it."""


class PolicyNotPending(Exception):
    """No such proposal waiting for a decision (never existed, other bank, or already decided)."""


class PolicyRecord(BaseModel):
    model_config = ConfigDict(frozen=True)
    policy_id: str
    bank_id: str
    scope_level: str
    scope_id: Optional[str] = None
    version: int
    status: str
    rule_ids: list[str] = []
    note: Optional[str] = None
    created_by: str
    created_at: datetime
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None


_COLUMNS = "policy_id, bank_id, scope_level, scope_id, version, status, rule_ids, note, created_by, created_at, approved_by, approved_at"


def _record(row: Any) -> PolicyRecord:
    d = dict(row)
    d["scope_id"] = d["scope_id"] or None
    return PolicyRecord(**d)


class PolicyStore:
    def __init__(self, pool: Any, *, pii_key: str, auditor: Any = None, max_attempts: int = 8, retry_backoff_seconds: float = 0.03) -> None:
        self._pool, self._key, self._auditor = pool, pii_key, auditor
        self._max_attempts, self._backoff = max(1, max_attempts), retry_backoff_seconds

    async def _retrying(self, fn):
        for attempt in range(1, self._max_attempts + 1):
            try:
                return await fn()
            except Exception as exc:  # noqa: BLE001
                retry = _is_conflict(exc) or type(exc).__name__ == "UniqueViolationError"
                if not retry or attempt == self._max_attempts:
                    raise
                await asyncio.sleep(self._backoff * attempt * (0.5 + random.random()))

    async def _audit(self, bank_id: str, level: str, scope_id: Optional[str], actor: str, action: str, record: PolicyRecord) -> None:
        if self._auditor is not None:
            await self._auditor.lifecycle(AuditEventType.ALERT_ROUTING_POLICY_CHANGED, bank_id=bank_id, incident_id=f"policy:{level}:{scope_id or '*'}", actor=actor,
                                          detail={"action": action, "version": record.version, "level": level, "scope_id": scope_id,
                                                  "policy_id": record.policy_id, "rule_count": len(record.rule_ids)})

    # ------------------------------------------------------------- writes

    async def propose(self, bank_id: str, level: str, scope_id: Optional[str], policy: Policy, *, proposed_by: str, note: Optional[str] = None) -> PolicyRecord:
        codes = validate_policy(policy, level=level) if level in LEVELS else ["unknown_level"]
        if level in ("PU", "SMB"):
            if not scope_id:
                codes.append("scope_required")
            elif policy.scope_id != scope_id:
                codes.append("scope_mismatch")
        if codes:
            raise PolicyInvalid(codes)
        scope = scope_id or ""
        policy_id = uuid.uuid4().hex

        async def go() -> PolicyRecord:
            row = await self._pool.fetchrow(
                "INSERT INTO platform.alert_routing_policies (policy_id, bank_id, scope_level, scope_id, version, status, policy_enc, rule_ids, note, created_by) "
                "SELECT $1,$2,$3,$4, COALESCE(MAX(version),0)+1, 'PENDING', pgp_sym_encrypt($5,$6)::bytea, $7::text[], $8, $9 "
                "FROM platform.alert_routing_policies WHERE bank_id=$2 AND scope_level=$3 AND scope_id=$4 "
                f"RETURNING {_COLUMNS}", policy_id, bank_id, level, scope, policy.model_dump_json(), self._key, [r.id for r in policy.rules], note, proposed_by)
            return _record(row)
        record = await self._retrying(go)
        await self._audit(bank_id, level, scope_id, proposed_by, "PROPOSED", record)
        return record

    async def approve(self, bank_id: str, policy_id: str, *, approved_by: str) -> PolicyRecord:
        async def go() -> PolicyRecord:
            async with self._pool.acquire() as conn:
                async with conn.transaction():
                    pending = await conn.fetchrow(f"SELECT {_COLUMNS} FROM platform.alert_routing_policies WHERE bank_id=$1 AND policy_id=$2 AND status='PENDING'",
                                                  bank_id, policy_id)
                    if pending is None:
                        raise PolicyNotPending(policy_id)
                    if pending["created_by"] == approved_by:
                        raise SameUserError(policy_id)
                    await conn.execute("UPDATE platform.alert_routing_policies SET status='SUPERSEDED' WHERE bank_id=$1 AND scope_level=$2 AND scope_id=$3 AND status='ACTIVE'",
                                       bank_id, pending["scope_level"], pending["scope_id"])
                    row = await conn.fetchrow(f"UPDATE platform.alert_routing_policies SET status='ACTIVE', approved_by=$3, approved_at=NOW() "
                                              f"WHERE bank_id=$1 AND policy_id=$2 AND status='PENDING' RETURNING {_COLUMNS}", bank_id, policy_id, approved_by)
                    if row is None:
                        raise PolicyNotPending(policy_id)
                    return _record(row)
        record = await self._retrying(go)
        await self._audit(bank_id, record.scope_level, record.scope_id, approved_by, "APPROVED", record)
        return record

    async def reject(self, bank_id: str, policy_id: str, *, rejected_by: str, note: Optional[str] = None) -> PolicyRecord:
        async def go():
            return await self._pool.fetchrow(
                f"UPDATE platform.alert_routing_policies SET status='REJECTED', approved_by=$3, approved_at=NOW(), note=COALESCE($4, note) "
                f"WHERE bank_id=$1 AND policy_id=$2 AND status='PENDING' RETURNING {_COLUMNS}", bank_id, policy_id, rejected_by, note)
        row = await self._retrying(go)
        if row is None:
            raise PolicyNotPending(policy_id)
        record = _record(row)
        await self._audit(bank_id, record.scope_level, record.scope_id, rejected_by, "REJECTED", record)
        return record

    # ------------------------------------------------------------- reads

    async def _policy_of(self, row: Any) -> Policy:
        return Policy.model_validate_json(row["body"])

    async def get_active(self, bank_id: str, level: str, scope_id: Optional[str]) -> Optional[Policy]:
        row = await self._pool.fetchrow(
            "SELECT pgp_sym_decrypt(policy_enc, $4) AS body FROM platform.alert_routing_policies WHERE bank_id=$1 AND scope_level=$2 AND scope_id=$3 AND status='ACTIVE'",
            bank_id, level, scope_id or "", self._key)
        return await self._policy_of(row) if row else None

    async def get_pending(self, bank_id: str, policy_id: str) -> Optional[PolicyRecord]:
        row = await self._pool.fetchrow(f"SELECT {_COLUMNS} FROM platform.alert_routing_policies WHERE bank_id=$1 AND policy_id=$2 AND status='PENDING'", bank_id, policy_id)
        return _record(row) if row else None

    async def history(self, bank_id: str, level: str, scope_id: Optional[str], *, limit: int) -> list[PolicyRecord]:
        rows = await self._pool.fetch(
            f"SELECT {_COLUMNS} FROM platform.alert_routing_policies WHERE bank_id=$1 AND scope_level=$2 AND scope_id=$3 ORDER BY version DESC LIMIT $4",
            bank_id, level, scope_id or "", min(max(limit, 1), MAX_LIST))
        return [_record(r) for r in rows]

    async def effective(self, bank_id: str, facts: IncidentFacts) -> dict[str, list[Policy]]:
        """The active policies that apply to an incident: the bank's, plus its PU's and its SMB's if they have one."""
        scopes = [("BANK", "")]
        if facts.pu_id:
            scopes.append(("PU", facts.pu_id))
        if facts.smb_id:
            scopes.append(("SMB", facts.smb_id))
        out: dict[str, list[Policy]] = {}
        for level, scope in scopes:
            policy = await self.get_active(bank_id, level, scope or None)
            if policy is not None:
                out[level] = [policy]
        return out

    async def get_record(self, bank_id: str, policy_id: str) -> Optional[PolicyRecord]:
        """A policy record in any status (None if it does not exist in this bank)."""
        row = await self._pool.fetchrow(f"SELECT {_COLUMNS} FROM platform.alert_routing_policies WHERE bank_id=$1 AND policy_id=$2", bank_id, policy_id)
        return _record(row) if row else None

    async def active_record(self, bank_id: str, level: str, scope_id: Optional[str]) -> Optional[PolicyRecord]:
        row = await self._pool.fetchrow(
            f"SELECT {_COLUMNS} FROM platform.alert_routing_policies WHERE bank_id=$1 AND scope_level=$2 AND scope_id=$3 AND status='ACTIVE'", bank_id, level, scope_id or "")
        return _record(row) if row else None

    async def list_active(self, bank_id: str) -> list[PolicyRecord]:
        rows = await self._pool.fetch(f"SELECT {_COLUMNS} FROM platform.alert_routing_policies WHERE bank_id=$1 AND status='ACTIVE' ORDER BY scope_level, scope_id LIMIT $2",
                                      bank_id, MAX_LIST)
        return [_record(r) for r in rows]

    async def list_pending(self, bank_id: str) -> list[PolicyRecord]:
        rows = await self._pool.fetch(f"SELECT {_COLUMNS} FROM platform.alert_routing_policies WHERE bank_id=$1 AND status='PENDING' ORDER BY created_at DESC LIMIT $2",
                                      bank_id, MAX_LIST)
        return [_record(r) for r in rows]

    async def get_by_id(self, bank_id: str, policy_id: str) -> Optional[tuple[PolicyRecord, Policy]]:
        """A policy and its record in any status, so an approver can read what they are deciding on."""
        row = await self._pool.fetchrow(
            f"SELECT {_COLUMNS}, pgp_sym_decrypt(policy_enc, $3) AS body FROM platform.alert_routing_policies WHERE bank_id=$1 AND policy_id=$2", bank_id, policy_id, self._key)
        return (_record(row), Policy.model_validate_json(row["body"])) if row else None
