# EJ Module Rules

## Critical Constraints
- Raw EJ files are immutable once ingested — never modify `ej_raw_logs` records
- OEM fingerprinting happens at the edge (Go binary) — do not replicate this logic in Python
- Dispute resolution requires CCTV evidence fetch before any auto-resolution decision

## Coding Patterns
- Every EJ canonical record must have a `canonical_hash` (SHA-256 of normalised content)
- LLM parsing must always include OEM context in the prompt (detected at fingerprint stage)
- BGE-M3 embeddings stored as `vector(1024)` in YugabyteDB — use pgvector extension
- Dispute case IDs: `dispute-{bank_id}-{npci_claim_id}` — idempotent workflow IDs

## Edge Agent (Go binary)
- Lives in `edge/ej-agent/` — Go standard library only, minimal dependencies
- Must buffer EJ files locally if central is unreachable (SQLite WAL)
- Compression target: gzip ~70% reduction before AES-256 encryption
- MCP resources: `ej://atm/{atm_id}/logs/{date}` — strict URI format

## LLM Parsing Rules
- Model: Llama 3.3 70B via vLLM (not vision model — EJ is text)
- Prompt must include: OEM fingerprint, raw log excerpt, canonical schema as JSON schema
- Never cache parsed results — each log file is unique
- If LLM extraction confidence < `config_service.get("ej.field_extraction.min_confidence")`, flag for human review — never hardcode 0.85

## Forbidden Patterns in EJ
- Storing ATM location coordinates without bank's data localisation approval
- Cross-bank EJ record queries (strict bank_id isolation)
- CCTV clip storage in YugabyteDB — use MinIO only, store reference in `cctv_evidences` table

---

## Enforcement

| Rule | Enforced By | Blocks |
|---|---|---|
| Raw EJ files immutable — no UPDATE on ej_raw_logs | Semgrep pattern: UPDATE ej_raw_logs in any .py file | PR merge blocked |
| OEM fingerprinting stays in Go edge agent only | `ej-parser-specialist` agent review: Python fingerprint logic = CRITICAL | PR merge blocked |
| LLM confidence < 0.85 → human review flag | `ej-parser-specialist` agent checklist: confidence threshold path covered | PR merge blocked |
| BGE-M3 embeddings as vector(1024) | Alembic migration CI test: wrong vector dimension fails schema validation | PR merge blocked |
| canonical_hash on every EJ record | Semgrep pattern: EJCanonicalRecord without canonical_hash field | PR merge blocked |
| CCTV clips in MinIO only — not in YugabyteDB | `security-auditor` agent + Semgrep: bytea column for cctv_ tables = CRITICAL | PR merge blocked |
