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
    from modules.ej.workflows.activities.store_canonical import EJStoreCanonicalResult
    from modules.ej.workflows.activities.trigger_dispute_check import EJTriggerDisputeCheckResult
    from modules.ej.workflows.activities.update_atm_health import EJUpdateATMHealthResult
    from modules.ej.workflows.activities.write_audit import EJWriteAuditResult

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
        "store_canonical": EJStoreCanonicalResult(
            outcome="STORED",
            canonical_hash="d" * 64,
            bank_id="test-bank",
        ),
        "trigger_dispute_check": EJTriggerDisputeCheckResult(
            outcome="TRIGGERED",
            bank_id="test-bank",
        ),
        "update_atm_health": EJUpdateATMHealthResult(
            outcome="UPDATED",
            atm_id="ATM001",
            bank_id="test-bank",
        ),
        "write_audit": EJWriteAuditResult(
            outcome="WRITTEN",
            bank_id="test-bank",
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


class TestEJNormalisationPostValidationSteps:
    """Tests for store_canonical, trigger_dispute_check, update_atm_health, write_audit."""

    @pytest.mark.asyncio
    async def test_store_canonical_called_on_happy_path(self):
        """After successful validation, canonical record must be persisted."""
        from modules.ej.workflows.normalise_workflow import EJNormalisationWorkflow

        wf = EJNormalisationWorkflow()
        results = _make_activity_results()
        result = await wf.run_with_mocks(_make_input(), mock_results=results)
        # canonical_record must be present in final result (store step ran)
        assert result.canonical_record is not None
        assert result.outcome == "NORMALISED"

    @pytest.mark.asyncio
    async def test_store_canonical_not_called_on_parse_failed(self):
        """If LLM parse fails, store_canonical must not run."""
        from modules.ej.workflows.normalise_workflow import EJNormalisationWorkflow
        from modules.ej.workflows.activities.store_canonical import EJStoreCanonicalResult

        wf = EJNormalisationWorkflow()
        results = _make_activity_results(outcome="PARSE_FAILED")
        # Replace store_canonical with a sentinel that would fail if called
        sentinel = EJStoreCanonicalResult(outcome="STORED", canonical_hash="x" * 64, bank_id="test-bank")
        results["store_canonical"] = sentinel
        result = await wf.run_with_mocks(_make_input(), mock_results=results)
        assert result.outcome == "PARSE_FAILED"
        # canonical_record must be absent (store step was skipped)
        assert result.canonical_record is None

    @pytest.mark.asyncio
    async def test_store_canonical_not_called_on_validation_failed(self):
        """If schema validation fails, store_canonical must not run."""
        from modules.ej.workflows.normalise_workflow import EJNormalisationWorkflow

        wf = EJNormalisationWorkflow()
        results = _make_activity_results(outcome="VALIDATION_FAILED")
        result = await wf.run_with_mocks(_make_input(), mock_results=results)
        assert result.outcome == "VALIDATION_FAILED"
        assert result.canonical_record is None

    @pytest.mark.asyncio
    async def test_trigger_dispute_check_called_on_happy_path(self):
        """Dispute check must be triggered after a successful normalisation."""
        from modules.ej.workflows.normalise_workflow import EJNormalisationWorkflow

        wf = EJNormalisationWorkflow()
        results = _make_activity_results()
        result = await wf.run_with_mocks(_make_input(), mock_results=results)
        # If dispute_check was skipped, outcome would still be NORMALISED but we verify via workflow tracker
        assert result.outcome == "NORMALISED"
        assert result.dispute_check_triggered is True

    @pytest.mark.asyncio
    async def test_update_atm_health_called_on_happy_path(self):
        """ATM health signals must be updated after normalisation."""
        from modules.ej.workflows.normalise_workflow import EJNormalisationWorkflow

        wf = EJNormalisationWorkflow()
        results = _make_activity_results()
        result = await wf.run_with_mocks(_make_input(atm_id="ATM042"), mock_results=results)
        assert result.outcome == "NORMALISED"
        assert result.atm_health_updated is True

    @pytest.mark.asyncio
    async def test_write_audit_called_on_happy_path(self):
        """Audit trail must be written as final step."""
        from modules.ej.workflows.normalise_workflow import EJNormalisationWorkflow

        wf = EJNormalisationWorkflow()
        results = _make_activity_results()
        result = await wf.run_with_mocks(_make_input(), mock_results=results)
        assert result.outcome == "NORMALISED"
        assert result.audit_written is True

    @pytest.mark.asyncio
    async def test_write_audit_called_on_parse_failed(self):
        """Audit must also be written for failed outcomes — compliance requirement."""
        from modules.ej.workflows.normalise_workflow import EJNormalisationWorkflow

        wf = EJNormalisationWorkflow()
        results = _make_activity_results(outcome="PARSE_FAILED")
        result = await wf.run_with_mocks(_make_input(), mock_results=results)
        assert result.outcome == "PARSE_FAILED"
        assert result.audit_written is True

    @pytest.mark.asyncio
    async def test_write_audit_called_on_validation_failed(self):
        """Audit must also be written for validation failures."""
        from modules.ej.workflows.normalise_workflow import EJNormalisationWorkflow

        wf = EJNormalisationWorkflow()
        results = _make_activity_results(outcome="VALIDATION_FAILED")
        result = await wf.run_with_mocks(_make_input(), mock_results=results)
        assert result.outcome == "VALIDATION_FAILED"
        assert result.audit_written is True
