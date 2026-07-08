"""
Tests for modules/cts/workflows/activities/signature.py

Siamese network verifies presented signature against vault specimens.
Vault miss → HUMAN_REVIEW (never auto-return — vault invariant).
Low match score → HUMAN_REVIEW.
Model unavailable → HUMAN_REVIEW.
"""
from unittest.mock import AsyncMock, MagicMock
import pytest


def _make_input(instrument_id="INST001", bank_id="test-bank", account_number="1234567890"):
    from modules.cts.workflows.activities.signature import SignatureActivityInput
    return SignatureActivityInput(
        instrument_id=instrument_id,
        bank_id=bank_id,
        account_number=account_number,
        signature_image_url="s3://bucket/INST001_sig.jpg",
    )


class TestSignatureInput:
    def test_requires_instrument_id(self):
        from modules.cts.workflows.activities.signature import SignatureActivityInput
        with pytest.raises(Exception):
            SignatureActivityInput(bank_id="b", account_number="123", signature_image_url="s3://x")

    def test_is_frozen(self):
        inp = _make_input()
        with pytest.raises(Exception):
            inp.account_number = "9999"


class TestSignatureVaultMiss:
    @pytest.mark.asyncio
    async def test_vault_miss_outcome_human_review(self):
        """CRITICAL: no specimens in vault → HUMAN_REVIEW, never auto-return."""
        from modules.cts.workflows.activities.signature import verify_signature
        from modules.cts.vaults.signature_vault import VaultResult

        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(
            return_value=VaultResult(outcome="HUMAN_REVIEW", specimens=[], miss_reason="VAULT_MISS")
        )
        mock_model = AsyncMock()

        result = await verify_signature(_make_input(), vault=mock_vault, model=mock_model, min_match_score=0.80)
        assert result.outcome == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_vault_miss_model_not_called(self):
        """If vault has no specimens, skip model call entirely."""
        from modules.cts.workflows.activities.signature import verify_signature
        from modules.cts.vaults.signature_vault import VaultResult

        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(
            return_value=VaultResult(outcome="HUMAN_REVIEW", specimens=[], miss_reason="VAULT_MISS")
        )
        mock_model = AsyncMock()

        await verify_signature(_make_input(), vault=mock_vault, model=mock_model, min_match_score=0.80)
        mock_model.compare.assert_not_called()

    @pytest.mark.asyncio
    async def test_vault_miss_reason_propagated(self):
        from modules.cts.workflows.activities.signature import verify_signature
        from modules.cts.vaults.signature_vault import VaultResult

        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(
            return_value=VaultResult(outcome="HUMAN_REVIEW", specimens=[], miss_reason="VAULT_MISS")
        )
        mock_model = AsyncMock()

        result = await verify_signature(_make_input(), vault=mock_vault, model=mock_model, min_match_score=0.80)
        assert "VAULT_MISS" in result.miss_reason

    @pytest.mark.asyncio
    async def test_vault_error_outcome_human_review(self):
        from modules.cts.workflows.activities.signature import verify_signature
        from modules.cts.vaults.signature_vault import VaultResult

        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(
            return_value=VaultResult(outcome="HUMAN_REVIEW", specimens=[], miss_reason="VAULT_ERROR")
        )
        mock_model = AsyncMock()

        result = await verify_signature(_make_input(), vault=mock_vault, model=mock_model, min_match_score=0.80)
        assert result.outcome == "HUMAN_REVIEW"


