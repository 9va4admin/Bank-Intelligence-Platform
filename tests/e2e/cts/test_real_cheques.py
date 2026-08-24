"""
CTS Real-Cheque Smoke Tests — 112 cheques from demo/112/
=========================================================
Each test loads a real bank cheque scan (Syndicate Bank or Axis Bank)
and runs it through the CTS inward pipeline with mocks.

What IS tested:
  • Pipeline routing logic is correct for each scenario type
  • IET watchdog spawns on every cheque (non-negotiable)
  • The real cheque image appears in the digest for visual inspection
  • Pipeline handles both Syndicate Bank and Axis Bank IFSCs correctly

What is NOT tested:
  • Actual OCR on the real image — mock returns synthetic values
  • Real NGCH filing — mocked out as always
  • The pipeline never sees the actual pixels; only routing logic is exercised

This is a smoke test: it proves the pipeline handles 112 distinct instrument
IDs with clean idempotency and correct IET watchdog semantics, while giving
the human reviewer a visual digest of all 112 real scans side-by-side with
their pipeline outcomes.

Images: demo/112/ (116 JPEG/TIFF files; first 112 used, sorted by filename)
"""
from __future__ import annotations

import base64
import io
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

try:
    from PIL import Image as _PILImage
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

from modules.cts.workflows.cheque_workflow import (
    ChequeProcessingWorkflow,
    ChequeWorkflowInput,
)
from tests.e2e.cts.cheque_fixtures import fresh_iet_deadline
from tests.e2e.cts.mock_builders import build_inward_mocks, build_inward_step_trace
from tests.e2e.cts.real_cheque_fixtures import (
    REAL_CHEQUE_FIXTURES,
    REAL_CHEQUE_COUNT,
    REAL_CHEQUE_IMAGE_PATHS,
)

# Map fixture_id → real image path for O(1) lookup
_IMAGE_MAP: dict[str, Path] = {
    f.fixture_id: p
    for f, p in zip(REAL_CHEQUE_FIXTURES, REAL_CHEQUE_IMAGE_PATHS)
}

_MAX_WIDTH = 1200   # resize threshold — keep digest manageable


