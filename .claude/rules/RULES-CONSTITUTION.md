# Rules Constitution — Every Rule Must Have Enforcement

## The Meta-Rule (Applies to Every Other Rules File)

```
A rule that is not enforced by a machine is not a rule.
It is a suggestion. Suggestions are ignored under pressure.
In banking software, pressure is constant. Therefore:

EVERY rule in .claude/rules/ MUST specify:
  1. WHAT enforces it (hook / CI stage / agent / settings.json deny / Semgrep rule)
  2. WHEN it runs (pre-commit / PR / release gate / runtime)
  3. WHAT HAPPENS on violation (commit blocked / merge blocked / deploy blocked)

A rules file with no ## Enforcement section is INCOMPLETE and must be rejected.
```

---

## Enforcement of This Very Rule

| Mechanism | What it checks | Blocks what |
|---|---|---|
| `.claude/hooks/pre-commit-security.sh` Check 8 | Every `.claude/rules/*.md` file that lacks an `## Enforcement` section | Commit blocked |
| `security-auditor` agent checklist item | On every PR, auditor verifies all touched rules files have enforcement sections | PR comment flagged CRITICAL |
| Claude Code (AI session rule) | Claude must refuse to write a new rules file without an `## Enforcement` section | Rejected in-session before file is written |

---

## Enforcement Map — All Rules Files

This table is the ground truth. Every row must have all three columns filled.
An empty "Enforced By" cell means the rule file is non-compliant with this constitution.

| Rules File | What It Governs | Enforced By |
|---|---|---|
| `cts.md` | IET safety, vault miss routing, NGCH filing, thresholds | pre-commit Check 3 (hardcoded thresholds), Semgrep `astra-vault-miss-must-review`, Semgrep `astra-no-hardcoded-threshold`, cts-workflow-reviewer agent |
| `isolation.md` | CTS↔EJ blast isolation | pre-commit Check 6 (cross-module imports), pre-commit Check 7 (wrong Redis ref), Semgrep `astra-no-cross-module-import`, CI checkov (namespace policy) |
| `temporal.md` | Workflow patterns, retry constants, IET watchdog | cts-workflow-reviewer agent, Semgrep custom rules (asyncio.sleep in workflows), CI SAST |
| `ai-inference.md` | vLLM queue routing, SHAP, Langfuse wrapping | Semgrep (vLLM calls without explicit queue), security-auditor agent SHAP check |
| `microservices.md` | Service identity, health endpoints, logging | CI lint (missing /health endpoints fail smoke test), no-print Semgrep rule |
| `api-versioning.md` | Breaking changes, deprecation headers, sunset | pre-commit Check 5 (removed endpoint refs), CI `api-compat` stage |
| `cicd.md` | Pipeline stages, Dockerfile standards, secrets in images | CI self-referential (pipeline itself enforces), Trivy image scan |
| `diagnostic-mcp.md` | Consent model, non-PII signals only, audit trail | OPA policy `astra/diagnostic` (runtime), security-auditor agent |
| `pii-data-protection.md` | Hashing, encryption, masking of PII | Semgrep `astra-no-select-star-pii`, pre-commit Check 4, security-auditor agent PII checklist |
| `secrets-vault.md` | All secrets via Vault, no env var secrets | gitleaks (pre-commit + CI), Semgrep `astra-no-direct-env-secrets`, pre-commit Check 1+2 |
| `security-scanning.md` | Scan ownership, CI gates, severity levels | CI pipeline itself (all stages `allow_failure: false`), release gate sign-off |
| `security.md` | General security baseline | All of the above (this file is the baseline, others are specifics) |
| `database.md` | Query patterns, connection pools, migrations | Semgrep `astra-no-select-star-pii`, Alembic migration CI check |
| `api.md` | Router structure, auth, rate limits, OTel | CI integration tests (auth failure = test fail), OpenAPI schema lint |
| `ej.md` | EJ immutability, edge agent, LLM parsing | ej-parser-specialist agent, CI contract tests for MCP server |

---

