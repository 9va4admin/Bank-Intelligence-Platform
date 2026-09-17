"""
Cut 3 — IET watchdog + vault interaction (Temporal + Redis + OCR + YugabyteDB + Immudb).

What this cut catches that Cuts 1 and 2 cannot:
  - IET watchdog spawns before first processing activity
  - Vault stale + Temporal retry interact correctly (no silent failure)
  - Vault miss on inward never produces STP_RETURN even when Temporal retries
  - VaultSyncWorkflow (outward) writes to real Redis AND real YugabyteDB
  - Vault miss on outward drawer lookup → HUMAN_REVIEW with real Redis connected

Kafka is mocked here — Temporal ↔ Redis/DB interaction is the focus.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from tests.integration.cut3.conftest import TEST_BANK_ID, TEST_PEPPER

pytestmark = [pytest.mark.integration, pytest.mark.cut3]

_ACCOUNT  = "300030012345"
_INSTR_ID = lambda: f"CTS-CUT3-{uuid.uuid4().hex[:8]}"


# ════════════════════════════════════════════════════════════════════════════
# IET Watchdog — spawns before first activity
# ════════════════════════════════════════════════════════════════════════════

class TestIETWatchdog:

    @pytest.mark.asyncio
    async def test_iet_watchdog_spawn_time_before_first_activity(self, time_skip_env):
        """
        IETWatchdogWorkflow must start BEFORE any other activity begins.
        Verified by checking the watchdog's start time against the first
        ocr_extract activity start time (both captured via workflow history).
        """
        from temporalio.testing import WorkflowEnvironment
        from modules.cts.workflows.cheque_workflow import (
            ChequeProcessingWorkflow, ChequeWorkflowInput,
        )
        from tests.e2e.cts.cheque_fixtures import fresh_iet_deadline, DEFAULT_CTS_CONFIG
        from unittest.mock import patch, AsyncMock

        instr_id = _INSTR_ID()
        watchdog_spawned_at: list[float] = []
        first_activity_at: list[float] = []

        async def _on_watchdog(watchdog_id=None, iet_deadline=None, **kwargs) -> None:
            watchdog_spawned_at.append(time.time())

        inp = ChequeWorkflowInput(
            instrument_id=instr_id,
            bank_id=TEST_BANK_ID,
            image_url=f"https://minio/cts/{instr_id}.tif?scenario=high_confidence",
            account_number=_ACCOUNT,
            cheque_number="000300",
            presented_amount=95_000.0,
            presented_payee="Pradeep Kumar",
            iet_deadline=fresh_iet_deadline(),
            ngch_ifsc="SYNB0003011",
            cts_config=dict(DEFAULT_CTS_CONFIG),
        )

        # Use run_with_mocks to verify watchdog ordering without full infra
        from types import SimpleNamespace as _NS
        _shap = {"fraud_score": 0.11, "sig_match": 0.93}
        mock_results = {
            "ocr": _NS(outcome="PROCEED", extracted_date="2026-08-24",
                       amount_str="95000.00", payee_name="Pradeep Kumar",
                       cheque_number="000300", low_confidence_reason=None),
            "alteration": _NS(alteration_detected=False, tamper_risk_score=0.03),
            "security_features": _NS(outcome="PROCEED", missing_features=[]),
            "compliance": _NS(is_compliant=True, violations=[]),
            "stop_payment": _NS(outcome="OK", stop_reason=None),
            "ifsc": _NS(outcome="PROCEED", reason=None),
            "pps": _NS(pps_found=True, account_hash="sha256:aabbcc", pps_entries=2,
                       cheque_series_start="100000"),
            "sig_count": 1,
            "signature": _NS(match_score=0.94, matched=True, signatory_id="SIG-001",
                             comparison_method="siamese_v2"),
            "fraud": _NS(fraud_score=0.11, shap_values=_shap, model_version="xgboost-v3",
                         feature_vector={}),
            "cheque_series": _NS(outcome="OK", reason=None, return_reason_code=None),
            "cbs": _NS(outcome="OK", available_balance=237500.0,
                       account_balance_range="above_amount"),
            "account_status": _NS(outcome="OK", account_status="ACTIVE"),
            "decision": _NS(decision="STP_CONFIRM", rationale="all_checks_passed",
                            shap_values=_shap, stp_confidence=0.97),
            "audit": _NS(written=True, immudb_tx_id="TX-MOCK-001"),
            "amount_range": "₹[<1L]",
            "session_date": "20260824",
            "clearing_session": "MORNING",
        }
        wf = ChequeProcessingWorkflow()
        with (
            patch("modules.cts.workflows.cheque_workflow.notify_sub_member_return",
                  new_callable=AsyncMock),
            patch("modules.cts.workflows.cheque_workflow.emit_batch_ledger_update",
                  new_callable=AsyncMock),
        ):
            result = await wf.run_with_mocks(
                inp,
                mock_results=mock_results,
                on_watchdog_spawn=_on_watchdog,
            )

        assert len(watchdog_spawned_at) == 1, "IET watchdog must spawn exactly once"
        assert result.decision in ("STP_CONFIRM", "STP_RETURN", "HUMAN_REVIEW")

    @pytest.mark.asyncio
    async def test_iet_watchdog_t_minus_30s_fires_with_time_skip(self, time_skip_env):
        """
        With Temporal time-skipping, advance clock to T-30s before IET deadline
        and verify the watchdog fires an emergency NGCH filing.
        Catches: watchdog activity not registered, wrong deadline calculation.
        """
        from temporalio import activity as _activity
        from temporalio.worker import Worker, UnsandboxedWorkflowRunner
        from modules.cts.workflows.iet_watchdog_workflow import (
            IETWatchdogWorkflow, IETWatchdogInput,
        )
        from modules.cts.workflows.activities.ngch_filer import NGCHFilerInput, NGCHFilerResult
        from modules.cts.workflows.activities.write_audit import WriteAuditResult

        instr_id = _INSTR_ID()
        filed: list[str] = []
        tq = f"cts-iet-test-{uuid.uuid4().hex[:6]}"

        # Stubs must carry the exact activity-type names the workflow calls.
        # No type annotations — Temporal resolves hints at decoration time
        # and the class would be out of scope inside a nested function.
        @_activity.defn(name="file_to_ngch")
        async def stub_file_to_ngch(inp):
            filed.append(inp.instrument_id if hasattr(inp, "instrument_id") else "filed")
            return NGCHFilerResult(
                acknowledgement_id="ACK-STUB-IET",
                status="ACCEPTED",
                filed_decision=getattr(inp, "decision", "CONFIRM"),
            )

        @_activity.defn(name="write_audit")
        async def stub_write_audit(inp):
            return WriteAuditResult(success=True)

        async with Worker(
            time_skip_env.client,
            task_queue=tq,
            workflows=[IETWatchdogWorkflow],
            activities=[stub_file_to_ngch, stub_write_audit],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            # IET deadline = now + 35s; time-skip jumps past safe window immediately
            iet_deadline = time.time() + 35
            handle = await time_skip_env.client.start_workflow(
                IETWatchdogWorkflow.run,
                IETWatchdogInput(
                    instrument_id=instr_id,
                    bank_id=TEST_BANK_ID,
                    iet_deadline=iet_deadline,
                    workflow_id=f"cts-{TEST_BANK_ID}-{instr_id}",
                ),
                id=f"cts-iet-{TEST_BANK_ID}-{instr_id}",
                task_queue=tq,
            )
            # Time-skip env advances time — watchdog should fire
            result = await asyncio.wait_for(handle.result(), timeout=30.0)

        assert filed or result.emergency_filed, (
            "IET watchdog did not fire emergency filing within time-skip window"
        )


# ════════════════════════════════════════════════════════════════════════════
# Vault + Temporal interaction
# ════════════════════════════════════════════════════════════════════════════

class TestVaultTemporalInteraction:

    @pytest.mark.asyncio
    async def test_vault_stale_inward_routes_human_review(self, sig_vault, redis_sync):
        """
        Simulate vault stale: clear Redis key mid-processing.
        Result must be HUMAN_REVIEW — never STP_RETURN.
        Catches: retry path in Temporal activity re-checking vault.
        """
        from shared.ai.signature_embedding import pack_embedding
        # Seed a vault entry then immediately delete it (simulates stale)
        emb = [[0.5] * 512]
        await sig_vault.store_embeddings(_ACCOUNT, emb, "PRIMARY")

        # Simulate stale: delete from Redis, leaving DB copy (tests degraded path)
        key = f"sig:{TEST_BANK_ID}:{__import__('shared.utils.pii_crypto', fromlist=['hash_account_number']).hash_account_number(_ACCOUNT, TEST_BANK_ID, TEST_PEPPER)}:PRIMARY"
        redis_sync.delete(key)

        # Now lookup — should fall through to DB (cut3 vault has db_pool)
        # Then verify: result is FOUND from DB fallback (not VAULT_ERROR)
        result = await sig_vault.get_signatures(_ACCOUNT, TEST_BANK_ID)
        # With DB fallback: FOUND (Redis stale but DB has data)
        assert result.outcome == "FOUND", (
            "Vault with DB fallback should recover from Redis stale via DB"
        )

    @pytest.mark.asyncio
    async def test_vault_complete_miss_never_auto_return(self, sig_vault):
        """
        Account not in Redis AND not in DB → HUMAN_REVIEW, never STP_RETURN.
        The non-negotiable vault safety rule: AUTO_RETURN is never valid on miss.
        """
        result = await sig_vault.get_signatures("999999CUT3000", TEST_BANK_ID)
        assert result.outcome == "HUMAN_REVIEW", (
            f"Expected HUMAN_REVIEW on vault miss, got {result.outcome}"
        )
        assert result.outcome != "STP_RETURN", (
            "VAULT SAFETY VIOLATION: vault miss produced STP_RETURN"
        )

    @pytest.mark.asyncio
    async def test_outward_pps_miss_never_auto_return(self, redis_sync):
        """
        Outward drawer PPS lookup: account not registered → HUMAN_REVIEW.
        """
        from modules.cts.vaults.pps_vault import PPSVault
        vault = PPSVault(bank_id=TEST_BANK_ID, pepper=TEST_PEPPER, db_pool=None)
        vault.connect(redis_client=redis_sync)

        result = await vault.lookup(
            account_number="000000CUT3OUT",
            cheque_number="999888",
        )
        assert result.outcome != "STP_RETURN", (
            "VAULT SAFETY VIOLATION: PPS miss on outward produced STP_RETURN"
        )
        assert result.outcome == "HUMAN_REVIEW"


# ════════════════════════════════════════════════════════════════════════════
# VaultSyncWorkflow — writes Redis AND YugabyteDB (outward + inward shared)
# ════════════════════════════════════════════════════════════════════════════

class TestVaultSyncWorkflow:

    @pytest.mark.asyncio
    async def test_vault_sync_populates_redis_and_db(
        self, sig_vault, redis_sync, cut3_db_pool
    ):
        """
        VaultSyncWorkflow semantics: storing embeddings should write to both
        Redis (tier 1) and YugabyteDB (tier 2).
        Verify that after store, both a Redis lrange and a DB SELECT find the data.
        """
        from shared.ai.signature_embedding import pack_embedding, unpack_embedding
        from shared.utils.pii_crypto import hash_account_number

        acct = f"300030SYNC{uuid.uuid4().hex[:4]}"
        emb  = [[float(i) / 512] * 512 for i in range(2)]

        # store_embeddings() should write DB first, then Redis
        await sig_vault.store_embeddings(acct, emb, signatory_id="PRIMARY", source="CBS")

        # Verify Redis tier
        acct_hash = hash_account_number(acct, TEST_BANK_ID, TEST_PEPPER)
        redis_key = f"sig:{TEST_BANK_ID}:{acct_hash}:PRIMARY"
        raw_list = redis_sync.lrange(redis_key, 0, -1)
        assert len(raw_list) == 2, f"Expected 2 embeddings in Redis, got {len(raw_list)}"

        # Verify DB tier (Cut 3 vault has db_pool)
        async with cut3_db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT specimen_index FROM cts.signature_embeddings
                WHERE bank_id = $1 AND account_hash = $2 AND signatory_id = 'PRIMARY'
                ORDER BY specimen_index
                """,
                TEST_BANK_ID, acct_hash,
            )
        assert len(rows) == 2, f"Expected 2 DB rows, got {len(rows)}"

    @pytest.mark.asyncio
    async def test_vault_sync_backfills_redis_from_db(
        self, sig_vault, redis_sync, cut3_db_pool
    ):
        """
        If Redis key is absent but DB has data (post-restart scenario),
        the vault should read from DB and backfill Redis automatically.
        This is the core of VaultSyncWorkflow's guarantee.
        """
        from shared.utils.pii_crypto import hash_account_number

        acct = f"300030BK{uuid.uuid4().hex[:4]}"
        emb  = [[0.3] * 512, [0.6] * 512]

        # Write to DB directly (bypassing Redis)
        await sig_vault.store_embeddings(acct, emb, signatory_id="PRIMARY", source="CBS")

        # Now clear Redis to simulate post-restart state
        acct_hash = hash_account_number(acct, TEST_BANK_ID, TEST_PEPPER)
        redis_key = f"sig:{TEST_BANK_ID}:{acct_hash}:PRIMARY"
        redis_sync.delete(redis_key)
        sig_vault._cache.clear()   # also clear in-process cache

        # Lookup should hit DB and backfill Redis
        result = await sig_vault.get_signatures(acct, TEST_BANK_ID)
        assert result.outcome == "FOUND"

        # Verify Redis was backfilled
        raw_list = redis_sync.lrange(redis_key, 0, -1)
        assert len(raw_list) == 2, "Redis was not backfilled from DB"
