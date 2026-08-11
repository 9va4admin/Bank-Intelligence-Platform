"""
Tests for modules/cts/workflows/activities/signature.py

Per-signatory embedding-based comparison.

Behaviour (post-rewrite):
  - sig_count=1 or sig_count=N: ALL detected ink bboxes are embedded and matched
  - For each account signatory: best cosine across ALL detected cheque sigs
    AND all specimens for that signatory is computed
  - Mandate BRE: ANY_ONE (≥1 signatory matched) | ALL_REQUIRED (all must match)
    | QUORUM_N (N must match)
  - Per-signatory verdict returned in result
  - Vault miss or embed failure → HUMAN_REVIEW (never AUTO_RETURN)
  - CBS fallback uses get_signatory_data() → per-signatory store
"""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

_DIM = 512


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unit_vec(dim: int = _DIM, axis: int = 0) -> list[float]:
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
        sig_bboxes=sig_bboxes or [[0.1, 0.7, 0.5, 0.9]],
        smb_id=smb_id,
    )


def _vault_single(embeddings: list[list[float]] = None):
    """Single-signatory vault with given embeddings."""
    vault = AsyncMock()
    vault.get_specimens_by_signatory = AsyncMock(
        return_value={"PRIMARY": embeddings or [_unit_vec(axis=0)]}
    )
    vault.get_mandate_rule = AsyncMock(return_value="ANY_ONE")
    return vault


def _vault_empty():
    """No signatories found — triggers CBS fallback."""
    vault = AsyncMock()
    vault.get_specimens_by_signatory = AsyncMock(return_value={})
    vault.get_mandate_rule = AsyncMock(return_value="ANY_ONE")
    vault.store_embeddings = AsyncMock()
    return vault


def _vault_multi(specimens_by_sig: dict):
    """Multi-signatory vault."""
    vault = AsyncMock()
    vault.get_specimens_by_signatory = AsyncMock(return_value=specimens_by_sig)
    vault.get_mandate_rule = AsyncMock(return_value="ANY_ONE")
    vault.store_embeddings = AsyncMock()
    return vault


def _embed_model(return_vector=None, raises=None):
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
# Result model
# ---------------------------------------------------------------------------

class TestSignatoryVerdictModel:
    def test_per_signatory_field_exists_in_result(self):
        from modules.cts.workflows.activities.signature import SignatureActivityResult
        r = SignatureActivityResult(outcome="PROCEED")
        assert hasattr(r, "per_signatory")
        assert isinstance(r.per_signatory, list)

    def test_mandate_rule_field_exists(self):
        from modules.cts.workflows.activities.signature import SignatureActivityResult
        r = SignatureActivityResult(outcome="PROCEED")
        assert hasattr(r, "mandate_rule")

    def test_signatories_matched_and_required_exist(self):
        from modules.cts.workflows.activities.signature import SignatureActivityResult
        r = SignatureActivityResult(outcome="PROCEED", signatories_matched=2, signatories_required=2)
        assert r.signatories_matched == 2
        assert r.signatories_required == 2

    def test_signatory_verdict_model(self):
        from modules.cts.workflows.activities.signature import SignatoryVerdict
        v = SignatoryVerdict(
            signatory_id="PRIMARY",
            best_score=0.95,
            specimen_index=0,
            verdict="MATCHED",
        )
        assert v.verdict == "MATCHED"
        assert v.best_score == 0.95


# ---------------------------------------------------------------------------
# Single-signatory path: embed one sig, match against multiple specimens
# ---------------------------------------------------------------------------

