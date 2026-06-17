# CI/CD Pipeline Rules (GitLab CI · Docker · Helm · OCI Registry)

## Pipeline Stages (Order — Never Reorder)
```
lint → test → security-scan → build-image → build-chart → publish → deploy-staging → smoke-test
```
Every stage must pass before the next begins. No parallel shortcuts across stages.

## GitLab CI Pipeline Structure
```yaml
# .gitlab-ci.yml at repo root
stages:
  - lint
  - test
  - security-scan
  - build-image
  - build-chart
  - publish
  - deploy-staging
  - smoke-test

variables:
  REGISTRY: registry.astra.internal
  CHART_REGISTRY: oci://registry.astra.internal/charts
  PYTHON_VERSION: "3.12"
  GO_VERSION: "1.22"
```

## Stage: lint
```yaml
lint-python:
  stage: lint
  script:
    - ruff check modules/ shared/ apps/api/ apps/ai-server/ --select E,F,W,I
    - ruff format --check modules/ shared/ apps/
  rules:
    - changes: ["**/*.py"]

lint-go:
  stage: lint
  script:
    - golangci-lint run ./edge/...
  rules:
    - changes: ["edge/**/*.go"]

lint-helm:
  stage: lint
  script:
    - helm lint infra/helm/cerebrum/
    - helm template astra-test infra/helm/cerebrum/ -f infra/helm/values/_defaults.yaml
        -f infra/helm/values/bank-template.yaml | kubeval --strict
```

## Stage: test
```yaml
test-python:
  stage: test
  script:
    - pytest modules/ shared/ apps/ --cov=. --cov-report=xml
        --cov-fail-under=80                      # overall minimum
        -k "not integration"                     # unit tests only in CI
  coverage: '/TOTAL.*\s+(\d+%)$/'
  artifacts:
    reports:
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml

test-cts-critical:
  stage: test
  script:
    # CTS workflow activities need 95% — separate check
    - pytest modules/cts/workflows/activities/ --cov=modules/cts/workflows/activities/
        --cov-fail-under=95
  rules:
    - changes: ["modules/cts/**"]
```

## Stage: api-compatibility
```yaml
api-compatibility:
  stage: security-scan   # runs in parallel with other security checks
  script:
    - chmod +x infra/ci-checks/check-api-compatibility.sh
    - BASE_BRANCH=$CI_MERGE_REQUEST_TARGET_BRANCH_NAME
        bash infra/ci-checks/check-api-compatibility.sh
  rules:
    - changes:
        - "apps/api/**"
        - "docs/api/**"
        - "apps/*/routers/**"
  allow_failure: false   # breaking API changes block merge — no exceptions
  artifacts:
    when: always
    paths:
      - docs/api/openapi-current.json   # saved for next run's diff comparison
```

## Stage: security-scan
```yaml
gitleaks:
  stage: security-scan
  script:
    - gitleaks detect --source . --no-banner
  allow_failure: false    # never skip — secrets in git = release blocked

trivy-image-scan:
  stage: security-scan
  script:
    # Scan base images for CVEs — block on CRITICAL
    - trivy image --exit-code 1 --severity CRITICAL python:3.12-slim
  needs: []

opa-policy-lint:
  stage: security-scan
  script:
    - opa check infra/opa/policies/ --strict
    - opa test infra/opa/policies/ -v
  rules:
    - changes: ["infra/opa/policies/**"]
```

