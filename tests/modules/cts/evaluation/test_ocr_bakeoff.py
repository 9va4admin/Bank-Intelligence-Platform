"""The bake-off scoring: normalisation, script detection, character error rate, the wrong-shown / withheld split, paired comparison, and the primary + second-reader pair analysis.
Pure functions, no model and no network. Thresholds are always passed in (they come from settings in real use)."""
from decimal import Decimal

import pytest

from modules.cts.evaluation.ocr_bakeoff import (
    Reading, Truth, cer, classify, cross_family_pairs, detect_script, mcnemar, names_agree, normalise_amount, normalise_text, paired_bootstrap_diff, pair_analysis, score,
)

GUARD = dict(guard_multiple=3, guard_min_chars=20)
KN, HI = "ರಾಜು ಪಂಡಿತ್", "राजू पंडीत"


def T(item, field="payee", text="Raju Pandit", script="LATIN", hw=True, quality="good", scoreable=True):
    return Truth(item_id=item, field=field, text=text, script=script, handwritten=hw, quality=quality, scoreable=scoreable)


def R(item, text, model="m", field="payee", failed=False, latency=10.0):
    return Reading(item_id=item, field=field, model=model, text=text, failed=failed, latency_ms=latency)


# ---------------------------------------------------------------- script and normalisation

def test_script_detection_names_the_majority_script_and_says_none_when_there_are_no_letters():
    assert detect_script(KN) == "KANNADA" and detect_script(HI) == "DEVANAGARI" and detect_script("Raju Pandit") == "LATIN"
    assert detect_script("தமிழ்") == "TAMIL" and detect_script("తెలుగు") == "TELUGU"
    assert detect_script("") == "NONE" and detect_script("123 /-") == "NONE" and detect_script(None) == "NONE"
    assert detect_script("Raju ರಾಜು ಪಂಡಿತ್") == "KANNADA"                        # more Kannada letters than Latin ones


def test_normalisation_makes_equal_text_equal_without_hiding_real_differences():
    assert normalise_text("  Raju   PANDIT. ") == normalise_text("raju pandit")
    assert normalise_text("é") == normalise_text("é")                  # decomposed and composed forms are the same text
    assert normalise_text("೧೨೩ ३४") == "123 34"                                    # Kannada and Devanagari digits read as digits
    assert normalise_text("Raju​ Pandit") == "raju pandit"                    # zero-width space is not text
    assert normalise_text("Raju Pandit") != normalise_text("Raju Pandt")
    assert normalise_text(None) == ""


def test_amounts_are_compared_as_numbers_whatever_the_decoration():
    assert normalise_amount("Rs. 30,000/-") == Decimal("30000") == normalise_amount("30000 only")
    assert normalise_amount("₹ 3,00,000.00") == Decimal("300000")             # Indian digit grouping
    assert normalise_amount("३०,०००") == Decimal("30000")  # Devanagari digits
    assert normalise_amount("abc") is None and normalise_amount("") is None and normalise_amount(None) is None


# ---------------------------------------------------------------- error rate and agreement

def test_character_error_rate_counts_edits_against_the_truth_and_never_exceeds_one():
    assert cer("abcd", "abcd") == 0.0
    assert cer("abcd", "abxd") == 0.25
    assert cer("abcd", "") == 1.0
    assert cer("ab", "abcdefgh") == 1.0                                            # capped: a long wrong answer is not "worse than totally wrong"
    assert cer("", "") == 0.0 and cer("", "x") == 1.0
    assert 0 < cer(KN, "ರಾಜು ಪಂಡಿತ") < 0.2                                         # one missing mark in Kannada is a small error


def test_two_reads_agree_when_their_letters_match_in_any_script_unlike_the_latin_only_rule_in_production():
    assert names_agree("Raju Pandit", "RAJU  PANDIT.", 0.99) is True
    assert names_agree(KN, KN, 0.99) is True and names_agree(HI, HI, 0.99) is True   # the production rule reduces these to nothing and never agrees
    assert names_agree(KN, "ರಾಜು ಪಂಡಿತ", 0.99) is False and names_agree(KN, "ರಾಜು ಪಂಡಿತ", 0.8) is True
    assert names_agree("Raju", "", 0.5) is False and names_agree(None, "Raju", 0.5) is False


# ---------------------------------------------------------------- classification of one reading

