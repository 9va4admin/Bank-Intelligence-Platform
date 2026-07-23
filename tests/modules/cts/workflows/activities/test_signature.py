"""
Tests for modules/cts/workflows/activities/signature.py

Embedding-based comparison: cheque crop → SignatureEmbeddingModel.embed() →
cosine_similarity vs stored vault embeddings.

Critical invariants:
  - Vault miss → HUMAN_REVIEW, NEVER AUTO_RETURN
  - Embedding model unavailable → HUMAN_REVIEW (degraded)
  - Low cosine score → HUMAN_REVIEW
  - High cosine score → PROCEED
"""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

_DIM = 512


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unit_vec(dim: int = _DIM, axis: int = 0) -> list[float]:
    """Unit vector along `axis` — cosine with another unit vector = 1 if same, 0 if orthogonal."""
    v = [0.0] * dim
    v[axis] = 1.0
    return v


def _const_vec(val: float, dim: int = _DIM) -> list[float]:
    return [val] * dim


def _mock_config(min_match_score: float = 0.80):
    cfg = AsyncMock()
    cfg.get_ai_config = AsyncMock(return_value={"ai.signature.min_match_score": min_match_score})
    return cfg


def _make_input(
    instrument_id="INST001",
    bank_id="test-bank",
    account_number="1234567890",
    sig_count: int = 1,
    sig_bboxes=None,
    smb_id=None,
):
    from modules.cts.workflows.activities.signature import SignatureActivityInput
    return SignatureActivityInput(
        instrument_id=instrument_id,
        bank_id=bank_id,
        account_number=account_number,
        signature_image_url="s3://bucket/INST001_sig.jpg",
        sig_count=sig_count,
        sig_bboxes=sig_bboxes or [],
        smb_id=smb_id,
    )


def _vault_found(embeddings: list[list[float]] = None):
    from modules.cts.vaults.signature_vault import VaultResult
    return VaultResult(outcome="FOUND", embeddings=embeddings or [_unit_vec(axis=0)])


def _vault_miss():
    from modules.cts.vaults.signature_vault import VaultResult
    return VaultResult(outcome="HUMAN_REVIEW", embeddings=[], miss_reason="VAULT_MISS")


def _vault_error():
    from modules.cts.vaults.signature_vault import VaultResult
    return VaultResult(outcome="HUMAN_REVIEW", embeddings=[], miss_reason="VAULT_ERROR")


def _embed_model(return_vector: list[float] = None, raises=None):
    """Mock embedding model whose embed() returns return_vector or raises."""
    model = AsyncMock()
    if raises:
        model.embed = AsyncMock(side_effect=raises)
    else:
        model.embed = AsyncMock(return_value=return_vector or _unit_vec(axis=0))
    return model


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------

class TestSignatureInput:
    def test_requires_instrument_id(self):
        from modules.cts.workflows.activities.signature import SignatureActivityInput
        with pytest.raises(Exception):
            SignatureActivityInput(bank_id="b", account_number="123", signature_image_url="s3://x")

    def test_is_frozen(self):
        inp = _make_input()
        with pytest.raises(Exception):
            inp.account_number = "9999"


# ---------------------------------------------------------------------------
# Multi-signature gate
# ---------------------------------------------------------------------------

class TestMultiSigGate:
    @pytest.mark.asyncio
    async def test_two_sigs_routes_to_human_review(self):
        from modules.cts.workflows.activities.signature import verify_signature
        result = await verify_signature(
            _make_input(sig_count=2), vault=AsyncMock(),
            config_service=_mock_config(), embedding_model=_embed_model(),
        )
        assert result.outcome == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_multi_sig_miss_reason(self):
        from modules.cts.workflows.activities.signature import verify_signature
        result = await verify_signature(
            _make_input(sig_count=3), vault=AsyncMock(),
            config_service=_mock_config(), embedding_model=_embed_model(),
        )
        assert "MULTI_SIGNATURE_DETECTED" in result.miss_reason

    @pytest.mark.asyncio
    async def test_multi_sig_vault_not_called(self):
        from modules.cts.workflows.activities.signature import verify_signature
        mock_vault = AsyncMock()
        await verify_signature(
            _make_input(sig_count=2), vault=mock_vault,
            config_service=_mock_config(), embedding_model=_embed_model(),
        )
        mock_vault.get_signatures.assert_not_called()

    @pytest.mark.asyncio
    async def test_multi_sig_embed_not_called(self):
        from modules.cts.workflows.activities.signature import verify_signature
        model = _embed_model()
        await verify_signature(
            _make_input(sig_count=2), vault=AsyncMock(),
            config_service=_mock_config(), embedding_model=model,
        )
        model.embed.assert_not_called()


