# Security Scanning Rules — Ownership, Gates, and Tools

## Who Is Responsible, When

```
DEVELOPER (before every commit)
  └─ Tool: gitleaks pre-commit hook (automatic, cannot be skipped)
  └─ Tool: /security-check slash command (manual, before raising PR)
  └─ Responsibility: zero secrets, no cross-module imports, no SELECT * on PII

CI PIPELINE (automatic on every PR — blocks merge)
  └─ gitleaks:   secret detection in all staged files + git history
  └─ Trivy:      CVE scan on Docker base images (CRITICAL = block)
  └─ checkov:    IaC security scan (Helm, K8s manifests)
  └─ OWASP DC:   dependency CVE check (Python packages, Go modules)
  └─ Semgrep:    SAST — SQL injection, hardcoded secrets, unsafe deserialization
  └─ api-compat: deprecated endpoint and breaking change detection (see rules/api-versioning.md)
  └─ OPA lint:   Rego policy correctness and security checks

SECURITY-AUDITOR AGENT (on every PR touching critical paths)
  └─ Invoked by: reviewer or automatically when PR touches auth/, vault/, audit/, ngch/
  └─ Runs:       .claude/agents/security-auditor.md checklist
  └─ Reports:    CRITICAL / HIGH / MEDIUM findings in PR comments
  └─ Authority:  CRITICAL findings block merge (same as CI)

RELEASE GATE (before every chart version is published)
  └─ Full DAST scan on staging environment (OWASP ZAP)
  └─ Penetration test checklist (manual, per major release)
  └─ RBI IT Framework control mapping verification (compliance/rbi-it-framework/)
  └─ Sign-off required: security_lead + compliance_officer

BANK DEPLOYMENT (after every upgrade)
  └─ Post-upgrade smoke test suite includes 3 security assertions:
       - Vault connectivity verified
       - mTLS between all pods verified (Istio check)
       - Audit trail write verified (Immudb write + read-back)
```

---

## CI Security Scan Configuration

```yaml
# .gitlab-ci.yml — security stages run in parallel

gitleaks:
  stage: security-scan
  script: gitleaks detect --source . --no-banner --exit-code 1
  allow_failure: false   # CRITICAL — blocks merge on any finding

trivy-images:
  stage: security-scan
  script:
    - trivy image --exit-code 1 --severity CRITICAL
        --scanners vuln,secret
        python:3.12-slim golang:1.22-alpine
  allow_failure: false

semgrep-sast:
  stage: security-scan
  script:
    - semgrep --config=p/python --config=p/flask --config=p/sql-injection
        --config=p/secrets --error
        modules/ shared/ apps/
  allow_failure: false

owasp-dependency-check:
  stage: security-scan
  script:
    - dependency-check --project astra --scan . --format JSON
        --failOnCVSS 7    # fail on HIGH and CRITICAL CVEs
        --out reports/
  artifacts:
    paths: [reports/dependency-check-report.json]

checkov-iac:
  stage: security-scan
  script:
    - checkov -d infra/ --framework helm,kubernetes
        --check CKV_K8S_*,CKV_SECRET_*,CKV_HELM_*
        --soft-fail-on MEDIUM   # MEDIUM = warn, HIGH/CRITICAL = block
  allow_failure: false

opa-policy-lint:
  stage: security-scan
  script:
    - opa check infra/opa/policies/ --strict
    - opa test infra/opa/policies/ -v --exit-zero-on-skipped
  rules:
    - changes: ["infra/opa/policies/**"]
```

---

## Semgrep Custom Rules (ASTRA-Specific)

