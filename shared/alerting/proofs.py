"""Readiness proofs: checks that have to be run, not just read.

`prove_audit_path` writes a sentinel alert (an intent and then an outcome) to the audit trail, reads both back and verifies them in the Merkle tree.
The sentinel carries no address, phone number or secret, and is marked so nobody mistakes it for a real alert.
`ProofStore` keeps the result of each run, so the Go-Live screen can say when it last passed and who ran it.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict, Field

log = structlog.get_logger()

AUDIT_PATH = "audit_path"
SENTINEL_COMPONENT = "readiness-proof"


class AuditProof(BaseModel):
    model_config = ConfigDict(frozen=True)
    ok: bool
    reason: str                                         # ok | not_connected | write_failed | verify_failed
    detail: dict[str, Any] = Field(default_factory=dict)


class Proof(BaseModel):
    model_config = ConfigDict(frozen=True)
    proof_id: str
    bank_id: str
    kind: str
    ok: bool
    detail: dict[str, Any]
    ran_by: str
    ran_at: datetime


def _sentinel_events(bank_id: str, actor: str, sentinel_id: str) -> list[dict[str, Any]]:
    base = {"incident_id": sentinel_id, "component": SENTINEL_COMPONENT, "sentinel": True, "channel": "bell", "ran_by": actor}
    return [
        {"event_type": "ALERT_DISPATCH_INTENDED", "bank_id": bank_id, "instrument_id": sentinel_id,
         "payload": {**base, "delivery_id": f"{sentinel_id}-d", "recipient_ref": "sentinel", "level": 0, "template_id": "readiness-proof", "severity": "P3", "rule_id": "sentinel"}},
        {"event_type": "ALERT_DELIVERY_SUCCEEDED", "bank_id": bank_id, "instrument_id": sentinel_id,
         "payload": {**base, "delivery_id": f"{sentinel_id}-d", "attempt": 1, "intent_ref": sentinel_id}},
    ]


async def prove_audit_path(client: Any, *, bank_id: str, collection: str, actor: str) -> AuditProof:
    """Write the sentinel intent and outcome, then verify both. Never raises: a problem is a failed proof with a reason."""
    if client is None:
        return AuditProof(ok=False, reason="not_connected")
    sentinel_id = f"sentinel-{uuid.uuid4().hex[:12]}"

    def run() -> AuditProof:
        written: list[dict[str, Any]] = []
        try:
            client.set_collection(collection)
            for event in _sentinel_events(bank_id, actor, sentinel_id):
                written.append(client.write_event(event))
        except Exception as exc:  # noqa: BLE001
            log.warning("alert_proof.audit_write_failed", bank_id=bank_id, error_type=type(exc).__name__)
            return AuditProof(ok=False, reason="write_failed", detail={"written": len(written), "sentinel": sentinel_id})
        detail = {"sentinel": sentinel_id, "intent_tx": written[0].get("tx_id"), "outcome_tx": written[1].get("tx_id")}
        try:
            verified = all(w.get("verified") is True and client.verify_event(w["key"]) is True for w in written)
        except Exception as exc:  # noqa: BLE001
            log.warning("alert_proof.audit_verify_failed", bank_id=bank_id, error_type=type(exc).__name__)
            verified = False
        return AuditProof(ok=verified, reason="ok" if verified else "verify_failed", detail=detail)
    return await asyncio.to_thread(run)


class ProofStore:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def record(self, bank_id: str, kind: str, ok: bool, detail: dict[str, Any], ran_by: str) -> str:
        proof_id = uuid.uuid4().hex
        await self._pool.execute(
            "INSERT INTO platform.alert_readiness_proofs (proof_id, bank_id, kind, ok, detail, ran_by) VALUES ($1,$2,$3,$4,$5::jsonb,$6)",
            proof_id, bank_id, kind, ok, json.dumps(detail), ran_by)
        return proof_id

    @staticmethod
    def _proof(row: Any) -> Proof:
        detail = row["detail"]
        return Proof(proof_id=row["proof_id"], bank_id=row["bank_id"], kind=row["kind"], ok=row["ok"], detail=json.loads(detail) if isinstance(detail, str) else dict(detail),
                     ran_by=row["ran_by"], ran_at=row["ran_at"])

    async def latest(self, bank_id: str, kind: str) -> Optional[Proof]:
        row = await self._pool.fetchrow(
            "SELECT proof_id, bank_id, kind, ok, detail, ran_by, ran_at FROM platform.alert_readiness_proofs WHERE bank_id=$1 AND kind=$2 ORDER BY ran_at DESC LIMIT 1",
            bank_id, kind)
        return self._proof(row) if row else None

    async def latest_many(self, bank_id: str, kinds: list[str]) -> dict[str, Proof]:
        rows = await self._pool.fetch(
            "SELECT DISTINCT ON (kind) proof_id, bank_id, kind, ok, detail, ran_by, ran_at FROM platform.alert_readiness_proofs "
            "WHERE bank_id=$1 AND kind = ANY($2::text[]) ORDER BY kind, ran_at DESC", bank_id, kinds)
        return {r["kind"]: self._proof(r) for r in rows}