# ---------------------------------------------------------------------------
# Vault miss → HUMAN_REVIEW (NEVER AUTO_RETURN)
# ---------------------------------------------------------------------------

class TestVaultMiss:
    @pytest.mark.asyncio
    async def test_vault_miss_outcome_human_review(self):
        from modules.cts.workflows.activities.signature import verify_signature
        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(return_value=_vault_miss())
        result = await verify_signature(
            _make_input(), vault=mock_vault,
            config_service=_mock_config(), embedding_model=_embed_model(),
        )
        assert result.outcome == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_vault_miss_reason_propagated(self):
        from modules.cts.workflows.activities.signature import verify_signature
        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(return_value=_vault_miss())
        result = await verify_signature(
            _make_input(), vault=mock_vault,
            config_service=_mock_config(), embedding_model=_embed_model(),
        )
        assert "VAULT_MISS" in result.miss_reason

    @pytest.mark.asyncio
    async def test_vault_miss_never_auto_return(self):
        from modules.cts.workflows.activities.signature import verify_signature
        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(return_value=_vault_miss())
        result = await verify_signature(
            _make_input(), vault=mock_vault,
            config_service=_mock_config(), embedding_model=_embed_model(),
        )
        assert result.outcome != "AUTO_RETURN"

    @pytest.mark.asyncio
    async def test_vault_error_outcome_human_review(self):
        from modules.cts.workflows.activities.signature import verify_signature
        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(return_value=_vault_error())
        result = await verify_signature(
            _make_input(), vault=mock_vault,
            config_service=_mock_config(), embedding_model=_embed_model(),
        )
        assert result.outcome == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_vault_error_degraded_flag(self):
        from modules.cts.workflows.activities.signature import verify_signature
        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(return_value=_vault_error())
        result = await verify_signature(
            _make_input(), vault=mock_vault,
            config_service=_mock_config(), embedding_model=_embed_model(),
        )
        assert result.degraded is True


# ---------------------------------------------------------------------------
# Embedding-based match (cosine similarity)
# ---------------------------------------------------------------------------

