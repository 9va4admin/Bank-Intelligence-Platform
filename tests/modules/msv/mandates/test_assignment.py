"""
Tests for modules/msv/mandates/assignment.py — greedy cosine similarity assignment.

Covers:
  - Perfect match (same vector) → score 1.0
  - Orthogonal vectors → score ~0.0
  - Best specimen wins (max across specimens)
  - Each detected sig matches at most one signatory
  - Fewer detected than signatories → unmatched signatories not in result
  - More detected than signatories → extras ignored
  - 512-dim vectors
"""
import math

import pytest

from modules.msv.mandates.assignment import assign_signatures, cosine_similarity
from modules.msv.mandates.models import SignatoryRecord


def _make_signatory(sig_id: str, role: str, embeddings: list[list[float]]) -> SignatoryRecord:
    return SignatoryRecord(
        signatory_id=sig_id,
        role=role,
        name_masked="P***",
        specimen_count=len(embeddings),
        embeddings=embeddings,
    )


def _unit_vec(idx: int, dim: int = 512) -> list[float]:
    """Return a unit vector with 1.0 at position idx, 0.0 elsewhere."""
    v = [0.0] * dim
    if idx < dim:
        v[idx] = 1.0
    return v


def _normalize(v: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in v))
    if norm == 0:
        return v
    return [x / norm for x in v]


