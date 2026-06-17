"""
CCTV evidence extraction activity.

Rules:
- Clip bytes stored in MinIO only — never returned inline in result
- object_key reference returned, not raw bytes
"""
from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict

log = structlog.get_logger()


class CCTVExtractInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    bank_id: str
    atm_id: str
    dispute_timestamp: str
    npci_claim_id: str
    window_seconds: int


class CCTVExtractResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str                    # "EXTRACTED" | "CCTV_UNAVAILABLE" | "STORE_FAILED" | "EXTRACTION_FAILED"
    object_key: Optional[str] = None
    camera_id: Optional[str] = None
    clip_data: None = None          # always None — clips are in MinIO, not here


async def extract_cctv_evidence(
    inp: CCTVExtractInput,
    *,
    cctv_adapter,
    object_store,
) -> CCTVExtractResult:
    try:
        clip = await cctv_adapter.fetch_clip(
            atm_id=inp.atm_id,
            timestamp=inp.dispute_timestamp,
            window_seconds=inp.window_seconds,
        )
    except Exception as exc:
        log.warning("cctv_extract.fetch_failed", atm_id=inp.atm_id, error=str(exc))
        return CCTVExtractResult(outcome="CCTV_UNAVAILABLE")

    object_key = f"cctv/{inp.bank_id}/{inp.atm_id}/{inp.npci_claim_id}.mp4"

    try:
        response = await object_store.put(
            key=object_key,
            content=clip.get("clip_data"),
            bank_id=inp.bank_id,
        )
        stored_key = response.get("object_key", object_key)
    except Exception as exc:
        log.warning("cctv_extract.store_failed", atm_id=inp.atm_id, error=str(exc))
        return CCTVExtractResult(outcome="STORE_FAILED")

    return CCTVExtractResult(
        outcome="EXTRACTED",
        object_key=stored_key,
        camera_id=clip.get("camera_id"),
    )
