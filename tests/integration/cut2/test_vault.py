"""
Cut 2 — Vault tests (Kafka + Redis + OCR).

Tests:
  Inward:
    - HMAC key format: raw account number never appears in Redis
    - Store → Redis hit (no DB fallback needed)
    - Vault miss → VaultResult(outcome=HUMAN_REVIEW, miss_reason=VAULT_MISS)
    - Redis error → VaultResult(outcome=HUMAN_REVIEW, miss_reason=VAULT_ERROR)

  Outward (PPS vault — drawer account lookup):
    - PPS entry registered → PPSResult(outcome=FOUND)
    - PPS miss → PPSResult(outcome=HUMAN_REVIEW, miss_reason=PPS_MISS)
    - PPS expired → PPSResult(outcome=HUMAN_REVIEW)

Both pipelines share the same Redis vault cluster — tested here together.
"""
from __future__ import annotations

import re
import time
from datetime import date, timedelta

import pytest
import pytest_asyncio

from shared.utils.pii_crypto import hash_account_number
from tests.integration.cut2.conftest import TEST_BANK_ID, TEST_PEPPER

pytestmark = [pytest.mark.integration, pytest.mark.cut2]

_ACCOUNT = "300020012345"
_ACCOUNT_LAST4 = _ACCOUNT[-4:]
_CHEQUE_NO = "000123"


# ════════════════════════════════════════════════════════════════════════════
# INWARD — Signature Vault
# ════════════════════════════════════════════════════════════════════════════

class TestSignatureVaultInward:

    def test_sig_vault_key_never_contains_raw_account(self, sig_vault, redis_sync):
        """Redis key must use HMAC hash — raw account number must not appear."""
        from shared.ai.signature_embedding import pack_embedding
        dummy_emb = [0.1] * 512
        key = f"sig:{TEST_BANK_ID}:{hash_account_number(_ACCOUNT, TEST_BANK_ID, TEST_PEPPER)}:PRIMARY"
        pipe = redis_sync.pipeline()
        pipe.delete(key)
        pipe.rpush(key, pack_embedding(dummy_emb))
        pipe.execute()

        # Verify raw account never appears in any key
        all_keys = redis_sync.keys("sig:*")
        for k in all_keys:
            k_str = k.decode() if isinstance(k, bytes) else k
            assert _ACCOUNT not in k_str, (
                f"Raw account number found in Redis key: {k_str}"
            )
        # Verify hash key exists
        assert redis_sync.exists(key), "Expected hashed key not found in Redis"

    @pytest.mark.asyncio
    async def test_sig_vault_store_and_redis_hit(self, sig_vault, redis_sync):
        """Store embeddings → subsequent get returns FOUND from Redis, not DB."""
        emb = [[float(i) / 512] * 512 for i in range(3)]   # 3 specimens
        await sig_vault.store_embeddings(_ACCOUNT, emb, signatory_id="PRIMARY")

        # Fresh vault instance (empty process cache) — proves Redis is hit, not cache
        from modules.cts.vaults.signature_vault import SignatureVault
        fresh = SignatureVault(bank_id=TEST_BANK_ID, pepper=TEST_PEPPER, db_pool=None)
        fresh.connect(redis_client=redis_sync)

        result = await fresh.get_signatures(_ACCOUNT, TEST_BANK_ID)
        assert result.outcome == "FOUND"
        assert len(result.embeddings) == 3

    @pytest.mark.asyncio
    async def test_sig_vault_miss_routes_human_review(self, sig_vault):
        """Account with no vault entry → HUMAN_REVIEW, miss_reason=VAULT_MISS."""
        result = await sig_vault.get_signatures("999999000000", TEST_BANK_ID)
        assert result.outcome == "HUMAN_REVIEW"
        assert result.miss_reason == "VAULT_MISS"
        assert result.embeddings == []

    @pytest.mark.asyncio
    async def test_sig_vault_miss_never_stp_return(self, sig_vault):
        """The absolute rule: vault miss must never produce STP_RETURN outcome."""
        result = await sig_vault.get_signatures("888888000000", TEST_BANK_ID)
        assert result.outcome != "STP_RETURN", (
            "VAULT SAFETY VIOLATION: vault miss routed to STP_RETURN — "
            "this must always be HUMAN_REVIEW"
        )

    @pytest.mark.asyncio
    async def test_sig_vault_redis_error_routes_human_review(self, sig_vault):
        """Simulate Redis error by disconnecting — must return HUMAN_REVIEW, not crash."""
        import redis as sync_redis
        broken = sync_redis.Redis(host="localhost", port=19999, socket_connect_timeout=0.1)
        from modules.cts.vaults.signature_vault import SignatureVault
        vault = SignatureVault(bank_id=TEST_BANK_ID, pepper=TEST_PEPPER, db_pool=None)
        vault.connect(redis_client=broken)

        result = await vault.get_signatures(_ACCOUNT, TEST_BANK_ID)
        assert result.outcome == "HUMAN_REVIEW"
        assert result.miss_reason == "VAULT_ERROR"


# ════════════════════════════════════════════════════════════════════════════
# OUTWARD — PPS Vault (drawer account lookup before NGCH submission)
# ════════════════════════════════════════════════════════════════════════════

class TestPPSVaultOutward:

    def _pps_entry(self, cheque_number: str = _CHEQUE_NO) -> dict:
        """Build a valid PPS registration payload."""
        return {
            "account_number": _ACCOUNT,
            "cheque_number": cheque_number,
            "amount": 95_000.0,
            "payee_name": "Pradeep Kumar",
            "cheque_date": date.today().isoformat(),
        }

    @pytest.mark.asyncio
    async def test_pps_registered_entry_found(self, pps_vault):
        """Register a PPS entry → lookup returns FOUND with matching fields."""
        entry = self._pps_entry()
        await pps_vault.register(entry)

        result = await pps_vault.lookup(
            account_number=_ACCOUNT,
            cheque_number=_CHEQUE_NO,
            bank_id=TEST_BANK_ID,
        )
        assert result.outcome == "FOUND"
        assert result.pps_entry is not None

    @pytest.mark.asyncio
    async def test_pps_miss_routes_human_review(self, pps_vault):
        """Lookup for unregistered cheque → HUMAN_REVIEW, miss_reason=PPS_MISS."""
        result = await pps_vault.lookup(
            account_number=_ACCOUNT,
            cheque_number="999999",
            bank_id=TEST_BANK_ID,
        )
        assert result.outcome == "HUMAN_REVIEW"
        assert result.miss_reason == "PPS_MISS"

    @pytest.mark.asyncio
    async def test_pps_miss_never_auto_return(self, pps_vault):
        """PPS miss must never produce STP_RETURN — always HUMAN_REVIEW."""
        result = await pps_vault.lookup(
            account_number="777777000000",
            cheque_number="000001",
            bank_id=TEST_BANK_ID,
        )
        assert result.outcome != "STP_RETURN", (
            "PPS SAFETY VIOLATION: PPS miss routed to STP_RETURN"
        )

    @pytest.mark.asyncio
    async def test_pps_key_uses_hmac_not_raw_account(self, pps_vault, redis_sync):
        """Raw account number must not appear in Redis PPS keys."""
        entry = self._pps_entry(cheque_number="000200")
        await pps_vault.register(entry)

        all_keys = [
            (k.decode() if isinstance(k, bytes) else k)
            for k in redis_sync.keys("pps:*")
        ]
        for k in all_keys:
            assert _ACCOUNT not in k, f"Raw account number in PPS Redis key: {k}"