class TestEmbeddingMatch:
    @pytest.mark.asyncio
    @patch("modules.cts.workflows.activities.signature._embed_image", new_callable=AsyncMock)
    async def test_same_vector_proceeds(self, mock_embed_image):
        """Cheque vector identical to stored → cosine = 1.0 → PROCEED."""
        from modules.cts.workflows.activities.signature import verify_signature
        v = _unit_vec(axis=0)
        mock_embed_image.return_value = v
        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(return_value=_vault_found([v]))
        result = await verify_signature(
            _make_input(), vault=mock_vault,
            config_service=_mock_config(0.80), embedding_model=_embed_model(v),
        )
        assert result.outcome == "PROCEED"

    @pytest.mark.asyncio
    @patch("modules.cts.workflows.activities.signature._embed_image", new_callable=AsyncMock)
    async def test_orthogonal_vector_human_review(self, mock_embed_image):
        """Cheque vector orthogonal to stored → cosine = 0.0 → HUMAN_REVIEW."""
        from modules.cts.workflows.activities.signature import verify_signature
        stored = _unit_vec(axis=0)
        cheque = _unit_vec(axis=1)  # orthogonal
        mock_embed_image.return_value = cheque
        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(return_value=_vault_found([stored]))
        result = await verify_signature(
            _make_input(), vault=mock_vault,
            config_service=_mock_config(0.80), embedding_model=_embed_model(cheque),
        )
        assert result.outcome == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    @patch("modules.cts.workflows.activities.signature._embed_image", new_callable=AsyncMock)
    async def test_best_of_multiple_specimens_used(self, mock_embed_image):
        """Best cosine score across all stored specimens is used."""
        from modules.cts.workflows.activities.signature import verify_signature
        v = _unit_vec(axis=0)
        orthogonal = _unit_vec(axis=1)
        cheque = _unit_vec(axis=0)   # matches v exactly
        mock_embed_image.return_value = cheque
        # Two stored: one orthogonal (score=0), one matching (score=1)
        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(return_value=_vault_found([orthogonal, v]))
        result = await verify_signature(
            _make_input(), vault=mock_vault,
            config_service=_mock_config(0.80), embedding_model=_embed_model(cheque),
        )
        assert result.outcome == "PROCEED"

    @pytest.mark.asyncio
    @patch("modules.cts.workflows.activities.signature._embed_image", new_callable=AsyncMock)
    async def test_match_score_returned(self, mock_embed_image):
        from modules.cts.workflows.activities.signature import verify_signature
        v = _const_vec(1.0)
        mock_embed_image.return_value = v
        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(return_value=_vault_found([v]))
        result = await verify_signature(
            _make_input(), vault=mock_vault,
            config_service=_mock_config(0.50), embedding_model=_embed_model(v),
        )
        assert result.match_score is not None
        assert result.match_score > 0.99

    @pytest.mark.asyncio
    async def test_no_embedding_model_human_review(self):
        """embedding_model=None → HUMAN_REVIEW (degraded) even when vault has embeddings."""
        from modules.cts.workflows.activities.signature import verify_signature
        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(return_value=_vault_found())
        result = await verify_signature(
            _make_input(), vault=mock_vault,
            config_service=_mock_config(), embedding_model=None,
        )
        assert result.outcome == "HUMAN_REVIEW"
        assert result.degraded is True

    @pytest.mark.asyncio
    @patch("modules.cts.workflows.activities.signature._embed_image", new_callable=AsyncMock)
    async def test_embed_failure_human_review(self, mock_embed_image):
        """_embed_image returns None (crop/embed failed) → HUMAN_REVIEW (degraded)."""
        from modules.cts.workflows.activities.signature import verify_signature
        mock_embed_image.return_value = None
        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(return_value=_vault_found())
        result = await verify_signature(
            _make_input(), vault=mock_vault,
            config_service=_mock_config(), embedding_model=_embed_model(),
        )
        assert result.outcome == "HUMAN_REVIEW"
        assert result.degraded is True

    @pytest.mark.asyncio
    @patch("modules.cts.workflows.activities.signature._embed_image", new_callable=AsyncMock)
    async def test_threshold_from_config(self, mock_embed_image):
        """Decision boundary moves with threshold — never hardcoded."""
        from modules.cts.workflows.activities.signature import verify_signature
        from shared.ai.signature_embedding import cosine_similarity
        # Two vectors with known cosine ~0.75
        v1 = [1.0, 1.0, 0.0] + [0.0] * (_DIM - 3)
        v2 = [1.0, 0.0, 0.0] + [0.0] * (_DIM - 3)
        score = cosine_similarity(v1, v2)
        mock_embed_image.return_value = v2
        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(return_value=_vault_found([v1]))

        result_pass = await verify_signature(
            _make_input(), vault=mock_vault, config_service=_mock_config(score - 0.05),
            embedding_model=_embed_model(v2),
        )
        result_fail = await verify_signature(
            _make_input(), vault=mock_vault, config_service=_mock_config(score + 0.05),
            embedding_model=_embed_model(v2),
        )
        assert result_pass.outcome == "PROCEED"
        assert result_fail.outcome == "HUMAN_REVIEW"


# ---------------------------------------------------------------------------
# CBS fallback — vault miss triggers CBS specimen fetch + embed + store
# ---------------------------------------------------------------------------