class TestSignatureMatch:
    @pytest.mark.asyncio
    async def test_high_match_score_outcome_proceed(self):
        from modules.cts.workflows.activities.signature import verify_signature
        from modules.cts.vaults.signature_vault import VaultResult

        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(
            return_value=VaultResult(outcome="FOUND", specimens=[b"specimen1", b"specimen2"])
        )
        mock_model = AsyncMock()
        mock_model.compare = AsyncMock(return_value={"best_match_score": 0.96, "scores": [0.96, 0.94]})

        result = await verify_signature(_make_input(), vault=mock_vault, model=mock_model, min_match_score=0.80)
        assert result.outcome == "PROCEED"

    @pytest.mark.asyncio
    async def test_high_match_returns_score(self):
        from modules.cts.workflows.activities.signature import verify_signature
        from modules.cts.vaults.signature_vault import VaultResult

        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(
            return_value=VaultResult(outcome="FOUND", specimens=[b"s1"])
        )
        mock_model = AsyncMock()
        mock_model.compare = AsyncMock(return_value={"best_match_score": 0.93, "scores": [0.93]})

        result = await verify_signature(_make_input(), vault=mock_vault, model=mock_model, min_match_score=0.80)
        assert result.match_score == 0.93

    @pytest.mark.asyncio
    async def test_low_match_score_outcome_human_review(self):
        from modules.cts.workflows.activities.signature import verify_signature
        from modules.cts.vaults.signature_vault import VaultResult

        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(
            return_value=VaultResult(outcome="FOUND", specimens=[b"s1"])
        )
        mock_model = AsyncMock()
        mock_model.compare = AsyncMock(return_value={"best_match_score": 0.55, "scores": [0.55]})

        result = await verify_signature(_make_input(), vault=mock_vault, model=mock_model, min_match_score=0.80)
        assert result.outcome == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_threshold_from_parameter(self):
        """min_match_score changes decision — not hardcoded."""
        from modules.cts.workflows.activities.signature import verify_signature
        from modules.cts.vaults.signature_vault import VaultResult

        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(
            return_value=VaultResult(outcome="FOUND", specimens=[b"s1"])
        )
        mock_model = AsyncMock()
        mock_model.compare = AsyncMock(return_value={"best_match_score": 0.75, "scores": [0.75]})

        result_pass = await verify_signature(_make_input(), vault=mock_vault, model=mock_model, min_match_score=0.70)
        mock_model.compare = AsyncMock(return_value={"best_match_score": 0.75, "scores": [0.75]})
        result_fail = await verify_signature(_make_input(), vault=mock_vault, model=mock_model, min_match_score=0.80)

        assert result_pass.outcome == "PROCEED"
        assert result_fail.outcome == "HUMAN_REVIEW"


