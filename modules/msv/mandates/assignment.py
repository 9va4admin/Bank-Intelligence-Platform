"""
Greedy cosine similarity assignment — N detected signatures × M enrolled signatories.

Algorithm:
  1. Build N × M similarity matrix where cell[i][j] = max cosine_sim(detected[i], specimen_k)
     for k in signatory[j].embeddings (max across all specimens).
  2. Greedy pass: iterate over detected signatures; for each one, find the best-remaining
     (unassigned) signatory. Assign them. Remove both from the available pool.
  3. Return MatchedSignatory for each assigned (detected, signatory) pair.

Each detected signature matches at most one signatory.
Each signatory can be matched by at most one detected signature.
Unmatched signatories (no detection claimed them) are simply absent from the result.
"""
import math

import numpy as np

from modules.msv.mandates.models import MatchedSignatory, SignatoryRecord


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """
    Cosine similarity between two equal-length vectors.
    Returns 0.0 if either vector is the zero vector (undefined cosine).
    """
    na = np.array(a, dtype=np.float32)
    nb = np.array(b, dtype=np.float32)

    norm_a = float(np.linalg.norm(na))
    norm_b = float(np.linalg.norm(nb))

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    return float(np.dot(na, nb) / (norm_a * norm_b))


def _max_specimen_similarity(
    detected: list[float],
    signatory: SignatoryRecord,
) -> tuple[float, int]:
    """
    Return (max_score, best_specimen_idx) across all specimens of a signatory.
    If the signatory has no embeddings, returns (0.0, 0).
    """
    if not signatory.embeddings:
        return 0.0, 0

    best_score = -2.0  # below any cosine value
    best_idx = 0

    for idx, specimen in enumerate(signatory.embeddings):
        score = cosine_similarity(detected, specimen)
        if score > best_score:
            best_score = score
            best_idx = idx

    return best_score, best_idx


def assign_signatures(
    detected_embeddings: list[list[float]],
    signatories: list[SignatoryRecord],
) -> list[MatchedSignatory]:
    """
    Greedy cosine similarity assignment.

    Args:
        detected_embeddings: list of N embedding vectors (one per detected signature crop)
        signatories:         list of M known signatories (each with multiple specimen embeddings)

    Returns:
        list of MatchedSignatory — one per successful (detected, signatory) assignment.
        Length <= min(N, M).
    """
    if not detected_embeddings or not signatories:
        return []

    n = len(detected_embeddings)
    m = len(signatories)

    # Build N × M score matrix (score, specimen_idx) per cell
    score_matrix: list[list[tuple[float, int]]] = []
    for i in range(n):
        row: list[tuple[float, int]] = []
        for j in range(m):
            score, specimen_idx = _max_specimen_similarity(detected_embeddings[i], signatories[j])
            row.append((score, specimen_idx))
        score_matrix.append(row)

    # Greedy assignment: repeatedly pick the highest-score unassigned (i, j) pair
    assigned_detections: set[int] = set()
    assigned_signatories: set[int] = set()
    results: list[MatchedSignatory] = []

    # Collect all (score, i, j, specimen_idx) candidates
    candidates: list[tuple[float, int, int, int]] = []
    for i in range(n):
        for j in range(m):
            score, specimen_idx = score_matrix[i][j]
            candidates.append((score, i, j, specimen_idx))

    # Sort descending by score
    candidates.sort(key=lambda x: x[0], reverse=True)

    for score, det_idx, sig_idx, specimen_idx in candidates:
        if det_idx in assigned_detections:
            continue
        if sig_idx in assigned_signatories:
            continue

        # Assign this pair
        assigned_detections.add(det_idx)
        assigned_signatories.add(sig_idx)

        sig = signatories[sig_idx]
        results.append(
            MatchedSignatory(
                signatory_id=sig.signatory_id,
                role=sig.role,
                name_masked=sig.name_masked,
                best_score=score,
                specimen_idx=specimen_idx,
            )
        )

        # Stop when all possible assignments have been made
        if len(assigned_detections) == min(n, m):
            break

    return results
