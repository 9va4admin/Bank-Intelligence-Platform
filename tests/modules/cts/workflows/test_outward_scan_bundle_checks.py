"""
TDD — OutwardScanWorkflow: ChequeImageBundle checks.

RED step: all tests fail until the workflow is extended to:
  1. Accept image_front_gray_url + image_uv_url in OutwardScanInput
  2. Call detect_alteration with front_gray_url when present
  3. Call analyze_uv_security with uv_image_url when present
  4. Validate cheque date after OCR (stale, post-dated, undated → CTS_REJECTED)

These are the gaps identified after the UV scanner bundling work:
  - OCR already extracts the cheque date; outward side never validates it
  - Front-gray alteration is not called on the outward path
  - UV security activity exists but is not wired into the workflow
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Helpers ──────────────────────────────────────────────────────────────────

def _import():
    from modules.cts.workflows.outward_scan_workflow import (
        OutwardScanInput, OutwardScanResult, OutwardScanWorkflow,
    )
    return OutwardScanInput, OutwardScanResult, OutwardScanWorkflow


def _base_inp(**overrides):
    from modules.cts.workflows.outward_scan_workflow import OutwardScanInput
    defaults = dict(
        scan_id="SCAN-001",
        instrument_id="INS-001",
        bank_id="kbl",
        bank_ifsc="KLBK0000001",
        session_id="SES-001",
        image_front_url="minio://cts/front_bw.tif",
        image_rear_url="minio://cts/rear_bw.tif",
    )
    defaults.update(overrides)
    return OutwardScanInput(**defaults)


# ── Input model: new optional fields ─────────────────────────────────────────

class TestOutwardScanInputBundleFields:

    def test_accepts_image_front_gray_url(self):
        """OutwardScanInput must accept front-gray image URL."""
        _, _, _ = _import()
        inp = _base_inp(image_front_gray_url="minio://cts/front_gray.tif")
        assert inp.image_front_gray_url == "minio://cts/front_gray.tif"

    def test_front_gray_url_defaults_none(self):
        """front_gray_url is optional — None when not provided."""
        _, _, _ = _import()
        inp = _base_inp()
        assert getattr(inp, "image_front_gray_url", None) is None

    def test_accepts_image_uv_url(self):
        """OutwardScanInput must accept UV image URL."""
        _, _, _ = _import()
        inp = _base_inp(image_uv_url="minio://cts/uv.tif")
        assert inp.image_uv_url == "minio://cts/uv.tif"

    def test_uv_url_defaults_none(self):
        """image_uv_url is optional — None when not provided (standard non-UV scanner)."""
        _, _, _ = _import()
        inp = _base_inp()
        assert getattr(inp, "image_uv_url", None) is None


# ── Date validation: stale cheque ────────────────────────────────────────────

class TestOutwardDateValidation:
    """
    Cheque date validation on the outward (presentee) path.
    Date is extracted by GOT-OCR2; workflow validates before proceeding to lot.

    RBI rule: cheques older than 3 months (90 days) are "stale" and cannot be
    presented for clearing. Post-dated cheques are held; undated cheques rejected.
    """

    def _make_workflow_with_mocks(self, ocr_date_str: str | None):
        """Build a workflow instance and a mock_results dict for run_with_mocks."""
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow
        from unittest.mock import MagicMock

        micr_mock = MagicMock()
        micr_mock.micr_line = "12345600123456001234"
        micr_mock.amount_figures = "5000.00"
        micr_mock.date = ocr_date_str          # ← what OCR returns
        micr_mock.degraded = False

        compliance_mock = MagicMock()
        compliance_mock.is_compliant = True
        compliance_mock.violations = []

        audit_mock = MagicMock()

        return OutwardScanWorkflow(), {
            "micr": micr_mock,
            "compliance": compliance_mock,
            "audit": audit_mock,
        }

    @pytest.mark.asyncio
    async def test_stale_cheque_returns_cts_rejected(self):
        """Cheque date > 90 days old → CTS_REJECTED with STALE_CHEQUE violation."""
        inp = _base_inp()
        wf, mocks = self._make_workflow_with_mocks(
            ocr_date_str=(date.today() - timedelta(days=100)).strftime("%d-%m-%Y")
        )
        result = await wf.run_with_mocks(inp, mocks)
        assert result.outcome == "CTS_REJECTED"
        assert any("STALE" in v for v in (result.violations or []))

    @pytest.mark.asyncio
    async def test_postdated_cheque_returns_post_dated_held(self):
        """Cheque date in the future → POST_DATED_HELD (valid instrument, held until maturity)."""
        inp = _base_inp()
        wf, mocks = self._make_workflow_with_mocks(
            ocr_date_str=(date.today() + timedelta(days=5)).strftime("%d-%m-%Y")
        )
        result = await wf.run_with_mocks(inp, mocks)
        assert result.outcome == "POST_DATED_HELD"
        assert any("POST_DATED" in v for v in (result.violations or []))

    @pytest.mark.asyncio
    async def test_undated_cheque_returns_cts_rejected(self):
        """OCR extracts no date (None) → CTS_REJECTED with UNDATED violation."""
        inp = _base_inp()
        wf, mocks = self._make_workflow_with_mocks(ocr_date_str=None)
        result = await wf.run_with_mocks(inp, mocks)
        assert result.outcome == "CTS_REJECTED"
        assert any("UNDATED" in v for v in (result.violations or []))

    @pytest.mark.asyncio
    async def test_valid_date_proceeds(self):
        """Valid cheque date (within 90 days, not future) → workflow continues normally."""
        inp = _base_inp()
        wf, mocks = self._make_workflow_with_mocks(
            ocr_date_str=(date.today() - timedelta(days=10)).strftime("%d-%m-%Y")
        )
        # No vision mock → ACCEPTED (no mismatch)
        result = await wf.run_with_mocks(inp, mocks)
        assert result.outcome == "ACCEPTED"


# ── Alteration detection on outward path ─────────────────────────────────────

class TestOutwardAlterationDetection:
    """
    When image_front_gray_url is present, detect_alteration must be called
    with front_gray_url. A confirmed alteration → MISMATCH_HELD.

    When front_gray is absent (standard non-gray scanner), alteration check
    is skipped — cannot detect what wasn't captured.
    """

    @pytest.mark.asyncio
    async def test_alteration_detected_on_gray_image_returns_mismatch_held(self):
        """Alteration confirmed on front-gray → MISMATCH_HELD."""
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow

        micr_mock = MagicMock()
        micr_mock.micr_line = "12345600123456001234"
        micr_mock.amount_figures = "5000.00"
        micr_mock.date = (date.today() - timedelta(days=10)).strftime("%d-%m-%Y")
        micr_mock.degraded = False

        compliance_mock = MagicMock()
        compliance_mock.is_compliant = True
        compliance_mock.violations = []

        alteration_mock = MagicMock()
        alteration_mock.alteration_detected = True
        alteration_mock.degraded = False
        alteration_mock.altered_fields = ["amount"]

        mocks = {
            "micr": micr_mock,
            "compliance": compliance_mock,
            "alteration": alteration_mock,
            "audit": MagicMock(),
        }

        inp = _base_inp(image_front_gray_url="minio://cts/front_gray.tif")
        result = await OutwardScanWorkflow().run_with_mocks(inp, mocks)

        assert result.outcome == "MISMATCH_HELD"
        assert result.violations is not None
        assert any("ALTERATION" in v for v in result.violations)

    @pytest.mark.asyncio
    async def test_no_gray_image_skips_alteration_check(self):
        """No front_gray_url → alteration check skipped; workflow proceeds normally."""
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow

        micr_mock = MagicMock()
        micr_mock.micr_line = "12345600123456001234"
        micr_mock.amount_figures = "5000.00"
        micr_mock.date = (date.today() - timedelta(days=10)).strftime("%d-%m-%Y")
        micr_mock.degraded = False

        compliance_mock = MagicMock()
        compliance_mock.is_compliant = True
        compliance_mock.violations = []

        mocks = {
            "micr": micr_mock,
            "compliance": compliance_mock,
            # No "alteration" key — should not be accessed
            "audit": MagicMock(),
        }

        inp = _base_inp()  # no image_front_gray_url
        result = await OutwardScanWorkflow().run_with_mocks(inp, mocks)
        assert result.outcome == "ACCEPTED"

    @pytest.mark.asyncio
    async def test_alteration_degraded_does_not_block(self):
        """Alteration check degrades (model unavailable) → proceed, do not reject."""
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow

        micr_mock = MagicMock()
        micr_mock.micr_line = "12345600123456001234"
        micr_mock.amount_figures = "5000.00"
        micr_mock.date = (date.today() - timedelta(days=10)).strftime("%d-%m-%Y")
        micr_mock.degraded = False

        compliance_mock = MagicMock()
        compliance_mock.is_compliant = True
        compliance_mock.violations = []

        alteration_mock = MagicMock()
        alteration_mock.alteration_detected = False
        alteration_mock.degraded = True          # model unavailable

        mocks = {
            "micr": micr_mock,
            "compliance": compliance_mock,
            "alteration": alteration_mock,
            "audit": MagicMock(),
        }

        inp = _base_inp(image_front_gray_url="minio://cts/front_gray.tif")
        result = await OutwardScanWorkflow().run_with_mocks(inp, mocks)
        assert result.outcome == "ACCEPTED"


# ── UV security on outward path ───────────────────────────────────────────────

class TestOutwardUVSecurity:
    """
    When image_uv_url is present, analyze_uv_security must be called.
    UV failure → MISMATCH_HELD (not outright reject — teller can override).
    UV degraded → proceed (cannot fail what scanner didn't capture).
    No UV image → skip check entirely.
    """

    @pytest.mark.asyncio
    async def test_uv_failure_returns_mismatch_held(self):
        """UV security fails (forgery detected) → MISMATCH_HELD for human review."""
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow

        micr_mock = MagicMock()
        micr_mock.micr_line = "12345600123456001234"
        micr_mock.amount_figures = "5000.00"
        micr_mock.date = (date.today() - timedelta(days=10)).strftime("%d-%m-%Y")
        micr_mock.degraded = False

        compliance_mock = MagicMock()
        compliance_mock.is_compliant = True
        compliance_mock.violations = []

        uv_mock = MagicMock()
        uv_mock.uv_security_passed = False
        uv_mock.degraded = False
        uv_mock.requires_human_review = True
        uv_mock.uv_risk_score = 0.87

        mocks = {
            "micr": micr_mock,
            "compliance": compliance_mock,
            "uv": uv_mock,
            "audit": MagicMock(),
        }

        inp = _base_inp(image_uv_url="minio://cts/uv.tif")
        result = await OutwardScanWorkflow().run_with_mocks(inp, mocks)

        assert result.outcome == "MISMATCH_HELD"
        assert result.violations is not None
        assert any("UV" in v for v in result.violations)

    @pytest.mark.asyncio
    async def test_uv_degraded_does_not_block(self):
        """UV check degrades (UV lamp absent/offline) → proceed optimistically."""
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow

        micr_mock = MagicMock()
        micr_mock.micr_line = "12345600123456001234"
        micr_mock.amount_figures = "5000.00"
        micr_mock.date = (date.today() - timedelta(days=10)).strftime("%d-%m-%Y")
        micr_mock.degraded = False

        compliance_mock = MagicMock()
        compliance_mock.is_compliant = True
        compliance_mock.violations = []

        uv_mock = MagicMock()
        uv_mock.uv_security_passed = False
        uv_mock.degraded = True                  # scanner has no UV lamp
        uv_mock.requires_human_review = True

        mocks = {
            "micr": micr_mock,
            "compliance": compliance_mock,
            "uv": uv_mock,
            "audit": MagicMock(),
        }

        inp = _base_inp(image_uv_url="minio://cts/uv.tif")
        result = await OutwardScanWorkflow().run_with_mocks(inp, mocks)
        assert result.outcome == "ACCEPTED"

    @pytest.mark.asyncio
    async def test_no_uv_image_skips_uv_check(self):
        """No image_uv_url → UV check skipped; workflow proceeds normally."""
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow

        micr_mock = MagicMock()
        micr_mock.micr_line = "12345600123456001234"
        micr_mock.amount_figures = "5000.00"
        micr_mock.date = (date.today() - timedelta(days=10)).strftime("%d-%m-%Y")
        micr_mock.degraded = False

        compliance_mock = MagicMock()
        compliance_mock.is_compliant = True
        compliance_mock.violations = []

        mocks = {
            "micr": micr_mock,
            "compliance": compliance_mock,
            # No "uv" key
            "audit": MagicMock(),
        }

        inp = _base_inp()  # no image_uv_url
        result = await OutwardScanWorkflow().run_with_mocks(inp, mocks)
        assert result.outcome == "ACCEPTED"

    @pytest.mark.asyncio
    async def test_uv_pass_allows_accepted(self):
        """UV security passes (all 3 features present) → does not block."""
        from modules.cts.workflows.outward_scan_workflow import OutwardScanWorkflow

        micr_mock = MagicMock()
        micr_mock.micr_line = "12345600123456001234"
        micr_mock.amount_figures = "5000.00"
        micr_mock.date = (date.today() - timedelta(days=10)).strftime("%d-%m-%Y")
        micr_mock.degraded = False

        compliance_mock = MagicMock()
        compliance_mock.is_compliant = True
        compliance_mock.violations = []

        uv_mock = MagicMock()
        uv_mock.uv_security_passed = True
        uv_mock.degraded = False
        uv_mock.requires_human_review = False

        mocks = {
            "micr": micr_mock,
            "compliance": compliance_mock,
            "uv": uv_mock,
            "audit": MagicMock(),
        }

        inp = _base_inp(image_uv_url="minio://cts/uv.tif")
        result = await OutwardScanWorkflow().run_with_mocks(inp, mocks)
        assert result.outcome == "ACCEPTED"