class TestSignatureSMBProxyRouting:
    """Phase 4 — when smb_id is set and smb_proxy provided, use proxy instead of vault."""

    def _make_smb_input(self):
        from modules.cts.workflows.activities.signature import SignatureActivityInput
        return SignatureActivityInput(
            instrument_id="INST-SMB-001",
            bank_id="saraswat-coop",
            account_number="9876543210",
            signature_image_url="s3://bucket/INST-SMB-001_sig.jpg",
            smb_id="cosmos-coop",
        )

    @pytest.mark.asyncio
    async def test_smb_proxy_called_when_smb_id_set(self):
        """Proxy get_signature is called when smb_id is on the input and proxy provided."""
        from modules.cts.workflows.activities.signature import verify_signature
        from modules.cts.vaults.signature_vault import VaultResult

        mock_proxy = AsyncMock()
        mock_proxy.get_signature = AsyncMock(
            return_value=VaultResult(outcome="FOUND", specimens=[b"smb_specimen"])
        )
        mock_model = AsyncMock()
        mock_model.compare = AsyncMock(return_value={"best_match_score": 0.91})
        mock_vault = AsyncMock()

        result = await verify_signature(self._make_smb_input(), vault=mock_vault, model=mock_model,
                                        min_match_score=0.80, smb_proxy=mock_proxy)

        mock_proxy.get_signature.assert_called_once()
        assert result.outcome == "PROCEED"

    @pytest.mark.asyncio
    async def test_smb_proxy_call_passes_correct_args(self):
        """Proxy is called with account_number, bank_id, smb_id from the input."""
        from modules.cts.workflows.activities.signature import verify_signature
        from modules.cts.vaults.signature_vault import VaultResult

        mock_proxy = AsyncMock()
        mock_proxy.get_signature = AsyncMock(
            return_value=VaultResult(outcome="FOUND", specimens=[b"s"])
        )
        mock_model = AsyncMock()
        mock_model.compare = AsyncMock(return_value={"best_match_score": 0.90})

        inp = self._make_smb_input()
        await verify_signature(inp, vault=AsyncMock(), model=mock_model,
                               min_match_score=0.80, smb_proxy=mock_proxy)

        mock_proxy.get_signature.assert_called_once_with(
            inp.account_number, inp.bank_id, inp.smb_id
        )

    @pytest.mark.asyncio
    async def test_vault_not_called_when_smb_proxy_used(self):
        """Local vault.get_signatures must NOT be called when proxy handles the request."""
        from modules.cts.workflows.activities.signature import verify_signature
        from modules.cts.vaults.signature_vault import VaultResult

        mock_proxy = AsyncMock()
        mock_proxy.get_signature = AsyncMock(
            return_value=VaultResult(outcome="FOUND", specimens=[b"s"])
        )
        mock_model = AsyncMock()
        mock_model.compare = AsyncMock(return_value={"best_match_score": 0.90})
        mock_vault = AsyncMock()

        await verify_signature(self._make_smb_input(), vault=mock_vault, model=mock_model,
                               min_match_score=0.80, smb_proxy=mock_proxy)

        mock_vault.get_signatures.assert_not_called()

    @pytest.mark.asyncio
    async def test_vault_used_when_smb_proxy_is_none(self):
        """When smb_proxy is None, always use local vault regardless of smb_id."""
        from modules.cts.workflows.activities.signature import verify_signature
        from modules.cts.vaults.signature_vault import VaultResult

        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(
            return_value=VaultResult(outcome="FOUND", specimens=[b"s"])
        )
        mock_model = AsyncMock()
        mock_model.compare = AsyncMock(return_value={"best_match_score": 0.90})

        # smb_proxy=None → must use vault even if smb_id is set
        result = await verify_signature(self._make_smb_input(), vault=mock_vault,
                                        model=mock_model, min_match_score=0.80, smb_proxy=None)

        mock_vault.get_signatures.assert_called_once()
        assert result.outcome == "PROCEED"

    @pytest.mark.asyncio
    async def test_vault_used_when_smb_id_none_even_if_proxy_provided(self):
        """When smb_id is None (SB instrument), use vault — never call proxy."""
        from modules.cts.workflows.activities.signature import verify_signature, SignatureActivityInput
        from modules.cts.vaults.signature_vault import VaultResult

        sb_input = SignatureActivityInput(
            instrument_id="INST-SB-001",
            bank_id="saraswat-coop",
            account_number="1111111111",
            signature_image_url="s3://bucket/sig.jpg",
            # smb_id not set → None by default
        )
        mock_proxy = AsyncMock()
        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(
            return_value=VaultResult(outcome="FOUND", specimens=[b"s"])
        )
        mock_model = AsyncMock()
        mock_model.compare = AsyncMock(return_value={"best_match_score": 0.90})

        await verify_signature(sb_input, vault=mock_vault, model=mock_model,
                               min_match_score=0.80, smb_proxy=mock_proxy)

        mock_proxy.get_signature.assert_not_called()
        mock_vault.get_signatures.assert_called_once()

    @pytest.mark.asyncio
    async def test_smb_proxy_miss_human_review(self):
        """Vault invariant applies to proxy: proxy HUMAN_REVIEW → HUMAN_REVIEW outcome."""
        from modules.cts.workflows.activities.signature import verify_signature
        from modules.cts.vaults.signature_vault import VaultResult

        mock_proxy = AsyncMock()
        mock_proxy.get_signature = AsyncMock(
            return_value=VaultResult(outcome="HUMAN_REVIEW", specimens=[], miss_reason="SMB_NO_SPECIMENS")
        )
        mock_model = AsyncMock()

        result = await verify_signature(self._make_smb_input(), vault=AsyncMock(), model=mock_model,
                                        min_match_score=0.80, smb_proxy=mock_proxy)

        assert result.outcome == "HUMAN_REVIEW"
        mock_model.compare.assert_not_called()

    @pytest.mark.asyncio
    async def test_smb_proxy_unavailable_human_review(self):
        """Proxy raises exception → HUMAN_REVIEW (degraded, never crash or auto-return)."""
        from modules.cts.workflows.activities.signature import verify_signature

        mock_proxy = AsyncMock()
        mock_proxy.get_signature = AsyncMock(side_effect=Exception("MCP proxy unreachable"))
        mock_model = AsyncMock()

        result = await verify_signature(self._make_smb_input(), vault=AsyncMock(), model=mock_model,
                                        min_match_score=0.80, smb_proxy=mock_proxy)

        assert result.outcome == "HUMAN_REVIEW"
        assert result.degraded is True

    @pytest.mark.asyncio
    async def test_smb_proxy_unavailable_miss_reason(self):
        """Proxy failure miss_reason contains SMB_PROXY_UNAVAILABLE."""
        from modules.cts.workflows.activities.signature import verify_signature

        mock_proxy = AsyncMock()
        mock_proxy.get_signature = AsyncMock(side_effect=TimeoutError("MCP timeout"))

        result = await verify_signature(self._make_smb_input(), vault=AsyncMock(), model=AsyncMock(),
                                        min_match_score=0.80, smb_proxy=mock_proxy)

        assert "SMB_PROXY_UNAVAILABLE" in result.miss_reason


