"""
Tests for internal/workflows/migration_diagnosis/activities.py

MigrationDiagnosisWorkflow activities — run on ASTRA's internal Temporal.
These activities NEVER run on a bank's cluster.

Invariants tested:
  1. parse_migration_logs strips secrets before passing to LLM
  2. llm_diagnose only receives sanitized log content
  3. generate_report never includes raw DB URLs or credentials
  4. write_audit always fires — even if notify steps fail
  5. All activities raise on missing consent token
  6. Bank log content is never written to ASTRA's DB — transient only
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass
from typing import Optional


# ── Input / output dataclasses (tested for correct field presence) ────────────

class TestMigrationRunInput:
    def test_has_bank_id(self):
        from internal.workflows.migration_diagnosis.activities import MigrationRunInput
        inp = MigrationRunInput(
            bank_id="kotak-mah",
            run_id="astra-kotak-mah-20260618T103045Z",
            consent_token="diag-token-abc123",
            mcp_endpoint="https://mcp.kotak-mah.internal:8443",
            chains=["platform", "cts"],
        )
        assert inp.bank_id == "kotak-mah"

    def test_has_run_id(self):
        from internal.workflows.migration_diagnosis.activities import MigrationRunInput
        inp = MigrationRunInput(
            bank_id="kotak-mah",
            run_id="astra-kotak-mah-20260618T103045Z",
            consent_token="diag-token-abc123",
            mcp_endpoint="https://mcp.kotak-mah.internal:8443",
            chains=["platform"],
        )
        assert inp.run_id == "astra-kotak-mah-20260618T103045Z"

    def test_has_chains_list(self):
        from internal.workflows.migration_diagnosis.activities import MigrationRunInput
        inp = MigrationRunInput(
            bank_id="kotak-mah",
            run_id="astra-kotak-mah-20260618T103045Z",
            consent_token="diag-token-abc123",
            mcp_endpoint="https://mcp.kotak-mah.internal:8443",
            chains=["platform", "cts", "ej"],
        )
        assert "platform" in inp.chains

    def test_consent_token_required(self):
        from internal.workflows.migration_diagnosis.activities import MigrationRunInput
        with pytest.raises(TypeError):
            MigrationRunInput(
                bank_id="kotak-mah",
                run_id="run-001",
                mcp_endpoint="https://mcp.kotak-mah.internal:8443",
                chains=["platform"],
                # consent_token missing — must fail
            )


class TestParseMigrationLogs:
    """parse_migration_logs: fetch JSONL from bank MCP, return sanitized entries."""

    @pytest.mark.asyncio
    async def test_returns_parsed_entries(self):
        from internal.workflows.migration_diagnosis.activities import (
            parse_migration_logs, MigrationRunInput, ParsedLogEntry,
        )
        sample_jsonl = (
            '{"ts":"2026-06-18T10:30:45Z","level":"INFO","run_id":"run-001",'
            '"chain":"platform","event":"MIGRATION_START","detail":"chain=platform","chart_version":"0.1.0"}\n'
            '{"ts":"2026-06-18T10:30:47Z","level":"ERROR","run_id":"run-001",'
            '"chain":"platform","event":"MIGRATION_FAILED","detail":"column already exists","chart_version":"0.1.0"}\n'
        )
        inp = MigrationRunInput(
            bank_id="test-bank",
            run_id="run-001",
            consent_token="tok-abc",
            mcp_endpoint="https://mcp.test-bank.internal:8443",
            chains=["platform"],
        )
        with patch(
            "internal.workflows.migration_diagnosis.activities._fetch_mcp_log",
            new_callable=AsyncMock,
            return_value=sample_jsonl,
        ):
            result = await parse_migration_logs(inp)

        assert len(result) == 2
        assert result[0].event == "MIGRATION_START"
        assert result[1].event == "MIGRATION_FAILED"

    @pytest.mark.asyncio
    async def test_strips_db_url_from_detail(self):
        """DB URLs must never reach the LLM — sanitized before returning."""
        from internal.workflows.migration_diagnosis.activities import (
            parse_migration_logs, MigrationRunInput,
        )
        # detail contains a DB URL (edge case: Alembic error message may include it)
        sample_jsonl = (
            '{"ts":"2026-06-18T10:30:47Z","level":"ERROR","run_id":"run-001",'
            '"chain":"platform","event":"MIGRATION_FAILED",'
            '"detail":"Could not connect to postgresql://admin:secret@yugabyte:5432/astra",'
            '"chart_version":"0.1.0"}\n'
        )
        inp = MigrationRunInput(
            bank_id="test-bank",
            run_id="run-001",
            consent_token="tok-abc",
            mcp_endpoint="https://mcp.test-bank.internal:8443",
            chains=["platform"],
        )
        with patch(
            "internal.workflows.migration_diagnosis.activities._fetch_mcp_log",
            new_callable=AsyncMock,
            return_value=sample_jsonl,
        ):
            result = await parse_migration_logs(inp)

        # DB URL with credentials must be scrubbed
        assert "secret" not in result[0].detail
        assert "admin" not in result[0].detail
        assert "postgresql://" not in result[0].detail

    @pytest.mark.asyncio
    async def test_raises_on_missing_consent_token(self):
        from internal.workflows.migration_diagnosis.activities import (
            parse_migration_logs, MigrationRunInput, ConsentDeniedError,
        )
        inp = MigrationRunInput(
            bank_id="test-bank",
            run_id="run-001",
            consent_token="",     # empty = no consent
            mcp_endpoint="https://mcp.test-bank.internal:8443",
            chains=["platform"],
        )
        with pytest.raises(ConsentDeniedError):
            await parse_migration_logs(inp)

    @pytest.mark.asyncio
    async def test_only_fetches_requested_chains(self):
        from internal.workflows.migration_diagnosis.activities import (
            parse_migration_logs, MigrationRunInput,
        )
        inp = MigrationRunInput(
            bank_id="test-bank",
            run_id="run-001",
            consent_token="tok-abc",
            mcp_endpoint="https://mcp.test-bank.internal:8443",
            chains=["platform"],   # only platform — must not fetch cts or ej
        )
        with patch(
            "internal.workflows.migration_diagnosis.activities._fetch_mcp_log",
            new_callable=AsyncMock,
            return_value='{"ts":"2026-06-18T10:30:45Z","level":"INFO","run_id":"run-001","chain":"platform","event":"MIGRATION_COMPLETE","detail":"","chart_version":"0.1.0"}\n',
        ) as mock_fetch:
            await parse_migration_logs(inp)

        # Should be called exactly once — only for "platform"
        assert mock_fetch.call_count == 1


class TestLLMDiagnose:
    """llm_diagnose: call Llama 3.3 70B with sanitized log entries, return diagnosis."""

    @pytest.mark.asyncio
    async def test_returns_diagnosis_with_root_cause(self):
        from internal.workflows.migration_diagnosis.activities import (
            llm_diagnose, ParsedLogEntry, DiagnosisResult,
        )
        entries = [
            ParsedLogEntry(ts="2026-06-18T10:30:45Z", level="INFO", run_id="run-001",
                           chain="platform", event="MIGRATION_START", detail="",
                           chart_version="0.1.0"),
            ParsedLogEntry(ts="2026-06-18T10:30:47Z", level="ERROR", run_id="run-001",
                           chain="platform", event="MIGRATION_FAILED",
                           detail="column 'bank_id' of relation 'banks' already exists",
                           chart_version="0.1.0"),
        ]
        mock_response = DiagnosisResult(
            root_cause="Column already exists — migration was partially applied in a prior run.",
            affected_chain="platform",
            recommended_action="Run alembic stamp head to mark the migration as applied, then retry.",
            confidence=0.91,
            severity="HIGH",
        )
        with patch(
            "internal.workflows.migration_diagnosis.activities._call_llm",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await llm_diagnose(entries)

        assert result.root_cause is not None
        assert result.confidence > 0.0
        assert result.severity in ("LOW", "MEDIUM", "HIGH", "CRITICAL")

    @pytest.mark.asyncio
    async def test_raises_on_empty_entries(self):
        from internal.workflows.migration_diagnosis.activities import (
            llm_diagnose, DiagnosisError,
        )
        with pytest.raises(DiagnosisError):
            await llm_diagnose([])

    @pytest.mark.asyncio
    async def test_never_passes_credentials_to_llm(self):
        """Verify prompt construction never includes credential patterns."""
        from internal.workflows.migration_diagnosis.activities import (
            llm_diagnose, ParsedLogEntry, DiagnosisResult, _build_diagnosis_prompt,
        )
        entries = [
            ParsedLogEntry(ts="2026-06-18T10:30:47Z", level="ERROR", run_id="run-001",
                           chain="platform", event="MIGRATION_FAILED",
                           detail="column already exists",
                           chart_version="0.1.0"),
        ]
        prompt = _build_diagnosis_prompt(entries)
        # Prompt must never contain patterns that look like credentials
        assert "postgresql://" not in prompt
        assert "password" not in prompt.lower()
        assert "@yugabyte" not in prompt


class TestGenerateReport:
    """generate_report: produce a structured markdown report from diagnosis."""

    @pytest.mark.asyncio
    async def test_returns_report_with_bank_id(self):
        from internal.workflows.migration_diagnosis.activities import (
            generate_report, DiagnosisResult, MigrationReport,
        )
        diagnosis = DiagnosisResult(
            root_cause="Column already exists.",
            affected_chain="platform",
            recommended_action="Run alembic stamp head.",
            confidence=0.91,
            severity="HIGH",
        )
        report = await generate_report(
            bank_id="test-bank",
            run_id="run-001",
            diagnosis=diagnosis,
        )
        assert report.bank_id == "test-bank"

    @pytest.mark.asyncio
    async def test_report_has_recommended_action(self):
        from internal.workflows.migration_diagnosis.activities import (
            generate_report, DiagnosisResult,
        )
        diagnosis = DiagnosisResult(
            root_cause="Column already exists.",
            affected_chain="platform",
            recommended_action="Run alembic stamp head.",
            confidence=0.91,
            severity="HIGH",
        )
        report = await generate_report(
            bank_id="test-bank",
            run_id="run-001",
            diagnosis=diagnosis,
        )
        assert report.recommended_action is not None

    @pytest.mark.asyncio
    async def test_report_never_contains_db_credentials(self):
        from internal.workflows.migration_diagnosis.activities import (
            generate_report, DiagnosisResult,
        )
        diagnosis = DiagnosisResult(
            root_cause="Column already exists.",
            affected_chain="platform",
            recommended_action="Run alembic stamp head.",
            confidence=0.91,
            severity="HIGH",
        )
        report = await generate_report(
            bank_id="test-bank",
            run_id="run-001",
            diagnosis=diagnosis,
        )
        assert "postgresql://" not in report.markdown_body
        assert "password" not in report.markdown_body.lower()


class TestWriteAudit:
    """write_audit: always fires — even if notify steps fail."""

    @pytest.mark.asyncio
    async def test_emits_audit_event(self):
        from internal.workflows.migration_diagnosis.activities import (
            write_audit, MigrationReport, DiagnosisResult,
        )
        from internal.workflows.migration_diagnosis.activities import MigrationRunInput
        inp = MigrationRunInput(
            bank_id="test-bank",
            run_id="run-001",
            consent_token="tok-abc",
            mcp_endpoint="https://mcp.test-bank.internal:8443",
            chains=["platform"],
        )
        diagnosis = DiagnosisResult(
            root_cause="Column already exists.",
            affected_chain="platform",
            recommended_action="Run alembic stamp head.",
            confidence=0.91,
            severity="HIGH",
        )
        report = MigrationReport(
            bank_id="test-bank",
            run_id="run-001",
            diagnosis=diagnosis,
            markdown_body="## Migration Diagnosis\n\nRoot cause: ...",
            recommended_action="Run alembic stamp head.",
            generated_at="2026-06-18T10:35:00Z",
        )
        with patch(
            "internal.workflows.migration_diagnosis.activities._write_immudb_event",
            new_callable=AsyncMock,
            return_value=None,
        ) as mock_immudb:
            await write_audit(inp, report)

        mock_immudb.assert_called_once()

    @pytest.mark.asyncio
    async def test_audit_event_never_stores_log_content(self):
        """Audit record captures metadata only — not raw log lines from bank."""
        from internal.workflows.migration_diagnosis.activities import (
            write_audit, MigrationReport, DiagnosisResult, MigrationRunInput,
            _build_audit_payload,
        )
        inp = MigrationRunInput(
            bank_id="test-bank",
            run_id="run-001",
            consent_token="tok-abc",
            mcp_endpoint="https://mcp.test-bank.internal:8443",
            chains=["platform"],
        )
        diagnosis = DiagnosisResult(
            root_cause="Column already exists.",
            affected_chain="platform",
            recommended_action="Run alembic stamp head.",
            confidence=0.91,
            severity="HIGH",
        )
        report = MigrationReport(
            bank_id="test-bank",
            run_id="run-001",
            diagnosis=diagnosis,
            markdown_body="## Migration Diagnosis",
            recommended_action="Run alembic stamp head.",
            generated_at="2026-06-18T10:35:00Z",
        )
        payload = _build_audit_payload(inp, report)
        # Audit payload must not store raw log lines — only metadata
        assert "JSONL" not in str(payload)
        assert payload["bank_id"] == "test-bank"
        assert payload["run_id"] == "run-001"
        assert "diagnosis_severity" in payload


class TestWorkflowIntegration:
    """Integration-level checks on the workflow definition itself."""

    def test_workflow_class_exists(self):
        from internal.workflows.migration_diagnosis.workflow import MigrationDiagnosisWorkflow
        assert MigrationDiagnosisWorkflow is not None

    def test_workflow_has_run_method(self):
        from internal.workflows.migration_diagnosis.workflow import MigrationDiagnosisWorkflow
        assert hasattr(MigrationDiagnosisWorkflow, "run")

    def test_workflow_input_type_is_migration_run_input(self):
        import inspect
        from internal.workflows.migration_diagnosis.workflow import MigrationDiagnosisWorkflow
        from internal.workflows.migration_diagnosis.activities import MigrationRunInput
        sig = inspect.signature(MigrationDiagnosisWorkflow.run)
        params = list(sig.parameters.values())
        # First param after self is the input
        assert len(params) >= 2
        annotation = params[1].annotation
        assert annotation is MigrationRunInput or annotation == "MigrationRunInput"
