"""
MigrationDiagnosisWorkflow — Temporal workflow on ASTRA's internal cluster.

Orchestrates diagnosis of a failed Helm upgrade migration for a bank.
Never runs inside a bank's environment.

Sequence:
  1. parse_migration_logs  — fetch + sanitise JSONL from bank MCP (with consent)
  2. llm_diagnose          — Llama 3.3 70B produces DiagnosisResult
  3. generate_report       — build MigrationReport markdown
  4. write_audit           — metadata-only event to ASTRA Immudb (always fires)
"""
from datetime import timedelta

try:
    from temporalio import workflow
    from temporalio.common import RetryPolicy
    _TEMPORAL_AVAILABLE = True
except ImportError:  # pragma: no cover — temporalio present in production
    _TEMPORAL_AVAILABLE = False

from internal.workflows.migration_diagnosis.activities import (
    MigrationRunInput,
    MigrationReport,
    parse_migration_logs,
    llm_diagnose,
    generate_report,
    write_audit,
)

_PARSE_RETRY_KWARGS = dict(maximum_attempts=3, initial_interval=timedelta(seconds=2),
                           backoff_coefficient=2.0) if _TEMPORAL_AVAILABLE else {}
_LLM_RETRY_KWARGS = dict(maximum_attempts=2, initial_interval=timedelta(seconds=5),
                         backoff_coefficient=2.0,
                         non_retryable_error_types=["DiagnosisError"]) if _TEMPORAL_AVAILABLE else {}
_AUDIT_RETRY_KWARGS = dict(maximum_attempts=None, initial_interval=timedelta(seconds=1),
                           maximum_interval=timedelta(minutes=5)) if _TEMPORAL_AVAILABLE else {}


def _workflow_defn(cls):
    if _TEMPORAL_AVAILABLE:
        return workflow.defn(cls)
    return cls


def _workflow_run(fn):
    if _TEMPORAL_AVAILABLE:
        return workflow.run(fn)
    return fn


@_workflow_defn
class MigrationDiagnosisWorkflow:
    @_workflow_run
    async def run(self, inp: MigrationRunInput) -> MigrationReport:
        if _TEMPORAL_AVAILABLE:
            parse_retry = RetryPolicy(**_PARSE_RETRY_KWARGS)
            llm_retry = RetryPolicy(**_LLM_RETRY_KWARGS)
            audit_retry = RetryPolicy(**_AUDIT_RETRY_KWARGS)

            entries = await workflow.execute_activity(
                parse_migration_logs, inp,
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=parse_retry,
            )
            diagnosis = await workflow.execute_activity(
                llm_diagnose, entries,
                start_to_close_timeout=timedelta(seconds=180),
                retry_policy=llm_retry,
            )
            report = await workflow.execute_activity(
                generate_report, args=[inp.bank_id, inp.run_id, diagnosis],
                start_to_close_timeout=timedelta(seconds=30),
            )
            await workflow.execute_activity(
                write_audit, args=[inp, report],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=audit_retry,
            )
        else:
            # Direct calls — used only during local testing without Temporal
            entries = await parse_migration_logs(inp)
            diagnosis = await llm_diagnose(entries)
            report = await generate_report(inp.bank_id, inp.run_id, diagnosis)
            await write_audit(inp, report)

        return report