class TestSignatureModelDegradation:
    @pytest.mark.asyncio
    async def test_model_unavailable_outcome_human_review(self):
        from modules.cts.workflows.activities.signature import verify_signature
        from modules.cts.vaults.signature_vault import VaultResult

        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(
            return_value=VaultResult(outcome="FOUND", specimens=[b"s1"])
        )
        mock_model = AsyncMock()
        mock_model.compare = AsyncMock(side_effect=Exception("Siamese model unavailable"))

        result = await verify_signature(_make_input(), vault=mock_vault, model=mock_model, min_match_score=0.80)
        assert result.outcome == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_model_unavailable_does_not_raise(self):
        from modules.cts.workflows.activities.signature import verify_signature
        from modules.cts.vaults.signature_vault import VaultResult

        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(
            return_value=VaultResult(outcome="FOUND", specimens=[b"s1"])
        )
        mock_model = AsyncMock()
        mock_model.compare = AsyncMock(side_effect=TimeoutError("GPU timeout"))

        result = await verify_signature(_make_input(), vault=mock_vault, model=mock_model, min_match_score=0.80)
        assert result is not None

    @pytest.mark.asyncio
    async def test_model_unavailable_degraded_flag(self):
        from modules.cts.workflows.activities.signature import verify_signature
        from modules.cts.vaults.signature_vault import VaultResult

        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(
            return_value=VaultResult(outcome="FOUND", specimens=[b"s1"])
        )
        mock_model = AsyncMock()
        mock_model.compare = AsyncMock(side_effect=RuntimeError("CUDA OOM"))

        result = await verify_signature(_make_input(), vault=mock_vault, model=mock_model, min_match_score=0.80)
        assert result.degraded is True


# ---------------------------------------------------------------------------
# Multi-signature detection — multiple ink marks on cheque → HUMAN_REVIEW
# ---------------------------------------------------------------------------

def _make_input_with_sig_count(sig_count: int):
    from modules.cts.workflows.activities.signature import SignatureActivityInput
    return SignatureActivityInput(
        instrument_id="INST-MULTI-001",
        bank_id="test-bank",
        account_number="1234567890",
        signature_image_url="s3://bucket/INST-MULTI-001_sig.jpg",
        sig_count=sig_count,
    )


