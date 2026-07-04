"""
EEH Session Manager.

One active session per branch per clearing date. Backed by Redis (hot cert lookup)
and YugabyteDB (cts.eeh_sessions persistent record).

Redis keys:
  eeh:cert:{cert_fingerprint}  → EEHSession JSON  (TTL = session_ttl_seconds)
  eeh:sess:{session_id}        → EEHSession JSON  (TTL = session_ttl_seconds)

Session lifecycle: ACTIVE → CLOSED | EXPIRED | REVOKED
"""
from __future__ import annotations

import json
import uuid
import structlog
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timezone
from typing import Any, Optional

log = structlog.get_logger()


# ── Redis key helpers ──────────────────────────────────────────────────────────

def session_cert_key(cert_fingerprint: str) -> str:
    return f"eeh:cert:{cert_fingerprint}"


def session_id_key(session_id: str) -> str:
    return f"eeh:sess:{session_id}"


# ── Exceptions ─────────────────────────────────────────────────────────────────

class SessionAlreadyActiveError(Exception):
    """Branch already has an active session for this clearing date."""


class SessionNotFoundError(Exception):
    """No active session found for the given cert fingerprint or session ID."""


class CertRevokedError(Exception):
    """The cert fingerprint belongs to a REVOKED session — access denied."""


# ── EEHSession ─────────────────────────────────────────────────────────────────

@dataclass
class EEHSession:
    session_id:        str
    bank_id:           str
    branch_id:         str
    operator_id:       str
    cert_fingerprint:  str
    hub_type:          str          # EEH | IEH
    clearing_date:     date
    expires_at:        datetime
    status:            str = "ACTIVE"
    total_uploaded:    int = 0
    total_accepted:    int = 0
    total_rejected:    int = 0
    opened_at:         datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["clearing_date"] = self.clearing_date.isoformat()
        d["expires_at"] = self.expires_at.isoformat()
        d["opened_at"] = self.opened_at.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "EEHSession":
        return cls(
            session_id=d["session_id"],
            bank_id=d["bank_id"],
            branch_id=d["branch_id"],
            operator_id=d["operator_id"],
            cert_fingerprint=d["cert_fingerprint"],
            hub_type=d["hub_type"],
            clearing_date=date.fromisoformat(d["clearing_date"]),
            expires_at=datetime.fromisoformat(d["expires_at"]),
            status=d.get("status", "ACTIVE"),
            total_uploaded=d.get("total_uploaded", 0),
            total_accepted=d.get("total_accepted", 0),
            total_rejected=d.get("total_rejected", 0),
            opened_at=datetime.fromisoformat(d["opened_at"]) if "opened_at" in d
                      else datetime.now(tz=timezone.utc),
        )


# ── SQL ───────────────────────────────────────────────────────────────────────

_INSERT_SESSION_SQL = """
INSERT INTO cts.eeh_sessions
  (session_id, bank_id, branch_id, operator_id, cert_fingerprint,
   hub_type, status, clearing_date, opened_at, expires_at)
VALUES ($1, $2, $3, $4, $5, $6, 'ACTIVE', $7, NOW(), $8)
"""

_CLOSE_SESSION_SQL = """
UPDATE cts.eeh_sessions
SET status = $2, closed_at = NOW(), updated_at = NOW()
WHERE session_id = $1
"""

_UPDATE_COUNTERS_SQL = """
UPDATE cts.eeh_sessions
SET total_uploaded = total_uploaded + $2,
    total_accepted = total_accepted + $3,
    total_rejected = total_rejected + $4,
    updated_at = NOW()
WHERE session_id = $1
"""

_FETCH_BY_CERT_SQL = """
SELECT session_id, bank_id, branch_id, operator_id, cert_fingerprint,
       hub_type, status, clearing_date, opened_at, expires_at,
       total_uploaded, total_accepted, total_rejected
FROM cts.eeh_sessions
WHERE cert_fingerprint = $1 AND status = 'ACTIVE'
ORDER BY opened_at DESC LIMIT 1
"""

_FETCH_BY_ID_SQL = """
SELECT session_id, bank_id, branch_id, operator_id, cert_fingerprint,
       hub_type, status, clearing_date, opened_at, expires_at,
       total_uploaded, total_accepted, total_rejected
FROM cts.eeh_sessions
WHERE session_id = $1
"""

_ACTIVE_BRANCH_SESSION_KEY = "eeh:active:{branch_id}:{clearing_date}"


# ── Manager ────────────────────────────────────────────────────────────────────

