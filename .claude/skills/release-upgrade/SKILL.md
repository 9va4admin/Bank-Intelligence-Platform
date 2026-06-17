---
name: release-upgrade
description: Cut a new ASTRA release and manage the upgrade process for a bank. Covers version tagging, Helm chart publishing, migration dry-run, and bank upgrade coordination.
---

# Skill: Cut a Release and Upgrade a Bank

## When to Use
User says: "cut release", "publish new version", "upgrade {bank} to {version}", "what's in this release".

## Part A — Cutting a Release (ASTRA Vendor)

### Step 1 — Pre-Release Checks
```
[ ] All tests passing on main branch (pytest + go test)
[ ] Coverage > 80% overall, > 95% for CTS workflow activities
[ ] No CRITICAL or HIGH findings from /security-check on changed files
[ ] CLAUDE.md updated if any architecture decisions changed
[ ] Migration files present in infra/migrations/ for any schema changes
[ ] Migration tested on staging YugabyteDB (up + down)
[ ] Release notes drafted (see Step 3)
```

### Step 2 — Version the Release
ASTRA uses semantic versioning:
- `MAJOR.MINOR.PATCH`
- MAJOR: breaking change to bank values file schema or API contracts
- MINOR: new feature, new OEM support, new module capability
- PATCH: bug fix, performance improvement, security patch

```bash
# Tag the release
git tag -a v{version} -m "ASTRA v{version}: {one-line summary}"
git push origin v{version}

# GitLab CI automatically:
# 1. Runs full test suite
# 2. Builds Docker images
# 3. Builds Helm chart with Chart.version = {version}
# 4. Pushes chart to OCI registry: oci://registry.astra.internal/charts/cerebrum:{version}
```

### Step 3 — Release Notes Format
```markdown
## ASTRA v{version} — {date}

### Upgrade Impact
- Schema migrations: YES/NO
- Bank values file changes required: YES/NO (list any new REQUIRED fields)
- Downtime required: NO (rolling update) / YES (explain why)
- Rollback supported: YES (always)

### What's New
- [CTS] ...
- [EJ] ...
- [Platform] ...

### Bug Fixes
- ...

### Security
- ...

### Upgrade Instructions
1. Review this release note with your Change Advisory Board
2. Update `astra.chart_version` in your bank values file to `{version}`
3. ArgoCD will show OutOfSync — trigger sync after CAB approval
4. Monitor smoke tests in post-upgrade hook output
5. If any issue: revert chart_version to previous — Alembic downgrade runs automatically
```

## Part B — Upgrading a Specific Bank

### Step 1 — Compatibility Check
Before upgrading, verify:
- Bank's current version: check `astra.chart_version` in their values file
- Skip-version upgrades: supported only if migration chain is unbroken (check `infra/migrations/`)
- If bank is 2+ versions behind: upgrade one version at a time

### Step 2 — Migration Dry Run
```bash
# Run Alembic dry-run against bank's DB (staging replica)
alembic --config infra/migrations/cts/alembic.ini upgrade {version} --sql
alembic --config infra/migrations/ej/alembic.ini upgrade {version} --sql

# Review generated SQL — check for:
# - Table locks on large tables (cheque_instruments, ej_raw_logs)
# - Irreversible operations (DROP COLUMN — should never appear)
# - Long-running index builds (schedule for off-peak)
```

### Step 3 — Upgrade Window
For CTS: upgrade during off-peak (after 4PM, before 10AM next day — outside clearing window)
For EJ: any time (non-critical path)

### Step 4 — Update Bank Values File
```yaml
# In infra/helm/values/banks/{bank_id}.yaml
astra:
  chart_version: "{new_version}"   # ← update this
```
Commit with message: `chore: upgrade {bank_id} to ASTRA v{new_version}`
Raise PR → bank_it_admin approval → merge → ArgoCD syncs

### Step 5 — Post-Upgrade Verification
```
[ ] Post-upgrade smoke test job: all green (check ArgoCD sync status)
[ ] CTS: process one test cheque end-to-end
[ ] EJ: trigger one EJ normalisation workflow
[ ] Vault: VaultSyncWorkflow completes successfully
[ ] Grafana: no new error spikes in dashboards
[ ] Temporal: no stuck workflows from upgrade
```
