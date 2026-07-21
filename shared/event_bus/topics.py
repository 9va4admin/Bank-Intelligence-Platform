"""Kafka topic name constants — single source of truth for all ASTRA topics.

Module isolation guarantee:
  CTS producers/consumers only use CTS_* and PLATFORM_* constants.
  EJ  producers/consumers only use EJ_*  and PLATFORM_* constants.
  No cross-module topic access is permitted (enforced by EventProducer's
  module-scope guard in shared/event_bus/producer.py).

Bank-scoped topics are f-strings — caller substitutes {bank_id}:
    from shared.event_bus.topics import CTS_INWARD
    topic = CTS_INWARD.format(bank_id=bank_id)
"""

# ---------------------------------------------------------------------------
# Platform — shared by all modules, always allowed
# ---------------------------------------------------------------------------

PLATFORM_AUDIT_EVENTS = "platform.audit.events"
PLATFORM_NOTIFICATIONS = "platform.notifications"
PLATFORM_CONFIG_CHANGED = "platform.config.changed"
PLATFORM_CACHE_INVALIDATION = "platform.cache.invalidation"

# ---------------------------------------------------------------------------
# CTS — inward clearing (drawee bank)
# ---------------------------------------------------------------------------

CTS_INWARD = "cts.inward.{bank_id}"
CTS_DECISIONS = "cts.decisions.{bank_id}"
CTS_HUMAN_REVIEW = "cts.human.review.{bank_id}"
CTS_VAULT_SYNC = "cts.vault.sync.{bank_id}"
CTS_VAULT_DELTA = "cts.vault.delta.{bank_id}"

# CTS — outward clearing (presentee bank)
CTS_OUTWARD_SCANNED = "cts.outward.scanned.{bank_id}"
CTS_OUTWARD_LOT_SEALED = "cts.outward.lot.sealed.{bank_id}"
CTS_OUTWARD_SUBMITTED = "cts.outward.submitted.{bank_id}"
CTS_MISMATCH = "cts.mismatch.{bank_id}.{branch_id}"

# CTS — sub-member bank routing
CTS_SMB_INBOUND = "cts.smb.inbound.{bank_id}"

# CTS — SB relay (agency CC mode)
CTS_SB_RELAY_INWARD  = "cts.sb.relay.inward.{agency_id}.{sb_bank_id}"
CTS_SB_RELAY_OUTWARD = "cts.sb.relay.outward.{agency_id}.{sb_bank_id}"

# ---------------------------------------------------------------------------
# EJ — ATM Electronic Journal
# ---------------------------------------------------------------------------

EJ_RAW_INGESTED = "ej.raw.ingested.{bank_id}"
EJ_CANONICAL = "ej.canonical.{bank_id}"
EJ_HEALTH_SIGNALS = "ej.health.signals.{bank_id}"
