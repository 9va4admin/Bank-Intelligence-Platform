"""Scoring breakdowns: how well new (unseen) words are read, and how accuracy changes with the model's confidence."""
import pytest
import torch

from htr_research.crnn import coverage_table, split_scores, word_confidence


def logits_for(path, num_classes=5, strength=8.0):
    """Logits (T, 1, C) whose best class at each step is the given path."""
    t = torch.zeros(len(path), 1, num_classes)
    for i, c in enumerate(path):
        t[i, 0, c] = strength
    return t


def test_confident_reading_scores_near_one():
    assert word_confidence(logits_for([0, 2, 2, 0, 3, 0]))[0] > 0.95


def test_unsure_reading_scores_low():
    flat = torch.zeros(6, 1, 5)
    flat[1, 0, 2] = 0.3   # the best class barely beats the rest
    flat[4, 0, 3] = 0.3
    assert word_confidence(flat)[0] < 0.4


def test_nothing_emitted_scores_zero():
    assert word_confidence(logits_for([0, 0, 0, 0]))[0] == 0.0


def test_one_confidence_per_image_in_the_batch():
    both = torch.cat([logits_for([0, 2, 0]), logits_for([3, 0, 0])], dim=1)
    assert len(word_confidence(both)) == 2


def test_split_scores_separates_seen_and_unseen_words():
    preds = ["abc", "abd", "xyz", "xzz"]
    refs = ["abc", "abc", "xyz", "xyz"]
    out = split_scores(preds, refs, known_words={"abc"})
    assert out["seen"]["n"] == 2 and out["unseen"]["n"] == 2
    assert out["seen"]["wer"] == pytest.approx(0.5)
    assert out["unseen"]["wer"] == pytest.approx(0.5)
    assert out["seen"]["cer"] == pytest.approx(1 / 6)


def test_split_scores_empty_group_is_none():
    out = split_scores(["a"], ["a"], known_words={"a"})
    assert out["unseen"] is None


def test_coverage_table_trades_coverage_for_accuracy():
    table = coverage_table([0.9, 0.8, 0.4], [True, True, False], thresholds=[0.0, 0.5, 0.85, 0.99])
    by_t = {row["threshold"]: row for row in table}
    assert by_t[0.0]["coverage"] == pytest.approx(1.0)
    assert by_t[0.0]["accuracy"] == pytest.approx(2 / 3)
    assert by_t[0.5]["coverage"] == pytest.approx(2 / 3)
    assert by_t[0.5]["accuracy"] == pytest.approx(1.0)
    assert by_t[0.85]["coverage"] == pytest.approx(1 / 3)
    assert by_t[0.99]["coverage"] == 0.0 and by_t[0.99]["accuracy"] is None