## Stage: build-image (Docker)
```yaml
# Build all service images
build-images:
  stage: build-image
  parallel:
    matrix:
      - SERVICE: api-gateway
        CONTEXT: apps/api
      - SERVICE: cts-agent-worker
        CONTEXT: modules/cts
      - SERVICE: ej-normalisation-worker
        CONTEXT: modules/ej
      - SERVICE: ai-inference-server
        CONTEXT: apps/ai-server
      - SERVICE: branch-ej-agent    # Go binary
        CONTEXT: edge/ej-agent
  script:
    - docker build
        --build-arg VERSION=${CI_COMMIT_TAG:-dev}
        --build-arg GIT_SHA=${CI_COMMIT_SHA}
        --cache-from ${REGISTRY}/astra/${SERVICE}:cache
        --tag ${REGISTRY}/astra/${SERVICE}:${CI_COMMIT_SHA}
        --tag ${REGISTRY}/astra/${SERVICE}:${CI_COMMIT_TAG:-dev}
        ${CONTEXT}
    - docker push ${REGISTRY}/astra/${SERVICE}:${CI_COMMIT_SHA}
  only:
    - main
    - tags
```

## Dockerfile Standards (All Services)
```dockerfile
# Python services — multi-stage to keep image small
FROM python:3.12-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim AS runtime
# Never run as root
RUN groupadd -r astra && useradd -r -g astra astra

WORKDIR /app
COPY --from=builder /install /usr/local
COPY . .

# Build args for traceability
ARG VERSION=dev
ARG GIT_SHA=unknown
ENV ASTRA_VERSION=${VERSION} GIT_SHA=${GIT_SHA}

# Health check baked into image
HEALTHCHECK --interval=10s --timeout=5s --start-period=60s \
  CMD curl -f http://localhost:8000/health/live || exit 1

USER astra
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

```dockerfile
# Go edge agent — truly minimal (scratch base)
FROM golang:1.22-alpine AS builder
WORKDIR /build
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-w -s" -o ej-agent ./edge/ej-agent/

FROM scratch AS runtime
COPY --from=builder /build/ej-agent /ej-agent
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
USER 1000:1000
ENTRYPOINT ["/ej-agent"]
```

## Stage: build-chart + publish
```yaml
build-and-publish-chart:
  stage: publish
  script:
    # Bump chart version from git tag
    - yq e ".version = \"${CI_COMMIT_TAG}\"" -i infra/helm/cerebrum/Chart.yaml
    - yq e ".appVersion = \"${CI_COMMIT_TAG}\"" -i infra/helm/cerebrum/Chart.yaml

    # Package and push to OCI registry
    - helm package infra/helm/cerebrum/ --destination ./dist/
    - helm push ./dist/cerebrum-${CI_COMMIT_TAG}.tgz ${CHART_REGISTRY}

    # Verify chart is pullable
    - helm pull ${CHART_REGISTRY}/cerebrum --version ${CI_COMMIT_TAG}
  only:
    - tags   # only on version tags (v1.x.y)
  environment:
    name: chart-registry
```

## Stage: deploy-staging + smoke-test
```yaml
deploy-staging:
  stage: deploy-staging
  script:
    # ASTRA's own staging environment (not a bank — internal test bank)
    - helm upgrade --install astra-staging ${CHART_REGISTRY}/cerebrum
        --version ${CI_COMMIT_TAG}
        --namespace astra-staging
        --values infra/helm/values/_defaults.yaml
        --values infra/helm/values/banks/staging-internal.yaml
        --wait --timeout 10m
  environment:
    name: staging
  only:
    - tags

smoke-test:
  stage: smoke-test
  script:
    - pytest tests/smoke/ --base-url=https://api.staging.astra.internal
        -m "smoke"
        --timeout=60
  needs: ["deploy-staging"]
  only:
    - tags
```

## Branch and Tag Conventions
```
main          → runs: lint + test + security-scan (no image build)
feature/*     → runs: lint + test only
claude/*      → runs: lint + test only (AI-assisted dev branches)
v1.x.y        → runs: full pipeline including image build + chart publish
hotfix/*      → runs: full pipeline, deploys to staging for validation
```

## What Is Never Done in CI
- No `kubectl apply` to any bank's production cluster — banks control their own ArgoCD
- No pushing to `main` without passing all stages
- No skipping gitleaks — CRITICAL finding blocks release always
- No manual steps in the pipeline — fully automated gate
- No cloud services called from CI runner — air-gapped pipeline
