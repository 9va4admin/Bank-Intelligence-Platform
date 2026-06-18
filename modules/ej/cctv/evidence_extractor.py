"""
CCTV evidence extraction for EJ dispute resolution.

Fetches clip from CCTV adapter, stores to MinIO object store.
Used by DisputeResolutionWorkflow before any auto-resolution decision.

CCTV clips stored in MinIO only — never in YugabyteDB.
Object key format: cctv/{bank_id}/{atm_id}/{claim_id}.mp4
"""
from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()


class NoFootageError(Exception):
    """Raised by CCTV adapter when no footage is available for the requested timestamp."""


class CCTVExtractionInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    atm_id: str
    branch_id: str
    timestamp: str
    claim_id: str


class CCTVExtractionResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str                        # "EXTRACTED" | "NO_FOOTAGE" | "ADAPTER_ERROR"
    bank_id: str
    object_key: Optional[str] = None
    clip_duration_seconds: Optional[int] = None
    frame_count: Optional[int] = None


async def extract_cctv_evidence(
    inp: CCTVExtractionInput,
    *,
    cctv_adapter,
    object_store,
) -> CCTVExtractionResult:
    """
    Fetch CCTV clip and store in MinIO.

    Returns EXTRACTED on success, NO_FOOTAGE if adapter has no clip,
    ADAPTER_ERROR on any other failure. Never raises — graceful degradation.
    """
    object_key = f"cctv/{inp.bank_id}/{inp.atm_id}/{inp.claim_id}.mp4"

    try:
        clip_data = await cctv_adapter.fetch_clip(
            atm_id=inp.atm_id,
            branch_id=inp.branch_id,
            timestamp=inp.timestamp,
        )
    except NoFootageError:
        log.info(
            "cctv.no_footage",
            atm_id=inp.atm_id,
            bank_id=inp.bank_id,
            claim_id=inp.claim_id,
        )
        return CCTVExtractionResult(outcome="NO_FOOTAGE", bank_id=inp.bank_id)
    except Exception as exc:
        log.warning(
            "cctv.adapter_error",
            atm_id=inp.atm_id,
            bank_id=inp.bank_id,
            claim_id=inp.claim_id,
            error=str(exc),
        )
        return CCTVExtractionResult(outcome="ADAPTER_ERROR", bank_id=inp.bank_id)

    clip_bytes = clip_data.get("clip_bytes", b"")
    duration_seconds = clip_data.get("duration_seconds")
    frame_count = clip_data.get("frame_count")

    try:
        store_result = await object_store.put(
            key=object_key,
            content=clip_bytes,
            bank_id=inp.bank_id,
        )
        stored_key = store_result.get("object_key", object_key) if store_result else object_key
    except Exception as exc:
        log.warning(
            "cctv.store_error",
            atm_id=inp.atm_id,
            bank_id=inp.bank_id,
            claim_id=inp.claim_id,
            error=str(exc),
        )
        return CCTVExtractionResult(outcome="ADAPTER_ERROR", bank_id=inp.bank_id)

    log.info(
        "cctv.extracted",
        atm_id=inp.atm_id,
        bank_id=inp.bank_id,
        claim_id=inp.claim_id,
        object_key=stored_key,
        duration_seconds=duration_seconds,
    )

    return CCTVExtractionResult(
        outcome="EXTRACTED",
        bank_id=inp.bank_id,
        object_key=stored_key,
        clip_duration_seconds=duration_seconds,
        frame_count=frame_count,
    )
