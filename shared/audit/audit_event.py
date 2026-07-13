"""
AuditEvent — immutable schema for every audit record written to Immudb.

Every write to YugabyteDB that modifies a cheque or EJ record must be
followed by an ImmudbClient.write_event(audit_event.to_json()) call.

HSM signing is required before Immudb write on all production paths.
In tests the HSM is mocked — AuditEvent.sign(mock_hsm) works the same way.
"""
import json
import time
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AuditEventType(str, Enum):
    # ── CTS Inward ─────────────────────────────────────────────────────────────
    CTS_DECISION = "CTS_DECISION"
    CTS_VAULT_MISS = "CTS_VAULT_MISS"
    CTS_NGCH_FILED = "CTS_NGCH_FILED"
    CTS_HUMAN_REVIEW_ESCALATED = "CTS_HUMAN_REVIEW_ESCALATED"
    CTS_HUMAN_REVIEW_RESOLVED = "CTS_HUMAN_REVIEW_RESOLVED"
    CTS_IET_WATCHDOG_FIRED = "CTS_IET_WATCHDOG_FIRED"       # T-30s emergency path fired
    CTS_REVIEW_TIMEOUT = "CTS_REVIEW_TIMEOUT"               # 55-min human review auto-return
    CTS_REVIEW_ASSIGNED = "CTS_REVIEW_ASSIGNED"             # instrument pushed to human queue

    # ── CTS Outward ────────────────────────────────────────────────────────────
    CTS_OUTWARD_QUEUE_DECISION = "CTS_OUTWARD_QUEUE_DECISION"  # Outward Q: manual confirm/reject decided

    # ── CTS NGCH / transport ───────────────────────────────────────────────────
    CTS_NGCH_TERMINAL_FAILURE = "CTS_NGCH_TERMINAL_FAILURE"  # max retries exhausted
    CTS_NGCH_CERT_EXPIRED = "CTS_NGCH_CERT_EXPIRED"          # mTLS cert expired

    # ── Kill switch ────────────────────────────────────────────────────────────
    CTS_KILL_SWITCH_ENGAGED = "CTS_KILL_SWITCH_ENGAGED"    # operator activates kill switch
    CTS_KILL_SWITCH_RELEASED = "CTS_KILL_SWITCH_RELEASED"  # operator deactivates kill switch
    CTS_KILL_SWITCH_APPLIED = "CTS_KILL_SWITCH_APPLIED"    # per-instrument: KP or KC applied

    # ── CBS connector ──────────────────────────────────────────────────────────
    CBS_UNREACHABLE = "CBS_UNREACHABLE"                     # CBS not responding during clearing
    CBS_AUTH_FAILED = "CBS_AUTH_FAILED"                     # CBS authentication failure
    CBS_RECOVERED = "CBS_RECOVERED"                         # CBS connectivity restored

    # ── Vault ──────────────────────────────────────────────────────────────────
    VAULT_STALE = "VAULT_STALE"                             # vault not synced for >24 hrs
    VAULT_INTEGRITY_FAIL = "VAULT_INTEGRITY_FAIL"           # vault integrity check failed
    VAULT_SYNC_FAILED = "VAULT_SYNC_FAILED"                 # VaultSyncWorkflow failed
    VAULT_SYNC = "VAULT_SYNC"                               # successful vault sync (existing)

    # ── EJ module ──────────────────────────────────────────────────────────────
    EJ_PARSED = "EJ_PARSED"
    EJ_DISPUTE_RESOLVED = "EJ_DISPUTE_RESOLVED"
    EJ_DISPUTE_ESCALATED = "EJ_DISPUTE_ESCALATED"
    EJ_ATM_HEALTH_CHANGED = "EJ_ATM_HEALTH_CHANGED"        # HEALTHY→DEGRADED→CRITICAL transition
    EJ_OEM_UNKNOWN = "EJ_OEM_UNKNOWN"                       # fingerprint produced no match

    # ── MCP connection config ──────────────────────────────────────────────────
    MCP_CONN_CREATED = "MCP_CONN_CREATED"           # new connection configured
    MCP_CONN_UPDATED = "MCP_CONN_UPDATED"           # endpoint/vendor/secret changed → status PENDING
    MCP_CONN_DELETED = "MCP_CONN_DELETED"           # connection removed
    MCP_CONN_TESTED_OK = "MCP_CONN_TESTED_OK"       # test passed → status ACTIVE
    MCP_CONN_TESTED_FAIL = "MCP_CONN_TESTED_FAIL"   # test failed → status ERROR
    MCP_CONN_SYNC_TRIGGERED = "MCP_CONN_SYNC_TRIGGERED"  # vault sync workflow started

    # ── Platform / infra ───────────────────────────────────────────────────────
    CONFIG_CHANGE = "CONFIG_CHANGE"
    DIAGNOSTIC_ACCESS = "DIAGNOSTIC_ACCESS"
    BANK_ONBOARDED = "BANK_ONBOARDED"


class HSMSigningError(RuntimeError):
    """Raised when the HSM fails to sign an audit event."""


class AuditEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_type: AuditEventType
    bank_id: str
    payload: dict[str, Any]

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = Field(default_factory=time.time)
    signature: bytes | None = Field(default=None)

    def to_json(self) -> bytes:
        """Return canonical JSON bytes for storage and signing."""
        data = {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "bank_id": self.bank_id,
            "timestamp": self.timestamp,
            "payload": self.payload,
        }
        if self.signature is not None:
            data["signature"] = self.signature.hex()
        return json.dumps(data, sort_keys=True, default=str).encode()

    def sign(self, hsm: Any) -> "AuditEvent":
        """
        Return a new AuditEvent with the HSM signature attached.

        hsm must expose: hsm.sign(bytes) -> bytes
        The bytes signed are to_json() of the unsigned event.
        Raises HSMSigningError on HSM failure.
        Raises ValueError if the event is already signed.
        """
        if self.signature is not None:
            raise ValueError("AuditEvent is already signed — cannot sign twice")

        canonical = self.to_json()
        try:
            sig = hsm.sign(canonical)
        except Exception as exc:
            raise HSMSigningError(f"HSM signing failed: {exc}") from exc

        return self.model_copy(update={"signature": sig})