def test_a_reading_is_exact_wrong_shown_or_withheld_and_empty_or_failed_reads_are_withheld_not_wrong():
    t = T("i1")
    assert classify(t, R("i1", "raju pandit"), **GUARD).outcome == "EXACT"
    assert classify(t, R("i1", "Raju Pandet"), **GUARD).outcome == "WRONG_SHOWN"
    for empty in (None, "", "  ", "null", "NULL"):
        assert classify(t, R("i1", empty), **GUARD).outcome == "WITHHELD"
    assert classify(t, R("i1", "Raju Pandit", failed=True), **GUARD).outcome == "WITHHELD"
    assert classify(t, None, **GUARD).outcome == "WITHHELD"                          # no reading at all is withheld, never silently dropped


def test_an_overlong_output_is_a_guard_failure_withheld_and_counted_so_a_repetition_loop_cannot_look_like_an_answer():
    t = T("i1", text="Raju")
    loop = "Raju " * 200
    c = classify(t, R("i1", loop), **GUARD)
    assert c.outcome == "WITHHELD" and c.guard_tripped is True
    assert classify(t, R("i1", "Raju Pandit Kumar Singh"), **GUARD).guard_tripped is False     # long but within the allowed multiple and minimum


def test_an_answer_in_the_wrong_script_is_flagged_as_such():
    t = T("i1", text=KN, script="KANNADA")
    c = classify(t, R("i1", "राजू पंडीत"), **GUARD)
    assert c.outcome == "WRONG_SHOWN" and c.script_wrong is True
    assert classify(t, R("i1", "ರಾಜು ಪಂಡಿತ"), **GUARD).script_wrong is False                         # wrong letters, right script
    assert classify(T("i2", text="Raju", script="LATIN"), R("i2", "ರಾಜು"), **GUARD).script_wrong is True


def test_amount_figures_are_judged_as_numbers():
    t = T("i1", field="amount_figures", text="30000", script="NONE", hw=False)
    assert classify(t, R("i1", "Rs. 30,000/-", field="amount_figures"), **GUARD).outcome == "EXACT"
    assert classify(t, R("i1", "3,00,000", field="amount_figures"), **GUARD).outcome == "WRONG_SHOWN"
    assert classify(t, R("i1", "thirty", field="amount_figures"), **GUARD).outcome == "WRONG_SHOWN"
    assert classify(t, R("i1", "Rs. 30,000/-", field="amount_figures"), **GUARD).script_wrong is False


# ---------------------------------------------------------------- scoring across items

def build():
    truths = [T("a"), T("b"), T("c"), T("d", script="KANNADA", text=KN, hw=True), T("e", scoreable=False)]
    readings = [R("a", "Raju Pandit"), R("b", "Raju Pandet"), R("d", KN), R("e", "wrong")]      # "c" has no reading; "e" is not scoreable
    return truths, readings


def test_scores_count_every_scoreable_item_per_model_field_and_stratum_with_intervals():
    truths, readings = build()
    rows = score(truths, readings, models=["m"], by=("script",), **GUARD)
    all_rows = {(r.field, r.stratum): r for r in rows}
    latin = all_rows[("payee", "LATIN")]
    assert (latin.n, latin.exact, latin.wrong_shown, latin.withheld) == (3, 1, 1, 1)           # a exact, b wrong, c has no reading
    kn = all_rows[("payee", "KANNADA")]
    assert (kn.n, kn.exact) == (1, 1)
    assert 0 <= latin.exact_ci[0] <= latin.exact <= latin.n and latin.exact_ci[1] <= 1.0
    assert all(r.n for r in rows)
    assert {r.dimension for r in rows} == {"all", "script"} and {(r.stratum, r.dimension) for r in rows if r.stratum == "ALL"} == {("ALL", "all")}   # each row says which split it is
    assert {(r.field, r.stratum): r for r in rows}[("payee", "ALL")].n == 4                  # the item that is not scoreable is left out


def test_the_overall_stratum_and_mean_cer_and_guard_counts_are_reported():
    truths, readings = build()
    readings.append(R("c", "Raju " * 100))
    rows = score(truths, readings, models=["m"], by=("script",), **GUARD)
    overall = {(r.field, r.stratum): r for r in rows}[("payee", "ALL")]
    assert overall.n == 4 and overall.guard_tripped == 1 and 0.0 <= overall.mean_cer <= 1.0