class TestCBSFallback:
    @pytest.mark.asyncio
    async def test_cbs_called_on_vault_miss(self):
        from modules.cts.workflows.activities.signature import verify_signature
        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(return_value=_vault_miss())
        mock_vault.store_embeddings = AsyncMock()
        mock_cbs = AsyncMock()
        mock_cbs.get_signature_specimens = AsyncMock(return_value=[b"cbs_img"])
        model = _embed_model(_unit_vec())
        with patch("modules.cts.workflows.activities.signature._embed_image",
                   new_callable=AsyncMock) as mock_ei:
            mock_ei.return_value = _unit_vec()
            await verify_signature(
                _make_input(), vault=mock_vault, config_service=_mock_config(0.80),
                embedding_model=model, cbs_connector=mock_cbs,
            )
        mock_cbs.get_signature_specimens.assert_called_once()

    @pytest.mark.asyncio
    async def test_cbs_not_called_on_vault_error(self):
        from modules.cts.workflows.activities.signature import verify_signature
        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(return_value=_vault_error())
        mock_cbs = AsyncMock()
        await verify_signature(
            _make_input(), vault=mock_vault, config_service=_mock_config(),
            embedding_model=_embed_model(), cbs_connector=mock_cbs,
        )
        mock_cbs.get_signature_specimens.assert_not_called()

    @pytest.mark.asyncio
    async def test_cbs_not_called_when_no_connector(self):
        from modules.cts.workflows.activities.signature import verify_signature
        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(return_value=_vault_miss())
        result = await verify_signature(
            _make_input(), vault=mock_vault, config_service=_mock_config(),
            embedding_model=_embed_model(), cbs_connector=None,
        )
        assert result.outcome == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_cbs_embeddings_stored_in_vault(self):
        """Embedded CBS specimens stored via store_embeddings (not store_signatures)."""
        from modules.cts.workflows.activities.signature import verify_signature
        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(return_value=_vault_miss())
        mock_vault.store_embeddings = AsyncMock()
        mock_cbs = AsyncMock()
        mock_cbs.get_signature_specimens = AsyncMock(return_value=[b"spec1", b"spec2"])
        model = _embed_model(_unit_vec())
        with patch("modules.cts.workflows.activities.signature._embed_image",
                   new_callable=AsyncMock) as mock_ei:
            mock_ei.return_value = _unit_vec()
            await verify_signature(
                _make_input(), vault=mock_vault, config_service=_mock_config(0.50),
                embedding_model=model, cbs_connector=mock_cbs,
            )
        mock_vault.store_embeddings.assert_called_once()

    @pytest.mark.asyncio
    async def test_cbs_fallback_proceeds_on_match(self):
        from modules.cts.workflows.activities.signature import verify_signature
        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(return_value=_vault_miss())
        mock_vault.store_embeddings = AsyncMock()
        mock_cbs = AsyncMock()
        mock_cbs.get_signature_specimens = AsyncMock(return_value=[b"spec"])
        v = _unit_vec()
        model = _embed_model(v)
        with patch("modules.cts.workflows.activities.signature._embed_image",
                   new_callable=AsyncMock) as mock_ei:
            mock_ei.return_value = v
            result = await verify_signature(
                _make_input(), vault=mock_vault, config_service=_mock_config(0.50),
                embedding_model=model, cbs_connector=mock_cbs,
            )
        assert result.outcome == "PROCEED"
        assert result.cbs_fallback_used is True

    @pytest.mark.asyncio
    async def test_cbs_empty_human_review(self):
        from modules.cts.workflows.activities.signature import verify_signature
        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(return_value=_vault_miss())
        mock_cbs = AsyncMock()
        mock_cbs.get_signature_specimens = AsyncMock(return_value=[])
        result = await verify_signature(
            _make_input(), vault=mock_vault, config_service=_mock_config(),
            embedding_model=_embed_model(), cbs_connector=mock_cbs,
        )
        assert result.outcome == "HUMAN_REVIEW"
        assert "NO_SIGNATURE_IN_VAULT" in result.miss_reason

    @pytest.mark.asyncio
    async def test_cbs_error_human_review_degraded(self):
        from modules.cts.workflows.activities.signature import verify_signature
        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(return_value=_vault_miss())
        mock_cbs = AsyncMock()
        mock_cbs.get_signature_specimens = AsyncMock(side_effect=Exception("CBS timeout"))
        result = await verify_signature(
            _make_input(), vault=mock_vault, config_service=_mock_config(),
            embedding_model=_embed_model(), cbs_connector=mock_cbs,
        )
        assert result.outcome == "HUMAN_REVIEW"
        assert result.degraded is True


