"""The routing rules engine: who is told, on which channels, and when it escalates, across the Bank, PU and SMB levels. Pure code, no database."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from shared.alerting.routing_policy import (
    BusinessHours, Calendar, EscalationStep, IncidentFacts, Policy, Rule, TargetSpec, resolve_routing, validate_policy,
)

IST = ZoneInfo("Asia/Kolkata")
CAL = Calendar(timezone="Asia/Kolkata", business=BusinessHours(days=[0, 1, 2, 3, 4], start="09:30", end="18:00"), holidays=["2026-11-19"])
WED_NOON = datetime(2026, 11, 18, 12, 0, tzinfo=IST)         # a working day, inside hours
WED_NIGHT = datetime(2026, 11, 18, 22, 0, tzinfo=IST)        # a working day, after hours
SAT_NOON = datetime(2026, 11, 21, 12, 0, tzinfo=IST)
HOLIDAY_NOON = datetime(2026, 11, 19, 12, 0, tzinfo=IST)


def T(kind, ref, *channels):
    return TargetSpec(kind=kind, ref=ref, channels=list(channels))


def facts(severity="P0", component="redis", pu=None, smb=None, team=""):
    return IncidentFacts(severity=severity, component=component, owning_team=team, pu_id=pu, smb_id=smb)


def route(policies, f=None, now=WED_NOON):
    return resolve_routing(f or facts(), policies, CAL, now)


def refs(step):
    return sorted((t.kind, t.ref) for t in step.targets)


# ---------------- one level -----------------

def test_the_first_matching_rule_wins_within_a_level():
    bank = Policy(rules=[
        Rule(id="db", severities=["P0"], components=["yugabyte"], targets=[T("role", "dba", "email")]),
        Rule(id="all-p0", severities=["P0"], targets=[T("role", "ops_manager", "email", "bell")]),
        Rule(id="never", severities=["P0"], targets=[T("role", "nobody", "email")]),
    ])
    r = route({"BANK": bank}, facts(component="redis"))
    assert [m.rule_id for m in r.matched] == ["all-p0"] and refs(r.steps[0]) == [("role", "ops_manager")]
    r2 = route({"BANK": bank}, facts(component="yugabyte"))
    assert refs(r2.steps[0]) == [("role", "dba")]


def test_components_match_by_name_or_pattern_and_teams_by_name():
    bank = Policy(rules=[Rule(id="data", components=["yuga*", "redis"], targets=[T("role", "dba", "email")]),
                         Rule(id="ai", teams=["ml"], targets=[T("role", "ml_engineer", "email")])])
    assert refs(route({"BANK": bank}, facts(component="yugabyte")).steps[0]) == [("role", "dba")]
    assert refs(route({"BANK": bank}, facts(component="redis")).steps[0]) == [("role", "dba")]
    assert refs(route({"BANK": bank}, facts(component="vllm", team="ml")).steps[0]) == [("role", "ml_engineer")]


def test_a_rule_with_no_conditions_matches_everything_and_severity_must_be_listed_when_given():
    bank = Policy(rules=[Rule(id="p1only", severities=["P1"], targets=[T("role", "a", "email")]), Rule(id="any", targets=[T("role", "b", "email")])])
    assert refs(route({"BANK": bank}, facts("P0")).steps[0]) == [("role", "b")]
    assert refs(route({"BANK": bank}, facts("P1")).steps[0]) == [("role", "a")]


def test_no_matching_rule_is_reported_not_guessed():
    r = route({"BANK": Policy(rules=[Rule(id="p1", severities=["P1"], targets=[T("role", "a", "email")])])}, facts("P3"))
    assert r.steps == [] and r.matched == [] and "no_rule_matched" in r.warnings


def test_no_policy_at_all_is_the_same_as_no_match():
    assert route({}).warnings == ["no_rule_matched"]


# ---------------- schedules -----------------

def test_business_hours_off_hours_weekends_and_holidays():
    bank = Policy(rules=[Rule(id="in", hours="business", targets=[T("role", "day", "email")]), Rule(id="out", hours="off_hours", targets=[T("role", "night", "email")])])
    assert refs(route({"BANK": bank}, now=WED_NOON).steps[0]) == [("role", "day")]
    assert refs(route({"BANK": bank}, now=WED_NIGHT).steps[0]) == [("role", "night")]
    assert refs(route({"BANK": bank}, now=SAT_NOON).steps[0]) == [("role", "night")]
    assert refs(route({"BANK": bank}, now=HOLIDAY_NOON).steps[0]) == [("role", "night")]


def test_the_edges_of_business_hours():
    bank = Policy(rules=[Rule(id="in", hours="business", targets=[T("role", "day", "email")]), Rule(id="out", hours="off_hours", targets=[T("role", "night", "email")])])
    at = lambda h, m: datetime(2026, 11, 18, h, m, tzinfo=IST)
    assert refs(route({"BANK": bank}, now=at(9, 30)).steps[0]) == [("role", "day")]
    assert refs(route({"BANK": bank}, now=at(9, 29)).steps[0]) == [("role", "night")]
    assert refs(route({"BANK": bank}, now=at(17, 59)).steps[0]) == [("role", "day")]
    assert refs(route({"BANK": bank}, now=at(18, 0)).steps[0]) == [("role", "night")]


def test_the_time_is_judged_in_the_banks_timezone_whatever_zone_it_is_given_in():
    from datetime import timezone
    bank = Policy(rules=[Rule(id="in", hours="business", targets=[T("role", "day", "email")]), Rule(id="out", hours="off_hours", targets=[T("role", "night", "email")])])
    utc_noon_ist = datetime(2026, 11, 18, 6, 30, tzinfo=timezone.utc)                 # 12:00 IST
    assert refs(route({"BANK": bank}, now=utc_noon_ist).steps[0]) == [("role", "day")]


# ---------------- escalation -----------------

def test_the_first_step_is_immediate_and_escalation_steps_follow_in_order():
    bank = Policy(rules=[Rule(id="p0", severities=["P0"], targets=[T("role", "ops_manager", "email", "bell")],
                              escalation=[EscalationStep(level=1, after_minutes=5, targets=[T("role", "bank_it_admin", "email", "whatsapp")]),
                                          EscalationStep(level=2, after_minutes=15, targets=[T("external", "cto@bank.example", "email")])],
                              repeat_minutes=30)])
    r = route({"BANK": bank})
    assert [(s.level, s.after_minutes) for s in r.steps] == [(0, 0), (1, 5), (2, 15)]
    assert refs(r.steps[1]) == [("role", "bank_it_admin")] and refs(r.steps[2]) == [("external", "cto@bank.example")]
    assert r.repeat_minutes == 30


# ---------------- accumulate and floor -----------------

def test_the_pu_and_smb_levels_add_people_to_the_banks():
    bank = Policy(rules=[Rule(id="b", targets=[T("role", "ops_manager", "email")])])
    pu = Policy(rules=[Rule(id="p", targets=[T("role", "pu_head", "email")])])
    smb = Policy(rules=[Rule(id="s", targets=[T("user", "smb-admin-7", "email")])])
    r = route({"BANK": bank, "PU": pu, "SMB": smb}, facts(pu="PU1", smb="SMB7"))
    assert refs(r.steps[0]) == [("role", "ops_manager"), ("role", "pu_head"), ("user", "smb-admin-7")]
    assert [(m.level, m.rule_id) for m in r.matched] == [("BANK", "b"), ("PU", "p"), ("SMB", "s")]


def test_a_level_applies_only_to_its_own_scope():
    bank = Policy(rules=[Rule(id="b", targets=[T("role", "ops_manager", "email")])])
    pu = Policy(rules=[Rule(id="p", targets=[T("role", "pu_head", "email")])], scope_id="PU1")
    smb = Policy(rules=[Rule(id="s", targets=[T("user", "smb-admin-7", "email")])], scope_id="SMB7")
    assert refs(route({"BANK": bank, "PU": pu, "SMB": smb}, facts(pu="PU2", smb="SMB9")).steps[0]) == [("role", "ops_manager")]
    assert refs(route({"BANK": bank, "PU": pu, "SMB": smb}, facts(pu="PU1")).steps[0]) == [("role", "ops_manager"), ("role", "pu_head")]
    assert refs(route({"BANK": bank, "PU": pu, "SMB": smb}, facts(smb="SMB7")).steps[0]) == [("role", "ops_manager"), ("user", "smb-admin-7")]


def test_a_person_named_at_two_levels_gets_the_union_of_channels_once():
    bank = Policy(rules=[Rule(id="b", targets=[T("role", "ops_manager", "email", "bell")])])
    pu = Policy(rules=[Rule(id="p", targets=[T("role", "ops_manager", "whatsapp", "email")])])
    r = route({"BANK": bank, "PU": pu}, facts(pu="PU1"))
    assert len(r.steps[0].targets) == 1 and r.steps[0].targets[0].channels == ["email", "bell", "whatsapp"]


def test_a_lower_level_with_no_matching_rule_changes_nothing_and_the_bank_still_applies():
    bank = Policy(rules=[Rule(id="b", targets=[T("role", "ops_manager", "email")])])
    pu = Policy(rules=[Rule(id="p", severities=["P3"], targets=[T("role", "pu_head", "email")])])
    assert refs(route({"BANK": bank, "PU": pu}, facts("P0", pu="PU1")).steps[0]) == [("role", "ops_manager")]


def test_escalation_timing_of_a_step_is_the_banks_and_lower_levels_add_targets_to_it():
    bank = Policy(rules=[Rule(id="b", targets=[T("role", "ops_manager", "email")],
                              escalation=[EscalationStep(level=1, after_minutes=10, targets=[T("role", "bank_it_admin", "email")])])])
    pu = Policy(rules=[Rule(id="p", targets=[T("role", "pu_head", "email")],
                            escalation=[EscalationStep(level=1, after_minutes=2, targets=[T("role", "pu_director", "email")]),
                                        EscalationStep(level=2, after_minutes=20, targets=[T("role", "pu_ceo", "email")])])])
    r = route({"BANK": bank, "PU": pu}, facts(pu="PU1"))
    by_level = {s.level: s for s in r.steps}
    assert by_level[1].after_minutes == 10                                        # the banks timing wins
    assert refs(by_level[1]) == [("role", "bank_it_admin"), ("role", "pu_director")]
    assert by_level[2].after_minutes == 20 and refs(by_level[2]) == [("role", "pu_ceo")]    # a step only the PU defines keeps its own timing


def test_repeat_interval_is_the_banks_and_a_lower_level_cannot_lengthen_it():
    bank = Policy(rules=[Rule(id="b", targets=[T("role", "a", "email")], repeat_minutes=30)])
    pu = Policy(rules=[Rule(id="p", targets=[T("role", "b", "email")], repeat_minutes=120)])
    assert route({"BANK": bank, "PU": pu}, facts(pu="PU1")).repeat_minutes == 30
    only_pu = Policy(rules=[Rule(id="p", targets=[T("role", "b", "email")], repeat_minutes=120)])
    assert route({"BANK": Policy(rules=[Rule(id="b", targets=[T("role", "a", "email")])]), "PU": only_pu}, facts(pu="PU1")).repeat_minutes == 120


# ---------------- quiet hold -----------------

def test_a_low_priority_alert_is_held_until_working_hours_only_if_the_bank_allows_it():
    allow = Policy(rules=[Rule(id="b", severities=["P2", "P3"], quiet_hold=True, targets=[T("role", "ops_manager", "email")])])
    r = route({"BANK": allow}, facts("P2"), now=WED_NIGHT)
    assert r.held is True
    assert route({"BANK": allow}, facts("P2"), now=WED_NOON).held is False           # inside hours: sent now


def test_p0_and_p1_are_never_held_and_a_lower_level_cannot_switch_holding_on():
    hold_all = Policy(rules=[Rule(id="b", quiet_hold=True, targets=[T("role", "ops_manager", "email")])])
    assert route({"BANK": hold_all}, facts("P0"), now=WED_NIGHT).held is False
    assert route({"BANK": hold_all}, facts("P1"), now=WED_NIGHT).held is False
    bank = Policy(rules=[Rule(id="b", targets=[T("role", "ops_manager", "email")])])
    pu = Policy(rules=[Rule(id="p", quiet_hold=True, targets=[T("role", "pu_head", "email")])])
    assert route({"BANK": bank, "PU": pu}, facts("P2", pu="PU1"), now=WED_NIGHT).held is False


# ---------------- validation -----------------

def _ok_p0_rule(**kw):
    base = dict(id="p0", severities=["P0"], targets=[T("role", "ops_manager", "email", "bell")])
    base.update(kw)
    return Rule(**base)


def test_a_sound_policy_has_no_errors():
    assert validate_policy(Policy(rules=[_ok_p0_rule(), Rule(id="rest", targets=[T("role", "ops_manager", "email")])]), level="BANK") == []


def test_the_bank_policy_must_cover_p0_with_a_target_on_two_channels():
    assert "p0_not_covered" in validate_policy(Policy(rules=[Rule(id="x", severities=["P1"], targets=[T("role", "a", "email")])]), level="BANK")
    assert "p0_needs_two_channels" in validate_policy(Policy(rules=[_ok_p0_rule(targets=[T("role", "a", "email")])]), level="BANK")
    assert "p0_needs_a_target" in validate_policy(Policy(rules=[_ok_p0_rule(targets=[])]), level="BANK")
    assert validate_policy(Policy(rules=[Rule(id="x", severities=["P1"], targets=[T("role", "a", "email")])]), level="PU") == []        # only the bank level is held to it


def test_rule_ids_must_be_unique_channels_known_and_escalation_steps_increasing():
    errors = validate_policy(Policy(rules=[_ok_p0_rule(), _ok_p0_rule()]), level="BANK")
    assert "duplicate_rule_id" in errors
    assert "unknown_channel" in validate_policy(Policy(rules=[_ok_p0_rule(targets=[T("role", "a", "email", "carrier-pigeon")])]), level="BANK")
    bad_steps = _ok_p0_rule(escalation=[EscalationStep(level=1, after_minutes=10, targets=[T("role", "a", "email")]),
                                        EscalationStep(level=2, after_minutes=5, targets=[T("role", "b", "email")])])
    assert "escalation_not_increasing" in validate_policy(Policy(rules=[bad_steps]), level="BANK")
    assert "negative_minutes" in validate_policy(Policy(rules=[_ok_p0_rule(repeat_minutes=-1)]), level="BANK")


def test_the_escalation_chain_must_end_with_a_person_not_only_a_group_or_nothing():
    chain = _ok_p0_rule(escalation=[EscalationStep(level=1, after_minutes=10, targets=[T("group", "everyone", "email")])])
    assert "escalation_must_end_with_a_person" in validate_policy(Policy(rules=[chain]), level="BANK")
    fine = _ok_p0_rule(escalation=[EscalationStep(level=1, after_minutes=10, targets=[T("role", "bank_it_admin", "email")])])
    assert validate_policy(Policy(rules=[fine]), level="BANK") == []


def test_the_quiet_hold_flag_is_refused_on_p0_and_p1_rules():
    assert "quiet_hold_not_allowed" in validate_policy(Policy(rules=[_ok_p0_rule(quiet_hold=True)]), level="BANK")


# ---------------- when do working hours next start (for held alerts) -----------------

def test_the_next_business_start_is_now_during_hours_and_the_next_opening_otherwise():
    from shared.alerting.routing_policy import next_business_start
    assert next_business_start(WED_NOON, CAL) == WED_NOON
    # Thursday 19th is a holiday in CAL, so after hours on Wednesday it opens on Friday 20th at 09:30
    assert next_business_start(WED_NIGHT, CAL) == datetime(2026, 11, 20, 9, 30, tzinfo=IST)
    assert next_business_start(SAT_NOON, CAL) == datetime(2026, 11, 23, 9, 30, tzinfo=IST)      # Saturday: Monday morning
    assert next_business_start(datetime(2026, 11, 18, 7, 0, tzinfo=IST), CAL) == datetime(2026, 11, 18, 9, 30, tzinfo=IST)    # before opening: today


def test_there_is_no_next_business_start_when_the_calendar_never_opens():
    from shared.alerting.routing_policy import next_business_start
    assert next_business_start(WED_NOON, Calendar(timezone="Asia/Kolkata", business=BusinessHours(days=[]))) is None
