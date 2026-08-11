"""ASTRA DEV-ONLY auth server — local login + TOTP MFA with no Vault/DB/Redis,
plus AuthenticationMiddleware so session-gated routes work against it too.

Generates an ephemeral RS256 keypair in-process and seeds THREE accounts (real
argon2 hashes). Serves the real /v1/auth/* router; the frontend reaches it via the
Vite proxy (/v1 -> http://127.0.0.1:8010).

Real MFA flow — no shortcuts: the FIRST sign-in for each user triggers enrolment
(scan the QR into an authenticator app), and every sign-in after that requires the
current 6-digit TOTP code from that app.

    uvicorn apps.api.dev_auth_server:app --port 8010

NEVER use in production: keys are ephemeral (restart = sessions dropped + re-enrol)
and accounts are seeded. Production wires SessionTokenService keys from Vault and
the real connectors + account store.

Routers registered here beyond auth are deliberately limited to ones with no
Vault/DB/Redis/Kafka dependency of their own — this stays a login+one-router dev
tool, not a second copy of apps/api/main.py. demo_cloud_extract qualifies: its
only external dependency (config_service.get_secret for the HF token) already
degrades to a clean 503 when config_service isn't initialised, which it isn't
here. AuthenticationMiddleware itself needs only app.state.session_service,
which this file already constructs for the login flow — no new dependency.
"""
from __future__ import annotations

# Load .env.local (gitignored) at import time so ASTRA_DEMO_HF_TOKEN and any
# other local dev secrets are available before the app starts. Never affects
# production — dev_auth_server is never run there.
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[2] / ".env.local", override=True)

import asyncpg
import structlog
from argon2 import PasswordHasher
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.middleware.authentication import AuthenticationMiddleware
from apps.api.routers import admin as admin_router
from apps.api.routers import audit as audit_router
from apps.api.routers import auth as auth_router
from apps.api.routers import batch as batch_router
from apps.api.routers import branches as branches_router
from apps.api.routers import demo_cloud_extract, observability
from apps.api.routers import mcp_connections as mcp_router
from apps.api.routers import notifications as notifications_router
from apps.api.routers import platform as platform_router
from apps.api.routers import processing_units as pu_router
from apps.api.routers import users as users_router
from shared.auth.auth_service import AuthService
from shared.auth.connectors.base import ASTRAIdentity
from shared.auth.connectors.local import LocalCredentials
from shared.auth.exceptions import AuthenticationError
from shared.auth.mfa import TOTPMFAService
from shared.auth.session_token import SessionTokenService

log = structlog.get_logger()

# username -> account. Users enrol TOTP on first sign-in (scan QR), then supply a
# code every time. Enrolment lives in memory, so a backend restart means re-enrol.
SEED_ACCOUNTS: dict[str, dict] = {
    # ── ASTRA Platform super admin — works in every deployed bank ──────────────
    # In production: password from Vault (secret/astra/platform/super_admin_password)
    # In dev: fixed known password below — first login always shows QR for TOTP enrol
    "__astra-admin": {
        "user_id": "usr-astra-sc", "password": "Astra@Platform2026!",
        "display_name": "ASTRA Platform Admin", "role": "platform_admin",
        "bank_type": "SB", "permission_level": "ADMIN",
        "entity_type": "sb", "entity_id": "__astra-platform__", "bank_id": "saraswat-coop",
        "clearing_zones": ["ALL"],
    },
    # ── Bank-specific dev accounts ─────────────────────────────────────────────
    "admin": {
        "user_id": "usr-admin", "password": "astra-dev-admin",
        "display_name": "Anita Rao", "role": "bank_it_admin",
        "bank_type": "SB", "permission_level": "ADMIN",
        "entity_type": "sb", "entity_id": "saraswat-coop", "bank_id": "saraswat-coop",
        "clearing_zones": ["ALL"],
    },
    "ops": {
        "user_id": "usr-ops", "password": "astra-dev-ops",
        "display_name": "Sunil Mehta", "role": "ops_manager",
        "bank_type": "SB", "permission_level": "EDIT",
        "entity_type": "sb", "entity_id": "saraswat-coop", "bank_id": "saraswat-coop",
        "clearing_zones": ["ALL"],
    },
    "smb": {
        "user_id": "usr-smb", "password": "astra-dev-smb",
        "display_name": "Vasavi Admin", "role": "smb_admin",
        "bank_type": "SMB", "permission_level": "ADMIN",
        "entity_type": "smb", "entity_id": "smb-mh-vasavi", "bank_id": "smb-mh-vasavi",
        "clearing_zones": ["MUMBAI"],
    },
}

