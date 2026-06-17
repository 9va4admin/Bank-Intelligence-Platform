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
