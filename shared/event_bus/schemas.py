"""
Kafka event envelope — every message published to any ASTRA topic must be
wrapped in this schema so consumers can version-gate their deserialisation.

From api-versioning.md:
  Every Kafka event envelope must carry schema_version.
  Consumer must handle both versions during migration window.
"""
import time
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class KafkaEventEnvelope(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str
    bank_id: str
    schema_version: str                    # "1.0", "2.0" — never omit
    payload: dict[str, Any]
    timestamp: float = Field(default_factory=time.time)