_PH = PasswordHasher()
for _acct in SEED_ACCOUNTS.values():
    _acct["password_hash"] = _PH.hash(_acct["password"])


def _gen_keys() -> tuple[str, str]:
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = k.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    pub = k.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return priv, pub


class _MemMfaStore:
    def __init__(self) -> None:
        self._d: dict[str, str] = {}

    async def put(self, uid: str, secret: str) -> None:
        self._d[uid] = secret

    async def get(self, uid: str):
        return self._d.get(uid)

    async def delete(self, uid: str) -> None:
        self._d.pop(uid, None)


class _MemAccounts:
    def __init__(self) -> None:
        self._enrolled: set[str] = set()

    async def is_totp_enrolled(self, uid: str) -> bool:
        return uid in self._enrolled

    async def set_totp_enrolled(self, uid: str, val: bool) -> None:
        self._enrolled.add(uid) if val else self._enrolled.discard(uid)


class _DevConnector:
    """Verifies any of the seeded accounts against its real argon2 hash."""

    @property
    def connector_type(self) -> str:
        return "local"

    async def authenticate(self, credentials: LocalCredentials) -> ASTRAIdentity:
        acct = SEED_ACCOUNTS.get(credentials.username)
        if acct is None:
            raise AuthenticationError("invalid credentials")
        try:
            _PH.verify(acct["password_hash"], credentials.password)
        except Exception:
            raise AuthenticationError("invalid credentials")
        # Platform admin adopts whichever bank_id the login request specified,
        # so the same credentials work in every deployed bank without re-seeding.
        is_platform_admin = acct.get("entity_id") == "__astra-platform__"
        bank_id = (credentials.bank_id or acct["bank_id"]) if is_platform_admin else acct["bank_id"]

        return ASTRAIdentity(
            user_id=acct["user_id"], username=credentials.username,
            display_name=acct["display_name"], entity_type=acct["entity_type"],
            entity_id=acct["entity_id"], bank_id=bank_id, role=acct["role"],
            clearing_zones=acct["clearing_zones"], connector_used="local",
            bank_type=acct["bank_type"], permission_level=acct["permission_level"],
        )

    async def health_check(self) -> bool:
        return True


