"""
run_ocr_live.py — Run the real OCR activity code against actual cheque images.

This script:
  1. Starts the OCR stub server as a subprocess (mimics GOT-OCR2.0 / vLLM API)
  2. Wires the real CascadeOrchestrator to the stub
  3. Calls the real ocr_extract() activity function on images from demo/112/
  4. Prints extracted field results with cascade level and confidence

This is NOT build_inward_mocks(). The full activity code path runs:
  - _extract_got_ocr2() → cascade orchestrator → stub API call
  - Confidence gating, amount cross-check, MICR validation
  - Indic zone refinement stage (skipped — no IndicOCR URL)
  - OCRActivityResult returned with real field values from the stub

Usage:
    python scripts/run_ocr_live.py
    python scripts/run_ocr_live.py --count 5
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import io
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEMO_DIR = ROOT / "demo" / "112"
STUB_PORT = 18010
STUB_URL = f"http://localhost:{STUB_PORT}"


# ── Stub management ───────────────────────────────────────────────────────────

def _stub_healthy() -> bool:
    try:
        import httpx
        r = httpx.get(f"{STUB_URL}/health", timeout=1.0)
        return r.status_code == 200 and r.json().get("service") == "ocr-stub"
    except Exception:
        return False


def start_stub() -> subprocess.Popen | None:
    if _stub_healthy():
        print(f"[stub] Already running at {STUB_URL}")
        return None
    print(f"[stub] Starting OCR stub on port {STUB_PORT}...")
    proc = subprocess.Popen(
        [sys.executable, "-m", "tests.integration.stubs.ocr_server"],
        env=os.environ.copy(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 12
    while not _stub_healthy():
        if time.time() > deadline:
            proc.kill()
            raise RuntimeError("OCR stub did not start within 12s")
        time.sleep(0.3)
    print(f"[stub] Ready at {STUB_URL}")
    return proc


# ── Minimal config_service stub ───────────────────────────────────────────────

class _ConfigStub:
    _data = {
        "ai.ocr.min_confidence":         0.85,
        "ai.ocr.min_indic_confidence":   0.60,
        "services.indic_ocr.url":        "",   # disabled — no IndicOCR in dev
        "cts.indic_ocr.kill_mode":       "NONE",
        "ai.cascade.l1_confidence_threshold": 0.85,
        "ai.cascade.high_value_threshold":    5_000_000.0,
        "ai.cascade.l2_escalation_enabled":   False,
        "ai.cascade.l1_model_ocr":       "got-ocr2-stub",
        "ai.cascade.l2_model_ocr":       "got-ocr2-stub",
    }

    async def get_ai_config(self, bank_id: str) -> dict:
        return dict(self._data)

    async def get(self, key: str) -> str:
        if key == "cts.indic_ocr.kill_mode":
            return "NONE"
        raise KeyError(key)


# ── Image → data URL (for stub) ───────────────────────────────────────────────

def _image_to_data_url(path: Path) -> str:
    from PIL import Image
    img = Image.open(path)
    # Resize to ≤750px wide (same as test_real_cheques.py)
    w, h = img.size
    if w > 750:
        img = img.resize((750, int(h * 750 / w)), Image.LANCZOS)
    buf = io.BytesIO()
    fmt = "JPEG" if path.suffix.lower() in (".jpg", ".jpeg") else "PNG"
    img.save(buf, format=fmt)
    b64 = base64.b64encode(buf.getvalue()).decode()
    mime = "image/jpeg" if fmt == "JPEG" else "image/png"
    return f"data:{mime};base64,{b64}"


# ── Build orchestrator pointed at stub ────────────────────────────────────────

def _build_orchestrator(bank_id: str):
    from openai import AsyncOpenAI
    from shared.ai.model_cascade import CascadeOrchestrator

    client = AsyncOpenAI(base_url=f"{STUB_URL}/v1", api_key="stub")
    config = {
        "ai.cascade.l1_confidence_threshold": 0.85,
        "ai.cascade.high_value_threshold":    5_000_000.0,
        "ai.cascade.l2_escalation_enabled":   False,
        "ai.cascade.l1_model_ocr":  "got-ocr2-stub",
        "ai.cascade.l2_model_ocr":  "got-ocr2-stub",
    }
    return CascadeOrchestrator(
        l1_client=client, l2_client=client, config=config, bank_id=bank_id
    )


# ── Run the real OCR activity ─────────────────────────────────────────────────

async def run_ocr_on_image(image_path: Path, bank_id: str, instrument_id: str) -> dict:
    from modules.cts.workflows.activities.ocr import OCRActivityInput, ocr_extract

    orchestrator = _build_orchestrator(bank_id)
    config_svc = _ConfigStub()

    # Encode image as data URL — same format the activity receives from MinIO
    image_url = _image_to_data_url(image_path)

    inp = OCRActivityInput(
        image_url=image_url,
        instrument_id=instrument_id,
        bank_id=bank_id,
    )

    # Run the REAL activity function (not via Temporal worker — called directly
    # so we can see output without infrastructure). Temporal sandbox guards
    # (no datetime.now, no asyncio.sleep) are not active here, but the business
    # logic — cascade call, confidence gating, amount cross-check — all run.
    result = await ocr_extract(inp, orchestrator, config_svc)
    return result.model_dump()


async def main(count: int) -> None:
    images = sorted(DEMO_DIR.glob("*.jpeg")) + sorted(DEMO_DIR.glob("*.tiff"))
    images = images[:count]

    if not images:
        print(f"No images found in {DEMO_DIR}")
        return

    print(f"\n{'='*70}")
    print(f"  ASTRA OCR Live Run — {len(images)} cheques — stub backend")
    print(f"  Code path: ocr_extract() -> CascadeOrchestrator -> OCR stub API")
    print(f"{'='*70}\n")

    for i, img_path in enumerate(images, 1):
        instrument_id = f"RC-LIVE-{i:04d}"
        bank_id = "saraswat-coop"

        t0 = time.perf_counter()
        result = await run_ocr_on_image(img_path, bank_id, instrument_id)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        print(f"[{i:02d}] {img_path.name}")
        print(f"     outcome          : {result['outcome']}")
        print(f"     cascade_level    : {result['cascade_level']}")
        print(f"     overall_conf     : {result['overall_confidence']:.3f}")
        print(f"     engines_used     : {result['ocr_engines_used']}")
        print(f"     micr_line        : {result['micr_line']}")
        print(f"     payee            : {result['payee']}")
        print(f"     amount_figures   : {result['amount_figures']}")
        print(f"     amount_words     : {result['amount_words']}")
        print(f"     date             : {result['date']}")
        print(f"     ifsc_code        : {result['ifsc_code']}")
        if result.get('low_confidence_reason'):
            print(f"     low_conf_reason  : {result['low_confidence_reason']}")
        if result.get('amount_mismatch'):
            print(f"     amount_mismatch  : {result['amount_mismatch']}")
        print(f"     elapsed          : {elapsed_ms:.1f} ms")
        print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=8,
                        help="Number of cheque images to run OCR on (default: 8)")
    args = parser.parse_args()

    proc = start_stub()
    try:
        asyncio.run(main(args.count))
    finally:
        if proc:
            proc.kill()
            proc.wait()
            print("[stub] Stopped.")
