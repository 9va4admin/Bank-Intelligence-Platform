"""
ConfigService — single gateway to all configuration and secrets in ASTRA.

Layer mapping:
  get_secret()         → Layer 5: pluggable SecretBackend (Vault / K8s Secrets / env vars)
  get()                → Layer 3: YugabyteDB config table (Redis-cached, Kafka-invalidated)
  get_platform()       → Layer 1+2: Helm-injected environment variables (immutable at runtime)
  evaluate_policy()    → Layer 4: OPA decision API (hot-reloaded Rego bundle)
  get_user_preference()→ Layer 5: YugabyteDB user_preferences table (per-request, no cache)

Secret backend is selected at startup via ASTRA_SECRETS_BACKEND env var:
  vault        → HashiCorp Vault KV v2 (default, for mid/large banks)
  env          → ASTRA_SECRET_* environment variables (dev/CI only)
  k8s_secrets  → Kubernetes Secret volume mount (smallest UCBs with no Vault)

No other file in the codebase may read os.environ, call hvac, or query the config
table directly. Import the singleton: from shared.config.config_service import config_service
"""
import asyncio
import hashlib
import json
import os
import time
from typing import Any

import asyncpg
import httpx
import redis.asyncio as aioredis
import structlog
from opentelemetry import trace

from shared.config.exceptions import (
    ConfigKeyNotFoundError,
    OPAUnavailableError,
    VaultUnavailableError,
)
from shared.config.secret_backends import (
    EnvSecretBackend,
    K8sSecretBackend,
    SecretBackend,
    VaultSecretBackend,
)

log = structlog.get_logger()
tracer = trace.get_tracer("astra.config")

_SECRET_CACHE_TTL_SECONDS = 30
_CONFIG_CACHE_TTL_SECONDS = 30
_OPA_CACHE_TTL_SECONDS = 1

# Fallback values when Layer 3 (Redis + YugabyteDB) is unavailable (dev/CI/degraded).
# Values mirror infra/helm/values/_defaults.yaml layer3 section.
# NEVER reference these literals from anywhere else — they exist only so that the
# config service can return a sane value instead of crashing with AttributeError
# when the DB pool is None during local development.
_LAYER3_DEFAULTS: dict[str, Any] = {
    # ── CTS thresholds ──────────────────────────────────────────────────────────
    "cts.iet_minutes": 180,
    "cts.stp_auto_confirm_threshold": 0.92,
    "cts.stp_mode": "FULL_MANUAL",
    "cts.stp_supervised_confirm_threshold": 0.95,
    "cts.stp_supervised_review_timeout_minutes": 30,
    "cts.human_review_fraud_threshold": 0.72,
    "cts.high_value_amount_threshold": 500000,
    "cts.vault_miss_action": "HUMAN_REVIEW",
    "cts.ocr_min_confidence": 0.90,
    "cts.signature_min_match_score": 0.85,
    "cts.alteration_risk_threshold": 0.65,
    "cts.iet_emergency_buffer_seconds": 30,
    "cts.human_review_max_wait_minutes": 55,
    "cts.cheque_validity_days": 90,
    "cts.pps_mandatory_threshold": 500000,
    "cts.clearing_session": "MORNING",
    "cts.shadow_credit_release_hours": 4,
    "cts.opa_required": True,
    "cts.rear_image_required": "false",
    "cts.outward_frozen_payee_action": "HUMAN_REVIEW",
    "cts.outward_dormant_payee_action": "HUMAN_REVIEW",
    "cts.outward_npa_payee_action": "HUMAN_REVIEW",
    "cts.indic_ocr.kill_mode": "NONE",
    # ── AI thresholds ───────────────────────────────────────────────────────────
    "ai.ocr.min_confidence": 0.90,
    "ai.signature.min_match_score": 0.85,
    "ai.fraud.score_threshold": 0.72,
    "ai.ej.field_extraction.min_confidence": 0.80,
    "ai.ej.field_extraction.max_weak_fields": 2,
    "ai.drift.alert_pct_threshold": 2.0,
    "ai.drift.auto_tighten_pct_threshold": 5.0,
    "ai.drift.pull_from_prod_pct_threshold": 8.0,
    # ── Platform health ─────────────────────────────────────────────────────────
    "platform_health_check.cadence_seconds": 60,
    "platform_health_check.max_human_review_queue_depth": 50,
    "platform_health_check.max_human_review_wait_minutes": 45.0,
    # ── Vault / feedback ────────────────────────────────────────────────────────
    "cts.ocr_feedback_retrain_threshold": 500,
    "cts.ocr_promote_min_improvement": 0.02,
    "vault.error_files.enabled": True,
    "vault.error_files.bucket": "astra-vault-errors",
    "vault.error_files.retention_days": 365,
    # ── AI / vLLM endpoints (graceful: dev worker logs warn, not error) ──────────
    "vllm.url": "http://localhost:8000",
    "vllm.l1_url": "http://localhost:8000",
    "db.cts.dsn": "postgresql://yugabyte:yugabyte@localhost:15433/yugabyte",
}