class TestSingleSignatory:
    @pytest.mark.asyncio
    @patch("modules.cts.workflows.activities.signature._embed_image", new_callable=AsyncMock)
    async def test_high_score_proceeds(self, mock_embed):
        from modules.cts.workflows.activities.signature import verify_signature
        v = _unit_vec(axis=0)
        mock_embed.return_value = v
        result = await verify_signature(
            _make_input(), vault=_vault_single([v]),
            config_service=_mock_config(0.80), embedding_model=_embed_model(v),
        )
        assert result.outcome == "PROCEED"

    @pytest.mark.asyncio
    @patch("modules.cts.workflows.activities.signature._embed_image", new_callable=AsyncMock)
    async def test_low_score_human_review(self, mock_embed):
        from modules.cts.workflows.activities.signature import verify_signature
        stored = _unit_vec(axis=0)
        cheque = _unit_vec(axis=1)  # orthogonal → cosine 0
        mock_embed.return_value = cheque
        result = await verify_signature(
            _make_input(), vault=_vault_single([stored]),
            config_service=_mock_config(0.80), embedding_model=_embed_model(cheque),
        )
        assert result.outcome == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    @patch("modules.cts.workflows.activities.signature._embed_image", new_callable=AsyncMock)
    async def test_best_specimen_used_when_multiple(self, mock_embed):
        """If 3 specimens stored and cheque matches specimen #2 best → PROCEED."""
        from modules.cts.workflows.activities.signature import verify_signature
        v = _unit_vec(axis=0)
        orthogonal = _unit_vec(axis=1)
        cheque = _unit_vec(axis=0)  # matches v exactly
        mock_embed.return_value = cheque
        # specimens: [orthogonal, orthogonal, v] — last one matches
        result = await verify_signature(
            _make_input(), vault=_vault_single([orthogonal, orthogonal, v]),
            config_service=_mock_config(0.80), embedding_model=_embed_model(cheque),
        )
        assert result.outcome == "PROCEED"

    @pytest.mark.asyncio
    @patch("modules.cts.workflows.activities.signature._embed_image", new_callable=AsyncMock)
    async def test_per_signatory_verdict_populated(self, mock_embed):
        from modules.cts.workflows.activities.signature import verify_signature
        v = _unit_vec(axis=0)
        mock_embed.return_value = v
        result = await verify_signature(
            _make_input(), vault=_vault_single([v]),
            config_service=_mock_config(0.80), embedding_model=_embed_model(v),
        )
        assert len(result.per_signatory) == 1
        assert result.per_signatory[0].signatory_id == "PRIMARY"
        assert result.per_signatory[0].verdict == "MATCHED"

    @pytest.mark.asyncio
    @patch("modules.cts.workflows.activities.signature._embed_image", new_callable=AsyncMock)
    async def test_match_score_in_result(self, mock_embed):
        from modules.cts.workflows.activities.signature import verify_signature
        v = _const_vec(1.0)
        mock_embed.return_value = v
        result = await verify_signature(
            _make_input(), vault=_vault_single([v]),
            config_service=_mock_config(0.50), embedding_model=_embed_model(v),
        )
        assert result.match_score is not None
        assert result.match_score > 0.99

    @pytest.mark.asyncio
    @patch("modules.cts.workflows.activities.signature._embed_image", new_callable=AsyncMock)
    async def test_threshold_from_config_not_hardcoded(self, mock_embed):
        from modules.cts.workflows.activities.signature import verify_signature
        from shared.ai.signature_embedding import cosine_similarity
        v1 = [1.0, 1.0, 0.0] + [0.0] * (_DIM - 3)
        v2 = [1.0, 0.0, 0.0] + [0.0] * (_DIM - 3)
        score = cosine_similarity(v1, v2)
        mock_embed.return_value = v2
        result_pass = await verify_signature(
            _make_input(), vault=_vault_single([v1]),
            config_service=_mock_config(score - 0.05), embedding_model=_embed_model(v2),
        )
        result_fail = await verify_signature(
            _make_input(), vault=_vault_single([v1]),
            config_service=_mock_config(score + 0.05), embedding_model=_embed_model(v2),
        )
        assert result_pass.outcome == "PROCEED"
        assert result_fail.outcome == "HUMAN_REVIEW"


# ---------------------------------------------------------------------------
# Multi-signature on cheque (sig_count ≥ 2) — handled in verify_signature directly
# ---------------------------------------------------------------------------

