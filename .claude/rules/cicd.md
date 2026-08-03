# CI/CD Pipeline Rules (GitLab CI · Docker · Helm · OCI Registry)

## Pipeline Stages (Order — Never Reorder)
```
lint → test → security-scan → build-image → build-chart → publish → deploy-staging → smoke-test
```
Every stage must pass before the next begins. No parallel shortcuts across stages.

## Stage Responsibilities

**lint:** `ruff check` + `ruff format --check` for Python (modules/, shared/, apps/); `golangci-lint` for Go (edge/); `helm lint` + `kubeval --strict` for Helm templates.

**test:** `pytest --cov-fail-under=80` overall; separate `pytest --cov-fail-under=95` for `modules/cts/workflows/activities/`; Go `go test ./...`. Unit tests only in CI (`-k "not integration"`).

**security-scan (all parallel, all `allow_failure: false`):** gitleaks (secrets), Trivy CRITICAL CVE on base images, Semgrep ASTRA custom rules (`infra/ci-checks/semgrep-astra.yaml`), OWASP dependency check (CVSS ≥ 7 = fail), checkov IaC (HIGH/CRITICAL = block), OPA policy lint + unit tests, api-compatibility check.

**build-image:** Multi-stage Docker for all services, tagged `${CI_COMMIT_SHA}` and `${CI_COMMIT_TAG}`. Services: api-gateway, cts-agent-worker, ej-normalisation-worker, ai-inference-server, branch-ej-agent (Go). Only on `main` and version tags.

**build-chart + publish:** Bump `Chart.yaml` version from git tag. `helm package` + `helm push` to OCI registry. Verify pullable. Only on `v1.x.y` tags.

**deploy-staging + smoke-test:** `helm upgrade --install astra-staging ... --wait --timeout 10m`. Then `pytest tests/smoke/ -m smoke --timeout=60`. Staging = ASTRA's own internal test bank, not a real bank cluster.

## Dockerfile Standards

- **Python services:** multi-stage (`builder` → `runtime`); non-root user `astra:astra`; `HEALTHCHECK` baked in; `ARG VERSION`/`GIT_SHA` for traceability; `CMD uvicorn ... --workers 1`
- **Go edge agent:** `FROM scratch` final stage; `CGO_ENABLED=0 GOOS=linux`; `USER 1000:1000`
- Rules: never run as root · never COPY `.env` files · never embed secrets in any layer

## Branch and Tag Conventions

| Branch | Pipeline |
|---|---|
| `main` | lint + test + security-scan (no image build) |
| `feature/*`, `claude/*` | lint + test only |
| `v1.x.y` | full pipeline: image build + chart publish |
| `hotfix/*` | full pipeline, deploys to staging |

## What Is Never Done in CI
- No `kubectl apply` to any bank's production cluster — banks control their own ArgoCD
- No pushing to `main` without all stages green
- No skipping gitleaks — secrets in git = release blocked
- No manual steps — fully automated gate
- No cloud services called from CI runner — air-gapped pipeline

---

## Enforcement

| Rule | Enforced By | Blocks |
|---|---|---|
| Pipeline stages not reordered | GitLab CI DAG `needs:` dependencies — structurally impossible to reorder | Pipeline fails to parse |
| Multi-stage Dockerfile | Trivy + hadolint | PR merge blocked |
| Non-root user in Docker images | checkov `CKV_DOCKER_*` + hadolint | PR merge blocked |
| No secrets in Docker images | Trivy `--scanners secret` on every image build | PR merge blocked |
| Chart version bumped on every release | CI `build-chart`: fails if Chart.yaml version not incremented vs previous tag | Release blocked |
| Smoke tests run post-deploy | Helm post-upgrade hook mandatory — cannot be disabled in bank values | Deploy blocked |