class TestSignatureMultiSigDetected:
    @pytest.mark.asyncio
    async def test_single_sig_count_proceeds_to_vault(self):
        """sig_count=1 (default) — normal vault lookup proceeds."""
        from modules.cts.workflows.activities.signature import verify_signature
        from modules.cts.vaults.signature_vault import VaultResult

        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(
            return_value=VaultResult(outcome="FOUND", specimens=[b"s1"])
        )
        mock_model = AsyncMock()
        mock_model.compare = AsyncMock(return_value={"best_match_score": 0.92})

        result = await verify_signature(
            _make_input_with_sig_count(1), vault=mock_vault, model=mock_model, min_match_score=0.80
        )
        mock_vault.get_signatures.assert_called_once()
        assert result.outcome == "PROCEED"

    @pytest.mark.asyncio
    async def test_two_signatures_routes_to_human_review(self):
        """sig_count=2 → HUMAN_REVIEW with MULTI_SIGNATURE_DETECTED."""
        from modules.cts.workflows.activities.signature import verify_signature

        mock_vault = AsyncMock()
        mock_model = AsyncMock()

        result = await verify_signature(
            _make_input_with_sig_count(2), vault=mock_vault, model=mock_model, min_match_score=0.80
        )
        assert result.outcome == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_three_signatures_routes_to_human_review(self):
        """sig_count=3 — same gate; any count > 1 triggers HUMAN_REVIEW."""
        from modules.cts.workflows.activities.signature import verify_signature

        result = await verify_signature(
            _make_input_with_sig_count(3), vault=AsyncMock(), model=AsyncMock(), min_match_score=0.80
        )
        assert result.outcome == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_multi_sig_miss_reason_contains_flag(self):
        """miss_reason must contain MULTI_SIGNATURE_DETECTED so downstream HRQ shows correct label."""
        from modules.cts.workflows.activities.signature import verify_signature

        result = await verify_signature(
            _make_input_with_sig_count(2), vault=AsyncMock(), model=AsyncMock(), min_match_score=0.80
        )
        assert "MULTI_SIGNATURE_DETECTED" in result.miss_reason

    @pytest.mark.asyncio
    async def test_multi_sig_vault_not_called(self):
        """Vault must not be queried when multiple signatures are detected."""
        from modules.cts.workflows.activities.signature import verify_signature

        mock_vault = AsyncMock()
        await verify_signature(
            _make_input_with_sig_count(2), vault=mock_vault, model=AsyncMock(), min_match_score=0.80
        )
        mock_vault.get_signatures.assert_not_called()

    @pytest.mark.asyncio
    async def test_multi_sig_model_not_called(self):
        """Model must not be invoked when multiple signatures are detected."""
        from modules.cts.workflows.activities.signature import verify_signature

        mock_model = AsyncMock()
        await verify_signature(
            _make_input_with_sig_count(2), vault=AsyncMock(), model=mock_model, min_match_score=0.80
        )
        mock_model.compare.assert_not_called()


# ---------------------------------------------------------------------------
# CBS fallback — vault miss triggers CBS specimen fetch
# ---------------------------------------------------------------------------