class TestMultipleDetectedSignatures:
    @pytest.mark.asyncio
    @patch("modules.cts.workflows.activities.signature._embed_image", new_callable=AsyncMock)
    async def test_two_sigs_detected_both_embedded(self, mock_embed):
        """sig_count=2 with 2 bboxes → _embed_image called twice."""
        from modules.cts.workflows.activities.signature import verify_signature
        v = _unit_vec(axis=0)
        mock_embed.return_value = v
        await verify_signature(
            _make_input(sig_count=2, sig_bboxes=[[0.1, 0.7, 0.4, 0.9], [0.5, 0.7, 0.9, 0.9]]),
            vault=_vault_single([v]),
            config_service=_mock_config(0.80),
            embedding_model=_embed_model(v),
        )
        assert mock_embed.call_count == 2

    @pytest.mark.asyncio
    @patch("modules.cts.workflows.activities.signature._embed_image", new_callable=AsyncMock)
    async def test_multi_sig_proceeds_if_signatory_matched_by_any_detected_sig(self, mock_embed):
        """Cheque has 2 ink sigs; PRIMARY signatory matched by sig #2 → PROCEED."""
        from modules.cts.workflows.activities.signature import verify_signature
        stored = _unit_vec(axis=0)
        # First embed call (sig#1) returns orthogonal; second (sig#2) matches stored
        mock_embed.side_effect = [_unit_vec(axis=1), stored]
        result = await verify_signature(
            _make_input(sig_count=2, sig_bboxes=[[0.0, 0.0, 0.2, 0.2], [0.5, 0.7, 0.9, 0.9]]),
            vault=_vault_single([stored]),
            config_service=_mock_config(0.80),
            embedding_model=_embed_model(),
        )
        assert result.outcome == "PROCEED"

    @pytest.mark.asyncio
    @patch("modules.cts.workflows.activities.signature._embed_image", new_callable=AsyncMock)
    async def test_all_crops_fail_is_human_review_degraded(self, mock_embed):
        """All embed attempts return None → HUMAN_REVIEW degraded."""
        from modules.cts.workflows.activities.signature import verify_signature
        mock_embed.return_value = None
        result = await verify_signature(
            _make_input(sig_count=2, sig_bboxes=[[0.0, 0.0, 0.2, 0.2], [0.5, 0.7, 0.9, 0.9]]),
            vault=_vault_single([_unit_vec()]),
            config_service=_mock_config(0.80),
            embedding_model=_embed_model(),
        )
        assert result.outcome == "HUMAN_REVIEW"
        assert result.degraded is True


# ---------------------------------------------------------------------------
# Multi-signatory account — mandate BRE
# ---------------------------------------------------------------------------

