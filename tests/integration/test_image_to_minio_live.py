"""Live proof that every route which puts a cheque image into MinIO produces a reference the
reading activities can follow back to the same bytes. Real MinIO, real upload code, real fetcher,
real image-quality activity; nothing in the path is mocked."""
from __future__ import annotations

import asyncio
import socket
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from modules.cts.scanner.file_watcher import DropFolderWatcher, WatcherConfig
from modules.cts.workflows.activities.image_quality import IQAInput, check_image_quality
from modules.cts.workflows.activities.inward_batch_activities import (
    UploadInstrumentImagesInput,
    upload_instrument_images,
)
from shared.storage import image_fetch
from shared.storage.image_fetch import fetch_image_bytes, image_ref
from shared.storage.minio_client import MinioObjectStore
from tests.integration.conftest import MINIO_ACCESS_KEY, MINIO_ENDPOINT, MINIO_SECRET_KEY

BUCKET = "cts-live-image-proof"
CHEQUE = Path(__file__).resolve().parents[2] / "docs" / "cheques" / "CHQ-001-100001.jpg"


def _minio_up() -> bool:
    host, port = MINIO_ENDPOINT.split(":")
    try:
        with socket.create_connection((host, int(port)), timeout=2):
            return True
    except OSError:
        return False


pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not _minio_up() or not CHEQUE.exists(), reason="needs the integration MinIO and a sample cheque"),
]


@pytest.fixture
def store():
    s = MinioObjectStore(MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY, secure=False)
    asyncio.run(s.ensure_bucket(BUCKET))
    image_fetch.configure_default_store(s)
    yield s
    image_fetch.configure_default_store(None)


async def _read_through_activity(ref: str) -> None:
    # The first thing every cheque does with its image reference.
    r = await check_image_quality(IQAInput(image_url=ref, instrument_id="LIVE-1", bank_id="it-bank"))
    assert r.outcome != "UNAVAILABLE", f"image could not be fetched from {ref}"


async def test_scanner_drop_folder_route(store, tmp_path):
    cfg = WatcherConfig(
        bank_id="it-bank", branch_id="B1", pu_id="PU1", drop_folder=tmp_path, metadata_glob="*.dat",
        stability_wait_seconds=0, kafka_topic="t", minio_store=store, minio_bucket=BUCKET,
    )
    inst = SimpleNamespace(scan_id="SCAN-LIVE-1", bundle_status=None, image_color_path=CHEQUE,
                           image_grey_path=None, image_rear_path=None)
    entry = (await DropFolderWatcher(config=cfg, mapper=None, kafka_producer=None)._upload_images([inst]))[0]
    ref = entry["image_front_bw_url"]
    assert ref.startswith("minio://")
    assert await fetch_image_bytes(ref) == CHEQUE.read_bytes()
    await _read_through_activity(ref)


async def test_inward_batch_route(store):
    # A stand-in CIBF: three image regions at known offsets, staged where the activity expects them.
    front, back, gray = CHEQUE.read_bytes(), b"BACK-IMAGE-BYTES", b"GRAY-IMAGE-BYTES"
    cibf = b"HDR" + front + back + gray
    await store.upload_bytes(BUCKET, "staging/live.cibf", cibf)
    out = await upload_instrument_images(
        UploadInstrumentImagesInput(
            bank_id="it-bank", batch_id="B-LIVE", item_seq_no="000001", cibf_staging_key="staging/live.cibf",
            front_bw_image_offset=3, front_bw_image_length=len(front),
            back_bw_image_offset=3 + len(front), back_bw_image_length=len(back),
            front_gray_image_offset=3 + len(front) + len(back), front_gray_image_length=len(gray),
            minio_bucket=BUCKET,
        ),
        minio_client=store._client,
    )
    assert out.uploaded, out.error
    ref = image_ref(BUCKET, out.front_bw_key)  # exactly what the inward batch workflow now passes
    assert await fetch_image_bytes(ref) == front
    assert await fetch_image_bytes(image_ref(BUCKET, out.back_bw_key)) == back
    await _read_through_activity(ref)


async def test_outward_api_presigned_put_route(store):
    # The API hands the scanner a presigned PUT link and records the object as s3://bucket/key.
    key = "it-bank/outward/PU1/SCAN-LIVE-2/front.jpg"
    url = await store.presigned_put_url(BUCKET, key)
    async with httpx.AsyncClient(timeout=15) as c:
        assert (await c.put(url, content=CHEQUE.read_bytes())).status_code == 200
    ref = image_ref(BUCKET, key)
    assert await fetch_image_bytes(ref) == CHEQUE.read_bytes()
    await _read_through_activity(ref)


async def test_model_server_receives_the_actual_image(store):
    # A vLLM server can only read http(s)/data URLs. The real cascade, given a MinIO reference, must send it the image itself.
    import base64
    import json

    from openai import AsyncOpenAI

    from shared.ai.model_cascade import CascadeOrchestrator

    key = "it-bank/inward/live/front.jpg"
    await store.upload_bytes(BUCKET, key, CHEQUE.read_bytes(), "image/jpeg")
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body["messages"][0]["content"][0]["image_url"]["url"])
        reply = {"id": "x", "object": "chat.completion", "created": 0, "model": body["model"],
                 "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "{}"}}],
                 "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
        return httpx.Response(200, json=reply)

    client = AsyncOpenAI(base_url="http://model.invalid/v1", api_key="x", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    cfg = {"ai.cascade.l1_confidence_threshold": 0.0, "ai.cascade.high_value_threshold": 1e12, "ai.cascade.l2_escalation_enabled": False}
    await CascadeOrchestrator(l1_client=client, l2_client=client, config=cfg, bank_id="it-bank").call_ocr(
        image_url=image_ref(BUCKET, key), prompt="read", cheque_amount=1.0)
    assert seen and seen[0].startswith("data:image/jpeg;base64,"), seen[:1]
    assert base64.b64decode(seen[0].split(",", 1)[1]) == CHEQUE.read_bytes()
