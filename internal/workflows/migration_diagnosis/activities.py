"""
MigrationDiagnosisWorkflow activities.

Runs on ASTRA's internal Temporal cluster — never deployed to a bank's environment.

Invariants:
  - Bank log content never persisted at ASTRA (transient only)
  - No diagnosis without a valid consent token
  - DB credentials stripped from log detail before any LLM call
  - Audit record stores metadata only — not raw JSONL lines
"""
import json
import re
from dataclasses import dataclass, field
from typing import Optional

import structlog

log = structlog.get_logger()

# Regex to scrub DB URLs including credentials from log detail text.
# Matches: postgresql://user:pass@host:port/db and similar schemes.
_DB_URL_RE = re.compile(
    r"[a-zA-Z][a-zA-Z0-9+\-.]*://"   # scheme
    r"[^@\s]*@"                        # user:pass@
    r"[^\s\"']*",                      # host/path
    re.IGNORECASE,
)


# ── Errors ────────────────────────────────────────────────────────────────────

class ConsentDeniedError(Exception):
    """Raised when consent_token is empty or invalid."""


class DiagnosisError(Exception):
    """Raised when diagnosis cannot be produced (e.g. empty log entries)."""


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class MigrationRunInput:
    bank_id: str
    run_id: str
    consent_token: str
    mcp_endpoint: str
    chains: list[str]


@dataclass
class ParsedLogEntry:
    ts: str
    level: str
    run_id: str
    chain: str
    event: str
    detail: str
    chart_version: str


@dataclass
class DiagnosisResult:
    root_cause: str
    affected_chain: str
    recommended_action: str
    confidence: float
    severity: str  # LOW | MEDIUM | HIGH | CRITICAL


@dataclass
class MigrationReport:
    bank_id: str
    run_id: str
    diagnosis: DiagnosisResult
    markdown_body: str
    recommended_action: str
    generated_at: str


# ── Internal helpers (mockable in tests) ─────────────────────────────────────

async def _fetch_mcp_log(mcp_endpoint: str, bank_id: str, run_id: str,
                         chain: str, consent_token: str) -> str:
    """Fetch JSONL log for one chain from bank's MCP server."""
    raise NotImplementedError("_fetch_mcp_log must be called via bank MCP in production")


async def _call_llm(prompt: str) -> "DiagnosisResult":
    """Call Llama 3.3 70B via internal vLLM to produce DiagnosisResult."""
    raise NotImplementedError("_call_llm must be called via internal vLLM in production")


async def _write_immudb_event(payload: dict) -> None:
    """Write audit event to ASTRA's internal Immudb instance."""
    raise NotImplementedError("_write_immudb_event must be wired to ASTRA Immudb in production")


# ── Private utilities ─────────────────────────────────────────────────────────

def _sanitise_detail(detail: str) -> str:
    """Strip DB URLs (including embedded credentials) from log detail text."""
    return _DB_URL_RE.sub("[REDACTED_DB_URL]", detail)


def _parse_jsonl_line(line: str) -> Optional[ParsedLogEntry]:
    line = line.strip()
    if not line:
        return None
    obj = json.loads(line)
    return ParsedLogEntry(
        ts=obj["ts"],
        level=obj["level"],
        run_id=obj["run_id"],
        chain=obj["chain"],
        event=obj["event"],
        detail=_sanitise_detail(obj.get("detail", "")),
        chart_version=obj.get("chart_version", ""),
    )


def _build_diagnosis_prompt(entries: list[ParsedLogEntry]) -> str:
    """Construct LLM prompt from sanitised log entries.

    Invariant: prompt must never contain credential patterns.
    """
    lines = []
    for e in entries:
        # Only include safe fields — detail has already been sanitised
        lines.append(f"[{e.ts}] [{e.level}] chain={e.chain} event={e.event} detail={e.detail}")

    log_text = "\n".join(lines)

    return (
        "You are an ASTRA platform support engineer diagnosing a failed Helm upgrade migration.\n"
        "Analyse the following sanitised migration log and return a JSON object with these fields:\n"
        "  root_cause (str), affected_chain (str), recommended_action (str),\n"
        "  confidence (float 0–1), severity (one of LOW/MEDIUM/HIGH/CRITICAL).\n\n"
        f"Migration log:\n{log_text}\n\n"
        "Respond with valid JSON only."
    )