```yaml
# infra/ci-checks/semgrep-astra.yaml
rules:
  - id: astra-no-direct-env-secrets
    pattern: os.environ.get("$KEY", "...")
    message: "Hardcoded default for secret '$KEY'. Use config_service.get_secret() instead."
    severity: ERROR
    languages: [python]

  - id: astra-no-select-star-pii
    pattern: |
      "SELECT * FROM $TABLE ..."
    metavariable-regex:
      metavariable: $TABLE
      regex: "(cheque_instruments|agent_decisions|users|ej_raw_logs)"
    message: "SELECT * on PII table — specify explicit column list."
    severity: ERROR
    languages: [python]

  - id: astra-no-cross-module-import
    pattern: |
      from modules.cts import ...
    paths:
      include: ["modules/ej/**"]
    message: "Cross-module import: EJ must not import from CTS."
    severity: ERROR
    languages: [python]

  - id: astra-no-hardcoded-threshold
    pattern-either:
      - pattern: "... > 0.72"
      - pattern: "... < 0.90"
      - pattern: "... > 500000"
      - pattern: "... == 180"
    message: "Hardcoded threshold — fetch from config_service instead."
    severity: WARNING
    languages: [python]
    paths:
      include: ["modules/**", "shared/**", "apps/**"]

  - id: astra-vault-miss-must-review
    pattern: |
      if not $VAULT_RESULT:
          return AUTO_RETURN
    message: "Vault miss routing to AUTO_RETURN is forbidden. Must route to HUMAN_REVIEW."
    severity: ERROR
    languages: [python]
```

---

## Security Findings Severity — What Blocks What

| Severity | Definition | Blocks commit? | Blocks merge? | Blocks release? |
|---|---|---|---|---|
| CRITICAL | Exploit in production, data breach risk, IET bypass | YES (pre-commit) | YES (CI) | YES |
| HIGH | Privilege escalation, secret exposure, auth bypass | NO | YES (CI) | YES |
| MEDIUM | PII exposure risk, missing audit trail, config issue | NO | NO (warning only) | NO (must document) |
| LOW | Code quality, best practice deviation | NO | NO | NO |

---

## Security Agent Trigger Paths
The `security-auditor` agent is automatically invoked (by convention, in PR review) when:
```
PR touches any of:
  shared/auth/           → authentication and RBAC changes
  shared/audit/          → audit trail changes
  shared/config/         → config_service / Vault integration
  modules/cts/mcp/       → NGCH adapter (external filing)
  infra/opa/policies/    → business policy rules
  apps/api/middleware/   → auth middleware, rate limiting
  infra/helm/cerebrum/   → chart-level platform constraints
```

Run manually for any PR with: `/security-check`

---

## What "Production-Ready" Means for Security

A release cannot be published to the OCI registry unless ALL of the following are green:
```
[ ] gitleaks: zero findings
[ ] Trivy: zero CRITICAL CVEs in base images
[ ] Semgrep: zero ERROR findings from ASTRA custom rules
[ ] OWASP DC: zero CVEs with CVSS >= 7.0 in dependencies
[ ] checkov: zero HIGH/CRITICAL IaC findings
[ ] OPA lint: all policies pass lint and unit tests
[ ] API compatibility: no breaking changes without versioning
[ ] security-auditor agent: no CRITICAL findings on changed files
[ ] DAST (OWASP ZAP): no HIGH findings on staging environment
```

---

## Enforcement

| Rule | Enforced By | Blocks |
|---|---|---|
| gitleaks runs on every commit | `.claude/hooks/pre-commit-security.sh` Check 1 (auto-installed) | Commit blocked |
| All CI security stages `allow_failure: false` | GitLab CI YAML itself — stages defined with allow_failure: false | Merge request blocked |
| CRITICAL CVE in base image blocks merge | Trivy CI stage exits 1 on CRITICAL | PR merge blocked |
| Semgrep ASTRA custom rules run on every PR | CI `semgrep-sast` stage pointing at `infra/ci-checks/semgrep-astra.yaml` | PR merge blocked |
| Security auditor agent reviews critical-path PRs | `.claude/agents/security-auditor.md` auto-invoked (by convention on PR to auth/vault/audit/ngch) | PR merge blocked on CRITICAL |
| Release gate requires security sign-off | Helm chart publish CI job: `needs: [security-sign-off]` | OCI publish blocked |
| Post-upgrade smoke test security assertions | Helm post-upgrade hook: 3 security assertions (Vault, mTLS, Immudb) | Post-upgrade rollback triggered |