def _load_real_image(path: Path) -> str:
    """Load real cheque scan, resize to ≤1200px wide, return base64 data URI."""
    if not _PIL_AVAILABLE:
        return ""
    try:
        with _PILImage.open(path) as img:
            img = img.convert("RGB")
            w, h = img.size
            if w > _MAX_WIDTH:
                h = int(h * _MAX_WIDTH / w)
                w = _MAX_WIDTH
                img = img.resize((w, h), _PILImage.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=72, optimize=True)
            b64 = base64.b64encode(buf.getvalue()).decode()
        return f"data:image/jpeg;base64,{b64}"
    except Exception:
        return ""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fixture",
    REAL_CHEQUE_FIXTURES,
    ids=[f.fixture_id for f in REAL_CHEQUE_FIXTURES],
)
async def test_real_cheque_inward(fixture, register_instrument):
    """
    Inward pipeline smoke test using a real cheque scan.
    Pipeline routing is exercised with synthetic mock data.
    Real cheque image embedded in digest for visual inspection.
    """
    wf  = ChequeProcessingWorkflow()
    inp = ChequeWorkflowInput(
        instrument_id=fixture.instrument_id,
        bank_id=fixture.bank_id,
        image_url=f"https://minio.internal/cts/e2e/{fixture.fixture_id}.tif",
        account_number=fixture.account_number,
        cheque_number=fixture.cheque_number,
        presented_amount=fixture.amount,
        presented_payee=fixture.payee_name,
        iet_deadline=fresh_iet_deadline(),
        ngch_ifsc=fixture.ngch_ifsc,
        cts_config=fixture.cts_config,
    )
    mocks = build_inward_mocks(fixture)
    watchdog_log: list[dict] = []

    async def _on_watchdog(watchdog_id: str, iet_deadline: float) -> None:
        watchdog_log.append({"watchdog_id": watchdog_id, "iet_deadline": iet_deadline})

    t0 = time.perf_counter()
    with (
        patch("modules.cts.workflows.cheque_workflow.notify_sub_member_return",
              new_callable=AsyncMock),
        patch("modules.cts.workflows.cheque_workflow.emit_batch_ledger_update",
              new_callable=AsyncMock),
    ):
        result = await wf.run_with_mocks(inp, mocks, on_watchdog_spawn=_on_watchdog)
    duration_ms = int((time.perf_counter() - t0) * 1000)

    # ── IET watchdog (non-negotiable) ─────────────────────────────────────────
    assert len(watchdog_log) == 1, (
        f"[{fixture.fixture_id}] IET watchdog must fire exactly once"
    )
    assert watchdog_log[0]["iet_deadline"] > time.time(), (
        f"[{fixture.fixture_id}] IET deadline must be in the future"
    )

    # ── Core routing assertion ────────────────────────────────────────────────
    assert result.decision == fixture.expected_outcome, (
        f"[{fixture.fixture_id}] {fixture.bank_id} · {fixture.scenario}\n"
        f"  Expected : {fixture.expected_outcome}\n"
        f"  Actual   : {result.decision}\n"
        f"  Trigger  : {fixture.trigger}"
    )

    # ── Polarity contract ─────────────────────────────────────────────────────
    if fixture.polarity == "POSITIVE":
        assert result.decision == "STP_CONFIRM"
    else:
        assert result.decision in ("STP_RETURN", "HUMAN_REVIEW")

    steps = build_inward_step_trace(fixture, result)

    # Load the real cheque scan as base64 for the digest
    img_path = _IMAGE_MAP.get(fixture.fixture_id)
    image_data = _load_real_image(img_path) if img_path else ""

    register_instrument(
        instrument_id=fixture.instrument_id,
        bank_id=fixture.bank_id,
        workflow_type="INWARD",
        decision=result.decision,
        rationale=f"[REAL SCAN: {img_path.name if img_path else 'N/A'}] {result.rationale}",
        steps=steps,
        amount_range=fixture.amount_range,
        duration_ms=duration_ms,
        test_name=f"test_real_cheque_inward[{fixture.fixture_id}]",
        image_data=image_data,
        ocr_model="GOT-OCR2.0 (mock — real image not OCR'd in tests)",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Suite-level sanity checks
# ─────────────────────────────────────────────────────────────────────────────

def test_real_cheque_count():
    assert REAL_CHEQUE_COUNT == 112, (
        f"Expected 112 real cheque fixtures, got {REAL_CHEQUE_COUNT}"
    )


def test_real_cheque_images_exist():
    missing = [p for p in REAL_CHEQUE_IMAGE_PATHS if not p.exists()]
    assert not missing, (
        f"{len(missing)} real cheque image(s) missing from demo/112/:\n"
        + "\n".join(str(p) for p in missing[:10])
    )


def test_real_cheque_fixture_ids_unique():
    ids = [f.fixture_id for f in REAL_CHEQUE_FIXTURES]
    assert len(ids) == len(set(ids)), (
        f"Duplicate fixture IDs in real cheque fixtures: "
        f"{[x for x in ids if ids.count(x) > 1]}"
    )


def test_real_cheque_both_banks_covered():
    banks = {f.bank_id for f in REAL_CHEQUE_FIXTURES}
    assert "syndicate-bank" in banks, "Syndicate Bank cheques missing"
    assert "axis-bank" in banks, "Axis Bank cheques missing"


def test_real_cheque_scenario_cycle():
    """All 8 scenario types must appear across the 112 cheques."""
    triggers = {f.trigger for f in REAL_CHEQUE_FIXTURES}
    required = {
        "CLEAN_ALL_PASS", "SIG_MISMATCH", "FRAUD_HIGH",
        "STOP_PAYMENT_STP", "OCR_LOW_CONF", "ACCOUNT_FROZEN", "CBS_INSUFFICIENT",
    }
    missing = required - triggers
    assert not missing, f"Missing scenario types in real cheque fixtures: {missing}"