def test_a_model_with_no_readings_is_all_withheld_not_missing_from_the_table():
    truths, _ = build()
    rows = score(truths, [], models=["silent"], by=("script",), **GUARD)
    overall = {(r.field, r.stratum): r for r in rows}[("payee", "ALL")]
    assert overall.model == "silent" and overall.withheld == overall.n == 4


# ---------------------------------------------------------------- paired comparison

def test_mcnemar_uses_only_the_items_where_the_models_disagree_and_gives_an_exact_p_value():
    a = {f"i{k}": k < 8 for k in range(20)}                                         # model A right on i0..i7
    b = {f"i{k}": (k < 8 and k >= 6) or k in (10, 11) for k in range(20)}           # B right on i6, i7, i10, i11
    r = mcnemar(a, b)
    assert (r.a_only, r.b_only, r.pairs) == (6, 2, 20)
    assert r.p_value == pytest.approx(0.2891, abs=1e-3)                             # exact two-sided binomial on 8 discordant pairs: 2 * (1+8+28)/256
    same = mcnemar({"x": True}, {"x": True})
    assert same.p_value == 1.0 and same.a_only == same.b_only == 0
    assert mcnemar({"x": True, "y": True}, {"x": False}).pairs == 1                  # only items present in both


def test_the_paired_bootstrap_is_deterministic_and_its_interval_straddles_zero_for_identical_models():
    a = [1, 0, 0, 1, 0, 0, 0, 1, 0, 0] * 5
    b = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0] * 5
    d1 = paired_bootstrap_diff(a, b, resamples=500, seed=7)
    d2 = paired_bootstrap_diff(a, b, resamples=500, seed=7)
    assert d1 == d2 and d1.diff == pytest.approx(0.3) and d1.lo > 0
    same = paired_bootstrap_diff(a, a, resamples=500, seed=7)
    assert same.diff == 0 and same.lo <= 0 <= same.hi


# ---------------------------------------------------------------- the pair: primary reader + independent second reader

def test_pairing_sorts_every_item_into_what_the_bank_would_actually_see():
    truths = [T(str(k)) for k in range(1, 7)]
    primary = [R("1", "Raju Pandit", "p"), R("2", "Raju Pandet", "p"), R("3", "Raju Pandit", "p"), R("4", "Raju Pandet", "p"), R("5", None, "p"), R("6", "Raju Pandit", "p")]
    second = [R("1", "Raju Pandit", "s"), R("2", "Raju Pandet", "s"), R("3", "Gopal Rao", "s"), R("4", "Raju Pandit", "s"), R("5", "Raju Pandit", "s")]  # "6": no second reading
    res = pair_analysis(truths, primary, second, primary_model="p", second_model="s", field="payee", min_similarity=0.99, **GUARD)
    assert res.n == 6
    assert res.agree_correct == 1                       # item 1
    assert res.wrong_shown == 1                         # item 2: both read the same wrong thing and agree: the dangerous case
    assert res.review_primary_correct == 2              # items 3 and 6: a good read sent to a human
    assert res.review_primary_wrong == 1                # item 4: the disagreement caught a wrong read
    assert res.review_primary_unread == 1               # item 5
    assert res.wrong_shown_rate == pytest.approx(1 / 6) and res.review_rate == pytest.approx(4 / 6)


def test_a_pair_works_for_indic_text_where_the_production_rule_could_never_agree():
    truths = [T("1", text=KN, script="KANNADA")]
    res = pair_analysis(truths, [R("1", KN, "p")], [R("1", KN, "s")], primary_model="p", second_model="s", field="payee", min_similarity=0.99, **GUARD)
    assert res.agree_correct == 1 and res.review_rate == 0


def test_only_pairs_of_different_model_families_are_proposed_and_both_orders_are_included():
    families = {"dots": "dots", "dots_m": "dots", "qwen8": "qwen", "qwen32": "qwen", "hunyuan": "hunyuan"}
    pairs = cross_family_pairs(families)
    assert ("dots", "dots_m") not in pairs and ("qwen8", "qwen32") not in pairs
    assert ("dots", "qwen8") in pairs and ("qwen8", "dots") in pairs and ("hunyuan", "dots") in pairs
    assert len(pairs) == 16                                                              # 20 ordered pairs minus the 4 ordered pairs inside a family
