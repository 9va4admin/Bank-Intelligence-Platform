# Secrets and Vault Rules (Zero Secrets in Code — Ever)

## The Absolute Rule
```
No password, token, key, or credential of any kind may exist in:
  - Source code (any language)
  - Git history (including deleted files — gitleaks scans entire history)
  - Environment variables set by application code
  - Kubernetes ConfigMaps (only Secrets, and only via Vault injection)
  - Docker images (no COPY of .env files)
  - Log files (Vault tokens are never logged)
  - API responses
  - CLAUDE.md, rules files, or any documentation

One and only one source: HashiCorp Vault — accessed via config_service.
```

---

## How Every Secret Is Fetched

```python
# shared/config/config_service.py is the ONLY gateway to secrets
# Application code NEVER calls Vault directly

# CORRECT — all secrets via config_service
from shared.config.config_service import config_service

db_password   = config_service.get_secret("db.cts.password")
redis_token   = config_service.get_secret("redis.cts.auth_token")
ngch_api_key  = config_service.get_secret("ngch.api_key")
cbs_password  = config_service.get_secret(f"cbs.{cbs_type}.password")

# FORBIDDEN — in any file, any language
DB_PASSWORD = "P@ssw0rd123"                      # hardcoded
db_pass = os.environ.get("DB_PASSWORD")          # direct env var
db_pass = os.environ.get("DB_PASSWORD", "admin") # env var with default
```

---

## Vault Secret Path Conventions

```
secret/astra/{bank_id}/db/cts/password
secret/astra/{bank_id}/redis/cts/auth_token
secret/astra/{bank_id}/ngch/api_key
secret/astra/{bank_id}/ngch/sftp_private_key
secret/astra/{bank_id}/cbs/finacle/password        (or bancs, flexcube)
secret/astra/{bank_id}/whatsapp/business_api_key
secret/astra/{bank_id}/hsm/operator_pin
secret/astra/{bank_id}/pii_hash_pepper             (HMAC pepper for account hashing)
secret/astra/{bank_id}/minio/access_key
secret/astra/{bank_id}/minio/secret_key
secret/astra/{bank_id}/immudb/admin_password
secret/astra/{bank_id}/temporal/tls/client_cert
secret/astra/{bank_id}/temporal/tls/client_key
```

All secrets rotated automatically every 24 hours via Vault dynamic secrets. Application reads fresh value from config_service on each rotation (30s cache TTL ensures pickup).

---

## Vault Agent Sidecar (How VAULT_TOKEN Reaches the Pod)

VAULT_ADDR and VAULT_TOKEN are the only env vars config_service reads directly — injected by Vault agent sidecar at pod startup. Application code never handles Vault authentication itself.

---

## Forbidden Patterns (gitleaks blocks these automatically)
```python
DB_URL = "postgresql://admin:P@ssw0rd@yugabyte:5432/astra"   # BLOCKED
REDIS_URL = "redis://:secretpassword@redis-cts:6379"          # BLOCKED
API_KEY = "sk-abc123xyz..."                                    # BLOCKED
os.environ.get("NGCH_KEY", "fallback_key")                    # BLOCKED (hardcoded default)

# Also forbidden in YAML/config files:
password: "mypassword"        # BLOCKED
token: "abc123"               # BLOCKED
```
