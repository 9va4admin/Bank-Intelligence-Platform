"""Tests for VaultSyncWorkflow and its four activities."""
import asyncio
import hashlib
import hmac
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from modules.cts.workflows.vault_sync_workflow import (
    VaultSyncInput,
    VaultSyncWorkflow,
    VaultSyncResult,
    SignatureRecord,
    PPSRecord,
    load_signatures_from_cbs,
    load_pps_from_cbs,
    warm_redis_vault,
    verify_vault_integrity,
    _hmac_key,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BANK_ID = "test-bank"
PEPPER = "test-pepper-xyz"
SYNC_DATE = "2026-06-18"


def _expected_key(prefix: str, account: str, suffix: str = "") -> str:
    digest = _hmac_key(PEPPER, BANK_ID, account)
    key = f"{prefix}:{BANK_ID}:{digest}"
    if suffix:
        key += f":{suffix}"
    return key


def _make_input():
    return VaultSyncInput(bank_id=BANK_ID, pepper=PEPPER, sync_date=SYNC_DATE)


# ---------------------------------------------------------------------------
# VaultSyncInput
# ---------------------------------------------------------------------------

class TestVaultSyncInput:
    def test_requires_bank_id(self):
        with pytest.raises(Exception):
            VaultSyncInput(pepper=PEPPER, sync_date=SYNC_DATE)

    def test_requires_pepper(self):
        with pytest.raises(Exception):
            VaultSyncInput(bank_id=BANK_ID, sync_date=SYNC_DATE)

    def test_is_frozen(self):
        inp = _make_input()
        with pytest.raises(Exception):
            inp.bank_id = "other"

    def test_workflow_id_is_deterministic(self):
        wf = VaultSyncWorkflow()
        assert wf.workflow_id(BANK_ID, SYNC_DATE) == f"cts-vaultsync-{BANK_ID}-{SYNC_DATE}"

    def test_workflow_id_includes_date_for_daily_idempotency(self):
        wf = VaultSyncWorkflow()
        id1 = wf.workflow_id(BANK_ID, "2026-06-18")
        id2 = wf.workflow_id(BANK_ID, "2026-06-19")
        assert id1 != id2


# ---------------------------------------------------------------------------
# load_signatures_from_cbs
# ---------------------------------------------------------------------------

class TestLoadSignaturesFromCBS:
    @pytest.mark.asyncio
    async def test_returns_signature_records(self):
        cbs = AsyncMock()
        cbs.list_signature_specimens.return_value = [
            {"account_number": "ACC001", "specimens": [b"sig_bytes"]},
        ]
        records = await load_signatures_from_cbs(BANK_ID, cbs_connector=cbs)
        assert len(records) == 1
        assert records[0].account_number == "ACC001"

    @pytest.mark.asyncio
    async def test_skips_invalid_records_missing_account(self):
        cbs = AsyncMock()
        cbs.list_signature_specimens.return_value = [
            {"account_number": "", "specimens": [b"s"]},
        ]
        records = await load_signatures_from_cbs(BANK_ID, cbs_connector=cbs)
        assert records == []

    @pytest.mark.asyncio
    async def test_skips_records_with_no_specimens(self):
        cbs = AsyncMock()
        cbs.list_signature_specimens.return_value = [
            {"account_number": "ACC001", "specimens": []},
        ]
        records = await load_signatures_from_cbs(BANK_ID, cbs_connector=cbs)
        assert records == []

    @pytest.mark.asyncio
    async def test_cbs_unavailable_raises(self):
        cbs = AsyncMock()
        cbs.list_signature_specimens.side_effect = Exception("CBS down")
        with pytest.raises(Exception, match="CBS down"):
            await load_signatures_from_cbs(BANK_ID, cbs_connector=cbs)

    @pytest.mark.asyncio
    async def test_multiple_records(self):
        cbs = AsyncMock()
        cbs.list_signature_specimens.return_value = [
            {"account_number": f"ACC{i:03d}", "specimens": [b"s"]}
            for i in range(5)
        ]
        records = await load_signatures_from_cbs(BANK_ID, cbs_connector=cbs)
        assert len(records) == 5


# ---------------------------------------------------------------------------
# load_pps_from_cbs
# ---------------------------------------------------------------------------

class TestLoadPPSFromCBS:
    @pytest.mark.asyncio
    async def test_returns_pps_records(self):
        cbs = AsyncMock()
        cbs.list_positive_pay_records.return_value = [
            {"account_number": "ACC001", "cheque_series_start": "100001",
             "amount": 50000.0, "payee": "Test Payee"},
        ]
        records = await load_pps_from_cbs(BANK_ID, cbs_connector=cbs)
        assert len(records) == 1
        assert records[0].amount == 50000.0

    @pytest.mark.asyncio
    async def test_skips_incomplete_records(self):
        cbs = AsyncMock()
        cbs.list_positive_pay_records.return_value = [
            {"account_number": "ACC001"},   # missing amount, payee, cheque_series
        ]
        records = await load_pps_from_cbs(BANK_ID, cbs_connector=cbs)
        assert records == []

    @pytest.mark.asyncio
    async def test_cbs_unavailable_raises(self):
        cbs = AsyncMock()
        cbs.list_positive_pay_records.side_effect = Exception("CBS timeout")
        with pytest.raises(Exception):
            await load_pps_from_cbs(BANK_ID, cbs_connector=cbs)

    @pytest.mark.asyncio
    async def test_ttl_seconds_optional(self):
        cbs = AsyncMock()
        cbs.list_positive_pay_records.return_value = [
            {"account_number": "ACC001", "cheque_series_start": "100001",
             "amount": 1000.0, "payee": "Payee", "ttl_seconds": 86400},
        ]
        records = await load_pps_from_cbs(BANK_ID, cbs_connector=cbs)
        assert records[0].ttl_seconds == 86400


# ---------------------------------------------------------------------------
# warm_redis_vault
# ---------------------------------------------------------------------------

class TestWarmRedisVault:
    @pytest.mark.asyncio
    async def test_writes_signature_keys(self):
        redis = MagicMock()
        pipe = MagicMock()
        redis.pipeline.return_value = pipe
        pipe.execute.return_value = None

        sig_records = [SignatureRecord(account_number="ACC001", specimens=[b"s1", b"s2"])]
        await warm_redis_vault(BANK_ID, PEPPER, sig_records, [], redis_client=redis)

        redis.pipeline.assert_called()
        # delete + rpush x2 = 3 calls for this record
        assert pipe.delete.called
        assert pipe.rpush.call_count == 2

    @pytest.mark.asyncio
    async def test_writes_pps_keys(self):
        redis = MagicMock()
        pipe = MagicMock()
        redis.pipeline.return_value = pipe
        pipe.execute.return_value = None

        pps_records = [PPSRecord(
            account_number="ACC001", cheque_series_start="100001",
            amount=50000.0, payee="Test"
        )]
        result = await warm_redis_vault(BANK_ID, PEPPER, [], pps_records, redis_client=redis)
        assert result["pps_records"] == 1

    @pytest.mark.asyncio
    async def test_returns_counts(self):
        redis = MagicMock()
        pipe = MagicMock()
        redis.pipeline.return_value = pipe
        pipe.execute.return_value = None

        sig_records = [SignatureRecord(account_number=f"ACC{i}", specimens=[b"s"]) for i in range(3)]
        pps_records = [PPSRecord(account_number=f"ACC{i}", cheque_series_start="100", amount=1.0, payee="P") for i in range(2)]
        result = await warm_redis_vault(BANK_ID, PEPPER, sig_records, pps_records, redis_client=redis)
        assert result["signatures"] == 3
        assert result["pps_records"] == 2

    @pytest.mark.asyncio
    async def test_pps_ttl_sets_expiry(self):
        redis = MagicMock()
        pipe = MagicMock()
        redis.pipeline.return_value = pipe
        pipe.execute.return_value = None

        pps_records = [PPSRecord(
            account_number="ACC001", cheque_series_start="100001",
            amount=1.0, payee="P", ttl_seconds=3600
        )]
        await warm_redis_vault(BANK_ID, PEPPER, [], pps_records, redis_client=redis)
        assert pipe.expire.called

    @pytest.mark.asyncio
    async def test_no_pps_ttl_does_not_expire(self):
        redis = MagicMock()
        pipe = MagicMock()
        redis.pipeline.return_value = pipe
        pipe.execute.return_value = None

        pps_records = [PPSRecord(
            account_number="ACC001", cheque_series_start="100001",
            amount=1.0, payee="P"
        )]
        await warm_redis_vault(BANK_ID, PEPPER, [], pps_records, redis_client=redis)
        pipe.expire.assert_not_called()


# ---------------------------------------------------------------------------
# verify_vault_integrity
# ---------------------------------------------------------------------------

class TestVerifyVaultIntegrity:
    @pytest.mark.asyncio
    async def test_passes_when_all_keys_present(self):
        redis = MagicMock()
        redis.llen.return_value = 2   # key exists with 2 specimens
        passed = await verify_vault_integrity(BANK_ID, PEPPER, ["ACC001", "ACC002"], redis_client=redis)
        assert passed is True

    @pytest.mark.asyncio
    async def test_fails_when_key_missing(self):
        redis = MagicMock()
        redis.llen.return_value = 0   # key exists but empty
        passed = await verify_vault_integrity(BANK_ID, PEPPER, ["ACC001"], redis_client=redis)
        assert passed is False

    @pytest.mark.asyncio
    async def test_fails_on_redis_error(self):
        redis = MagicMock()
        redis.llen.side_effect = Exception("Redis timeout")
        passed = await verify_vault_integrity(BANK_ID, PEPPER, ["ACC001"], redis_client=redis)
        assert passed is False

    @pytest.mark.asyncio
    async def test_empty_sample_passes(self):
        redis = MagicMock()
        passed = await verify_vault_integrity(BANK_ID, PEPPER, [], redis_client=redis)
        assert passed is True


# ---------------------------------------------------------------------------
# VaultSyncWorkflow.run_with_mocks
# ---------------------------------------------------------------------------

class TestVaultSyncWorkflowOrchestration:
    def _make_cbs(self, accounts=3):
        cbs = AsyncMock()
        cbs.list_signature_specimens.return_value = [
            {"account_number": f"ACC{i:03d}", "specimens": [b"s"]}
            for i in range(accounts)
        ]
        cbs.list_positive_pay_records.return_value = [
            {"account_number": f"ACC{i:03d}", "cheque_series_start": "100001",
             "amount": 1000.0, "payee": "Payee"}
            for i in range(accounts)
        ]
        return cbs

    def _make_redis(self):
        redis = MagicMock()
        pipe = MagicMock()
        redis.pipeline.return_value = pipe
        pipe.execute.return_value = None
        redis.llen.return_value = 1   # all keys present
        return redis

    @pytest.mark.asyncio
    async def test_sync_complete_outcome(self):
        wf = VaultSyncWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            cbs_connector=self._make_cbs(),
            redis_client=self._make_redis(),
            sample_accounts=["ACC000"],
        )
        assert result.outcome == "SYNC_COMPLETE"

    @pytest.mark.asyncio
    async def test_counts_signatures(self):
        wf = VaultSyncWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            cbs_connector=self._make_cbs(accounts=5),
            redis_client=self._make_redis(),
            sample_accounts=[],
        )
        assert result.signatures_loaded == 5

    @pytest.mark.asyncio
    async def test_counts_pps_records(self):
        wf = VaultSyncWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            cbs_connector=self._make_cbs(accounts=3),
            redis_client=self._make_redis(),
            sample_accounts=[],
        )
        assert result.pps_records_loaded == 3

    @pytest.mark.asyncio
    async def test_integrity_check_passed(self):
        wf = VaultSyncWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            cbs_connector=self._make_cbs(),
            redis_client=self._make_redis(),
            sample_accounts=["ACC000"],
        )
        assert result.integrity_check_passed is True

    @pytest.mark.asyncio
    async def test_partial_failure_when_signature_load_fails(self):
        cbs = AsyncMock()
        cbs.list_signature_specimens.side_effect = Exception("CBS down")
        wf = VaultSyncWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            cbs_connector=cbs,
            redis_client=self._make_redis(),
        )
        assert result.outcome == "PARTIAL_FAILURE"
        assert result.signatures_loaded == 0

    @pytest.mark.asyncio
    async def test_partial_failure_when_pps_load_fails(self):
        cbs = AsyncMock()
        cbs.list_signature_specimens.return_value = [
            {"account_number": "ACC001", "specimens": [b"s"]}
        ]
        cbs.list_positive_pay_records.side_effect = Exception("PPS timeout")
        wf = VaultSyncWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            cbs_connector=cbs,
            redis_client=self._make_redis(),
        )
        assert result.outcome == "PARTIAL_FAILURE"
        assert result.pps_records_loaded == 0

    @pytest.mark.asyncio
    async def test_integrity_check_in_result(self):
        redis = self._make_redis()
        redis.llen.return_value = 0   # all keys missing → integrity fails
        wf = VaultSyncWorkflow()
        result = await wf.run_with_mocks(
            _make_input(),
            cbs_connector=self._make_cbs(accounts=1),
            redis_client=redis,
            sample_accounts=["ACC000"],
        )
        assert result.integrity_check_passed is False
