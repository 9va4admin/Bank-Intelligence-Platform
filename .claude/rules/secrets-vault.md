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
whatsapp_key  = config_service.get_secret("whatsapp.business_api_key")
hsm_pin       = config_service.get_secret("hsm.operator_pin")
cbs_password  = config_service.get_secret(f"cbs.{cbs_type}.password")

# FORBIDDEN — in any file, any language
DB_PASSWORD = "P@ssw0rd123"                      # hardcoded
db_pass = os.environ.get("DB_PASSWORD")          # direct env var
db_pass = os.environ.get("DB_PASSWORD", "admin") # env var with default
password = settings.DB_PASSWORD                  # settings object from env
```

---

## config_service Secret Fetch Pattern

```python
# shared/config/config_service.py (internal implementation)
import hvac   # HashiCorp Vault client

class ConfigService:
    def __init__(self):
        self._vault = hvac.Client(
            url=os.environ["VAULT_ADDR"],        # only env vars allowed: VAULT_ADDR, VAULT_TOKEN
            token=os.environ["VAULT_TOKEN"],     # injected by Vault agent sidecar at pod startup
        )
        self._cache = {}   # short-lived in-memory cache (30 seconds max)

    def get_secret(self, key: str) -> str:
        """
        Fetches secret from Vault. Caches for 30 seconds.
        Key format: "service.field" → Vault path: secret/astra/{bank_id}/{service}/{field}
        """
        if key in self._cache and not self._is_stale(key):
            return self._cache[key]

        bank_id = self._bank_id   # set at startup from Helm-injected env var
        vault_path = f"secret/astra/{bank_id}/{key.replace('.', '/')}"

        response = self._vault.secrets.kv.v2.read_secret_version(path=vault_path)
        value = response["data"]["data"]["value"]

        self._cache[key] = value
        return value

    def get(self, key: str) -> any:
        """Non-secret config from YugabyteDB (Layer 3) or Helm env (Layer 2)."""
        ...
```

---

## Vault Secret Path Conventions

```
secret/astra/{bank_id}/db/cts/password
secret/astra/{bank_id}/db/ej/password
secret/astra/{bank_id}/redis/cts/auth_token
secret/astra/{bank_id}/redis/ej/auth_token
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

All secrets rotated automatically every 24 hours via Vault dynamic secrets.
Application reads fresh value from config_service on each rotation (30s cache TTL ensures pickup).

---

## Vault Agent Sidecar (How VAULT_TOKEN Reaches the Pod)

```yaml
# In Helm pod template — Vault agent injects VAULT_TOKEN at startup
# Application code never handles Vault authentication itself
annotations:
  vault.hashicorp.com/agent-inject: "true"
  vault.hashicorp.com/role: "astra-{service-name}"
  vault.hashicorp.com/agent-inject-secret-vault-token: "auth/token/lookup-self"
  # Vault agent writes token to /vault/secrets/token
  # Pod startup script sets VAULT_TOKEN from this file
  # After that, config_service uses VAULT_TOKEN normally
```

---

## What Runs Before Secrets Touch Code

### gitleaks (pre-commit + CI — blocks on any pattern match)
```bash
# Patterns blocked by gitleaks (in .gitleaks.toml):
- password\s*=\s*["'][^"']{6,}["']
- api_key\s*=\s*["'][^"']{10,}["']
- private_key\s*=\s*["']-----BEGIN
- token\s*=\s*["'][A-Za-z0-9+/]{20,}["']
- secret\s*=\s*["'][^"']{8,}["']
- AKIA[A-Z0-9]{16}        (AWS key pattern — should never appear in ASTRA)
- hvs\.[A-Za-z0-9_-]{90}  (Vault token pattern)
```

### Trivy (CI — scans Docker images for embedded secrets)
```bash
trivy image --scanners secret astra/{service}:{version}
# Fails build if any secret pattern found in image layers
```

### checkov (CI — scans IaC for hardcoded secrets)
```bash
checkov -d infra/ --check CKV_SECRET_*
# Scans Helm templates, K8s manifests for hardcoded values
```

---

## Forbidden Patterns (gitleaks blocks these automatically)
```python
# These patterns will fail pre-commit AND CI:
DB_URL = "postgresql://admin:P@ssw0rd@yugabyte:5432/astra"   # BLOCKED
REDIS_URL = "redis://:secretpassword@redis-cts:6379"          # BLOCKED
API_KEY = "sk-abc123xyz..."                                    # BLOCKED
os.environ["DB_PASSWORD"] = "admin"                           # BLOCKED (sets env)
os.environ.get("NGCH_KEY", "fallback_key")                    # BLOCKED (hardcoded default)

# Also forbidden in YAML/config files:
password: "mypassword"        # BLOCKED in any .yaml file
token: "abc123"               # BLOCKED
connectionString: "...pwd=x"  # BLOCKED
```

---

## Enforcement

| Rule | Enforced By | Blocks |
|---|---|---|
| No hardcoded passwords/tokens/keys | gitleaks (pre-commit hook + CI `gitleaks` stage) | Commit blocked + PR merge blocked |
| No os.environ.get() in app code | Semgrep `astra-no-direct-env-secrets` | PR merge blocked |
| No secrets in Docker images | Trivy `--scanners secret` on every image | PR merge blocked |
| No secrets in Helm/K8s manifests | checkov `CKV_SECRET_*` on infra/ | PR merge blocked |
| config_service is the only gateway | Semgrep: `hvac.Client(` outside `shared/config/config_service.py` = ERROR | PR merge blocked |
| Vault token never logged | Semgrep pattern: log.*VAULT_TOKEN or log.*hvs\. | PR merge blocked |
| VAULT_ADDR and VAULT_TOKEN from env only (inside config_service) | `security-auditor` agent verifies no other code touches these env vars | PR merge |