## What Counts as Enforcement

Ranked from strongest to weakest. Use the strongest available:

```
1. BLOCKS COMMIT   — pre-commit hook exits non-zero. Developer cannot commit without fixing.
2. BLOCKS MERGE    — CI stage fails. PR cannot be merged without fixing.
3. BLOCKS RELEASE  — Release gate fails. Chart cannot be published without sign-off.
4. BLOCKS AT RUNTIME — OPA policy denies the request. System enforces even if code is wrong.
5. AGENT REVIEW    — security-auditor or cts-workflow-reviewer flags in PR. Human must dismiss CRITICAL.
```

"Documentation only" is NOT enforcement. If a rule can only be caught by a human reading code
in review, it is a guideline, not a rule. Rename the file section to `## Guideline` if that is
what it actually is.

---

## Adding a New Rule — Mandatory Checklist

Before writing any new rule in any `.claude/rules/` file:

```
[ ] Is there an existing enforcement mechanism that catches violations?
      If YES → reference it in ## Enforcement
      If NO  → create the enforcement (Semgrep rule / hook check / CI stage) FIRST
               then write the rule

[ ] Does the enforcement block commit, merge, or release?
      "Only visible in PR review" is insufficient for CRITICAL rules.

[ ] Is the enforcement tested?
      Add a test case to .claude/hooks/test-enforcement.sh that intentionally
      violates the rule and verifies the enforcement catches it.

[ ] Is the enforcement listed in this file's Enforcement Map?
      Update the table above.
```

---

## AI Session Enforcement (This Session — Claude Code)

Because Claude Code writes code and rules in every session, the AI itself is an enforcement layer:

```
Claude MUST:
  - Refuse to write a new .claude/rules/*.md file without an ## Enforcement section
  - Refuse to write code that violates any rule even if not asked to check
  - Add ## Enforcement section to any rules file it edits that lacks one
  - Run /security-check mentally before proposing any code touching auth/, vault/, audit/
  - Never write os.environ.get() — always config_service
  - Never write SELECT * on PII tables — even in examples (use explicit columns)
  - Never write a hardcoded threshold — even in comments (write config_service.get("...") instead)

Claude MUST NOT wait to be asked. If Claude sees a violation while working on
something else, it flags it immediately as a separate finding.
```

---

## Enforcement Test Suite

```bash
# .claude/hooks/test-enforcement.sh
# Run this to verify all enforcement mechanisms are working.
# All tests must pass before any release.

# Test 1: gitleaks catches hardcoded password
echo 'DB_PASSWORD = "P@ssw0rd123"' > /tmp/test_secret.py
gitleaks detect --source /tmp/test_secret.py --no-banner --exit-code 1
assert_exit_code 1 "gitleaks must catch hardcoded password"

# Test 2: pre-commit catches cross-module import
echo 'from modules.cts import cheque_workflow' > modules/ej/test_violation.py
run_pre_commit_hook
assert_exit_code 1 "pre-commit must catch cross-module import"
rm modules/ej/test_violation.py

# Test 3: Semgrep catches SELECT *
echo 'cur.execute("SELECT * FROM cheque_instruments WHERE bank_id = $1")' > /tmp/test_pii.py
semgrep --config=infra/ci-checks/semgrep-astra.yaml /tmp/test_pii.py
assert_exit_code 1 "Semgrep must catch SELECT * on PII table"

# Test 4: Semgrep catches hardcoded threshold
echo 'if fraud_score > 0.72:' > /tmp/test_threshold.py
semgrep --config=infra/ci-checks/semgrep-astra.yaml /tmp/test_threshold.py
assert_exit_code 1 "Semgrep must catch hardcoded threshold"

# Test 5: Rules file without Enforcement section fails pre-commit
echo '# My Rule\nDo this thing.' > .claude/rules/test_no_enforcement.md
run_pre_commit_hook
assert_exit_code 1 "pre-commit must catch rules file without ## Enforcement section"
rm .claude/rules/test_no_enforcement.md

echo "All enforcement tests passed."
```
