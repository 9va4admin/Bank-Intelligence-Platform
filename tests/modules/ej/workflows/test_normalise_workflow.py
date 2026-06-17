"""
Tests for modules/ej/workflows/normalise_workflow.py

EJNormalisationWorkflow: ingest → fingerprint → llm_parse → validate → store.
Workflow ID: ej-normalise-{bank_id}-{raw_log_hash} (idempotent).
Terminal states: NORMALISED | PARSE_FAILED | VALIDATION_FAILED
"""
import pytest
from unittest.mock import AsyncMock


def _make_input(raw_log_hash="abc123", atm_id="ATM001", bank_id="test-bank"):
    from modules.ej.workflows.normalise_workflow import EJNormalisationInput
    return EJNormalisationInput(
        raw_log="[ATM001] 2026-06-17 10:30:00 DISPENSE 5000 OK",
        raw_log_hash=raw_log_hash,
        atm_id=atm_id,
        bank_id=bank_id,
        oem_fingerprint="NCR_SELFSERV",
        source="branch-mcp",
    )


def _make_activity_results(outcome="NORMALISED"):
    from modules.ej.workflows.activities.ingest import EJIngestResult
    from modules.ej.workflows.activities.fingerprint import EJFingerprintResult
    from modules.ej.workflows.activities.llm_parse import EJLLMParseActivityResult
    from modules.ej.workflows.activities.validate import EJValidateResult

    return {
        "ingest": EJIngestResult(
            outcome="ACCEPTED",
            raw_log_hash="abc123",
            object_key="ej/test-bank/ATM001/abc123.log",
            bank_id="test-bank",
        ),
        "fingerprint": EJFingerprintResult(
            outcome="VALIDATED",
            oem_fingerprint="NCR_SELFSERV",
            bank_id="test-bank",
        ),
        "llm_parse": EJLLMParseActivityResult(
            outcome="NORMALISED" if outcome != "PARSE_FAILED" else "PARSE_FAILED",
            canonical_record={"transaction_type": "DISPENSE", "amount": 5000.0,
                              "status": "SUCCESS", "timestamp": "2026-06-17T10:30:00+05:30"},
            canonical_hash="d" * 64,
        ),
        "validate": EJValidateResult(
            outcome="VALID" if outcome not in ("PARSE_FAILED", "VALIDATION_FAILED") else "INVALID",
            bank_id="test-bank",
            validation_errors=[],
        ),
    }


class TestEJNormalisationInput:
    def test_requires_raw_log(self):
        from modules.ej.workflows.normalise_workflow import EJNormalisationInput
        with pytest.raises(Exception):
            EJNormalisationInput(raw_log_hash="h", atm_id="A", bank_id="b",
                                 oem_fingerprint="NCR", source="s")

    def test_is_frozen(self):
        inp = _make_input()
        with pytest.raises(Exception):
            inp.raw_log = "other"

    def test_workflow_id_is_deterministic(self):
        from modules.ej.workflows.normalise_workflow import EJNormalisationWorkflow
        wf = EJNormalisationWorkflow()
        wf_id = wf.workflow_id("test-bank", "abc123")
        assert wf_id == "ej-normalise-test-bank-abc123"


class TestEJNormalisationHappyPath:
    @pytest.mark.asyncio
    async def test_happy_path_returns_normalised(self):
        from modules.ej.workflows.normalise_workflow import EJNormalisationWorkflow

        wf = EJNormalisationWorkflow()
        result = await wf.run_with_mocks(_make_input(), mock_results=_make_activity_results())
        assert result.outcome == "NORMALISED"

    @pytest.mark.asyncio
    async def test_result_has_canonical_hash(self):
        from modules.ej.workflows.normalise_workflow import EJNormalisationWorkflow

        wf = EJNormalisationWorkflow()
        result = await wf.run_with_mocks(_make_input(), mock_results=_make_activity_results())
        assert result.canonical_hash is not None

    @pytest.mark.asyncio
    async def test_result_has_bank_id(self):
        from modules.ej.workflows.normalise_workflow import EJNormalisationWorkflow

        wf = EJNormalisationWorkflow()
        result = await wf.run_with_mocks(_make_input(bank_id="kotak"), mock_results=_make_activity_results())
        assert result.bank_id == "kotak"

    @pytest.mark.asyncio
    async def test_result_is_frozen(self):
        from modules.ej.workflows.normalise_workflow import EJNormalisationWorkflow

        wf = EJNormalisationWorkflow()
        result = await wf.run_with_mocks(_make_input(), mock_results=_make_activity_results())
        with pytest.raises(Exception):
            result.outcome = "other"


class TestEJNormalisationFailurePaths:
    @pytest.mark.asyncio
    async def test_parse_failed_returns_parse_failed(self):
        from modules.ej.workflows.normalise_workflow import EJNormalisationWorkflow

        wf = EJNormalisationWorkflow()
        results = _make_activity_results(outcome="PARSE_FAILED")
        result = await wf.run_with_mocks(_make_input(), mock_results=results)
        assert result.outcome == "PARSE_FAILED"

    @pytest.mark.asyncio
    async def test_validation_failed_returns_validation_failed(self):
        from modules.ej.workflows.normalise_workflow import EJNormalisationWorkflow

        wf = EJNormalisationWorkflow()
        results = _make_activity_results(outcome="VALIDATION_FAILED")
        result = await wf.run_with_mocks(_make_input(), mock_results=results)
        assert result.outcome == "VALIDATION_FAILED"

    @pytest.mark.asyncio
    async def test_unknown_oem_recorded_in_result(self):
        from modules.ej.workflows.normalise_workflow import EJNormalisationWorkflow
        from modules.ej.workflows.activities.fingerprint import EJFingerprintResult

        wf = EJNormalisationWorkflow()
        results = _make_activity_results()
        results["fingerprint"] = EJFingerprintResult(
            outcome="UNKNOWN_OEM",
            oem_fingerprint="MYSTERY_VENDOR",
            bank_id="test-bank",
        )
        result = await wf.run_with_mocks(_make_input(), mock_results=results)
        # Unknown OEM still proceeds — just flagged
        assert result.oem_fingerprint == "MYSTERY_VENDOR"
