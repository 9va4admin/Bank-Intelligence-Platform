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
    CTS_DECISION = "CTS_DECISION"
    CTS_VAULT_MISS = "CTS_VAULT_MISS"
    CTS_NGCH_FILED = "CTS_NGCH_FILED"
    CTS_HUMAN_REVIEW_ESCALATED = "CTS_HUMAN_REVIEW_ESCALATED"
    CTS_HUMAN_REVIEW_RESOLVED = "CTS_HUMAN_REVIEW_RESOLVED"
    EJ_PARSED = "EJ_PARSED"
    EJ_DISPUTE_RESOLVED = "EJ_DISPUTE_RESOLVED"
    EJ_DISPUTE_ESCALATED = "EJ_DISPUTE_ESCALATED"
    CONFIG_CHANGE = "CONFIG_CHANGE"
    DIAGNOSTIC_ACCESS = "DIAGNOSTIC_ACCESS"
    VAULT_SYNC = "VAULT_SYNC"
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
