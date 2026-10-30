"""Bucket resolution for inward cheques.

A cheque that needs a human decision is classed by kind (HVC / CA / IP / FCC / LVC in the admin's priority order) or
falls to HR; a cheque the system decided is SIP-Success or SIP-Reject. All thresholds come from config."""
import pytest

from modules.cts.buckets import ALL_BUCKETS, BucketFacts, resolve_bucket, matched_buckets

CFG = {
    "bucket_priority": ["HVC", "CA", "IP", "FCC", "LVC"],
    "bucket_hvc_min_amount": 500_000, "bucket_lvc_max_amount": 50_000,
    "bucket_frequent_min_cheques": 5, "bucket_frequent_window_days": 30,
    "bucket_corporate_account_types": ["CORPORATE"], "bucket_institution_account_types": ["INSTITUTION", "GOVERNMENT"],
}


def human(**kw):
    return BucketFacts(needs_human=True, **kw)


def test_the_nine_buckets_exist():
    assert set(ALL_BUCKETS) == {"HVC", "CA", "IP", "LVC", "FCC", "SIP_SUCCESS", "SIP_REJECT", "HR", "MISC"}


# --- system-decided -----------------------------------------------------------------------------------------

def test_a_system_confirm_is_sip_success_and_a_system_return_is_sip_reject():
    assert resolve_bucket(BucketFacts(needs_human=False, system_decision="CONFIRM", amount=900_000), CFG) == "SIP_SUCCESS"
    assert resolve_bucket(BucketFacts(needs_human=False, system_decision="RETURN"), CFG) == "SIP_REJECT"


def test_a_system_decision_we_cannot_classify_goes_to_human_review_not_a_sip_bucket():
    assert resolve_bucket(BucketFacts(needs_human=False, system_decision=None), CFG) == "HR"


# --- class buckets for cheques that need a human ------------------------------------------------------------

@pytest.mark.parametrize("facts,expected", [
    (human(amount=500_000), "HVC"),                                          # at the threshold counts as high value
    (human(amount=2_000_000, account_type="CORPORATE"), "HVC"),              # priority: HVC before CA
    (human(amount=90_000, account_type="CORPORATE"), "CA"),
    (human(amount=90_000, account_type="GOVERNMENT"), "IP"),
    (human(amount=90_000, account_type="INSTITUTION"), "IP"),
    (human(amount=90_000, recent_cheques=7), "FCC"),
    (human(amount=3_000, recent_cheques=9), "FCC"),                          # FCC before LVC
    (human(amount=3_000, recent_cheques=1), "LVC"),
    (human(amount=90_000, recent_cheques=1), "HR"),                          # fits no class
    (human(), "HR"),                                                         # nothing known
])
def test_class_buckets_follow_the_priority_order(facts, expected):
    assert resolve_bucket(facts, CFG) == expected


def test_a_bank_maintained_account_list_puts_an_account_in_ca_or_ip():
    assert resolve_bucket(human(amount=90_000, listed_in=frozenset({"CA"})), CFG) == "CA"
    assert resolve_bucket(human(amount=90_000, listed_in=frozenset({"IP"})), CFG) == "IP"


def test_the_admins_priority_order_is_respected():
    cfg = {**CFG, "bucket_priority": ["LVC", "FCC", "CA", "IP", "HVC"]}
    assert resolve_bucket(human(amount=3_000, recent_cheques=9, account_type="CORPORATE"), cfg) == "LVC"


def test_a_bucket_left_out_of_the_priority_list_is_never_assigned():
    cfg = {**CFG, "bucket_priority": ["HVC", "CA"]}
    assert resolve_bucket(human(amount=3_000), cfg) == "HR"


def test_unknown_amount_never_matches_an_amount_rule():
    assert resolve_bucket(human(amount=None), CFG) == "HR"


def test_matched_buckets_lists_every_class_a_cheque_fits_for_the_admin_screen():
    assert matched_buckets(human(amount=900_000, account_type="CORPORATE", recent_cheques=9), CFG) == ["HVC", "CA", "FCC"]


def test_missing_config_falls_back_to_safe_defaults():
    assert resolve_bucket(human(amount=900_000), {}) == "HVC"
