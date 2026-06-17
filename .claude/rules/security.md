# Security Rules (Banking Grade — Non-Negotiable)

## Secrets
- Zero secrets in code or git — Vault only via `shared/config/config_service.py`
- Any string matching patterns: `password`, `secret`, `key`, `token`, `credential` must come from config_service
- Never use `os.environ.get()` directly in application code — use config_service wrapper

## Network
- Every outbound HTTP client must use mTLS: load cert from Vault, not from disk
- No `verify=False` in any requests call — ever
- All internal service URLs from config_service, never hardcoded

## Logging
- Account numbers: mask to `****{last4}` before logging
- Cheque amounts: log in brackets (₹XX,XX,XXX range) not exact value
- Customer names: first initial + `***` only
- Never log JWT tokens, session IDs, or Vault tokens

## Database
- No `SELECT *` on any table containing PII (cheque_instruments, users, agent_decisions)
- All queries must specify column list explicitly
- Parameterised queries only — no f-string SQL construction
- YugabyteDB connections via pgbouncer pool — never direct from application

## AI Security
- Every AI decision must have SHAP values computed and stored
- No AI decision auto-filed to NGCH without fraud score + SHAP stored first
- Model inference endpoints require mTLS client cert (vLLM behind Istio)

## Audit
- Every write to YugabyteDB that modifies a cheque or EJ record: must emit to `platform.audit.events` Kafka topic
- AuditEvent must be HSM-signed before Immudb write
- Audit writes are fire-and-forget from app perspective — Temporal handles durability

---

## Enforcement

| Rule | Enforced By | Blocks |
|---|---|---|
| Zero secrets in code | gitleaks (pre-commit hook + CI `gitleaks` stage) | Commit blocked + PR merge blocked |
| No os.environ.get() in app code | Semgrep `astra-no-direct-env-secrets` | PR merge blocked |
| No verify=False in HTTP calls | Semgrep `python.requests.security.disabled-cert-validation` | PR merge blocked |
| Account numbers masked in logs | `security-auditor` agent PII checklist + Semgrep log masking rule | PR merge blocked |
| No SELECT * on PII tables | Semgrep `astra-no-select-star-pii` + pre-commit Check 4 | Commit blocked |
| SHAP values before NGCH filing | `cts-workflow-reviewer` agent checklist item 6 | PR merge (CRITICAL) |
| Audit write after every DB write | `cts-workflow-reviewer` / `ej-parser-specialist` agent checklists | PR merge (CRITICAL) |