class TestMultiSignatoryAccount:
    @pytest.mark.asyncio
    @patch("modules.cts.workflows.activities.signature._embed_image", new_callable=AsyncMock)
    async def test_any_one_mandate_passes_if_one_matches(self, mock_embed):
        """ANY_ONE: PRIMARY matched, JOINT_1 not → PROCEED."""
        from modules.cts.workflows.activities.signature import verify_signature
        v = _unit_vec(axis=0)
        mock_embed.return_value = v  # cheque sig
        vault = _vault_multi({
            "PRIMARY": [v],                     # will match
            "JOINT_1": [_unit_vec(axis=1)],     # won't match
        })
        vault.get_mandate_rule = AsyncMock(return_value="ANY_ONE")
        result = await verify_signature(
            _make_input(), vault=vault,
            config_service=_mock_config(0.80), embedding_model=_embed_model(v),
        )
        assert result.outcome == "PROCEED"
        assert result.signatories_matched == 1

    @pytest.mark.asyncio
    @patch("modules.cts.workflows.activities.signature._embed_image", new_callable=AsyncMock)
    async def test_all_required_mandate_fails_if_one_missing(self, mock_embed):
        """ALL_REQUIRED: PRIMARY matched, JOINT_1 not → HUMAN_REVIEW."""
        from modules.cts.workflows.activities.signature import verify_signature
        v = _unit_vec(axis=0)
        mock_embed.return_value = v
        vault = _vault_multi({
            "PRIMARY": [v],
            "JOINT_1": [_unit_vec(axis=1)],
        })
        vault.get_mandate_rule = AsyncMock(return_value="ALL_REQUIRED")
        result = await verify_signature(
            _make_input(), vault=vault,
            config_service=_mock_config(0.80), embedding_model=_embed_model(v),
        )
        assert result.outcome == "HUMAN_REVIEW"
        assert result.signatories_matched == 1
        assert result.signatories_required == 2

    @pytest.mark.asyncio
    @patch("modules.cts.workflows.activities.signature._embed_image", new_callable=AsyncMock)
    async def test_all_required_mandate_passes_when_all_match(self, mock_embed):
        """ALL_REQUIRED: both PRIMARY and JOINT_1 matched → PROCEED."""
        from modules.cts.workflows.activities.signature import verify_signature
        v = _unit_vec(axis=0)
        mock_embed.return_value = v
        vault = _vault_multi({
            "PRIMARY": [v],
            "JOINT_1": [v],
        })
        vault.get_mandate_rule = AsyncMock(return_value="ALL_REQUIRED")
        result = await verify_signature(
            _make_input(), vault=vault,
            config_service=_mock_config(0.80), embedding_model=_embed_model(v),
        )
        assert result.outcome == "PROCEED"
        assert result.signatories_matched == 2

    @pytest.mark.asyncio
    @patch("modules.cts.workflows.activities.signature._embed_image", new_callable=AsyncMock)
    async def test_quorum_2_of_3_passes_with_two_matches(self, mock_embed):
        """QUORUM_2: 2 of 3 signatories matched → PROCEED."""
        from modules.cts.workflows.activities.signature import verify_signature
        v = _unit_vec(axis=0)
        mock_embed.return_value = v
        vault = _vault_multi({
            "AUTH_A": [v],
            "AUTH_B": [v],
            "AUTH_C": [_unit_vec(axis=1)],  # won't match
        })
        vault.get_mandate_rule = AsyncMock(return_value="QUORUM_2")
        result = await verify_signature(
            _make_input(), vault=vault,
            config_service=_mock_config(0.80), embedding_model=_embed_model(v),
        )
        assert result.outcome == "PROCEED"
        assert result.signatories_matched == 2
        assert result.signatories_required == 2

    @pytest.mark.asyncio
    @patch("modules.cts.workflows.activities.signature._embed_image", new_callable=AsyncMock)
    async def test_quorum_2_of_3_fails_with_one_match(self, mock_embed):
        """QUORUM_2: only 1 of 3 matched → HUMAN_REVIEW."""
        from modules.cts.workflows.activities.signature import verify_signature
        v = _unit_vec(axis=0)
        mock_embed.return_value = v
        vault = _vault_multi({
            "AUTH_A": [v],
            "AUTH_B": [_unit_vec(axis=1)],
            "AUTH_C": [_unit_vec(axis=2)],
        })
        vault.get_mandate_rule = AsyncMock(return_value="QUORUM_2")
        result = await verify_signature(
            _make_input(), vault=vault,
            config_service=_mock_config(0.80), embedding_model=_embed_model(v),
        )
        assert result.outcome == "HUMAN_REVIEW"

    @pytest.mark.asyncio
    @patch("modules.cts.workflows.activities.signature._embed_image", new_callable=AsyncMock)
    async def test_per_signatory_results_all_populated(self, mock_embed):
        """per_signatory has one entry per signatory with verdict."""
        from modules.cts.workflows.activities.signature import verify_signature
        v = _unit_vec(axis=0)
        mock_embed.return_value = v
        vault = _vault_multi({
            "PRIMARY": [v],
            "JOINT_1": [_unit_vec(axis=1)],
        })
        vault.get_mandate_rule = AsyncMock(return_value="ANY_ONE")
        result = await verify_signature(
            _make_input(), vault=vault,
            config_service=_mock_config(0.80), embedding_model=_embed_model(v),
        )
        sig_ids = {r.signatory_id for r in result.per_signatory}
        assert "PRIMARY" in sig_ids
        assert "JOINT_1" in sig_ids

    @pytest.mark.asyncio
    @patch("modules.cts.workflows.activities.signature._embed_image", new_callable=AsyncMock)
    async def test_matched_verdict_has_specimen_index(self, mock_embed):
        """MATCHED signatories include the specimen_index that was the best match."""
        from modules.cts.workflows.activities.signature import verify_signature
        v = _unit_vec(axis=0)
        mock_embed.return_value = v
        vault = _vault_single([_unit_vec(axis=1), v])  # specimen_index 1 matches
        result = await verify_signature(
            _make_input(), vault=vault,
            config_service=_mock_config(0.80), embedding_model=_embed_model(v),
        )
        matched = [r for r in result.per_signatory if r.verdict == "MATCHED"]
        assert matched[0].specimen_index == 1

    @pytest.mark.asyncio
    @patch("modules.cts.workflows.activities.signature._embed_image", new_callable=AsyncMock)
    async def test_no_match_verdict_has_no_specimen_index(self, mock_embed):
        """NO_MATCH signatories have specimen_index=None."""
        from modules.cts.workflows.activities.signature import verify_signature
        v = _unit_vec(axis=0)
        mock_embed.return_value = v
        vault = _vault_single([_unit_vec(axis=1)])  # won't match
        result = await verify_signature(
            _make_input(), vault=vault,
            config_service=_mock_config(0.99), embedding_model=_embed_model(v),
        )
        no_match = [r for r in result.per_signatory if r.verdict == "NO_MATCH"]
        assert no_match[0].specimen_index is None


