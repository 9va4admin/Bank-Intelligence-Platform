# Enforcement Map — All Rules Files

Reference for CI/pre-commit hook setup. Not needed during coding sessions.

| Rules File | What It Governs | Enforced By |
|---|---|---|
| `cts.md` | IET safety, vault miss routing, NGCH filing, thresholds | pre-commit Check 3, Semgrep `astra-vault-miss-must-review` + `astra-no-hardcoded-threshold`, cts-workflow-reviewer agent |
| `isolation.md` | CTS-only blast isolation (EJ is in `atm-ej-platform` repo) | pre-commit Check 6+7, Semgrep `astra-no-cross-module-import`, CI checkov |
| `temporal.md` | Workflow patterns, retry constants, IET watchdog | cts-workflow-reviewer agent, Semgrep (asyncio.sleep in workflows), CI SAST |
| `ai-inference.md` | vLLM queue routing, SHAP, Langfuse wrapping | Semgrep (vLLM calls without explicit queue), security-auditor agent |
| `microservices.md` | Service identity, health endpoints, logging | CI lint (missing /health endpoints), no-print Semgrep rule |
| `api-versioning.md` | Breaking changes, deprecation headers, sunset | pre-commit Check 5, CI `api-compat` stage |
| `cicd.md` | Pipeline stages, Dockerfile standards, secrets in images | CI self-referential, Trivy image scan |
| `diagnostic-mcp.md` | Consent model, non-PII signals only, audit trail | OPA policy `astra/diagnostic` (runtime), security-auditor agent |
| `pii-data-protection.md` | Hashing, encryption, masking of PII | Semgrep `astra-no-select-star-pii`, pre-commit Check 4, security-auditor agent |
| `secrets-vault.md` | All secrets via Vault, no env var secrets | gitleaks (pre-commit + CI), Semgrep `astra-no-direct-env-secrets`, pre-commit Check 1+2 |
| `security-scanning.md` | Scan ownership, CI gates, severity levels | CI pipeline itself (all stages `allow_failure: false`), release gate |
| `security.md` | General security baseline | All of the above |
| `database.md` | Query patterns, connection pools, migrations | Semgrep `astra-no-select-star-pii`, Alembic migration CI check |
| `api.md` | Router structure, auth, rate limits, OTel | CI integration tests, OpenAPI schema lint |
| `frontend.md` | Multi-theme support, `useTheme()` pattern | Semgrep (hardcoded dark wrapper classes), code review |
| `sb-smb-context.md` | SB vs SMB bank type scoping | `security-auditor` agent, Semgrep (hardcoded bank_type) |
| `messages.md` | Single-source message registry | pre-commit Check 11, CI `build --validate-only` |
| `tdd.md` | RED→GREEN sequence, coverage minimums | pre-commit Check 9+10, CI `pytest --cov-fail-under` |

## Enforcement Strength (ranked)
1. BLOCKS COMMIT — pre-commit hook exits non-zero
2. BLOCKS MERGE — CI stage fails
3. BLOCKS RELEASE — release gate requires sign-off
4. BLOCKS AT RUNTIME — OPA policy denies the request
5. AGENT REVIEW — security-auditor flags in PR; human must dismiss CRITICAL