_DEV_SCHEMA_DDL = """
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE SCHEMA IF NOT EXISTS platform;
CREATE SCHEMA IF NOT EXISTS cts;

-- ── Platform: bank registry (FK anchor for all bank_id columns) ──────────────
CREATE TABLE IF NOT EXISTS platform.banks (
    bank_id          TEXT NOT NULL,
    bank_name        TEXT NOT NULL,
    bank_code        TEXT NOT NULL DEFAULT '',
    ifsc_prefix      TEXT NOT NULL DEFAULT '',
    ngch_member_code TEXT,
    bank_type        TEXT NOT NULL DEFAULT 'COOPERATIVE',
    is_active        BOOLEAN NOT NULL DEFAULT true,
    onboarded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deactivated_at   TIMESTAMPTZ,
    PRIMARY KEY (bank_id)
);

-- Seed dev banks so every FK-less query still resolves
INSERT INTO platform.banks (bank_id, bank_name, bank_code, ifsc_prefix, bank_type)
VALUES
  ('saraswat-coop', 'Saraswat Co-operative Bank', 'SRCB', 'SRCB', 'COOPERATIVE'),
  ('smb-mh-vasavi',  'Vasavi Co-operative Bank',  'VASB', 'VASB', 'COOPERATIVE')
ON CONFLICT (bank_id) DO NOTHING;

-- ── Platform: user accounts (argon2 hash + TOTP) ─────────────────────────────
CREATE TABLE IF NOT EXISTS platform.local_auth_accounts (
    user_id          TEXT NOT NULL,
    bank_id          TEXT NOT NULL,
    entity_type      TEXT NOT NULL,
    entity_id        TEXT NOT NULL,
    username         TEXT NOT NULL,
    display_name     TEXT,
    password_hash    TEXT NOT NULL,
    role             TEXT NOT NULL,
    permission_level TEXT NOT NULL DEFAULT 'VIEW',
    bank_type        TEXT NOT NULL DEFAULT 'SB',
    clearing_zones   TEXT[] NOT NULL DEFAULT '{}',
    email            TEXT,
    phone            TEXT,
    totp_enrolled    BOOLEAN NOT NULL DEFAULT false,
    is_active        BOOLEAN NOT NULL DEFAULT true,
    failed_attempts  INTEGER NOT NULL DEFAULT 0,
    locked_until     DOUBLE PRECISION,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at    TIMESTAMPTZ,
    PRIMARY KEY (user_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_laa_username_bank
    ON platform.local_auth_accounts (username, bank_id);
CREATE INDEX IF NOT EXISTS ix_laa_bank_id
    ON platform.local_auth_accounts (bank_id);

-- ── Platform: Layer 3 config values (hot-reloadable thresholds) ──────────────
CREATE TABLE IF NOT EXISTS platform.config_values (
    config_id    TEXT NOT NULL DEFAULT gen_random_uuid()::text,
    bank_id      TEXT NOT NULL,
    module       TEXT NOT NULL DEFAULT 'cts',
    config_key   TEXT NOT NULL,
    config_value TEXT NOT NULL,
    value_type   TEXT NOT NULL DEFAULT 'float',
    description  TEXT,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by   TEXT NOT NULL DEFAULT 'system',
    PRIMARY KEY (config_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_config_values_key
    ON platform.config_values (bank_id, module, config_key);

-- ── Platform: config maker-checker pending changes ────────────────────────────
CREATE TABLE IF NOT EXISTS platform.config_pending_changes (
    change_id    TEXT NOT NULL,
    bank_id      TEXT NOT NULL,
    config_key   TEXT NOT NULL,
    new_value    TEXT NOT NULL,
    reason       TEXT,
    status       TEXT NOT NULL DEFAULT 'PENDING_APPROVAL',
    submitted_by TEXT NOT NULL,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actioned_by  TEXT,
    actioned_at  TIMESTAMPTZ,
    PRIMARY KEY (change_id)
);
CREATE INDEX IF NOT EXISTS ix_config_pending_bank
    ON platform.config_pending_changes (bank_id, status);

-- ── Platform: Layer 2 Helm-values change requests ────────────────────────────
CREATE TABLE IF NOT EXISTS platform.layer2_change_requests (
    request_id      TEXT NOT NULL,
    bank_id         TEXT NOT NULL,
    config_key      TEXT NOT NULL,
    current_value   TEXT NOT NULL DEFAULT '',
    requested_value TEXT NOT NULL,
    reason          TEXT NOT NULL,
    cab_ticket      TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'PENDING_ASTRA_REVIEW',
    submitted_by    TEXT NOT NULL,
    submitted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (request_id)
);

-- ── Platform: notification records ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS platform.notification_records (
    notification_id TEXT NOT NULL,
    bank_id         TEXT NOT NULL,
    template_id     TEXT,
    recipient_role  TEXT,
    recipient_user  TEXT,
    channel         TEXT NOT NULL DEFAULT 'EMAIL',
    status          TEXT NOT NULL DEFAULT 'PENDING',
    sent_at         TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload         TEXT,
    PRIMARY KEY (notification_id)
);

-- ── CTS: Processing Units ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cts.processing_units (
    pu_id                 TEXT NOT NULL,
    bank_id               TEXT NOT NULL,
    pu_name               TEXT NOT NULL,
    clearing_zone         TEXT NOT NULL,
    ngch_participant_code TEXT NOT NULL DEFAULT '',
    temporal_task_queue   TEXT NOT NULL DEFAULT '',
    kafka_inward_topic    TEXT NOT NULL DEFAULT '',
    max_agent_swarm_size  INTEGER NOT NULL DEFAULT 200,
    is_active             BOOLEAN NOT NULL DEFAULT true,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ,
    created_by            TEXT NOT NULL DEFAULT 'system',
    PRIMARY KEY (pu_id)
);
CREATE INDEX IF NOT EXISTS ix_pu_bank_id ON cts.processing_units (bank_id);

-- ── CTS: Branches ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cts.branches (
    branch_id             TEXT NOT NULL,
    bank_id               TEXT NOT NULL,
    smb_id                TEXT,
    branch_name           TEXT NOT NULL,
    branch_ifsc           TEXT NOT NULL,
    city                  TEXT,
    district              TEXT,
    state                 TEXT,
    address               TEXT,
    pin_code              TEXT,
    phone_number          TEXT,
    pu_id                 TEXT,
    scanner_input_mode    TEXT NOT NULL DEFAULT 'UI_UPLOAD',
    is_scanning_enabled   BOOLEAN NOT NULL DEFAULT true,
    is_active             BOOLEAN NOT NULL DEFAULT true,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ,
    created_by            TEXT NOT NULL DEFAULT 'system',
    PRIMARY KEY (branch_id),
    CONSTRAINT ck_branches_scanner_input_mode CHECK (scanner_input_mode IN ('UI_UPLOAD', 'FOLDER_DROP', 'SDK_PUSH'))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_branches_ifsc ON cts.branches (branch_ifsc);
CREATE INDEX IF NOT EXISTS ix_branches_bank_id ON cts.branches (bank_id);
-- Migration: existing installs get the column with default value
ALTER TABLE cts.branches ADD COLUMN IF NOT EXISTS scanner_input_mode TEXT NOT NULL DEFAULT 'UI_UPLOAD';
ALTER TABLE cts.branches DROP CONSTRAINT IF EXISTS ck_branches_scanner_input_mode;
ALTER TABLE cts.branches ADD CONSTRAINT ck_branches_scanner_input_mode CHECK (scanner_input_mode IN ('UI_UPLOAD', 'FOLDER_DROP', 'SDK_PUSH'));
-- Migration: drop duplicate drop_folder_base_path (canonical location is scanner_configs.drop_folder_path)
ALTER TABLE cts.branches DROP COLUMN IF EXISTS drop_folder_base_path;

-- ── CTS: Scanner registrations (SDK_PUSH mode — machine identity lifecycle) ──
CREATE TABLE IF NOT EXISTS cts.scanner_registrations (
    registration_id           TEXT NOT NULL,
    bank_id                   TEXT NOT NULL,
    branch_id                 TEXT NOT NULL,
    branch_ifsc               TEXT NOT NULL,
    scanner_config_id         TEXT,
    sdk_version               TEXT,
    registration_token_hash   TEXT NOT NULL,
    status                    TEXT NOT NULL DEFAULT 'PENDING',
    last_heartbeat_at         TIMESTAMPTZ,
    last_scan_submitted_at    TIMESTAMPTZ,
    heartbeat_interval_seconds INTEGER NOT NULL DEFAULT 60,
    scans_today               INTEGER NOT NULL DEFAULT 0,
    errors_today              INTEGER NOT NULL DEFAULT 0,
    last_error                TEXT,
    registered_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    registered_by             TEXT NOT NULL,
    is_active                 BOOLEAN NOT NULL DEFAULT true,
    PRIMARY KEY (registration_id),
    CONSTRAINT ck_scanner_reg_status CHECK (status IN ('PENDING', 'ONLINE', 'DEGRADED', 'OFFLINE'))
);
CREATE INDEX IF NOT EXISTS ix_scanner_registrations_bank_id ON cts.scanner_registrations (bank_id);
CREATE INDEX IF NOT EXISTS ix_scanner_registrations_branch_ifsc ON cts.scanner_registrations (branch_ifsc);
-- Partial unique index: one active registration per branch (allows re-registration after deactivation)
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE schemaname = 'cts'
          AND tablename = 'scanner_registrations'
          AND indexname = 'uq_scanner_registrations_active_branch'
    ) THEN
        CREATE UNIQUE INDEX uq_scanner_registrations_active_branch
            ON cts.scanner_registrations (bank_id, branch_ifsc)
            WHERE is_active = true;
    END IF;
END $$;

-- ── CTS: Scanner OEM configs (FOLDER_DROP mode — file watcher settings) ─────
CREATE TABLE IF NOT EXISTS cts.scanner_configs (
    scanner_config_id     TEXT NOT NULL,
    bank_id               TEXT NOT NULL,
    branch_id             TEXT,
    branch_ifsc           TEXT,
    scanner_oem           TEXT NOT NULL,
    scanner_model         TEXT NOT NULL,
    output_format         TEXT NOT NULL,
    date_format           TEXT NOT NULL,
    amount_format         TEXT NOT NULL,
    field_mapping         JSONB NOT NULL DEFAULT '{}',
    image_naming_pattern  TEXT NOT NULL,
    image_side_mapping    JSONB NOT NULL DEFAULT '{}',
    drop_folder_path      TEXT NOT NULL,
    is_active             BOOLEAN NOT NULL DEFAULT true,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ,
    created_by            TEXT NOT NULL DEFAULT 'system',
    PRIMARY KEY (scanner_config_id)
);
CREATE INDEX IF NOT EXISTS ix_scanner_configs_bank_id ON cts.scanner_configs (bank_id);
CREATE INDEX IF NOT EXISTS ix_scanner_configs_branch_id ON cts.scanner_configs (branch_id);
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE schemaname = 'cts'
          AND tablename = 'scanner_configs'
          AND indexname = 'uq_scanner_configs_bank_branch'
    ) THEN
        CREATE UNIQUE INDEX uq_scanner_configs_bank_branch
            ON cts.scanner_configs (bank_id, COALESCE(branch_id, ''));
    END IF;
END $$;

-- ── CTS: MCP connection configs (CBS, Vault, PPS links) ──────────────────────
CREATE TABLE IF NOT EXISTS cts.mcp_connection_configs (
    id                     TEXT NOT NULL,
    bank_id                TEXT NOT NULL,
    connection_type        TEXT NOT NULL,
    smb_id                 TEXT,
    smb_name               TEXT,
    cbs_vendor             TEXT,
    endpoint_url_encrypted BYTEA,
    vault_secret_ref       TEXT,
    status                 TEXT NOT NULL DEFAULT 'PENDING',
    last_tested_at         TIMESTAMPTZ,
    last_test_latency_ms   INTEGER,
    last_sync_at           TIMESTAMPTZ,
    vault_record_count     INTEGER,
    error_message          TEXT,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at             TIMESTAMPTZ,
    created_by             TEXT NOT NULL DEFAULT 'system',
    PRIMARY KEY (id)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_mcp_bank_type_smb
    ON cts.mcp_connection_configs (bank_id, connection_type, COALESCE(smb_id, ''));
CREATE INDEX IF NOT EXISTS ix_mcp_bank_id ON cts.mcp_connection_configs (bank_id);

-- ── CTS: Clearing sessions (used by batch/dashboard pages) ───────────────────
CREATE TABLE IF NOT EXISTS cts.clearing_sessions (
    session_id         TEXT NOT NULL,
    bank_id            TEXT NOT NULL,
    session_type       TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'OPEN',
    clearing_date      DATE NOT NULL DEFAULT CURRENT_DATE,
    total_instruments  INTEGER NOT NULL DEFAULT 0,
    opened_at          TIMESTAMPTZ,
    sealed_at          TIMESTAMPTZ,
    submitted_at       TIMESTAMPTZ,
    reconciled_at      TIMESTAMPTZ,
    npci_ack_ref       TEXT,
    PRIMARY KEY (session_id)
);
CREATE INDEX IF NOT EXISTS ix_cs_bank_date
    ON cts.clearing_sessions (bank_id, clearing_date);

-- ── Config: bank config values (queried by config_service._fetch_from_db) ────
CREATE SCHEMA IF NOT EXISTS config;
CREATE TABLE IF NOT EXISTS config.bank_config (
    bank_id    TEXT NOT NULL,
    key        TEXT NOT NULL,
    value      TEXT NOT NULL,
    value_type TEXT NOT NULL DEFAULT 'float',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (bank_id, key)
);

-- ── Platform: dev seed users (local auth — dev/staging only) ────────────────
-- __astra-admin is the ASTRA platform super admin — seeded for every bank.
-- Password: Astra@Platform2026!  |  In production: from Vault.
-- Use this to bootstrap any bank deployment, then create bank-specific users.
INSERT INTO platform.local_auth_accounts
    (user_id, bank_id, entity_type, entity_id, username, display_name,
     password_hash, role, permission_level, bank_type, clearing_zones, totp_enrolled)
VALUES
  -- ASTRA platform super admin — saraswat-coop
  ('usr-astra-sc', 'saraswat-coop', 'sb', '__astra-platform__', '__astra-admin', 'ASTRA Platform Admin',
   '$argon2id$v=19$m=65536,t=3,p=4$afqXPdEUxZfyel832blAyA$UOf0mZXvX06owJ7Pykn/HIJZPpGnLJs9HS/zpaeNjcM',
   'platform_admin', 'ADMIN', 'SB', ARRAY['ALL'], false),
  -- ASTRA platform super admin — federal-bank
  ('usr-astra-fb', 'federal-bank',  'sb', '__astra-platform__', '__astra-admin', 'ASTRA Platform Admin',
   '$argon2id$v=19$m=65536,t=3,p=4$afqXPdEUxZfyel832blAyA$UOf0mZXvX06owJ7Pykn/HIJZPpGnLJs9HS/zpaeNjcM',
   'platform_admin', 'ADMIN', 'SB', ARRAY['ALL'], false),
  -- Bank-specific dev accounts
  ('usr-admin', 'saraswat-coop', 'sb',  'saraswat-coop', 'admin', 'Anita Rao',
   '$argon2id$v=19$m=65536,t=3,p=4$RpL0cwR5KMqXDBHoxOYL4w$uimuuZjif2n7t8HwlOU2zEgV9euZTCsRASVNaAgj29I',
   'bank_it_admin', 'ADMIN', 'SB', ARRAY['ALL'], false),
  ('usr-ops',   'saraswat-coop', 'sb',  'saraswat-coop', 'ops',   'Sunil Mehta',
   '$argon2id$v=19$m=65536,t=3,p=4$OjmmP/u5VC/orNBhlNSRyA$ULGjkdbrZLs9FUVAY6mOvmN+wtW0whA/CCb0xKIk0iY',
   'ops_manager', 'EDIT', 'SB', ARRAY['ALL'], false),
  ('usr-smb',   'smb-mh-vasavi', 'smb', 'smb-mh-vasavi', 'smb',   'Vasavi Admin',
   '$argon2id$v=19$m=65536,t=3,p=4$WVVrBi7dk2K+WI79D05Njg$Bw6eRjYKWAsrdKrFs5hxvuGzOxr7SNc8mP2RGkagZBQ',
   'smb_admin',   'ADMIN', 'SMB', ARRAY['MUMBAI'], false)
ON CONFLICT (username, bank_id) DO NOTHING;

-- Seed CTS + AI defaults for saraswat-coop so activities have thresholds to load
INSERT INTO config.bank_config (bank_id, key, value, value_type) VALUES
  -- CTS thresholds (queried via get_cts_config())
  ('saraswat-coop', 'cts.iet_minutes',                    '180',   'int'),
  ('saraswat-coop', 'cts.stp_auto_confirm_threshold',     '0.92',  'float'),
  ('saraswat-coop', 'cts.human_review_fraud_threshold',   '0.72',  'float'),
  ('saraswat-coop', 'cts.high_value_amount_threshold',    '500000','float'),
  ('saraswat-coop', 'cts.vault_miss_action',              'HUMAN_REVIEW', 'str'),
  ('saraswat-coop', 'cts.ocr_min_confidence',             '0.85',  'float'),
  ('saraswat-coop', 'cts.signature_min_match_score',      '0.80',  'float'),
  ('saraswat-coop', 'cts.cheque_validity_days',           '90',    'int'),
  ('saraswat-coop', 'cts.very_high_value_threshold',      '1000000','float'),
  ('saraswat-coop', 'cts.smb.min_iet_headroom_s',         '30',    'int'),
  -- AI thresholds (queried via get_ai_config())
  ('saraswat-coop', 'ai.ocr.min_confidence',              '0.85',  'float'),
  ('saraswat-coop', 'ai.signature.min_match_score',       '0.80',  'float'),
  ('saraswat-coop', 'ai.fraud.score_threshold',           '0.72',  'float'),
  ('saraswat-coop', 'ai.tamper_risk_threshold',           '0.35',  'float'),
  ('saraswat-coop', 'ai.llm_request_timeout_s',          '120',   'int'),
  ('saraswat-coop', 'ai.ej.field_extraction.min_confidence', '0.80', 'float'),
  ('saraswat-coop', 'ai.ej.field_extraction.max_weak_fields', '3', 'int'),
  ('saraswat-coop', 'ai.drift.alert_pct_threshold',      '0.02',  'float'),
  ('saraswat-coop', 'ai.drift.auto_tighten_pct_threshold','0.05', 'float'),
  ('saraswat-coop', 'ai.drift.pull_from_prod_pct_threshold','0.08','float'),
  -- Legacy flat keys (some older activities use these directly)
  ('saraswat-coop', 'stp_auto_confirm_threshold',    '0.92',  'float'),
  ('saraswat-coop', 'human_review_fraud_threshold',   '0.72',  'float'),
  ('saraswat-coop', 'ocr_min_confidence',             '0.85',  'float'),
  ('saraswat-coop', 'sig_min_match_score',            '0.80',  'float'),
  ('saraswat-coop', 'high_value_amount_threshold',    '500000','float'),
  ('saraswat-coop', 'iet_minutes',                    '180',   'int'),
  ('saraswat-coop', 'cheque_validity_days',           '90',    'int'),
  ('saraswat-coop', 'vault_miss_action',              'HUMAN_REVIEW', 'str'),
  ('saraswat-coop', 'opa_required',                   'false', 'bool'),
  ('saraswat-coop', 'kill_switch_enabled',            'false', 'bool'),
  -- Vault / Bloom filter config
  ('saraswat-coop', 'vault.bloom_expected_items',     '100000','int'),
  ('saraswat-coop', 'vault.bloom_false_positive_rate','0.001', 'float'),
  -- ── federal-bank: same defaults as saraswat-coop ──────────────────────────
  ('federal-bank', 'cts.iet_minutes',                    '180',   'int'),
  ('federal-bank', 'cts.stp_auto_confirm_threshold',     '0.92',  'float'),
  ('federal-bank', 'cts.human_review_fraud_threshold',   '0.72',  'float'),
  ('federal-bank', 'cts.high_value_amount_threshold',    '500000','float'),
  ('federal-bank', 'cts.vault_miss_action',              'HUMAN_REVIEW', 'str'),
  ('federal-bank', 'cts.ocr_min_confidence',             '0.85',  'float'),
  ('federal-bank', 'cts.signature_min_match_score',      '0.80',  'float'),
  ('federal-bank', 'cts.cheque_validity_days',           '90',    'int'),
  ('federal-bank', 'cts.very_high_value_threshold',      '1000000','float'),
  ('federal-bank', 'cts.smb.min_iet_headroom_s',         '30',    'int'),
  ('federal-bank', 'ai.ocr.min_confidence',              '0.85',  'float'),
  ('federal-bank', 'ai.signature.min_match_score',       '0.80',  'float'),
  ('federal-bank', 'ai.fraud.score_threshold',           '0.72',  'float'),
  ('federal-bank', 'ai.tamper_risk_threshold',           '0.35',  'float'),
  ('federal-bank', 'ai.llm_request_timeout_s',          '120',   'int'),
  ('federal-bank', 'ai.drift.alert_pct_threshold',      '0.02',  'float'),
  ('federal-bank', 'ai.drift.auto_tighten_pct_threshold','0.05', 'float'),
  ('federal-bank', 'ai.drift.pull_from_prod_pct_threshold','0.08','float'),
  ('federal-bank', 'stp_auto_confirm_threshold',    '0.92',  'float'),
  ('federal-bank', 'human_review_fraud_threshold',   '0.72',  'float'),
  ('federal-bank', 'ocr_min_confidence',             '0.85',  'float'),
  ('federal-bank', 'sig_min_match_score',            '0.80',  'float'),
  ('federal-bank', 'high_value_amount_threshold',    '500000','float'),
  ('federal-bank', 'iet_minutes',                    '180',   'int'),
  ('federal-bank', 'cheque_validity_days',           '90',    'int'),
  ('federal-bank', 'vault_miss_action',              'HUMAN_REVIEW', 'str'),
  ('federal-bank', 'opa_required',                   'false', 'bool'),
  ('federal-bank', 'kill_switch_enabled',            'false', 'bool'),
  ('federal-bank', 'vault.bloom_expected_items',     '100000','int'),
  ('federal-bank', 'vault.bloom_false_positive_rate','0.001', 'float')
ON CONFLICT (bank_id, key) DO NOTHING;
"""