# ---------------------------------------------------------------------------
# Vault miss → CBS fallback
# ---------------------------------------------------------------------------

class TestVaultMissAndCBSFallback:
    @pytest.mark.asyncio
    async def test_vault_empty_no_connector_human_review(self):
        from modules.cts.workflows.activities.signature import verify_signature
        with patch("modules.cts.workflows.activities.signature._embed_image",
                   new_callable=AsyncMock) as mock_embed:
            mock_embed.return_value = _unit_vec()
            result = await verify_signature(
                _make_input(), vault=_vault_empty(),
                config_service=_mock_config(), embedding_model=_embed_model(),
                cbs_connector=None,
            )
        assert result.outcome == "HUMAN_REVIEW"
        assert "NO_SIGNATURE_IN_VAULT" in (result.miss_reason or "")

    @pytest.mark.asyncio
    async def test_vault_empty_cbs_signatory_data_called(self):
        """On vault miss, get_signatory_data() is called on CBS connector."""
        from modules.cts.workflows.activities.signature import verify_signature
        mock_cbs = AsyncMock()
        mock_cbs.get_signatory_data = AsyncMock(return_value=[])
        mock_cbs.get_signature_specimens = AsyncMock(return_value=[])
        with patch("modules.cts.workflows.activities.signature._embed_image",
                   new_callable=AsyncMock) as mock_embed:
            mock_embed.return_value = _unit_vec()
            await verify_signature(
                _make_input(), vault=_vault_empty(),
                config_service=_mock_config(), embedding_model=_embed_model(),
                cbs_connector=mock_cbs,
            )
        mock_cbs.get_signatory_data.assert_called_once()

    @pytest.mark.asyncio
    async def test_cbs_signatory_data_stored_per_signatory(self):
        """CBS signatory data stored with signatory_id, not flat."""
        from modules.cts.workflows.activities.signature import verify_signature
        from shared.cbs_connector.base import CBSSignatoryData
        v = _unit_vec()
        vault = _vault_empty()
        sig_data = [
            CBSSignatoryData(
                signatory_id="PRIMARY",
                role="DRAWER",
                name_masked="R***",
                specimen_images=[b"fake_img_bytes"],
                operation_type="S",
            )
        ]
        mock_cbs = AsyncMock()
        mock_cbs.get_signatory_data = AsyncMock(return_value=sig_data)
        model = _embed_model(v)
        with patch("modules.cts.workflows.activities.signature._embed_image",
                   new_callable=AsyncMock) as mock_embed:
            mock_embed.return_value = v
            await verify_signature(
                _make_input(), vault=vault,
                config_service=_mock_config(0.50), embedding_model=model,
                cbs_connector=mock_cbs,
            )
        vault.store_embeddings.assert_called_once()
        call_kwargs = vault.store_embeddings.call_args
        assert call_kwargs[1].get("signatory_id") == "PRIMARY" or (
            len(call_kwargs[0]) > 2 and call_kwargs[0][2] == "PRIMARY"
        )

    @pytest.mark.asyncio
    async def test_cbs_fallback_proceeds_on_match(self):
        from modules.cts.workflows.activities.signature import verify_signature
        from shared.cbs_connector.base import CBSSignatoryData
        v = _unit_vec()
        vault = _vault_empty()
        sig_data = [
            CBSSignatoryData(
                signatory_id="PRIMARY", role="DRAWER", name_masked="R***",
                specimen_images=[b"img"], operation_type="S",
            )
        ]
        mock_cbs = AsyncMock()
        mock_cbs.get_signatory_data = AsyncMock(return_value=sig_data)
        model = _embed_model(v)
        with patch("modules.cts.workflows.activities.signature._embed_image",
                   new_callable=AsyncMock) as mock_embed:
            mock_embed.return_value = v
            result = await verify_signature(
                _make_input(), vault=vault,
                config_service=_mock_config(0.50), embedding_model=model,
                cbs_connector=mock_cbs,
            )
        assert result.outcome == "PROCEED"
        assert result.cbs_fallback_used is True

    @pytest.mark.asyncio
    async def test_cbs_error_human_review_degraded(self):
        from modules.cts.workflows.activities.signature import verify_signature
        mock_cbs = AsyncMock()
        mock_cbs.get_signatory_data = AsyncMock(side_effect=Exception("CBS timeout"))
        mock_cbs.get_signature_specimens = AsyncMock(side_effect=Exception("CBS timeout"))
        with patch("modules.cts.workflows.activities.signature._embed_image",
                   new_callable=AsyncMock) as mock_embed:
            mock_embed.return_value = _unit_vec()
            result = await verify_signature(
                _make_input(), vault=_vault_empty(),
                config_service=_mock_config(), embedding_model=_embed_model(),
                cbs_connector=mock_cbs,
            )
        assert result.outcome == "HUMAN_REVIEW"
        assert result.degraded is True

    @pytest.mark.asyncio
    async def test_vault_empty_never_auto_return(self):
        from modules.cts.workflows.activities.signature import verify_signature
        with patch("modules.cts.workflows.activities.signature._embed_image",
                   new_callable=AsyncMock) as mock_embed:
            mock_embed.return_value = _unit_vec()
            result = await verify_signature(
                _make_input(), vault=_vault_empty(),
                config_service=_mock_config(), embedding_model=_embed_model(),
            )
        assert result.outcome != "AUTO_RETURN"


