---
name: new-microservice
description: Scaffold a new ASTRA microservice end-to-end. Covers FastAPI app skeleton, health checks, OTel setup, Dockerfile, Helm deployment, Kafka wiring, and CI pipeline registration.
---

# Skill: Create a New Microservice

## When to Use
User says: "create a new service", "add a microservice for {X}", "scaffold {service-name}".

---

## Step 1 — Classify the Service

Answer before writing any code:

| Question | Determines |
|---|---|
| CTS, EJ, or Platform (shared)? | Which namespace, which Kafka topics, which Redis cluster |
| Does it consume Kafka? | Whether KEDA ScaledObject is needed |
| Does it serve HTTP? | Whether FastAPI app + Ingress needed, or Temporal worker only |
| Does it call AI models? | Which vLLM queues, Langfuse setup needed |
| Does it write to DB? | Which pgbouncer pool, which YugabyteDB schema |

Services live in:
- `apps/api/routers/{name}.py` if it's a new **router** on the existing API gateway
- `modules/cts/` or `modules/ej/` if it's a new **domain service** (new Temporal worker or processor)
- `shared/` if it's a **platform service** (audit, notifications, config)

---

## Step 2 — FastAPI Service Skeleton

```
apps/{service-name}/
├── main.py              ← FastAPI app, lifespan, OTel init
├── routers/
│   └── {domain}.py      ← Route handlers (no business logic here)
├── services/
│   └── {domain}.py      ← Business logic, Temporal triggers
├── models/
│   ├── requests.py      ← Pydantic request models
│   └── responses.py     ← Pydantic response models
├── dependencies.py      ← FastAPI deps: auth, RBAC, DB session
├── Dockerfile
└── requirements.txt
```

```python
# main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from shared.observability.otel_setup import configure_otel
from shared.config.config_service import config_service
import structlog

log = structlog.get_logger()
SERVICE_NAME = "{service-name}"   # replace with actual name

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    configure_otel(service_name=SERVICE_NAME,
                   service_version=config_service.get("platform.version"))
    log.info("service.started", service=SERVICE_NAME)
    yield
    # Shutdown
    log.info("service.stopped", service=SERVICE_NAME)

app = FastAPI(
    title=f"ASTRA {SERVICE_NAME}",
    version=config_service.get("platform.version"),
    lifespan=lifespan,
    docs_url="/docs" if config_service.get("env") == "development" else None,
    redoc_url=None,
)

# Routers
from routers import {domain}
app.include_router({domain}.router_v1)

# Health (no auth — Kubernetes probes)
from routers import health
app.include_router(health.router)
```

```python
# routers/health.py — copy this exactly for every service
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()

@router.get("/health/live", include_in_schema=False)
async def liveness():
    return {"status": "ok"}

@router.get("/health/ready", include_in_schema=False)
async def readiness():
    # Add checks relevant to this service
    checks = {}
    all_ok = all(checks.values()) if checks else True
    return JSONResponse(
        {"status": "ready" if all_ok else "degraded", "checks": checks},
        status_code=200 if all_ok else 503,
    )

@router.get("/metrics", include_in_schema=False)
async def metrics():
    import prometheus_client
    return prometheus_client.generate_latest()
```

---

## Step 3 — Kafka Consumer (if service consumes events)

```python
# shared/event_bus/consumer.py pattern
from shared.event_bus.consumer import AstraConsumer
from shared.config.config_service import config_service

consumer = AstraConsumer(
    topics=[f"cts.inward.{bank_id}"],           # only own module's topics
    group_id=f"cg-cts-{SERVICE_NAME}-{bank_id}", # naming: cg-{module}-{service}-{bank_id}
    bootstrap_servers=config_service.get("kafka.bootstrap_servers"),
)

# KEDA ScaledObject triggers scale-up when lag > 10
# Defined in infra/helm/cerebrum/templates/keda-{service}.yaml
```

---

## Step 4 — Dockerfile (copy standard, change CMD only)

Use the standard Python multi-stage Dockerfile from `rules/cicd.md`.
Change only:
- `HEALTHCHECK` port if not 8000
- `CMD` to point to this service's `main:app`
- `COPY` paths for this service's code

---

## Step 5 — Helm Deployment Resources

Create `infra/helm/cerebrum/templates/{service-name}.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "cerebrum.fullname" . }}-{service-name}
  namespace: astra-{module}-{{ .Values.bank.id }}   # correct module namespace
spec:
  replicas: {{ .Values.sizing.{service_name}.min_replicas }}
  selector:
    matchLabels:
      app: {service-name}
      bank: {{ .Values.bank.id }}
  template:
    spec:
      serviceAccountName: astra-{service-name}    # dedicated SA — least privilege
      containers:
        - name: {service-name}
          image: {{ .Values.global.registry }}/astra/{service-name}:{{ .Chart.AppVersion }}
          ports:
            - containerPort: 8000
          env:
            - name: BANK_ID
              value: {{ .Values.bank.id }}
            - name: MODULE
              value: {module}
            # No secrets in env — all via Vault sidecar
          envFrom:
            - secretRef:
                name: astra-vault-{service-name}   # injected by Vault agent sidecar
          livenessProbe:
            httpGet: {path: /health/live, port: 8000}
            initialDelaySeconds: 30
          readinessProbe:
            httpGet: {path: /health/ready, port: 8000}
            initialDelaySeconds: 10
          resources:
            requests:
              cpu: {{ .Values.sizing.{service_name}.cpu_request | default "100m" }}
              memory: {{ .Values.sizing.{service_name}.memory_request | default "256Mi" }}
            limits:
              cpu: {{ .Values.sizing.{service_name}.cpu_limit | default "500m" }}
              memory: {{ .Values.sizing.{service_name}.memory_limit | default "512Mi" }}
```

---

## Step 6 — Register in CI Pipeline

Add to `.gitlab-ci.yml` build-images matrix:
```yaml
- SERVICE: {service-name}
  CONTEXT: apps/{service-name}   # or modules/{module}/{service-name}
```

Add to CLAUDE.md microservices index (Section 14):
```markdown
| `{service-name}` | Python | {one-line purpose} |
```

---

## Step 7 — Checklist Before PR

```
[ ] SERVICE_NAME constant matches Kubernetes Deployment name
[ ] /health/live and /health/ready endpoints present and returning correct status codes
[ ] /metrics endpoint present (Prometheus scrape)
[ ] OTel configured in lifespan startup
[ ] structlog used — no print() anywhere
[ ] All config from config_service — no os.environ.get() in service code
[ ] Kafka consumer group follows cg-{module}-{service}-{bank_id} naming
[ ] Kafka topics only from own module (no cross-module topic subscription)
[ ] Dockerfile is multi-stage, runs as non-root user
[ ] Helm Deployment in correct namespace (astra-cts-* or astra-ej-*)
[ ] Helm ResourceQuota updated if this service needs significant CPU/memory
[ ] Service added to CI build matrix
[ ] Service added to CLAUDE.md microservices index
[ ] Health check endpoints tested: liveness returns 200, readiness returns 503 when deps down
```
