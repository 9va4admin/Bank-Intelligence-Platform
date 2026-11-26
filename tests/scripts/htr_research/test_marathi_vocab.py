"""Marathi cheque vocabulary: number words, amount-in-words composition, and the word lists."""
import re

import pytest

from htr_research import marathi_vocab as mv

DEVANAGARI = re.compile(r"^[ऀ-ॿ‌‍]+$")


def test_every_number_from_zero_to_hundred_has_a_word():
    assert sorted(mv.NUMBER_WORDS) == list(range(0, 101))


def test_number_words_are_distinct_and_devanagari():
    words = list(mv.NUMBER_WORDS.values())
    assert len(set(words)) == len(words)
    assert all(DEVANAGARI.match(w) for w in words)


@pytest.mark.parametrize("n,expected", [
    (1, "एक"), (10, "दहा"), (19, "एकोणीस"), (25, "पंचवीस"), (50, "पन्नास"), (99, "नव्व्याण्णव"), (100, "शंभर"),
])
def test_known_number_words(n, expected):
    assert mv.NUMBER_WORDS[n] == expected


@pytest.mark.parametrize("amount,expected", [
    (0, "शून्य"),
    (7, "सात"),
    (100, "शंभर"),
    (250, "दोनशे पन्नास"),
    (900, "नऊशे"),
    (1000, "एक हजार"),
    (12345, "बारा हजार तीनशे पंचेचाळीस"),
    (100000, "एक लाख"),
    (525000, "पाच लाख पंचवीस हजार"),
    (10000000, "एक कोटी"),
    (12500000, "एक कोटी पंचवीस लाख"),
])
def test_amount_in_words(amount, expected):
    assert mv.amount_to_words(amount) == expected


def test_amount_phrase_wraps_with_rupees_and_only():
    assert mv.amount_phrase(12345) == "रुपये बारा हजार तीनशे पंचेचाळीस फक्त"


def test_amount_rejects_negative_and_too_large():
    with pytest.raises(ValueError):
        mv.amount_to_words(-1)
    with pytest.raises(ValueError):
        mv.amount_to_words(10**9)


def test_numerals_convert_both_ways():
    assert mv.to_devanagari_digits("12,345") == "१२,३४५"
    assert mv.to_devanagari_digits("0") == "०"


def test_word_lists_are_clean_and_unique():
    for name in ("FIRST_NAMES_MALE", "FIRST_NAMES_FEMALE", "SURNAMES", "CITIES", "CHEQUE_TERMS"):
        items = getattr(mv, name)
        assert len(items) >= 15, name
        assert len(set(items)) == len(items), name
        assert all(DEVANAGARI.match(w) for w in items), name


def test_cheque_terms_cover_the_phrases_on_a_cheque():
    for term in ("रुपये", "फक्त", "धारकास"):
        assert term in mv.CHEQUE_TERMS


def test_every_word_is_exported_without_duplicates():
    words = mv.all_words()
    assert len(set(words)) == len(words)
    assert "पाटील" in words and "पुणे" in words and "लाख" in words


def test_prompt_sheet_is_reproducible_and_balanced():
    a = mv.prompt_sheet(seed=7, size=60)
    b = mv.prompt_sheet(seed=7, size=60)
    assert a == b
    assert len(a) == 60
    kinds = {k for k, _ in a}
    assert {"number", "name", "city", "term"} <= kinds