def build_app() -> FastAPI:
    priv, pub = _gen_keys()
    session_service = SessionTokenService(priv, pub, issuer="astra-auth", ttl_seconds=900)
    mfa = TOTPMFAService(_MemMfaStore(), issuer="ASTRA")
    accounts = _MemAccounts()
    svc = AuthService(
        connector=_DevConnector(), mfa=mfa,
        session_service=session_service, account_store=accounts,
    )

    app = FastAPI(title="ASTRA Dev Auth (local only)")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:4000", "http://localhost:5173"],
        allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
    )
    # Reads only request.app.state.session_service (set right below) — no
    # Vault/DB dependency, safe to add here unlike most of main.py's stack.
    app.add_middleware(AuthenticationMiddleware)

    app.state.session_service = session_service
    app.state.auth_service = svc
    # db_pool_cts is wired in startup (see below) — branches use real YugabyteDB
    app.state.db_pool_cts = None
    app.state.redis_cts = None
    app.state.vault_client = None
    app.state.kafka_admin = None
    app.state.temporal_client = None

    @app.on_event("startup")
    async def _connect_yugabyte() -> None:
        try:
            pool = await asyncpg.create_pool(
                host="localhost",
                port=15433,
                user="yugabyte",
                password="yugabyte",
                database="yugabyte",
                min_size=2,
                max_size=10,
                command_timeout=30,
            )
            async with pool.acquire() as conn:
                await conn.execute(_DEV_SCHEMA_DDL)
            app.state.db_pool_cts = pool
            log.info("dev_auth.yugabyte_connected", host="localhost", port=15433,
                     note="all management tables created/verified")
        except Exception as exc:
            log.warning("dev_auth.yugabyte_unavailable_fallback_to_memory", error=str(exc))
            # db_pool_cts stays None → branches router falls back to _BRANCH_STORE

    @app.on_event("shutdown")
    async def _disconnect_yugabyte() -> None:
        pool = app.state.db_pool_cts
        if pool:
            await pool.close()
    app.include_router(auth_router.router_v1)
    app.include_router(demo_cloud_extract.router_v1)
    app.include_router(observability.router_v1)
    # Platform router: readiness + smoke-test degrade gracefully when state is None.
    # start-all / start have zero app.state dependency (docker subprocess only).
    app.include_router(platform_router.router_v1)

    # ── Management routers — all use db_pool_cts; degrade gracefully when None ──
    # Kafka/Redis/Immudb stubs are defined inline in each router so missing
    # producers return no-ops rather than 500s. Tables are created by _DEV_SCHEMA_DDL
    # in the startup event above.
    app.include_router(branches_router.router_v1)
    app.include_router(pu_router.router_v1)
    app.include_router(users_router.router_v1)
    app.include_router(admin_router.router_v1)
    app.include_router(mcp_router.router_v1)
    # notifications uses db_pool_platform (None here) → returns empty list (safe)
    app.include_router(notifications_router.router_v1)
    # audit uses db_pool_cts; immudb is None → audit writes are no-ops (safe)
    app.include_router(audit_router.router_v1)
    # batch uses cts.clearing_sessions (created by DDL) → returns empty list on fresh DB
    app.include_router(batch_router.router_v1)

    @app.get("/health/live", include_in_schema=False)
    async def live():
        return {"status": "ok"}

    _banner()
    return app