def _build_audit_payload(inp: MigrationRunInput, report: MigrationReport) -> dict:
    """Build the Immudb audit record.

    Stores metadata only — not raw JSONL content from the bank.
    """
    return {
        "event_type": "MIGRATION_DIAGNOSIS",
        "bank_id": inp.bank_id,
        "run_id": inp.run_id,
        "chains_diagnosed": inp.chains,
        "diagnosis_severity": report.diagnosis.severity,
        "diagnosis_confidence": report.diagnosis.confidence,
        "affected_chain": report.diagnosis.affected_chain,
        "generated_at": report.generated_at,
        # consent_token is intentionally EXCLUDED — never logged
    }


# ── Activities ────────────────────────────────────────────────────────────────

async def parse_migration_logs(inp: MigrationRunInput) -> list[ParsedLogEntry]:
    """Fetch JSONL from bank MCP for each requested chain and return sanitised entries.

    Raises ConsentDeniedError if consent_token is empty.
    Fetches only the chains listed in inp.chains.
    """
    if not inp.consent_token:
        raise ConsentDeniedError(
            f"No consent token provided for bank_id={inp.bank_id} run_id={inp.run_id}"
        )

    entries: list[ParsedLogEntry] = []

    for chain in inp.chains:
        raw_jsonl = await _fetch_mcp_log(
            mcp_endpoint=inp.mcp_endpoint,
            bank_id=inp.bank_id,
            run_id=inp.run_id,
            chain=chain,
            consent_token=inp.consent_token,
        )
        for line in raw_jsonl.splitlines():
            entry = _parse_jsonl_line(line)
            if entry is not None:
                entries.append(entry)

    log.info("migration.parse_logs.complete",
             bank_id=inp.bank_id, run_id=inp.run_id,
             chains=inp.chains, entry_count=len(entries))

    return entries


async def llm_diagnose(entries: list[ParsedLogEntry]) -> DiagnosisResult:
    """Call Llama 3.3 70B with sanitised entries to produce a DiagnosisResult.

    Raises DiagnosisError if entries list is empty.
    """
    if not entries:
        raise DiagnosisError("Cannot diagnose: no log entries provided")

    prompt = _build_diagnosis_prompt(entries)
    result = await _call_llm(prompt)
    return result


async def generate_report(
    bank_id: str,
    run_id: str,
    diagnosis: DiagnosisResult,
) -> MigrationReport:
    """Produce a structured MigrationReport from a DiagnosisResult.

    The markdown_body never includes raw DB credentials — only the sanitised
    diagnosis fields that came through _sanitise_detail earlier.
    """
    from datetime import datetime, timezone

    markdown_body = (
        f"## Migration Diagnosis — {bank_id}\n\n"
        f"**Run ID:** {run_id}\n\n"
        f"**Affected Chain:** {diagnosis.affected_chain}\n\n"
        f"**Severity:** {diagnosis.severity}\n\n"
        f"**Root Cause:**\n\n{diagnosis.root_cause}\n\n"
        f"**Recommended Action:**\n\n{diagnosis.recommended_action}\n\n"
        f"**Confidence:** {diagnosis.confidence:.0%}\n"
    )

    return MigrationReport(
        bank_id=bank_id,
        run_id=run_id,
        diagnosis=diagnosis,
        markdown_body=markdown_body,
        recommended_action=diagnosis.recommended_action,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


async def write_audit(inp: MigrationRunInput, report: MigrationReport) -> None:
    """Write a metadata-only audit event to ASTRA's internal Immudb.

    Always fires — must be called even if prior notify steps fail.
    Raw bank log content is never included in the audit payload.
    """
    payload = _build_audit_payload(inp, report)
    await _write_immudb_event(payload)
    log.info("migration.audit.written",
             bank_id=inp.bank_id, run_id=inp.run_id,
             severity=report.diagnosis.severity)
