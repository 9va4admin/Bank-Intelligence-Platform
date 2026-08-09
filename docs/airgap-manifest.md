# ASTRA Air-Gap Deployment Manifest

Provide this document to the bank's IT team when the deployment server has no internet access.
The bank downloads these images on any internet-connected machine, transfers them, and loads them.

---

## Step-by-step for the bank's IT team

### On any machine that HAS internet (takes ~30 min, ~5 GB):

```
# Option A — Use ASTRA's export script (recommended, handles everything):
powershell -ExecutionPolicy Bypass -File scripts\export-bundle.ps1

# Option B — Manual pull and save:
docker pull <each image below>
docker save -o astra-bundle.tar <all images below>
```

### Transfer to the air-gapped server:
Copy `astra-bundle.tar` via USB drive, internal file share, or CD/DVD.

### On the air-gapped bank server:
```
docker load -i astra-bundle.tar
docker compose -f infra/docker-compose.pilot.yml up -d
```

---

## Complete Image List

All images required for ASTRA v1.0.0 pilot.
The bank's IT security team can verify sha256 digests after pulling.

### ASTRA Application Images (built from source by ASTRA team, included in bundle)

| Image | Description |
|---|---|
| `astra/api:1.0.0` | FastAPI backend — CTS processing, auth, admin, observability |
| `astra/cts-worker:1.0.0` | Temporal CTS worker — cheque workflow engine |
| `astra/web:1.0.0` | React frontend served by nginx |

### Infrastructure Images (pulled from Docker Hub)

| Image | Version | Size (approx) | Purpose |
|---|---|---|---|
| `yugabytedb/yugabyte` | `2.20.1.0-b97` | ~1.2 GB | Operational database (PostgreSQL-compatible) |
| `confluentinc/cp-kafka` | `7.6.1` | ~700 MB | Event bus (Kafka KRaft mode, no Zookeeper) |
| `temporalio/auto-setup` | `1.24.2` | ~150 MB | Workflow orchestration engine |
| `temporalio/ui` | `2.26.2` | ~50 MB | Temporal web UI |
| `postgres` | `15-alpine` | ~80 MB | Temporal's internal metadata store |
| `redis` | `7.2-alpine` | ~30 MB | CTS vault + config cache (×2 instances) |
| `minio/minio` | `RELEASE.2024-01-16T16-07-38Z` | ~120 MB | Object store (cheque images, audit files) |
| `codenotary/immudb` | `1.9.5` | ~80 MB | Immutable audit trail |
| `hashicorp/vault` | `1.15` | ~100 MB | Secrets management (dev mode for POC) |
| `nginx` | `1.27-alpine` | ~15 MB | Web server for React frontend |

**Total bundle size: ~2.5 GB compressed tar**

---

## What does NOT need to be installed on the bank's server

| Component | Why not needed |
|---|---|
| Python | Runs inside `astra/api` and `astra/cts-worker` Docker images |
| Node.js | Frontend is pre-built; nginx serves static HTML/CSS/JS |
| pip / npm | All dependencies baked into Docker images at build time |
| Java / JVM | Not used anywhere in ASTRA |
| Any database client | DB accessed by services within Docker network only |

**Only Docker Desktop (or Docker Engine on Linux) needs to be installed on the server.**

---

## Ports the bank's firewall needs to allow (inbound to the server)

| Port | Protocol | Service | Who needs access |
|---|---|---|---|
| 80 | TCP | Web UI (nginx) | Bank operators' browsers |
| 8010 | TCP | ASTRA API | Web UI (same machine), scanner integration |
| 18088 | TCP | Temporal UI | Admin / ops team only |
| 19091 | TCP | MinIO console | Admin only |

All other ports (Redis :16379, Kafka :19092, YugabyteDB :15433, etc.) are **internal Docker network only** — do NOT expose to the bank network.

---

## Minimum server requirements

| Resource | Minimum | Recommended |
|---|---|---|
| CPU | 8 cores | 16 cores |
| RAM | 16 GB | 32 GB |
| Disk | 200 GB SSD | 500 GB SSD |
| OS | Windows Server 2019+ or Ubuntu 22.04+ | Ubuntu 22.04 LTS |
| Docker | Docker Desktop 4.x (Windows) or Docker Engine 24+ (Linux) | Latest stable |

---

## Verifying image integrity after load

After `docker load`, verify images are present:
```
docker images | grep -E "astra|yugabyte|kafka|temporal|redis|minio|immudb|vault|nginx|postgres"
```

To verify a specific image digest matches what ASTRA shipped:
```
docker inspect <image>:<tag> --format='{{.Id}}'
```
Compare with the digest in the ASTRA release notes for that version.
