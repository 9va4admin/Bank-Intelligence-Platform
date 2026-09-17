"""Add extended columns to cts.agent_decisions for outward pipeline.

Adds processing_duration_ms, alteration_detected, signature_verdict,
pps_checked, pps_verdict, cbs_balance_status, degraded_mode,
ocr_engines_used, indic_ocr_kill_switch_active, iet_margin_seconds,
registry_version — all needed by persist_agent_decision activity.
"""

SQL_UPGRADE = """
ALTER TABLE cts.agent_decisions
    ADD CONSTRAINT IF NOT EXISTS uq_agent_decisions_workflow_id UNIQUE (workflow_id),
    ADD COLUMN IF NOT EXISTS processing_duration_ms     INTEGER,
    ADD COLUMN IF NOT EXISTS alteration_detected        BOOLEAN     NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS signature_verdict          TEXT        NOT NULL DEFAULT 'UNKNOWN',
    ADD COLUMN IF NOT EXISTS pps_checked                BOOLEAN     NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS pps_verdict                TEXT        NOT NULL DEFAULT 'UNKNOWN',
    ADD COLUMN IF NOT EXISTS cbs_balance_status         TEXT        NOT NULL DEFAULT 'UNKNOWN',
    ADD COLUMN IF NOT EXISTS degraded_mode              BOOLEAN     NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS ocr_engines_used           TEXT[],
    ADD COLUMN IF NOT EXISTS indic_ocr_kill_switch_active BOOLEAN   NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS iet_margin_seconds         INTEGER     NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS registry_version           TEXT;
"""

SQL_DOWNGRADE = """
ALTER TABLE cts.agent_decisions
    DROP CONSTRAINT IF EXISTS uq_agent_decisions_workflow_id,
    DROP COLUMN IF EXISTS processing_duration_ms,
    DROP COLUMN IF EXISTS alteration_detected,
    DROP COLUMN IF EXISTS signature_verdict,
    DROP COLUMN IF EXISTS pps_checked,
    DROP COLUMN IF EXISTS pps_verdict,
    DROP COLUMN IF EXISTS cbs_balance_status,
    DROP COLUMN IF EXISTS degraded_mode,
    DROP COLUMN IF EXISTS ocr_engines_used,
    DROP COLUMN IF EXISTS indic_ocr_kill_switch_active,
    DROP COLUMN IF EXISTS iet_margin_seconds,
    DROP COLUMN IF EXISTS registry_version;
"""


async def upgrade(conn):
    await conn.execute(SQL_UPGRADE)


async def downgrade(conn):
    await conn.execute(SQL_DOWNGRADE)