class EEHSessionManager:
    """
    Manages EEH/IEH branch sessions. Inject one instance per FastAPI app (lifespan).

    Args:
        redis: Async Redis client.
        db:    Async asyncpg connection / pool.
    """

    def __init__(self, *, redis: Any, db: Any) -> None:
        self._redis = redis
        self._db = db

    # ── Open ─────────────────────────────────────────────────────────────────

    async def open_session(
        self,
        *,
        bank_id: str,
        branch_id: str,
        operator_id: str,
        cert_fingerprint: str,
        hub_type: str,
        clearing_date: date,
        session_ttl_seconds: int,
    ) -> EEHSession:
        # Check for existing active session for this branch today
        active_key = _ACTIVE_BRANCH_SESSION_KEY.format(
            branch_id=branch_id, clearing_date=clearing_date.isoformat()
        )
        existing_raw = await self._redis.get(active_key)
        if existing_raw is not None:
            raise SessionAlreadyActiveError(
                f"Branch {branch_id!r} already has an active session for {clearing_date}. "
                f"Close the existing session before opening a new one."
            )

        from datetime import timedelta
        expires_at = datetime.now(tz=timezone.utc) + timedelta(seconds=session_ttl_seconds)
        session = EEHSession(
            session_id=str(uuid.uuid4()),
            bank_id=bank_id,
            branch_id=branch_id,
            operator_id=operator_id,
            cert_fingerprint=cert_fingerprint,
            hub_type=hub_type,
            clearing_date=clearing_date,
            expires_at=expires_at,
        )

        # Persist to DB
        await self._db.execute(
            _INSERT_SESSION_SQL,
            session.session_id, bank_id, branch_id, operator_id,
            cert_fingerprint, hub_type, clearing_date, expires_at,
        )

        # Cache in Redis — two keys: by cert and by session_id
        payload = json.dumps(session.to_dict())
        await self._redis.set(
            session_cert_key(cert_fingerprint), payload, ex=session_ttl_seconds
        )
        await self._redis.set(
            session_id_key(session.session_id), payload, ex=session_ttl_seconds
        )
        # Active-branch sentinel (one per branch per day)
        await self._redis.set(active_key, session.session_id, ex=session_ttl_seconds)

        log.info(
            "eeh.session.opened",
            session_id=session.session_id,
            branch_id=branch_id,
            hub_type=hub_type,
        )
        return session

    # ── Resolve ───────────────────────────────────────────────────────────────

    async def resolve_by_cert(self, cert_fingerprint: str) -> EEHSession:
        """Hot path: called on every gRPC/SSE request to validate the session."""
        raw = await self._redis.get(session_cert_key(cert_fingerprint))
        if raw is not None:
            session = EEHSession.from_dict(json.loads(raw))
            if session.status == "REVOKED":
                raise CertRevokedError(f"Cert {cert_fingerprint!r} is revoked.")
            if session.status != "ACTIVE":
                raise SessionNotFoundError(
                    f"Session for cert {cert_fingerprint!r} is {session.status}."
                )
            return session

        # Redis miss → DB fallback
        row = await self._db.fetchrow(_FETCH_BY_CERT_SQL, cert_fingerprint)
        if row is None:
            raise SessionNotFoundError(
                f"No active session found for cert {cert_fingerprint!r}."
            )
        session = EEHSession.from_dict(dict(row))
        if session.status == "REVOKED":
            raise CertRevokedError(f"Cert {cert_fingerprint!r} is revoked.")
        return session

    # ── Close ─────────────────────────────────────────────────────────────────

    async def close_session(self, session_id: str, status: str = "CLOSED") -> None:
        raw = await self._redis.get(session_id_key(session_id))
        if raw is None:
            log.warning("eeh.session.close_not_found", session_id=session_id)
            return

        session = EEHSession.from_dict(json.loads(raw))
        session_dict = session.to_dict()
        session_dict["status"] = status
        payload = json.dumps(session_dict)

        await self._redis.set(
            session_cert_key(session.cert_fingerprint), payload, ex=3600
        )
        await self._redis.set(session_id_key(session_id), payload, ex=3600)
        await self._db.execute(_CLOSE_SESSION_SQL, session_id, status)

        log.info("eeh.session.closed", session_id=session_id, status=status)

    # ── Counters ──────────────────────────────────────────────────────────────

    async def record_batch_result(
        self, *, session_id: str, accepted: int, rejected: int
    ) -> None:
        raw = await self._redis.get(session_id_key(session_id))
        if raw is None:
            return

        session_dict = json.loads(raw)
        uploaded = accepted + rejected
        session_dict["total_uploaded"] = session_dict.get("total_uploaded", 0) + uploaded
        session_dict["total_accepted"] = session_dict.get("total_accepted", 0) + accepted
        session_dict["total_rejected"] = session_dict.get("total_rejected", 0) + rejected

        payload = json.dumps(session_dict)
        await self._redis.set(
            session_id_key(session_id), payload,
            keepttl=True,
        )
        await self._db.execute(
            _UPDATE_COUNTERS_SQL, session_id, uploaded, accepted, rejected
        )
