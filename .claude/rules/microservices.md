# Microservice Rules (FastAPI · Health Checks · API Versioning · Service Mesh)

## Service Identity — Every Service Must Have
```python
# apps/api/main.py (and every service's entrypoint)
from fastapi import FastAPI
from shared.observability.otel_setup import configure_otel
from shared.config.config_service import config_service

SERVICE_NAME = "cts-agent-worker"   # must match Kubernetes Deployment name exactly
SERVICE_VERSION = config_service.get("platform.version")  # from Helm chart

app = FastAPI(
    title=f"ASTRA {SERVICE_NAME}",
    version=SERVICE_VERSION,
    docs_url="/docs" if config_service.get("env") == "development" else None,
    redoc_url=None,
)

configure_otel(service_name=SERVICE_NAME, service_version=SERVICE_VERSION)
```

## API Versioning Strategy
All public API routes are versioned. Internal service-to-service routes are not versioned (Istio handles compatibility).

```python
# URL versioning — prefix all public routes with /v{n}
# apps/api/routers/cts.py
from fastapi import APIRouter

router_v1 = APIRouter(prefix="/v1/cts", tags=["CTS v1"])

@router_v1.post("/inward/{instrument_id}/submit")
async def submit_inward_cheque(...): ...

# When introducing breaking changes → new router:
router_v2 = APIRouter(prefix="/v2/cts", tags=["CTS v2"])
# v1 stays alive for minimum 2 ASTRA releases (deprecation window)
```

```python
# Deprecation headers on v1 routes (when v2 exists):
from fastapi import Response

@router_v1.post("/inward/{instrument_id}/submit")
async def submit_inward_cheque_v1(..., response: Response):
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "2027-01-01"   # removal date
    response.headers["Link"] = '</v2/cts/inward/{instrument_id}/submit>; rel="successor-version"'
    # ... same logic as v2
```

## Health Check Endpoints (Kubernetes Probes)
Every service must expose these exact paths — no auth required:

```python
from fastapi import APIRouter
router = APIRouter()

@router.get("/health/live", include_in_schema=False)
async def liveness():
    # Returns 200 if process is alive (not deadlocked)
    # Never check external dependencies here — only internal state
    return {"status": "ok", "service": SERVICE_NAME}

@router.get("/health/ready", include_in_schema=False)
async def readiness():
    # Returns 200 only when ready to serve traffic
    # Check: DB connection, Redis connection, Vault reachable, Kafka producer ready
    checks = {
        "db": await check_yugabyte_connection(),
        "redis": await check_redis_connection(),
        "vault": await check_vault_token(),
        "kafka": await check_kafka_producer(),
    }
    all_healthy = all(checks.values())
    status_code = 200 if all_healthy else 503
    return JSONResponse({"status": "ready" if all_healthy else "degraded", "checks": checks},
                        status_code=status_code)

@router.get("/metrics", include_in_schema=False)
async def metrics():
    # Prometheus scrape endpoint — served by opentelemetry-prometheus exporter
    # Do not hand-write this — OTel handles it
    return prometheus_client.generate_latest()
```

## Kubernetes Probe Configuration (in Helm templates)
```yaml
livenessProbe:
  httpGet:
    path: /health/live
    port: 8000
  initialDelaySeconds: 30
  periodSeconds: 10
  failureThreshold: 3

readinessProbe:
  httpGet:
    path: /health/ready
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 5
  failureThreshold: 3

startupProbe:
  httpGet:
    path: /health/live
    port: 8000
  failureThreshold: 30    # allow 5 minutes for slow startup (model loading)
  periodSeconds: 10
```

## Service-to-Service Communication
- All internal calls via Kubernetes Service DNS: `http://{service-name}.{namespace}.svc.cluster.local`
- Istio handles mTLS automatically — no TLS code in service clients
- Service URLs from config_service — never hardcoded
- Timeouts always set — no default (default = infinite = bad)

```python
# Correct internal client
import httpx

async def call_fraud_service(input: FraudInput, bank_id: str) -> FraudResult:
    url = config_service.get(f"services.fraud_scoring.url")  # from config, not hardcoded
    async with httpx.AsyncClient(timeout=10.0) as client:  # always explicit timeout
        response = await client.post(f"{url}/v1/score", json=input.model_dump())
        response.raise_for_status()
        return FraudResult.model_validate(response.json())
```

## Request / Response Standards
```python
# Every response is a typed Pydantic model — no bare dict returns
class ChequeSubmitResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    instrument_id: str
    workflow_id: str
    status: Literal["ACCEPTED", "REJECTED"]
    estimated_decision_ms: int
    request_id: str   # = OTel trace ID

# Every error response follows this structure:
class ErrorResponse(BaseModel):
    error_code: str     # e.g. "CTS_VAULT_MISS", "EJ_OEM_UNKNOWN"
    message: str        # human-readable, safe to show in UI
    request_id: str     # OTel trace ID for log correlation
    # Never include: stack traces, internal paths, SQL errors
```

## Logging Standards (structlog — never print())
```python
import structlog
log = structlog.get_logger()

# Correct
log.info("cheque.submitted",
         bank_id=bank_id,
         instrument_id=instrument_id,
         amount_range="₹1L-₹5L",    # range, not exact amount
         account_suffix="****4521")  # masked

# Forbidden
print(f"Processing cheque {account_number} for ₹{amount}")  # raw PII + print()
log.info(f"Amount: {amount}")   # f-string logging loses structure
```

## Ingress and Load Balancing
- External traffic enters via: **Istio Ingress Gateway** (not nginx) → routes to `api-gateway` service
- `api-gateway` is the single public entry point — all other services are cluster-internal only
- Load balancing across pods: handled by Kubernetes Service (round-robin by default)
- Istio handles: mTLS termination, rate limiting, circuit breaking, canary traffic splits
- No nginx deployed — Istio Ingress Gateway serves this role for ASTRA

```yaml
# infra/k8s/istio-ingress.yaml pattern
apiVersion: networking.istio.io/v1alpha3
kind: VirtualService
metadata:
  name: astra-api-gateway
spec:
  hosts: ["api.astra.{bank_id}.internal"]
  gateways: ["astra-gateway"]
  http:
    - match: [{uri: {prefix: "/v1/"}}]
      route:
        - destination:
            host: api-gateway
            port: {number: 8000}
      timeout: 30s
      retries:
        attempts: 2
        retryOn: "gateway-error,connect-failure"
```

## Forbidden Patterns
- Returning `dict` from any API endpoint — always use typed Pydantic model
- Hardcoding service URLs — always config_service
- Missing health check endpoints — Kubernetes cannot manage the pod lifecycle
- Exposing `/docs` (Swagger UI) in production — information disclosure
- Direct pod-to-pod communication bypassing Istio service mesh
- Using nginx separately — Istio Ingress Gateway is the standard
