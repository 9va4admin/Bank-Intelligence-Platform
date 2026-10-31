"""What the drop-folder watcher publishes is exactly what the outward trigger must read.

Found by the first live outward run (2026-10-31): the watcher wrote image_front_bw_url / image_front_gray_url / image_rear_url /
image_uv_url, the trigger read image_front_url, so every scanned cheque reached OutwardScanWorkflow with an empty image
("unsupported image URL scheme: ''") and was rejected UNDATED. Each side's own tests used its own assumed key; none joined them."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.cts.scanner.file_watcher import DropFolderWatcher, WatcherConfig
from modules.cts.scanner.outward_scan_trigger import OutwardScanTrigger


class _Store:
    async def upload_bytes(self, bucket, key, data, content_type="application/octet-stream"):
        return key


@pytest.mark.asyncio
async def test_every_image_the_watcher_uploads_reaches_the_workflow_input(tmp_path):
    img = tmp_path / "c.jpg"
    img.write_bytes(b"x")
    uv = tmp_path / "uv.jpg"
    uv.write_bytes(b"u")
    cfg = WatcherConfig(bank_id="b", branch_id="B1", pu_id="PU1", drop_folder=tmp_path, metadata_glob="*.dat",
                        stability_wait_seconds=0, kafka_topic="t", minio_store=_Store(), minio_bucket="bkt")
    inst = SimpleNamespace(scan_id="S1", bundle_status=None, image_color_path=img, image_grey_path=img,
                           image_rear_path=img, image_uv_path=uv)
    entry = (await DropFolderWatcher(config=cfg, mapper=None, kafka_producer=None)._upload_images([inst]))[0]

    temporal = MagicMock()
    temporal.start_workflow = AsyncMock()
    trigger = OutwardScanTrigger(bank_id="b", bootstrap_servers="x", temporal_client=temporal, task_queue="q")
    await trigger._start_one_workflow(scan_id="S1", wf_id="w", scan_data=entry, event={}, batch_id="B", pu_id="PU1", branch_id="B1")

    inp = temporal.start_workflow.await_args.args[1]
    assert inp.image_front_url == entry["image_front_bw_url"] and inp.image_front_url.startswith("minio://")
    assert inp.image_front_gray_url == entry["image_front_gray_url"]
    assert inp.image_rear_url == entry["image_rear_url"]
    assert inp.image_uv_url == entry["image_uv_url"]


@pytest.mark.asyncio
async def test_the_older_image_front_url_key_still_works():
    temporal = MagicMock()
    temporal.start_workflow = AsyncMock()
    trigger = OutwardScanTrigger(bank_id="b", bootstrap_servers="x", temporal_client=temporal, task_queue="q")
    await trigger._start_one_workflow(scan_id="S1", wf_id="w", scan_data={"scan_id": "S1", "image_front_url": "minio://b/k.tif"},
                                      event={}, batch_id="B", pu_id="", branch_id="")
    assert temporal.start_workflow.await_args.args[1].image_front_url == "minio://b/k.tif"


# ── image metrics: CTS-2010 compliance needs DPI / colour depth / size, and the drop folder carries none of them ──────────
# Second finding of the same live run: with the image now reaching OCR, every cheque was still rejected MISSING_IMAGE_METRICS
# because nothing between the scanner folder and the workflow measured the image. They are measured from the file itself.

def _jpeg(path, dpi=(200, 200), mode="RGB"):
    from PIL import Image
    Image.new(mode, (40, 20), 255).save(path, dpi=dpi)
    return path


def test_measure_image_reports_dpi_colour_depth_and_size(tmp_path):
    from modules.cts.scanner.image_metrics import measure_image
    p = _jpeg(tmp_path / "a.jpg")
    m = measure_image(p.read_bytes())
    assert m["dpi"] == 200 and m["colour_depth"] == 24 and m["file_size_kb"] == pytest.approx(p.stat().st_size / 1024)


def test_measure_image_grey_and_bitonal_depths(tmp_path):
    from modules.cts.scanner.image_metrics import measure_image
    assert measure_image(_jpeg(tmp_path / "g.jpg", mode="L").read_bytes())["colour_depth"] == 8
    from PIL import Image
    b = tmp_path / "b.tif"
    Image.new("1", (40, 20), 1).save(b, dpi=(200, 200))
    assert measure_image(b.read_bytes())["colour_depth"] == 1


def test_measure_image_never_invents_a_dpi_the_file_does_not_state(tmp_path):
    from PIL import Image
    from modules.cts.scanner.image_metrics import measure_image
    p = tmp_path / "nodpi.png"
    Image.new("RGB", (40, 20), 255).save(p)          # PNG without a pHYs chunk
    assert measure_image(p.read_bytes())["dpi"] is None


def test_measure_image_unreadable_bytes_give_no_metrics():
    from modules.cts.scanner.image_metrics import measure_image
    assert measure_image(b"not an image") == {"dpi": None, "colour_depth": None, "file_size_kb": pytest.approx(12 / 1024)}


@pytest.mark.asyncio
async def test_measured_metrics_travel_from_the_watcher_to_the_workflow_input(tmp_path):
    front, rear = _jpeg(tmp_path / "f.jpg"), _jpeg(tmp_path / "r.jpg", dpi=(300, 300), mode="L")
    cfg = WatcherConfig(bank_id="b", branch_id="B1", pu_id="PU1", drop_folder=tmp_path, metadata_glob="*.dat",
                        stability_wait_seconds=0, kafka_topic="t", minio_store=_Store(), minio_bucket="bkt")
    inst = SimpleNamespace(scan_id="S1", bundle_status=None, image_color_path=front, image_grey_path=front, image_rear_path=rear)
    entry = (await DropFolderWatcher(config=cfg, mapper=None, kafka_producer=None)._upload_images([inst]))[0]
    temporal = MagicMock()
    temporal.start_workflow = AsyncMock()
    trigger = OutwardScanTrigger(bank_id="b", bootstrap_servers="x", temporal_client=temporal, task_queue="q")
    await trigger._start_one_workflow(scan_id="S1", wf_id="w", scan_data=entry, event={}, batch_id="B", pu_id="PU1", branch_id="B1")
    inp = temporal.start_workflow.await_args.args[1]
    assert (inp.front_dpi, inp.front_colour_depth, inp.rear_dpi, inp.rear_colour_depth) == (200, 24, 300, 8)
    assert inp.front_file_size_kb == pytest.approx(front.stat().st_size / 1024)
    assert inp.rear_file_size_kb == pytest.approx(rear.stat().st_size / 1024)
