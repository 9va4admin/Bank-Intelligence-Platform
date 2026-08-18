# Module Isolation Rules (CTS — this repo only)

## The Fundamental Principle
CTS is the only module in this repository. The EJ (ATM Electronic Journal) module
lives in a separate repo: `9va4admin/atm-ej-platform`. There is no cross-repo code
sharing at the Python import level — isolation is structural.

## Kubernetes Namespaces
- CTS namespace: `astra-cts-{bank_id}`
- Every Kubernetes resource (Deployment, Service, HPA, ScaledObject) belongs to this namespace
- ResourceQuota and LimitRange defined per namespace — no sharing
- Istio AuthorizationPolicy controls intra-CTS service access

## Kafka
- CTS topics: `cts.*` only — CTS workers never subscribe to `ej.*` or any other module's topics
- Separate KEDA ScaledObject per CTS service — scaling events are independent
- Consumer group naming: `cg-cts-{service}-{bank_id}`

## Redis
- `redis-cts` cluster: Signature Vault, PPS Vault, CTS session cache
- Connection string from config_service: `redis.cts.url`

## Database Connection Pools
- pgbouncer-cts: max connections defined in CTS Helm values
- Application code connects to: `config_service.get("db.cts.dsn")`
- Schema: all CTS tables under `cts` schema

## AI Inference Queues
- CTS exclusive queues: `cts-vision` (Qwen2-VL), `cts-ocr` (GOT-OCR2)
- Queue name passed explicitly in every vLLM request — never use default queue
- Separate vLLM worker processes per queue

## Temporal Task Queues
- CTS workers poll: `cts-processing-{bank_id}` only
- Worker Deployments are dedicated to CTS

## Python Module Boundaries
- `from modules.ej import *` is FORBIDDEN in any file in this repo — EJ is a separate repo
- Cross-module data exchange (if needed) happens only via Kafka events or shared `analytics-service` (async, read-only)
- Shared utilities: only `shared/` — never copy-paste into a module directory

## Allowed Shared Services
| Service | CTS partition |
|---|---|
| audit-service | Immudb collection: `cts_events` |
| notification-service | Consumer group: `cg-notify-cts` |
| analytics-service | Read-only, async |

## Forbidden Patterns
- Any Python import from `modules.ej` or `apps.ej_ingestion` — those live in `atm-ej-platform`
- KEDA ScaledObject that watches `ej.*` Kafka topics
- Single vLLM worker serving EJ queues from this repo's workers