class TestCosineSimilarity:
    def test_identical_vectors_score_1(self):
        v = [1.0, 0.0, 0.0]
        assert abs(cosine_similarity(v, v) - 1.0) < 1e-6

    def test_orthogonal_vectors_score_0(self):
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        assert abs(cosine_similarity(a, b)) < 1e-6

    def test_opposite_vectors_score_minus_1(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert abs(cosine_similarity(a, b) - (-1.0)) < 1e-6

    def test_512_dim_vectors(self):
        a = _unit_vec(0, 512)
        b = _unit_vec(0, 512)
        assert abs(cosine_similarity(a, b) - 1.0) < 1e-6

    def test_512_dim_orthogonal(self):
        a = _unit_vec(0, 512)
        b = _unit_vec(1, 512)
        assert abs(cosine_similarity(a, b)) < 1e-6

    def test_non_unit_vectors_still_normalised(self):
        a = [2.0, 0.0, 0.0]
        b = [3.0, 0.0, 0.0]
        assert abs(cosine_similarity(a, b) - 1.0) < 1e-6

    def test_zero_vector_returns_0(self):
        a = [0.0, 0.0, 0.0]
        b = [1.0, 0.0, 0.0]
        # cosine of zero vector is undefined — should return 0.0 gracefully
        result = cosine_similarity(a, b)
        assert result == 0.0


class TestAssignSignatures:
    def test_perfect_match_single_sig(self):
        vec = _unit_vec(0)
        detected = [vec]
        signatories = [_make_signatory("sig-001", "CFO", [vec])]
        matches = assign_signatures(detected, signatories)
        assert len(matches) == 1
        assert matches[0].signatory_id == "sig-001"
        assert abs(matches[0].best_score - 1.0) < 1e-6

    def test_two_distinct_sigs_matched_correctly(self):
        vec_a = _unit_vec(0)
        vec_b = _unit_vec(1)
        detected = [vec_a, vec_b]
        signatories = [
            _make_signatory("sig-001", "CFO", [vec_a]),
            _make_signatory("sig-002", "DIRECTOR", [vec_b]),
        ]
        matches = assign_signatures(detected, signatories)
        assert len(matches) == 2
        matched_ids = {m.signatory_id for m in matches}
        assert "sig-001" in matched_ids
        assert "sig-002" in matched_ids

    def test_best_specimen_wins(self):
        """max across 3 specimens — the best one should determine the score."""
        query = _unit_vec(5)
        # sig-001 has 3 specimens: one perfect match at index 2
        embeddings = [_unit_vec(3), _unit_vec(4), _unit_vec(5)]
        detected = [query]
        signatories = [_make_signatory("sig-001", "CFO", embeddings)]
        matches = assign_signatures(detected, signatories)
        assert len(matches) == 1
        assert matches[0].specimen_idx == 2            # specimen 2 is the best match
        assert abs(matches[0].best_score - 1.0) < 1e-6

    def test_each_detected_matches_at_most_one_signatory(self):
        """Two identical detected vectors — only first one can claim a signatory."""
        vec = _unit_vec(0)
        detected = [vec, vec]
        signatories = [_make_signatory("sig-001", "CFO", [vec])]
        # Two detections for one signatory — one match, one unmatched
        matches = assign_signatures(detected, signatories)
        matched_ids = {m.signatory_id for m in matches}
        # At most one match per signatory
        assert len(set(m.signatory_id for m in matches)) == len(matches)

    def test_fewer_detected_than_signatories(self):
        """Only 1 detected — only the best matching signatory is in result."""
        vec_a = _unit_vec(0)
        vec_b = _unit_vec(1)
        detected = [vec_a]
        signatories = [
            _make_signatory("sig-001", "CFO", [vec_a]),
            _make_signatory("sig-002", "DIRECTOR", [vec_b]),
        ]
        matches = assign_signatures(detected, signatories)
        # Only 1 detection → at most 1 match returned
        assert len(matches) == 1
        assert matches[0].signatory_id == "sig-001"

    def test_more_detected_than_signatories_extras_ignored(self):
        """3 detections, 2 signatories — extras ignored, 2 matches returned."""
        vec_a = _unit_vec(0)
        vec_b = _unit_vec(1)
        vec_c = _unit_vec(2)
        detected = [vec_a, vec_b, vec_c]
        signatories = [
            _make_signatory("sig-001", "CFO", [vec_a]),
            _make_signatory("sig-002", "DIRECTOR", [vec_b]),
        ]
        matches = assign_signatures(detected, signatories)
        assert len(matches) == 2

    def test_empty_detected_returns_empty(self):
        signatories = [_make_signatory("sig-001", "CFO", [_unit_vec(0)])]
        matches = assign_signatures([], signatories)
        assert matches == []

    def test_empty_signatories_returns_empty(self):
        matches = assign_signatures([_unit_vec(0)], [])
        assert matches == []

    def test_both_empty_returns_empty(self):
        matches = assign_signatures([], [])
        assert matches == []

    def test_score_reflects_best_not_worst_specimen(self):
        """Even with multiple weak specimens, the best one counts."""
        query = _unit_vec(10)
        weak1 = _unit_vec(11)
        weak2 = _unit_vec(12)
        best  = _unit_vec(10)   # perfect match
        signatories = [_make_signatory("sig-001", "CFO", [weak1, weak2, best])]
        matches = assign_signatures([query], signatories)
        assert abs(matches[0].best_score - 1.0) < 1e-6
        assert matches[0].specimen_idx == 2

    def test_name_masked_preserved_in_result(self):
        vec = _unit_vec(0)
        signatories = [
            SignatoryRecord(
                signatory_id="sig-001",
                role="CFO",
                name_masked="P***",
                specimen_count=1,
                embeddings=[vec],
            )
        ]
        matches = assign_signatures([vec], signatories)
        assert matches[0].name_masked == "P***"

    def test_role_preserved_in_result(self):
        vec = _unit_vec(0)
        signatories = [_make_signatory("sig-001", "DIRECTOR", [vec])]
        matches = assign_signatures([vec], signatories)
        assert matches[0].role == "DIRECTOR"

    def test_each_signatory_matched_at_most_once(self):
        """Many detected vectors should not produce duplicate signatory assignments."""
        vec = _unit_vec(0)
        detected = [vec] * 5  # 5 copies of same detected signature
        signatories = [_make_signatory("sig-001", "CFO", [vec])]
        matches = assign_signatures(detected, signatories)
        # sig-001 can only be assigned once
        assert sum(1 for m in matches if m.signatory_id == "sig-001") <= 1
