"""
CTS Extended E2E — 80 synthetic multi-lingual cheques
=======================================================
8 languages × 10 inward scenario types = 80 fixtures
IDs: EX-IN-001 … EX-IN-080

Languages tested:
  Hindi · Marathi · Tamil · Telugu · Kannada · Gujarati · Bengali · Malayalam

Scenarios per language:
  CLEAN_ALL_PASS · STOP_PAYMENT_STP · OCR_LOW_CONF · ALTERATION ·
  FRAUD_HIGH · ACCOUNT_FROZEN · CBS_INSUFFICIENT · SIGNATURE_MISMATCH ·
  HIGH_VALUE_CLEAN · POST_DATED

Each test asserts the SAME routing invariant as the corresponding base
scenario — proving the pipeline decision is language-agnostic.
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest

from modules.cts.workflows.cheque_workflow import (
    ChequeProcessingWorkflow,
    ChequeWorkflowInput,
)
from tests.e2e.cts.cheque_fixtures import fresh_iet_deadline
from tests.e2e.cts.extended_fixtures import EXTENDED_FIXTURES, EXTENDED_COUNT
from tests.e2e.cts.image_factory import generate_cheque_image
from tests.e2e.cts.mock_builders import build_inward_mocks, build_inward_step_trace

# Index offset so each extended fixture picks a unique image from the generator
# (no pool needed — synthetic images are generated fresh from fixture data)
_EX_START_IDX = 1000


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fixture",
    EXTENDED_FIXTURES,
    ids=[f.fixture_id for f in EXTENDED_FIXTURES],
)
async def test_cts_extended_e2e(fixture, register_instrument):
    """
    Extended inward pipeline E2E across 8 languages.
    Core assertion: routing decision is language-agnostic —
    same trigger → same expected_outcome regardless of Indic script.
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

    # ── Language-agnostic routing assertion ───────────────────────────────────
    assert result.decision == fixture.expected_outcome, (
        f"[{fixture.fixture_id}] {fixture.language} · {fixture.scenario}\n"
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

    register_instrument(
        instrument_id=fixture.instrument_id,
        bank_id=fixture.bank_id,
        workflow_type="INWARD",
        decision=result.decision,
        rationale=result.rationale,
        steps=steps,
        amount_range=fixture.amount_range,
        duration_ms=duration_ms,
        test_name=f"test_cts_extended_e2e[{fixture.fixture_id}]",
        image_data=generate_cheque_image(fixture),
    )


def test_extended_fixture_count():
    assert EXTENDED_COUNT == 80, f"Expected 80 extended fixtures, got {EXTENDED_COUNT}"


def test_extended_all_languages_present():
    langs = {f.language for f in EXTENDED_FIXTURES}
    expected = {"Hindi", "Marathi", "Tamil", "Telugu", "Kannada", "Gujarati", "Bengali", "Malayalam"}
    assert expected == langs, f"Missing: {expected - langs}"


def test_extended_all_triggers_present():
    triggers = {f.trigger for f in EXTENDED_FIXTURES}
    required = {"CLEAN_ALL_PASS", "STOP_PAYMENT_STP", "OCR_LOW_CONF",
                "ALTERATION", "FRAUD_HIGH", "ACCOUNT_FROZEN",
                "CBS_INSUFFICIENT", "SIG_MISMATCH",
                "HIGH_VALUE_CLEAN", "CBS_UNAVAILABLE"}
    assert required == triggers, f"Missing: {required - triggers}"


def test_extended_multi_sig_present():
    """HIGH_VALUE_CLEAN fixtures (≥ ₹20L) must have ≥ 2-sig requirement."""
    high_val = [f for f in EXTENDED_FIXTURES if f.trigger == "HIGH_VALUE_CLEAN"]
    assert all(f.amount >= 2_000_000 for f in high_val), (
        "HIGH_VALUE_CLEAN fixtures must have amount ≥ 20L for 2-sig rendering"
    )