# ---------------------------------------------------------------------------
# No embedding model → HUMAN_REVIEW (degraded)
# ---------------------------------------------------------------------------

class TestNoEmbeddingModel:
    @pytest.mark.asyncio
    async def test_no_model_human_review(self):
        from modules.cts.workflows.activities.signature import verify_signature
        result = await verify_signature(
            _make_input(), vault=_vault_single(),
            config_service=_mock_config(), embedding_model=None,
        )
        assert result.outcome == "HUMAN_REVIEW"
        assert result.degraded is True

    @pytest.mark.asyncio
    async def test_no_model_miss_reason_set(self):
        from modules.cts.workflows.activities.signature import verify_signature
        result = await verify_signature(
            _make_input(), vault=_vault_single(),
            config_service=_mock_config(), embedding_model=None,
        )
        assert result.miss_reason == "MODEL_UNAVAILABLE"


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
    async def test_smb_proxy_called_when_smb_id_set(self, mock_embed):
        from modules.cts.workflows.activities.signature import verify_signature
        from modules.cts.vaults.signature_vault import VaultResult
        v = _unit_vec()
        mock_embed.return_value = v
        mock_proxy = AsyncMock()
        mock_proxy.get_signature = AsyncMock(
            return_value=VaultResult(outcome="FOUND", embeddings=[v])
        )
        result = await verify_signature(
            self._smb_input(), vault=AsyncMock(),
            config_service=_mock_config(0.50),
            embedding_model=_embed_model(v), smb_proxy=mock_proxy,
        )
        mock_proxy.get_signature.assert_called_once()
        assert result.outcome == "PROCEED"

    @pytest.mark.asyncio
    async def test_vault_not_called_when_proxy_used(self):
        from modules.cts.workflows.activities.signature import verify_signature
        from modules.cts.vaults.signature_vault import VaultResult
        v = _unit_vec()
        mock_proxy = AsyncMock()
        mock_proxy.get_signature = AsyncMock(
            return_value=VaultResult(outcome="FOUND", embeddings=[v])
        )
        mock_vault = AsyncMock()
        with patch("modules.cts.workflows.activities.signature._embed_image",
                   new_callable=AsyncMock) as mock_embed:
            mock_embed.return_value = v
            await verify_signature(
                self._smb_input(), vault=mock_vault,
                config_service=_mock_config(0.50),
                embedding_model=_embed_model(v), smb_proxy=mock_proxy,
            )
        mock_vault.get_specimens_by_signatory.assert_not_called()

    @pytest.mark.asyncio
    async def test_smb_proxy_unavailable_human_review_degraded(self):
        from modules.cts.workflows.activities.signature import verify_signature
        mock_proxy = AsyncMock()
        mock_proxy.get_signature = AsyncMock(side_effect=Exception("MCP timeout"))
        with patch("modules.cts.workflows.activities.signature._embed_image",
                   new_callable=AsyncMock) as mock_embed:
            mock_embed.return_value = _unit_vec()
            result = await verify_signature(
                self._smb_input(), vault=AsyncMock(),
                config_service=_mock_config(),
                embedding_model=_embed_model(), smb_proxy=mock_proxy,
            )
        assert result.outcome == "HUMAN_REVIEW"
        assert result.degraded is True

    @pytest.mark.asyncio
    async def test_vault_used_when_proxy_none(self):
        from modules.cts.workflows.activities.signature import verify_signature
        v = _unit_vec()
        mock_vault = _vault_single([v])
        with patch("modules.cts.workflows.activities.signature._embed_image",
                   new_callable=AsyncMock) as mock_embed:
            mock_embed.return_value = v
            result = await verify_signature(
                self._smb_input(), vault=mock_vault,
                config_service=_mock_config(0.50),
                embedding_model=_embed_model(v), smb_proxy=None,
            )
        mock_vault.get_specimens_by_signatory.assert_called_once()
        assert result.outcome == "PROCEED"