# ---------------------------------------------------------------------------
# SMB proxy routing
# ---------------------------------------------------------------------------

class TestSMBProxyRouting:
    def _smb_input(self):
        return _make_input(
            instrument_id="INST-SMB-001",
            bank_id="saraswat-coop",
            account_number="9876543210",
            smb_id="cosmos-coop",
        )

    @pytest.mark.asyncio
    @patch("modules.cts.workflows.activities.signature._embed_image", new_callable=AsyncMock)
    async def test_smb_proxy_called_when_smb_id_set(self, mock_ei):
        from modules.cts.workflows.activities.signature import verify_signature
        v = _unit_vec()
        mock_ei.return_value = v
        mock_proxy = AsyncMock()
        mock_proxy.get_signature = AsyncMock(return_value=_vault_found([v]))
        mock_vault = AsyncMock()
        result = await verify_signature(
            self._smb_input(), vault=mock_vault, config_service=_mock_config(0.50),
            embedding_model=_embed_model(v), smb_proxy=mock_proxy,
        )
        mock_proxy.get_signature.assert_called_once()
        assert result.outcome == "PROCEED"

    @pytest.mark.asyncio
    async def test_vault_not_called_when_proxy_used(self):
        from modules.cts.workflows.activities.signature import verify_signature
        v = _unit_vec()
        mock_proxy = AsyncMock()
        mock_proxy.get_signature = AsyncMock(return_value=_vault_found([v]))
        mock_vault = AsyncMock()
        with patch("modules.cts.workflows.activities.signature._embed_image",
                   new_callable=AsyncMock) as mock_ei:
            mock_ei.return_value = v
            await verify_signature(
                self._smb_input(), vault=mock_vault, config_service=_mock_config(0.50),
                embedding_model=_embed_model(v), smb_proxy=mock_proxy,
            )
        mock_vault.get_signatures.assert_not_called()

    @pytest.mark.asyncio
    async def test_smb_proxy_unavailable_human_review_degraded(self):
        from modules.cts.workflows.activities.signature import verify_signature
        mock_proxy = AsyncMock()
        mock_proxy.get_signature = AsyncMock(side_effect=Exception("MCP timeout"))
        result = await verify_signature(
            self._smb_input(), vault=AsyncMock(), config_service=_mock_config(),
            embedding_model=_embed_model(), smb_proxy=mock_proxy,
        )
        assert result.outcome == "HUMAN_REVIEW"
        assert result.degraded is True

    @pytest.mark.asyncio
    async def test_smb_proxy_miss_human_review(self):
        from modules.cts.workflows.activities.signature import verify_signature
        mock_proxy = AsyncMock()
        mock_proxy.get_signature = AsyncMock(
            return_value=_vault_miss()
        )
        result = await verify_signature(
            self._smb_input(), vault=AsyncMock(), config_service=_mock_config(),
            embedding_model=_embed_model(), smb_proxy=mock_proxy,
        )
        assert result.outcome == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    async def test_vault_used_when_proxy_none(self):
        from modules.cts.workflows.activities.signature import verify_signature
        v = _unit_vec()
        mock_vault = AsyncMock()
        mock_vault.get_signatures = AsyncMock(return_value=_vault_found([v]))
        with patch("modules.cts.workflows.activities.signature._embed_image",
                   new_callable=AsyncMock) as mock_ei:
            mock_ei.return_value = v
            result = await verify_signature(
                self._smb_input(), vault=mock_vault, config_service=_mock_config(0.50),
                embedding_model=_embed_model(v), smb_proxy=None,
            )
        mock_vault.get_signatures.assert_called_once()
        assert result.outcome == "PROCEED"
