# Rules Constitution — Every Rule Must Have Enforcement

## The Meta-Rule

```
A rule that is not enforced by a machine is not a rule — it is a suggestion.
Suggestions are ignored under pressure. In banking software, pressure is constant.

EVERY rule in .claude/rules/ MUST specify:
  1. WHAT enforces it (hook / CI stage / agent / Semgrep rule)
  2. WHEN it runs (pre-commit / PR / release gate / runtime)
  3. WHAT HAPPENS on violation (commit blocked / merge blocked / deploy blocked)

A rules file with no ## Enforcement section is INCOMPLETE.
```

## Enforcement of This Very Rule

| Mechanism | What it checks | Blocks what |
|---|---|---|
| `.claude/hooks/pre-commit-security.sh` Check 8 | Every `.claude/rules/*.md` lacking `## Enforcement` section | Commit blocked |
| `security-auditor` agent | On every PR, verifies all touched rules files have enforcement sections | PR flagged CRITICAL |
| Claude Code session rule | Claude refuses to write a new rules file without `## Enforcement` | Rejected in-session |

---

## Enforcement Map — All Rules Files

| Rules File | What It Governs | Enforced By |
|---|---|---|
| `cts.md` | IET safety, vault miss routing, NGCH filing, thresholds | pre-commit Check 3, Semgrep `astra-vault-miss-must-review` + `astra-no-hardcoded-threshold`, cts-workflow-reviewer agent |
| `isolation.md` | CTS↔EJ blast isolation | pre-commit Check 6+7, Semgrep `astra-no-cross-module-import`, CI checkov |
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
| `ej.md` | EJ immutability, edge agent, LLM parsing | ej-parser-specialist agent, CI contract tests for MCP server |
| `frontend.md` | Multi-theme support, `useTheme()` pattern | Semgrep (hardcoded dark wrapper classes), code review |
| `sb-smb-context.md` | SB vs SMB bank type scoping — every page, data fetch, download | `security-auditor` agent, Semgrep (hardcoded bank_type) |
| `messages.md` | Single-source message registry | pre-commit Check 11, CI `build --validate-only` |
| `tdd.md` | RED→GREEN sequence, coverage minimums | pre-commit Check 9+10, CI `pytest --cov-fail-under` |

---

## What Counts as Enforcement (ranked strongest→weakest)

1. **BLOCKS COMMIT** — pre-commit hook exits non-zero
2. **BLOCKS MERGE** — CI stage fails
3. **BLOCKS RELEASE** — release gate requires sign-off
4. **BLOCKS AT RUNTIME** — OPA policy denies the request
5. **AGENT REVIEW** — security-auditor flags in PR; human must dismiss CRITICAL

"Documentation only" is NOT enforcement. If a rule can only be caught by a human reading code in review, it is a guideline, not a rule.

---

## Adding a New Rule — Mandatory Checklist

```
[ ] Is there an existing enforcement mechanism that catches violations?
      If YES → reference it in ## Enforcement
      If NO  → create the enforcement (Semgrep rule / hook check / CI stage) FIRST

[ ] Does the enforcement block commit, merge, or release?
      "Only visible in PR review" is insufficient for CRITICAL rules.

[ ] Is the enforcement listed in the Enforcement Map above?
      Update the table.
```

---

## AI Session Enforcement (Claude Code)

Claude MUST:
- Refuse to write a new `.claude/rules/*.md` file without an `## Enforcement` section
- Refuse code that violates any rule even if not asked to check
- Never write `os.environ.get()` — always `config_service`
- Never write `SELECT *` on PII tables — even in examples
- Never write a hardcoded threshold — write `config_service.get("...")` instead
- Flag violations immediately when spotted, even while working on something else

---

## Enforcement

| Rule | Enforced By | Blocks |
|---|---|---|
| Every `.claude/rules/*.md` has `## Enforcement` section | pre-commit Check 8 | Commit blocked |
| Touched rules files verified to have enforcement sections | `security-auditor` agent on every PR | PR flagged CRITICAL |
| Claude refuses to write rules files without enforcement | Claude Code AI session rule | Session-time enforcement |