class TestSignatureCBSFallback:
    def _vault_miss(self):
        from modules.cts.vaults.signature_vault import VaultResult
        return VaultResult(outcome="HUMAN_REVIEW", specimens=[], miss_reason="VAULT_MISS")

    def _vault_error(self):
        from modules.cts.vaults.signature_vault import VaultResult
        return VaultResult(outcome="HUMAN_REVIEW", specimens=[], miss_reason="VAULT_ERROR")

    @pytest.mark.asyncio
    async def test_cbs_called_on_vault_miss(self):
        """Vault miss → CBS connector queried as fallback."""
        from modules.cts.workflows.activities.signature import verify_signature

        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(return_value=self._vault_miss())
        mock_vault.store_signatures = AsyncMock()
        mock_cbs = AsyncMock()
        mock_cbs.get_signature_specimens = AsyncMock(return_value=[b"cbs_s1"])
        mock_model = AsyncMock()
        mock_model.compare = AsyncMock(return_value={"best_match_score": 0.91})

        await verify_signature(
            _make_input(), vault=mock_vault, model=mock_model,
            min_match_score=0.80, cbs_connector=mock_cbs
        )
        mock_cbs.get_signature_specimens.assert_called_once()

    @pytest.mark.asyncio
    async def test_cbs_not_called_on_vault_error(self):
        """VAULT_ERROR (Redis down) does NOT trigger CBS fallback — only VAULT_MISS does."""
        from modules.cts.workflows.activities.signature import verify_signature

        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(return_value=self._vault_error())
        mock_cbs = AsyncMock()

        await verify_signature(
            _make_input(), vault=mock_vault, model=AsyncMock(),
            min_match_score=0.80, cbs_connector=mock_cbs
        )
        mock_cbs.get_signature_specimens.assert_not_called()

    @pytest.mark.asyncio
    async def test_cbs_not_called_when_no_connector(self):
        """No cbs_connector → vault miss produces standard HUMAN_REVIEW, no CBS attempt."""
        from modules.cts.workflows.activities.signature import verify_signature

        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(return_value=self._vault_miss())

        result = await verify_signature(
            _make_input(), vault=mock_vault, model=AsyncMock(),
            min_match_score=0.80, cbs_connector=None
        )
        assert result.outcome == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_cbs_specimens_stored_in_vault(self):
        """CBS specimens must be written to vault so subsequent cheques avoid CBS hit."""
        from modules.cts.workflows.activities.signature import verify_signature

        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(return_value=self._vault_miss())
        mock_vault.store_signatures = AsyncMock()
        mock_cbs = AsyncMock()
        mock_cbs.get_signature_specimens = AsyncMock(return_value=[b"cbs_s1", b"cbs_s2"])
        mock_model = AsyncMock()
        mock_model.compare = AsyncMock(return_value={"best_match_score": 0.89})

        await verify_signature(
            _make_input(), vault=mock_vault, model=mock_model,
            min_match_score=0.80, cbs_connector=mock_cbs
        )
        mock_vault.store_signatures.assert_called_once()
        stored_specimens = mock_vault.store_signatures.call_args[0][1]
        assert stored_specimens == [b"cbs_s1", b"cbs_s2"]

    @pytest.mark.asyncio
    async def test_cbs_fallback_proceeds_when_specimens_found(self):
        """CBS returns specimens → compare runs → high score → PROCEED."""
        from modules.cts.workflows.activities.signature import verify_signature

        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(return_value=self._vault_miss())
        mock_vault.store_signatures = AsyncMock()
        mock_cbs = AsyncMock()
        mock_cbs.get_signature_specimens = AsyncMock(return_value=[b"cbs_spec"])
        mock_model = AsyncMock()
        mock_model.compare = AsyncMock(return_value={"best_match_score": 0.95})

        result = await verify_signature(
            _make_input(), vault=mock_vault, model=mock_model,
            min_match_score=0.80, cbs_connector=mock_cbs
        )
        assert result.outcome == "PROCEED"

    @pytest.mark.asyncio
    async def test_cbs_fallback_human_review_on_empty_cbs(self):
        """CBS returns empty list → HUMAN_REVIEW with NO_SIGNATURE_IN_VAULT."""
        from modules.cts.workflows.activities.signature import verify_signature

        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(return_value=self._vault_miss())
        mock_cbs = AsyncMock()
        mock_cbs.get_signature_specimens = AsyncMock(return_value=[])

        result = await verify_signature(
            _make_input(), vault=mock_vault, model=AsyncMock(),
            min_match_score=0.80, cbs_connector=mock_cbs
        )
        assert result.outcome == "HUMAN_REVIEW"
        assert "NO_SIGNATURE_IN_VAULT" in result.miss_reason

    @pytest.mark.asyncio
    async def test_cbs_fallback_human_review_on_cbs_error(self):
        """CBS connector raises → HUMAN_REVIEW (degraded), never crash."""
        from modules.cts.workflows.activities.signature import verify_signature

        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(return_value=self._vault_miss())
        mock_cbs = AsyncMock()
        mock_cbs.get_signature_specimens = AsyncMock(side_effect=Exception("CBS timeout"))

        result = await verify_signature(
            _make_input(), vault=mock_vault, model=AsyncMock(),
            min_match_score=0.80, cbs_connector=mock_cbs
        )
        assert result.outcome == "HUMAN_REVIEW"
        assert result.degraded is True

    @pytest.mark.asyncio
    async def test_cbs_fallback_result_flags_cbs_used(self):
        """When CBS fallback is used successfully, result.cbs_fallback_used = True."""
        from modules.cts.workflows.activities.signature import verify_signature

        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(return_value=self._vault_miss())
        mock_vault.store_signatures = AsyncMock()
        mock_cbs = AsyncMock()
        mock_cbs.get_signature_specimens = AsyncMock(return_value=[b"spec"])
        mock_model = AsyncMock()
        mock_model.compare = AsyncMock(return_value={"best_match_score": 0.88})

        result = await verify_signature(
            _make_input(), vault=mock_vault, model=mock_model,
            min_match_score=0.80, cbs_connector=mock_cbs
        )
        assert result.cbs_fallback_used is True

    @pytest.mark.asyncio
    async def test_normal_vault_hit_cbs_fallback_not_set(self):
        """Normal vault hit → cbs_fallback_used must be False."""
        from modules.cts.workflows.activities.signature import verify_signature
        from modules.cts.vaults.signature_vault import VaultResult

        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(
            return_value=VaultResult(outcome="FOUND", specimens=[b"s1"])
        )
        mock_model = AsyncMock()
        mock_model.compare = AsyncMock(return_value={"best_match_score": 0.94})

        result = await verify_signature(
            _make_input(), vault=mock_vault, model=mock_model, min_match_score=0.80
        )
        assert result.cbs_fallback_used is False
