"""Outward review buckets: what kind of held item is it? Value (from the masked amount range the scan event keeps) and the
reason it was held. Everything comes from bank configuration."""
from modules.cts.buckets import ALL_BUCKETS
from modules.cts.outward_buckets import OUTWARD_BUCKETS, classify_outward

LOW, HIGH = "₹[<1L]", "₹[10L-1Cr]"


def test_a_high_value_item_is_high_value_whatever_held_it():
    assert classify_outward("MISMATCH_HELD", HIGH, {}) == "OUT_HV"
    assert classify_outward("HUMAN_REVIEW", HIGH, {}) == "OUT_HV"


def test_otherwise_the_reason_it_was_held_decides():
    assert classify_outward("MISMATCH_HELD", LOW, {}) == "OUT_MISMATCH"
    assert classify_outward("CTS_REJECTED", LOW, {}) == "OUT_COMPLIANCE"
    assert classify_outward("WORKFLOW_ERROR", LOW, {}) == "OUT_COMPLIANCE"
    assert classify_outward("HUMAN_REVIEW", LOW, {}) == "OUT_REVIEW"


def test_an_unknown_outcome_is_never_lost_it_goes_to_general_review():
    assert classify_outward("SOMETHING_NEW", LOW, {}) == "OUT_REVIEW"
    assert classify_outward(None, None, {}) == "OUT_REVIEW"


def test_the_banks_ranges_and_priority_are_configuration():
    cfg = {"outward_high_value_ranges": ["₹[1L-5L]"], "outward_bucket_priority": ["OUT_MISMATCH", "OUT_HV", "OUT_COMPLIANCE", "OUT_REVIEW"]}
    assert classify_outward("HUMAN_REVIEW", "₹[1L-5L]", cfg) == "OUT_HV"
    assert classify_outward("MISMATCH_HELD", "₹[1L-5L]", cfg) == "OUT_MISMATCH"        # the bank put mismatches first
    assert classify_outward("HUMAN_REVIEW", HIGH, cfg) == "OUT_REVIEW"                 # 10L-1Cr is not high value to this bank


def test_the_buckets_can_be_subscribed_to_like_any_other():
    assert set(OUTWARD_BUCKETS) <= set(ALL_BUCKETS)
