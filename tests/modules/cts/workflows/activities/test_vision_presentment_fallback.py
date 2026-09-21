"""run_vision_presentment_check must never crash when no vLLM orchestrator exists.
Found by the real outward run: orchestrator=None -> AttributeError on call_vision, failing
5 real workflows. Order now: orchestrator -> config-gated HF cloud -> degrade (scanner
stays authoritative for presentment, result flagged degraded)."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.cts.workflows.activities.outward_scan_activities import (
    VisionPresentmentCheckInput, run_vision_presentment_check,
)


def _inp(scanner="45000.00"):
    return VisionPresentmentCheckInput(instrument_id="i1", image_front_url="http://x/y.jpg",
                                       scanner_amount_str=scanner, cheque_amount=45000.0, bank_id="kbl")


@pytest.mark.asyncio
async def test_no_orchestrator_and_cloud_disabled_degrades_without_raising():
    with patch("shared.ai.hf_cloud_fallback.cloud_fallback_enabled", new=AsyncMock(return_value=False)):
        r = await run_vision_presentment_check(_inp(), orchestrator=None, config_service=MagicMock())
    assert r.has_mismatch is False and r.vision_amount_str is None and r.degraded is True


@pytest.mark.asyncio
async def test_no_orchestrator_uses_cloud_when_enabled_and_detects_mismatch():
    cloud = '```json\n{"amount_figures": "54,000.00"}\n```'
    with patch("shared.ai.hf_cloud_fallback.cloud_fallback_enabled", new=AsyncMock(return_value=True)), \
         patch("shared.ai.hf_cloud_fallback.call_hf_vision", new=AsyncMock(return_value=cloud)), \
         patch("modules.cts.workflows.activities.outward_scan_activities._fetch_image_bytes",
               new=AsyncMock(return_value=b"img")):
        r = await run_vision_presentment_check(_inp("45000.00"), orchestrator=None, config_service=MagicMock())
    assert r.has_mismatch is True and r.vision_amount_str == "54,000.00" and r.degraded is False


@pytest.mark.asyncio
async def test_orchestrator_error_falls_back_instead_of_raising():
    orch = MagicMock(); orch.call_vision = AsyncMock(side_effect=RuntimeError("vllm down"))
    with patch("shared.ai.hf_cloud_fallback.cloud_fallback_enabled", new=AsyncMock(return_value=False)):
        r = await run_vision_presentment_check(_inp(), orchestrator=orch, config_service=MagicMock())
    assert r.has_mismatch is False and r.degraded is True


@pytest.mark.asyncio
async def test_orchestrator_result_still_used_when_available():
    orch = MagicMock()
    orch.call_vision = AsyncMock(return_value=MagicMock(content=json.dumps({"amount_figures": "45000.00"})))
    r = await run_vision_presentment_check(_inp("45000.00"), orchestrator=orch, config_service=MagicMock())
    assert r.has_mismatch is False and r.vision_amount_str == "45000.00" and r.degraded is False