# ---------------------------------------------------------------------------
# Morphological preprocessing (_apply_morphological_normalisation)
# ---------------------------------------------------------------------------

class TestMorphologicalNormalisation:
    def test_returns_pil_image_with_cv2_available(self):
        try:
            import cv2  # noqa: F401
            import numpy as np  # noqa: F401
        except ImportError:
            pytest.skip("cv2/numpy not available")
        from PIL import Image as _PIL
        from modules.cts.workflows.activities.signature import _apply_morphological_normalisation
        img = _PIL.new("RGB", (100, 50), color=(255, 255, 255))
        for x in range(20, 80):
            img.putpixel((x, 25), (0, 0, 0))
        result = _apply_morphological_normalisation(img)
        assert isinstance(result, _PIL.Image)

    def test_returns_original_when_cv2_unavailable(self, monkeypatch):
        import builtins
        real_import = builtins.__import__
        def mock_import(name, *args, **kwargs):
            if name == "cv2":
                raise ImportError("simulated")
            return real_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", mock_import)
        from PIL import Image as _PIL
        import sys
        sys.modules.pop("modules.cts.workflows.activities.signature", None)
        from modules.cts.workflows.activities.signature import _apply_morphological_normalisation
        img = _PIL.new("RGB", (100, 50), color=(255, 255, 255))
        result = _apply_morphological_normalisation(img)
        assert isinstance(result, _PIL.Image)

    def test_no_raise_on_solid_white(self):
        try:
            import cv2  # noqa: F401
        except ImportError:
            pytest.skip("cv2 not available")
        from PIL import Image as _PIL
        from modules.cts.workflows.activities.signature import _apply_morphological_normalisation
        img = _PIL.new("RGB", (100, 50), color=(255, 255, 255))
        result = _apply_morphological_normalisation(img)
        assert isinstance(result, _PIL.Image)