def _banner() -> None:
    line = "=" * 68
    # Separate platform super admin from bank-specific accounts
    super_admin = {u: a for u, a in SEED_ACCOUNTS.items() if a.get("entity_id") == "__astra-platform__"}
    bank_accounts = {u: a for u, a in SEED_ACCOUNTS.items() if a.get("entity_id") != "__astra-platform__"}

    super_rows = "\n".join(
        f"  *** {u:<14} / {a['password']:<22} ->  {a['role']} (ALL BANKS) ***"
        for u, a in super_admin.items()
    )
    bank_rows = "\n".join(
        f"      {u:<14} / {a['password']:<22} ->  {a['role']} ({a['bank_type']}, {a['bank_id']})"
        for u, a in bank_accounts.items()
    )
    print(
        f"\n{line}\n"
        f"  ASTRA DEV AUTH  |  http://localhost:8010  |  NEVER use in production\n"
        f"{line}\n"
        f"  PLATFORM SUPER ADMIN  (works in every bank — use to bootstrap):\n"
        f"{super_rows}\n\n"
        f"  Bank-specific dev accounts:\n"
        f"{bank_rows}\n\n"
        f"  First sign-in = scan the QR with an authenticator app (Google\n"
        f"  Authenticator / Authy), then enter the 6-digit code. Every sign-in\n"
        f"  after that asks for the current code from your app.\n"
        f"  NOTE: after uvicorn restart, run:  UPDATE platform.local_auth_accounts\n"
        f"        SET totp_enrolled=false, failed_attempts=0;\n"
        f"{line}\n"
    )


app = build_app()
