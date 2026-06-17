# Module Isolation Rules (CTS ↔ EJ)

## The Fundamental Principle
CTS load must never degrade EJ. EJ failure must never affect CTS.
Enforced by hard boundaries — not by convention.

## Kubernetes Namespaces
- CTS namespace: `astra-cts-{bank_id}`
- EJ namespace:  `astra-ej-{bank_id}`
- Every Kubernetes resource (Deployment, Service, HPA, ScaledObject) belongs to exactly one namespace
- ResourceQuota and LimitRange defined per namespace — never shared
- Istio AuthorizationPolicy blocks direct CTS→EJ and EJ→CTS pod communication

## Kafka
- CTS topics: `cts.*` only — CTS workers never subscribe to `ej.*`
- EJ topics: `ej.*` only — EJ workers never subscribe to `cts.*`
- Separate KEDA ScaledObject per module — scaling events are independent
- Consumer group naming: `cg-cts-{service}-{bank_id}` and `cg-ej-{service}-{bank_id}`

## Redis
- `redis-cts` cluster: Signature Vault, PPS Vault, CTS session cache
- `redis-ej` cluster: EJ canonical cache, ATM health signals, dispute embeddings
- No shared cluster — eviction pressure in one cannot affect the other
- Connection strings come from config_service keyed by module: `redis.cts.url` and `redis.ej.url`

## Database Connection Pools
- pgbouncer-cts: max connections defined in CTS Helm values
- pgbouncer-ej: max connections defined in EJ Helm values
- Application code connects to: `config_service.get("db.cts.dsn")` or `config_service.get("db.ej.dsn")`
- Schema separation: all CTS tables under `cts` schema, all EJ tables under `ej` schema

## AI Inference Queues
- CTS exclusive queues: `cts-vision` (Qwen2-VL), `cts-ocr` (GOT-OCR2)
- EJ exclusive queues: `ej-reasoning` (Llama 3.3 70B), `ej-embeddings` (BGE-M3)
- Queue name passed explicitly in every vLLM request — never use default queue
- Separate vLLM worker processes per queue — GPU contention is impossible

## Temporal Task Queues
- CTS workers poll: `cts-processing-{bank_id}` only
- EJ workers poll: `ej-normalisation-{bank_id}`, `ej-dispute-{bank_id}` only
- Worker Deployments are separate — one cannot accidentally pick up the other's tasks

## Python Module Boundaries
- `from modules.cts import *` is FORBIDDEN in any file under `modules/ej/`
- `from modules.ej import *` is FORBIDDEN in any file under `modules/cts/`
- Cross-module data exchange happens only via Kafka events or shared `analytics-service` (async, read-only)
- Shared utilities: only `shared/` — never copy-paste into a module directory

## Allowed Shared Services
These services are shared but have per-module rate limits and separate logical partitions:

| Service | CTS partition | EJ partition |
|---|---|---|
| audit-service | Immudb collection: `cts_events` | Immudb collection: `ej_events` |
| notification-service | Consumer group: `cg-notify-cts` | Consumer group: `cg-notify-ej` |
| analytics-service | Read-only, async | Read-only, async |

## Forbidden Patterns
- Shared Redis cluster between CTS and EJ
- Shared pgbouncer pool between CTS and EJ
- Any Python import across module boundaries
- KEDA ScaledObject that watches both `cts.*` and `ej.*` Kafka topics
- Single vLLM worker serving both CTS and EJ queues

---

## Enforcement

| Rule | Enforced By | Blocks |
|---|---|---|
| No cross-module Python imports | pre-commit Check 6 + Semgrep `astra-no-cross-module-import` | Commit blocked |
| CTS code never references redis-ej | pre-commit Check 7 | Commit blocked |
| EJ code never references redis-cts | pre-commit Check 7 | Commit blocked |
| Separate K8s namespaces | checkov `CKV_K8S_*` — verifies ResourceQuota exists per namespace | PR merge (CI checkov stage) |
| Separate KEDA ScaledObjects | Helm chart lint — ScaledObject must declare namespace explicitly | PR merge (CI lint stage) |
| Separate Temporal task queues | `cts-workflow-reviewer` agent — verifies worker polls only own queue | PR merge |
