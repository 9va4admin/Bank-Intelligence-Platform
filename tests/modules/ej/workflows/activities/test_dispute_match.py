"""
Tests for modules/ej/workflows/activities/dispute_match.py

Semantic matching of NPCI dispute claims to EJ canonical records using BGE-M3 embeddings.
"""
import pytest
from unittest.mock import AsyncMock


def _make_input(bank_id="test-bank", atm_id="ATM001", npci_claim_id="CLAIM001"):
    from modules.ej.workflows.activities.dispute_match import EJDisputeMatchInput
    return EJDisputeMatchInput(
        bank_id=bank_id,
        atm_id=atm_id,
        npci_claim_id=npci_claim_id,
        claim_amount=5000.0,
        claim_timestamp="2026-06-17T10:30:00+05:30",
        claim_type="CASH_NOT_DISPENSED",
    )


class TestEJDisputeMatchInput:
    def test_requires_npci_claim_id(self):
        from modules.ej.workflows.activities.dispute_match import EJDisputeMatchInput
        with pytest.raises(Exception):
            EJDisputeMatchInput(bank_id="b", atm_id="a", claim_amount=100.0,
                                claim_timestamp="2026-06-17", claim_type="X")

    def test_is_frozen(self):
        inp = _make_input()
        with pytest.raises(Exception):
            inp.npci_claim_id = "other"


class TestEJDisputeMatchHappyPath:
    @pytest.mark.asyncio
    async def test_match_found_returns_matched(self):
        from modules.ej.workflows.activities.dispute_match import match_dispute_to_ej

        mock_embedder = AsyncMock()
        mock_embedder.embed = AsyncMock(return_value=[0.1] * 1024)

        mock_search = AsyncMock()
        mock_search.search = AsyncMock(return_value=[{
            "canonical_hash": "abc123",
            "score": 0.95,
            "canonical_record": {"transaction_type": "DISPENSE", "amount": 5000.0},
        }])

        result = await match_dispute_to_ej(_make_input(), embedder=mock_embedder, vector_search=mock_search)
        assert result.outcome == "MATCHED"

    @pytest.mark.asyncio
    async def test_match_result_has_canonical_hash(self):
        from modules.ej.workflows.activities.dispute_match import match_dispute_to_ej

        mock_embedder = AsyncMock()
        mock_embedder.embed = AsyncMock(return_value=[0.1] * 1024)

        mock_search = AsyncMock()
        mock_search.search = AsyncMock(return_value=[{
            "canonical_hash": "deadbeef",
            "score": 0.92,
            "canonical_record": {},
        }])

        result = await match_dispute_to_ej(_make_input(), embedder=mock_embedder, vector_search=mock_search)
        assert result.matched_canonical_hash == "deadbeef"

    @pytest.mark.asyncio
    async def test_match_result_has_score(self):
        from modules.ej.workflows.activities.dispute_match import match_dispute_to_ej

        mock_embedder = AsyncMock()
        mock_embedder.embed = AsyncMock(return_value=[0.1] * 1024)

        mock_search = AsyncMock()
        mock_search.search = AsyncMock(return_value=[{
            "canonical_hash": "abc",
            "score": 0.88,
            "canonical_record": {},
        }])

        result = await match_dispute_to_ej(_make_input(), embedder=mock_embedder, vector_search=mock_search)
        assert result.match_score == 0.88


class TestEJDisputeMatchNoMatch:
    @pytest.mark.asyncio
    async def test_no_results_returns_no_match(self):
        from modules.ej.workflows.activities.dispute_match import match_dispute_to_ej

        mock_embedder = AsyncMock()
        mock_embedder.embed = AsyncMock(return_value=[0.1] * 1024)

        mock_search = AsyncMock()
        mock_search.search = AsyncMock(return_value=[])

        result = await match_dispute_to_ej(_make_input(), embedder=mock_embedder, vector_search=mock_search)
        assert result.outcome == "NO_MATCH"

    @pytest.mark.asyncio
    async def test_low_score_returns_no_match(self):
        from modules.ej.workflows.activities.dispute_match import match_dispute_to_ej

        mock_embedder = AsyncMock()
        mock_embedder.embed = AsyncMock(return_value=[0.1] * 1024)

        mock_search = AsyncMock()
        mock_search.search = AsyncMock(return_value=[{
            "canonical_hash": "abc",
            "score": 0.50,
            "canonical_record": {},
        }])

        result = await match_dispute_to_ej(
            _make_input(), embedder=mock_embedder, vector_search=mock_search,
            min_match_score=0.80
        )
        assert result.outcome == "NO_MATCH"


class TestEJDisputeMatchDegradation:
    @pytest.mark.asyncio
    async def test_embedder_failure_returns_match_failed(self):
        from modules.ej.workflows.activities.dispute_match import match_dispute_to_ej

        mock_embedder = AsyncMock()
        mock_embedder.embed = AsyncMock(side_effect=RuntimeError("BGE-M3 down"))

        result = await match_dispute_to_ej(_make_input(), embedder=mock_embedder, vector_search=AsyncMock())
        assert result.outcome == "MATCH_FAILED"

    @pytest.mark.asyncio
    async def test_search_failure_does_not_raise(self):
        from modules.ej.workflows.activities.dispute_match import match_dispute_to_ej

        mock_embedder = AsyncMock()
        mock_embedder.embed = AsyncMock(return_value=[0.1] * 1024)

        mock_search = AsyncMock()
        mock_search.search = AsyncMock(side_effect=RuntimeError("pgvector down"))

        result = await match_dispute_to_ej(_make_input(), embedder=mock_embedder, vector_search=mock_search)
        assert result is not None
