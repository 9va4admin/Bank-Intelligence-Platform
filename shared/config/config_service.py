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

from shared.config.redis_options import redis_options
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
from shared.messages import get_message

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
_ALLOCATION_PREFIXES = ("cts.allocation_", "cts.hybrid_auto_assign", "cts.bucket_", "cts.sip_", "cts.maker_checker", "cts.checker_",
                        "cts.outward_session", "cts.outward_cutoff", "cts.outward_maker", "cts.outward_branch_first",
                        "cts.outward_checker", "cts.outward_high_value", "cts.outward_bucket", "cts.custody_")

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
    # STP architecture fix (2026-09-23): previously ANY low-confidence field among
    # date/payee/amount_words/amount_figures hard-exited the workflow to HUMAN_REVIEW
    # before signature/CBS/fraud ever ran — so those signals could never corroborate a
    # cheque whose only weakness was handwriting OCR (payee name / amount-in-words),
    # even when everything else was clean. See modules/cts/workflows/cheque_workflow.py's
    # _MULTISIGNAL_RESCUE_FIELDS for the exact, conservative scope: only payee and
    # amount_words are eligible (neither feeds a hard auto-return gate in decision.py —
    # the actual paid amount is always inp.presented_amount from NGCH, never OCR's
    # reading); date and amount_figures weakness still early-exits exactly as before,
    # since those feed decision.py's undated/post-dated/stale and amount-mismatch hard
    # gates and a wrong auto-return is worse than an unnecessary human review.
    "cts.ocr_multisignal_rescue_enabled": False,   # default OFF (2026-10-13): unreadable payee/words -> human review
    "cts.payee_reread_min_similarity": 0.99,      # handwritten payee: letters of the two reads must match this closely
    "cts.payee_reference_min_similarity": 0.97,   # payee read vs reference payee from presentment/PPS
    "cts.field_reread_model": "qwen3-vl-32b",    # independent second-read model for the MICR band and the amount box
    "cts.payee_reread_model": "qwen3-vl-32b",     # independent second-opinion model for the payee re-read
    "cts.micr_branch_master": [],                 # valid 9-digit sort codes for this bank; [] = check disabled
    "cts.signature_absent_action": "HUMAN_REVIEW",  # signature not detected: HUMAN_REVIEW (default) or AUTO_RETURN (opt-in)
    "cts.date_implausible_age_days": 1095,        # older than this = probable OCR year misread -> human review, not auto-return
    "cts.iqa_min_width": 700,                     # image quality (RRC 39): calibrated on 70 real scans, see preprocessing/image_quality.py
    "cts.iqa_min_height": 300,
    "cts.iqa_min_sharpness": 300.0,
    "cts.iqa_min_contrast": 60.0,
    "cts.amount_presented_tolerance": 1.0,        # rupees: OCR amount vs presented (NGCH) amount
    "cts.date_implausible_future_days": 365,      # further in the future than this = probable misread -> human review
    "cts.alteration_risk_threshold": 0.65,
    "cts.iet_emergency_buffer_seconds": 30,
    "cts.human_review_max_wait_minutes": 55,
    # ── Human-review allocation (see modules/cts/allocation) ───────────────────
    "cts.allocation_mode": "SELF",                    # SELF | HYBRID | AUTO
    "cts.allocation_lock_ttl_minutes": 10,            # a claim lapses if the holder is idle this long
    "cts.hybrid_auto_assign_timeout_minutes": 5,      # HYBRID: auto-assign after this long unclaimed
    "cts.allocation_strategy": "LEAST_LOADED",        # LEAST_LOADED | RANDOM
    "cts.allocation_max_per_reviewer": 10,            # auto-assign cap per reviewer; 0 = no cap (urgent items ignore it)
    "cts.allocation_urgent_margin_minutes": 30,       # items this close to their IET jump the queue and ignore the cap
    "cts.allocation_rebalance_enabled": True,         # spread unopened auto-assigned work as reviewers log in
    "cts.allocation_rebalance_interval_seconds": 60,  # at most one rebalance per bank per interval (joins bypass it)
    "cts.allocation_rebalance_max_moves": 20,         # cap on items moved in one rebalance
    "cts.allocation_retry_seconds": 60,               # retry delay when no eligible reviewer is available
    # ── Buckets (modules/cts/buckets.py) and the SIP hold ──────────────────────
    "cts.bucket_routing_enabled": False,              # True: reviewers work only the buckets an admin connected them to
    "cts.bucket_priority": ["HVC", "CA", "IP", "FCC", "LVC"],   # which class bucket wins when a cheque fits several
    "cts.bucket_hvc_min_amount": 500000,              # HVC: presented amount at or above this (rupees)
    "cts.bucket_lvc_max_amount": 50000,               # LVC: presented amount below this (rupees)
    "cts.bucket_frequent_min_cheques": 5,             # FCC: at least this many cheques on the account ...
    "cts.bucket_frequent_window_days": 30,            # ... in this many days
    "cts.bucket_corporate_account_types": ["CORPORATE"],                 # CA: CBS account types
    "cts.bucket_institution_account_types": ["INSTITUTION", "GOVERNMENT"],   # IP: CBS account types
    "cts.bucket_overflow_after_minutes": 10,          # an item nobody in its bucket can take moves to MISC after this
    "cts.sip_review_timeout_minutes": 15,             # SIP hold (bank-wide): the system decision is filed if nobody acts
    "cts.sip_iet_guard_minutes": 10,                  # never hold a system decision within this many minutes of its IET
    "cts.outward_session_cutoffs": ["14:30"],         # outward clearing session cut-off(s), local "HH:MM" - configurable per bank
    "cts.outward_session_timezone": "Asia/Kolkata",
    "cts.outward_high_value_ranges": ["₹[5L-10L]", "₹[10L-1Cr]", "₹[>1Cr]"],   # outward items in these masked amount ranges are OUT_HV
    "cts.outward_bucket_priority": ["OUT_HV", "OUT_MISMATCH", "OUT_COMPLIANCE", "OUT_REVIEW"],   # which outward bucket wins
    "cts.outward_maker_scope": "CENTRAL",             # who makes outward decisions: CENTRAL | BRANCH | BRANCH_FIRST
    "cts.outward_branch_first_fallback_minutes": 10,  # BRANCH_FIRST: central staff may take an item after it has waited this long
    "cts.outward_checker_scope": "ANY",               # who checks: ANY (not the maker) | CENTRAL
    "cts.outward_cutoff_guard_minutes": 10,           # never leave a staged decision unfiled within this many minutes of the cut-off
    "cts.custody_branch_hold_days": 7,                # an original kept at its branch longer than this is flagged overdue for handover
    "cts.custody_retention_years": 10,                # how long central storage keeps an original before it may be disposed of (confirm with the bank)
    "cts.maker_checker_enabled": False,             # True: a reviewer's decision (the maker) goes to a checker before it is filed
    "cts.checker_review_timeout_minutes": 15,         # no checker in this time: the maker's decision is filed (never past the IET guard)
    "cts.cheque_validity_days": 90,
    "cts.pps_mandatory_threshold": 500000,
    # Layer 4 business-policy rules (CLAUDE.md §2.6) — evaluated by shared.policy_engine.
    # Ported from the former infra/opa/policies/cts_routing.rego triggers.
    "cts.policy_rules": [
        {"id": "government_cheque", "outcome": "HUMAN_REVIEW", "reason": "government_cheque",
         "when": [{"field": "has_government_flag", "op": "eq", "value": True}]},
        {"id": "court_order", "outcome": "HUMAN_REVIEW", "reason": "court_order_cheque",
         "when": [{"field": "has_court_order_flag", "op": "eq", "value": True}]},
        {"id": "high_value_first_day", "outcome": "HUMAN_REVIEW", "reason": "high_value_first_clearing_day",
         "when": [{"field": "amount", "op": "gt", "value": "$cfg.high_value_amount_threshold"},
                  {"field": "is_first_clearing_day", "op": "eq", "value": True}]},
        {"id": "account_frozen", "outcome": "HUMAN_REVIEW", "reason": "account_frozen",
         "when": [{"field": "account_status", "op": "eq", "value": "FROZEN"}]},
        {"id": "account_closed", "outcome": "AUTO_RETURN", "reason": "account_closed",
         "when": [{"field": "account_status", "op": "eq", "value": "CLOSED"}]},
    ],
    "cts.clearing_session": "MORNING",
    "cts.shadow_credit_release_hours": 4,
    "cts.opa_required": True,
    "cts.rear_image_required": "false",
    "cts.strict_image_quality": "true",    # RBI CTS-2010 compliance ON by default (matches Helm _defaults.yaml); a dev/UAT bank opts OUT explicitly via its own Layer 3 value
    "cts.outward_frozen_payee_action": "HUMAN_REVIEW",
    "cts.outward_dormant_payee_action": "HUMAN_REVIEW",
    "cts.outward_npa_payee_action": "HUMAN_REVIEW",
    "cts.indic_ocr.kill_mode": "NONE",
    # OFF everywhere by default — real cloud dependency, dev/test exception
    # only. See shared/ai/hf_cloud_fallback.py's module docstring.
    "cts.allow_cloud_ai_fallback": False,
    # ── AI thresholds ───────────────────────────────────────────────────────────
    "ai.ocr.min_confidence": 0.90,
    "ai.signature.min_match_score": 0.85,
    "ai.fraud.score_threshold": 0.72,
    "ai.ej.field_extraction.min_confidence": 0.80,
    "ai.ej.field_extraction.max_weak_fields": 2,
    "ai.drift.alert_pct_threshold": 2.0,
    "ai.drift.auto_tighten_pct_threshold": 5.0,
    "ai.drift.pull_from_prod_pct_threshold": 8.0,
    # ── AI service endpoints ────────────────────────────────────────────────────
    "services.indic_ocr.url": "http://localhost:8021",
    "services.sig_detector.url": "http://localhost:8020",
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
    "redis.cts.url": "redis://localhost:16379/0",
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
                raise RuntimeError(get_message("PLATFORM_BANK_ID_ENV_VAR_NOT"))
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
                    get_message("PLATFORM_UNKNOWN_ASTRA_SECRETS_BACKEND_VALID", backend_name=backend_name, value=', '.join(known_backends))
                )
            self._secret_backend = backend_cls()
            await self._secret_backend.initialise(bank_id)

            # Layer 3: Redis cache URL — degrades gracefully when unavailable
            # (worker/API still boots; Layer 3 config calls raise ConfigKeyNotFoundError
            # and each caller must tolerate that by using Layer 1/2 defaults)
            try:
                redis_url = await self._secret_backend.get("redis.config.url")
                self._redis = aioredis.from_url(redis_url, decode_responses=True, **redis_options(self.get_platform))
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
                get_message("PLATFORM_CONFIG_KEY_NOT_SET_LAYER", key_value=key)
            )

    async def _fetch_from_db(self, key: str) -> Any:
        if self._db_pool is None:
            if key in _LAYER3_DEFAULTS:
                return _LAYER3_DEFAULTS[key]
            raise ConfigKeyNotFoundError(
                get_message("PLATFORM_CONFIG_KEY_NOT_FOUND_DB", key_value=key)
            )
        # Key namespace convention (see infra/migrations/platform/versions/
        # 20260618_002_platform_config_and_policies.py): "module.config_key",
        # e.g. "cts.iet_minutes" -> module="cts", config_key="iet_minutes".
        module, _, config_key = key.partition(".")
        async with self._db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT config_value, value_type FROM platform.config_values "
                "WHERE bank_id = $1 AND module = $2 AND config_key = $3",
                self._bank_id,
                module,
                config_key,
            )
        if row is None:
            # Row absent from DB — fall back to built-in defaults before raising.
            if key in _LAYER3_DEFAULTS:
                log.debug("config.get.db_miss_using_default", key=key, bank_id=self._bank_id)
                return _LAYER3_DEFAULTS[key]
            raise ConfigKeyNotFoundError(
                get_message("PLATFORM_CONFIG_KEY_NOT_FOUND_FOR", key_value=key, bank_id=self._bank_id)
            )
        raw = row["config_value"]
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
                get_message("PLATFORM_PLATFORM_CONFIG_ENV_VAR_NOT", key_value=key, env_var=env_var, bank_id=self._bank_id)
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
                raise OPAUnavailableError(get_message("PLATFORM_OPA_UNREACHABLE_FOR_POLICY", policy=policy, exc=exc)) from exc

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
                "SELECT pref_value FROM platform.user_preferences "
                "WHERE user_id = $1::uuid AND pref_key = $2",
                user_id,
                key,
            )
        if row is None:
            return None
        try:
            return json.loads(row["pref_value"])
        except (json.JSONDecodeError, TypeError):
            return row["pref_value"]

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
        alloc_keys = [k for k in _LAYER3_DEFAULTS if k.startswith(_ALLOCATION_PREFIXES)]
        results = await asyncio.gather(*[self.get(k) for k in keys + alloc_keys])
        out = dict(zip(keys + alloc_keys, results))
        # Allocation code (queue router, review consumer) reads bare names; the dotted keys above stay as they were.
        for k in alloc_keys:
            out[k.removeprefix("cts.")] = out[k]
        return out

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
            # read by synthesise_decision from the workflow's cts_config
            "ocr_min_confidence":                "cts.ocr_min_confidence",
            "sig_min_match_score":               "cts.signature_min_match_score",
            "ocr_multisignal_rescue_enabled":    "cts.ocr_multisignal_rescue_enabled",
            "payee_reference_min_similarity":    "cts.payee_reference_min_similarity",
            "micr_branch_master":                "cts.micr_branch_master",
            "signature_absent_action":           "cts.signature_absent_action",
            "date_implausible_age_days":         "cts.date_implausible_age_days",
            "amount_presented_tolerance":        "cts.amount_presented_tolerance",
            "date_implausible_future_days":      "cts.date_implausible_future_days",
            # review buckets and the SIP hold (read by cheque_workflow.finalise)
            "bucket_routing_enabled":            "cts.bucket_routing_enabled",
            "bucket_priority":                   "cts.bucket_priority",
            "bucket_hvc_min_amount":             "cts.bucket_hvc_min_amount",
            "bucket_lvc_max_amount":             "cts.bucket_lvc_max_amount",
            "bucket_frequent_min_cheques":       "cts.bucket_frequent_min_cheques",
            "bucket_frequent_window_days":       "cts.bucket_frequent_window_days",
            "bucket_corporate_account_types":    "cts.bucket_corporate_account_types",
            "bucket_institution_account_types":  "cts.bucket_institution_account_types",
            "sip_review_timeout_minutes":        "cts.sip_review_timeout_minutes",
            "sip_iet_guard_minutes":             "cts.sip_iet_guard_minutes",
            "maker_checker_enabled":             "cts.maker_checker_enabled",
            "checker_review_timeout_minutes":    "cts.checker_review_timeout_minutes",
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
                get_message("PLATFORM_GET_VAULT_CLIENT_IS_ONLY", name__=type(self._secret_backend).__name__)
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
                get_message("PLATFORM_CONFIG_SERVICE_INITIALISE_HAS_NOT")
            )

    @property
    def bank_id(self) -> str:
        return self._bank_id


# Singleton — import this everywhere, never instantiate ConfigService directly
config_service = ConfigService()