class ConfigService:
    def __init__(self) -> None:
        # Populated by initialise() — not usable until then
        self._bank_id: str = ""
        self._secret_backend: SecretBackend | None = None
        self._redis: aioredis.Redis | None = None
        self._db_pool: asyncpg.Pool | None = None
        self._opa_url: str = ""

        # In-process caches (secrets never go to Redis)
        self._secret_cache: dict[str, tuple[str, float]] = {}  # key → (value, fetched_at)
        self._opa_cache: dict[str, tuple[dict, float]] = {}    # input_hash → (result, fetched_at)

        self._ready = False

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    async def initialise(self) -> None:
        """
        Called once at pod startup (in FastAPI lifespan or Temporal worker main).

        Reads BANK_ID and ASTRA_SECRETS_BACKEND from env — the only place in the
        entire codebase where os.environ is accessed directly (for bootstrap only).
        """
        with tracer.start_as_current_span("config_service.initialise"):
            bank_id = os.environ.get("BANK_ID", "")
            if not bank_id:
                raise RuntimeError("BANK_ID env var not set — check Helm values")
            self._bank_id = bank_id

            # Resolve and initialise the secret backend.
            # Dict is built here (not at module level) so that patching the class
            # names in tests intercepts the lookup correctly.
            backend_name = os.environ.get("ASTRA_SECRETS_BACKEND", "vault").lower()
            known_backends = {
                "vault": VaultSecretBackend,
                "env": EnvSecretBackend,
                "k8s_secrets": K8sSecretBackend,
            }
            backend_cls = known_backends.get(backend_name)
            if backend_cls is None:
                raise RuntimeError(
                    f"Unknown ASTRA_SECRETS_BACKEND='{backend_name}'. "
                    f"Valid values: {', '.join(known_backends)}."
                )
            self._secret_backend = backend_cls()
            await self._secret_backend.initialise(bank_id)

            # Layer 3: Redis cache URL — degrades gracefully when unavailable
            # (worker/API still boots; Layer 3 config calls raise ConfigKeyNotFoundError
            # and each caller must tolerate that by using Layer 1/2 defaults)
            try:
                redis_url = await self._secret_backend.get("redis.config.url")
                self._redis = aioredis.from_url(redis_url, decode_responses=True)
                await self._redis.ping()
            except Exception as _redis_exc:
                log.warning("config_service.layer3_redis_unavailable", error=str(_redis_exc))
                self._redis = None

            # Layer 3: YugabyteDB pool DSN — same graceful degradation
            try:
                db_dsn = await self._secret_backend.get("db.config.dsn")
                self._db_pool = await asyncpg.create_pool(db_dsn, min_size=1, max_size=5)
            except Exception as _db_exc:
                log.warning("config_service.layer3_db_unavailable", error=str(_db_exc))
                self._db_pool = None

            # Layer 4: OPA URL from platform env (not secret — cluster-internal address)
            self._opa_url = os.environ.get("OPA_URL", "http://opa.astra-platform.svc.cluster.local:8181")

            self._ready = True
            log.info("config_service.ready", bank_id=self._bank_id, backend=backend_name)

    async def shutdown(self) -> None:
        if self._db_pool:
            await self._db_pool.close()
        if self._redis:
            await self._redis.aclose()
        if self._secret_backend:
            await self._secret_backend.shutdown()
        self._ready = False

    # ------------------------------------------------------------------
    # Layer 5 — Secret backend (Vault / K8s / env)
    # ------------------------------------------------------------------

    async def get_secret(self, key: str) -> str:
        """
        Fetch a secret from the configured backend.

        key format:   "db.cts.password"
        vault path:   secret/astra/{bank_id}/db/cts/password  (Vault backend)
        env var:      ASTRA_SECRET_DB_CTS_PASSWORD             (env backend)
        file path:    /var/run/secrets/astra/db.cts.password   (K8s backend)

        Cached in-process for 30 seconds. Never cached to Redis.
        Raises VaultUnavailableError — callers must handle, never silently default.
        """
        self._assert_ready()
        with tracer.start_as_current_span("config.get_secret") as span:
            span.set_attribute("secret_key", key)
            span.set_attribute("bank_id", self._bank_id)

            cached_value, fetched_at = self._secret_cache.get(key, (None, 0.0))
            if cached_value is not None and (time.monotonic() - fetched_at) < _SECRET_CACHE_TTL_SECONDS:
                return cached_value

            value = await self._secret_backend.get(key)
            self._secret_cache[key] = (value, time.monotonic())
            return value

    # ------------------------------------------------------------------
    # Layer 3 — YugabyteDB config table (Redis-cached)
    # ------------------------------------------------------------------

    async def get(self, key: str) -> Any:
        """
        Fetch a bank-configurable runtime value (Layer 3).

        Stored in YugabyteDB config table, cached in Redis for 30 seconds.
        Invalidated by Kafka platform.config.changed events via CacheInvalidator.

        When both Redis and YugabyteDB are unavailable (dev/CI/degraded):
        falls back to _LAYER3_DEFAULTS. Raises ConfigKeyNotFoundError only if
        the key is absent from defaults too — never raises AttributeError.

        Examples:
            config_service.get("cts.human_review_fraud_threshold")  → 0.72
            config_service.get("cts.iet_minutes")                   → 180
            config_service.get("ej.llm_field_min_confidence")       → 0.80
        """
        self._assert_ready()
        with tracer.start_as_current_span("config.get") as span:
            span.set_attribute("config_key", key)
            span.set_attribute("bank_id", self._bank_id)

            cache_key = f"config:{self._bank_id}:{key}"

            # ── Redis cache (skip when unavailable) ──────────────────────────
            if self._redis is not None:
                try:
                    cached = await self._redis.get(cache_key)
                    if cached is not None:
                        return json.loads(cached)
                except Exception as _redis_exc:
                    log.warning("config.get.redis_error", key=key, error=str(_redis_exc))

            # ── YugabyteDB (skip when unavailable) ───────────────────────────
            if self._db_pool is not None:
                value = await self._fetch_from_db(key)
                if self._redis is not None:
                    try:
                        await self._redis.setex(
                            cache_key, _CONFIG_CACHE_TTL_SECONDS, json.dumps(value)
                        )
                    except Exception:
                        pass  # cache write failure is non-fatal
                return value

            # ── Both unavailable: use built-in defaults ───────────────────────
            if key in _LAYER3_DEFAULTS:
                return _LAYER3_DEFAULTS[key]

            raise ConfigKeyNotFoundError(
                f"Config key '{key}' not set. Layer 3 (Redis + DB) both unavailable "
                f"and no built-in default exists. Add to _LAYER3_DEFAULTS or check "
                f"infra/helm/values/_defaults.yaml."
            )

    async def _fetch_from_db(self, key: str) -> Any:
        if self._db_pool is None:
            if key in _LAYER3_DEFAULTS:
                return _LAYER3_DEFAULTS[key]
            raise ConfigKeyNotFoundError(
                f"Config key '{key}' not found — DB pool unavailable."
            )
        async with self._db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT value, value_type FROM config.bank_config WHERE bank_id = $1 AND key = $2",
                self._bank_id,
                key,
            )
        if row is None:
            raise ConfigKeyNotFoundError(
                f"Config key '{key}' not found for bank '{self._bank_id}'. "
                f"Check Admin UI or infra/helm/values/_defaults.yaml."
            )
        raw = row["value"]
        vtype = row["value_type"]
        if vtype == "float":
            return float(raw)
        if vtype == "int":
            return int(raw)
        if vtype == "bool":
            return raw.lower() == "true"
        if vtype == "json":
            return json.loads(raw)
        return raw  # string

    # ------------------------------------------------------------------
    # Layer 1+2 — Helm env vars (immutable at runtime)
    # ------------------------------------------------------------------

    def get_platform(self, key: str) -> str:
        """
        Read a platform-level or deployment-topology value injected by Helm.

        These are immutable at runtime — changing them requires a Helm upgrade.
        Examples:
            get_platform("platform.version")      → "1.3.2"
            get_platform("module.cts.enabled")    → "true"
            get_platform("cbs.connector.type")    → "finacle"

        Key is transformed to env var: "module.cts.enabled" → "MODULE_CTS_ENABLED"
        """
        env_var = key.upper().replace(".", "_")
        value = os.environ.get(env_var)
        if value is None:
            raise ConfigKeyNotFoundError(
                f"Platform config '{key}' (env var {env_var}) not set. "
                f"Check infra/helm/values/banks/{self._bank_id}.yaml"
            )
        return value

    # ------------------------------------------------------------------
    # Layer 4 — OPA policy evaluation
    # ------------------------------------------------------------------

    async def evaluate_policy(self, policy: str, input_data: dict) -> dict:
        """
        Evaluate an OPA Rego policy with the given input.

        policy:     "astra/cts/routing"
        input_data: {"cheque": {...}, "bank_id": "...", "account_status": "..."}
        returns:    OPA result dict e.g. {"requires_human_review": true, "reason": "VAULT_MISS"}

        Cached for 1 second by (policy, sha256(input)).
        On OPAUnavailableError → callers MUST default to HUMAN_REVIEW, never to STP.
        """
        self._assert_ready()
        with tracer.start_as_current_span("config.evaluate_policy") as span:
            span.set_attribute("opa_policy", policy)
            span.set_attribute("bank_id", self._bank_id)

            input_hash = hashlib.sha256(
                json.dumps(input_data, sort_keys=True).encode()
            ).hexdigest()
            cache_key = f"{policy}:{input_hash}"

            cached_result, fetched_at = self._opa_cache.get(cache_key, (None, 0.0))
            if cached_result is not None and (time.monotonic() - fetched_at) < _OPA_CACHE_TTL_SECONDS:
                return cached_result

            url = f"{self._opa_url}/v1/data/{policy.replace('/', '.')}"
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    response = await client.post(url, json={"input": input_data})
                    response.raise_for_status()
                    result = response.json().get("result", {})
                    self._opa_cache[cache_key] = (result, time.monotonic())
                    return result
            except OPAUnavailableError:
                raise
            except Exception as exc:
                log.error("config.opa.unavailable", policy=policy, error=str(exc))
                raise OPAUnavailableError(f"OPA unreachable for policy '{policy}': {exc}") from exc

    # ------------------------------------------------------------------
    # Layer 5 — User preferences (per-request, no cache)
    # ------------------------------------------------------------------

    async def get_user_preference(self, user_id: str, key: str) -> Any:
        """
        Fetch a per-user UI preference. Returns None if not set — callers apply defaults.

        Examples:
            get_user_preference("ops123", "dashboard_layout")  → {"panels": [...]}
            get_user_preference("ops123", "locale")            → "en-IN"
        """
        self._assert_ready()
        async with self._db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT value FROM config.user_preferences WHERE user_id = $1 AND key = $2",
                user_id,
                key,
            )
        if row is None:
            return None
        try:
            return json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            return row["value"]

    # ------------------------------------------------------------------
    # Convenience helpers used across CTS and EJ
    # ------------------------------------------------------------------

    async def get_cts_config(self, bank_id: str | None = None) -> dict:
        """
        Fetch all CTS thresholds in one call. bank_id param ignored — instance is
        already scoped to self._bank_id. Kept for call-site clarity.
        """
        keys = [
            "cts.iet_minutes",
            "cts.stp_auto_confirm_threshold",
            "cts.human_review_fraud_threshold",
            "cts.high_value_amount_threshold",
            "cts.vault_miss_action",
            "cts.ocr_min_confidence",
            "cts.signature_min_match_score",
        ]
        results = await asyncio.gather(*[self.get(k) for k in keys])
        return dict(zip(keys, results))

    async def get_workflow_thresholds(self, bank_id: str | None = None) -> dict:
        """Return all thresholds that ChequeProcessingWorkflow reads from
        ChequeWorkflowInput.cts_config, keyed by the BARE name the workflow
        uses (no 'cts.' prefix).  This is what the inward submission endpoint
        fetches and passes as cts_config to start_workflow().

        Includes every key read by cheque_workflow.py and human_review_workflow.py
        so no workflow code path ever falls back to a hardcoded literal.
        """
        # Map: bare workflow key → config_service dotted key
        key_map = {
            "human_review_max_wait_minutes":     "cts.human_review_max_wait_minutes",
            "human_review_fraud_threshold":      "cts.human_review_fraud_threshold",
            "stp_auto_confirm_threshold":        "cts.stp_auto_confirm_threshold",
            "high_value_amount_threshold":       "cts.high_value_amount_threshold",
            "stp_mode":                          "cts.stp_mode",
            "stp_supervised_confirm_threshold":  "cts.stp_supervised_confirm_threshold",
            "stp_supervised_review_timeout_minutes": "cts.stp_supervised_review_timeout_minutes",
            "clearing_session":                  "cts.clearing_session",
        }
        results = await asyncio.gather(*[self.get(v) for v in key_map.values()])
        return dict(zip(key_map.keys(), results))

    async def get_ej_config(self, bank_id: str | None = None) -> dict:
        """Fetch all EJ thresholds in one call."""
        keys = [
            "ej.llm_field_min_confidence",
            "ej.max_weak_fields_before_reject",
            "ej.pull_schedule",
            "ej.dispute_auto_resolve_categories",
        ]
        results = await asyncio.gather(*[self.get(k) for k in keys])
        return dict(zip(keys, results))

    async def get_ai_config(self, bank_id: str | None = None) -> dict:
        """Fetch AI model thresholds. All are Layer 3 — bank-configurable via Admin UI."""
        keys = [
            "ai.ocr.min_confidence",
            "ai.signature.min_match_score",
            "ai.fraud.score_threshold",
            "ai.ej.field_extraction.min_confidence",
            "ai.ej.field_extraction.max_weak_fields",
            "ai.drift.alert_pct_threshold",
            "ai.drift.auto_tighten_pct_threshold",
            "ai.drift.pull_from_prod_pct_threshold",
        ]
        results = await asyncio.gather(*[self.get(k) for k in keys])
        return dict(zip(keys, results))

    def get_vault_client(self):
        """Return the underlying hvac.Client (VaultSecretBackend only).

        Use this to share the already-authenticated Vault client with subsystems
        (e.g. VaultTOTPSecretStore) instead of having them create a second client
        from the same VAULT_ADDR / VAULT_TOKEN env vars.

        Raises RuntimeError if the active backend is not Vault.
        """
        from shared.config.secret_backends.vault_backend import VaultSecretBackend
        self._assert_ready()
        if not isinstance(self._secret_backend, VaultSecretBackend):
            raise RuntimeError(
                "get_vault_client() is only available when "
                "ASTRA_SECRETS_BACKEND=vault is active. "
                f"Current backend: {type(self._secret_backend).__name__}"
            )
        return self._secret_backend._vault

    def get_vision_ai_kill_switch(self) -> "VisionAIKillSwitch":
        """
        Return a VisionAIKillSwitch bound to this config_service instance.

        Usage in CTS workflow:
            ks = config_service.get_vision_ai_kill_switch()
            status = await ks.check(bank_id=bank_id, smb_id=smb_id)

        The returned checker resolves kill-switch mode via Layer 3 config (hot-reload,
        maker-checker, Immudb-audited, <30s propagation via Kafka platform.config.changed).
        """
        from modules.cts.kill_switch.vision_ai_kill_switch import VisionAIKillSwitch
        return VisionAIKillSwitch(self)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _assert_ready(self) -> None:
        if not self._ready:
            raise RuntimeError(
                "config_service.initialise() has not been awaited. "
                "Call it in the FastAPI lifespan or Temporal worker startup."
            )

    @property
    def bank_id(self) -> str:
        return self._bank_id


# Singleton — import this everywhere, never instantiate ConfigService directly
config_service = ConfigService()
