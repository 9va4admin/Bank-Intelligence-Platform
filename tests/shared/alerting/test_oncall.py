"""Who is on call right now: shifts (including overnight ones), rotation, overrides, holidays, the fallback, gap detection, and how an on-call target in a
routing result becomes real people. Pure code, no database."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from shared.alerting.oncall import Fallback, OnCall, Rota, Shift, expand_oncall_targets, find_gaps, validate_rota, who_is_on_call
from shared.alerting.routing_policy import BusinessHours, Calendar, ResolvedStep, ResolvedTarget, Routing

IST = ZoneInfo("Asia/Kolkata")
CAL = Calendar(timezone="Asia/Kolkata", business=BusinessHours(), holidays=["2026-11-19"])


def at(day, hour, minute=0):
    """2026-11-16 is a Monday."""
    return datetime(2026, 11, 16, hour, minute, tzinfo=IST) + timedelta(days=day)


def users(result):
    return sorted(result.users)


def now_on(rota, when, overrides=None):
    return who_is_on_call(rota, overrides or [], when, CAL)


DAY = Shift(days=[0, 1, 2, 3, 4], start="09:30", end="18:00", users=["alice"])


def test_a_shift_covers_its_days_and_hours_only():
    rota = Rota(shifts=[DAY])
    assert users(now_on(rota, at(0, 12))) == ["alice"] and now_on(rota, at(0, 12)).source == "shift"
    assert now_on(rota, at(0, 9, 29)).users == [] and now_on(rota, at(0, 18)).users == []        # the end is exclusive
    assert now_on(rota, at(5, 12)).users == []                                                    # Saturday


def test_an_overnight_shift_belongs_to_the_day_it_starts():
    night = Rota(shifts=[Shift(days=[0, 1, 2, 3, 4], start="22:00", end="06:00", users=["nina"])])
    assert users(now_on(night, at(0, 23))) == ["nina"]                      # Monday 23:00
    assert users(now_on(night, at(1, 2))) == ["nina"]                       # Tuesday 02:00 is Monday's shift
    assert now_on(night, at(0, 2)).users == []                              # Monday 02:00 would be Sunday's shift: not in days
    assert users(now_on(night, at(5, 2))) == ["nina"]                       # Saturday 02:00 is Friday's shift
    assert now_on(night, at(1, 12)).users == []


def test_several_shifts_can_cover_the_clock_between_them():
    rota = Rota(shifts=[Shift(days=list(range(7)), start="06:00", end="14:00", users=["a"]), Shift(days=list(range(7)), start="14:00", end="22:00", users=["b"]),
                        Shift(days=list(range(7)), start="22:00", end="06:00", users=["c"])])
    assert [users(now_on(rota, at(2, h))) for h in (3, 7, 15, 23)] == [["c"], ["a"], ["b"], ["c"]]


def test_everyone_listed_is_on_call_together_unless_the_shift_rotates():
    assert users(now_on(Rota(shifts=[Shift(days=list(range(7)), start="00:00", end="23:59", users=["a", "b"])]), at(0, 12))) == ["a", "b"]


def test_weekly_and_daily_rotation_pick_one_person_in_turn():
    weekly = Rota(shifts=[Shift(days=list(range(7)), start="00:00", end="23:59", users=["a", "b", "c"], rotation="weekly")])
    picks = [users(now_on(weekly, at(7 * w, 12)))[0] for w in range(4)]
    assert sorted(set(picks[:3])) == ["a", "b", "c"] and picks[3] == picks[0]               # a full cycle, then it repeats
    assert len({tuple(users(now_on(weekly, at(d, 12)))) for d in range(7)}) == 1             # the same person all week
    daily = Rota(shifts=[Shift(days=list(range(7)), start="00:00", end="23:59", users=["a", "b"], rotation="daily")])
    assert len({tuple(users(now_on(daily, at(d, 12)))) for d in range(2)}) == 2


def test_an_override_replaces_the_rota_for_its_period():
    rota = Rota(shifts=[DAY])
    ov = [{"user_id": "bob", "starts_at": at(0, 10), "ends_at": at(0, 14)}]
    r = now_on(rota, at(0, 12), ov)
    assert users(r) == ["bob"] and r.source == "override"
    assert users(now_on(rota, at(0, 15), ov)) == ["alice"]                 # after it ends the rota is back
    assert users(now_on(rota, at(0, 9, 45), ov)) == ["alice"]


def test_overlapping_overrides_are_all_on_call_and_an_override_can_cover_a_gap():
    ov = [{"user_id": "bob", "starts_at": at(5, 8), "ends_at": at(5, 20)}, {"user_id": "carol", "starts_at": at(5, 10), "ends_at": at(5, 12)}]
    assert users(now_on(Rota(shifts=[DAY]), at(5, 11), ov)) == ["bob", "carol"]


def test_the_fallback_covers_what_no_shift_does_and_nothing_is_reported_when_there_is_none():
    rota = Rota(shifts=[DAY], fallback=Fallback(users=["manager"]))
    r = now_on(rota, at(5, 12))
    assert users(r) == ["manager"] and r.source == "fallback"
    none = now_on(Rota(shifts=[DAY]), at(5, 12))
    assert none.users == [] and none.source == "none"


def test_holiday_handling_per_shift():
    rota = Rota(shifts=[Shift(days=list(range(7)), start="00:00", end="23:59", users=["workday"], holidays="exclude"),
                        Shift(days=list(range(7)), start="00:00", end="23:59", users=["holiday"], holidays="only")])
    assert users(now_on(rota, at(2, 12))) == ["workday"]                    # Wednesday 18 Nov
    assert users(now_on(rota, at(3, 12))) == ["holiday"]                    # Thursday 19 Nov is in the calendar's holidays


def test_gaps_are_found_and_merged():
    weekdays_only = Rota(shifts=[Shift(days=[0, 1, 2, 3, 4], start="00:00", end="23:59", users=["a"])])
    gaps = find_gaps(weekdays_only, [], CAL, start=at(0, 0), days=7, step_minutes=60)
    assert len(gaps) == 1 and gaps[0][0] == at(5, 0) and gaps[0][1] >= at(6, 23)          # Saturday and Sunday as one gap
    full = Rota(shifts=[Shift(days=list(range(7)), start="00:00", end="23:59", users=["a"])])
    assert find_gaps(full, [], CAL, start=at(0, 0), days=7, step_minutes=60) == []
    assert find_gaps(Rota(shifts=[DAY], fallback=Fallback(users=["m"])), [], CAL, start=at(0, 0), days=7, step_minutes=60) == []      # a fallback closes every gap


# ---------------- turning on-call targets into people -----------------

def _routing():
    return Routing(steps=[
        ResolvedStep(level=0, after_minutes=0, targets=[ResolvedTarget(kind="oncall", ref="ops", channels=["email", "whatsapp"]), ResolvedTarget(kind="role", ref="ops_manager", channels=["bell"])]),
        ResolvedStep(level=1, after_minutes=10, targets=[ResolvedTarget(kind="oncall", ref="dba", channels=["email"])])])


def test_an_on_call_target_becomes_the_people_on_call_with_the_same_channels():
    r = expand_oncall_targets(_routing(), {"ops": OnCall(users=["alice", "bob"], source="shift"), "dba": OnCall(users=["dora"], source="shift")})
    first = sorted((t.kind, t.ref, tuple(t.channels)) for t in r.steps[0].targets)
    assert first == [("role", "ops_manager", ("bell",)), ("user", "alice", ("email", "whatsapp")), ("user", "bob", ("email", "whatsapp"))]
    assert [(t.kind, t.ref) for t in r.steps[1].targets] == [("user", "dora")] and r.steps[1].after_minutes == 10


def test_an_unfilled_rota_is_dropped_with_a_warning_not_silently():
    r = expand_oncall_targets(_routing(), {"ops": OnCall(users=[], source="none")})
    assert "oncall_unfilled:ops" in r.warnings and "oncall_unfilled:dba" in r.warnings        # an unknown rota counts as unfilled
    assert [(t.kind, t.ref) for t in r.steps[0].targets] == [("role", "ops_manager")]


def test_a_person_already_named_gets_the_union_of_channels_once():
    routing = Routing(steps=[ResolvedStep(level=0, after_minutes=0, targets=[ResolvedTarget(kind="user", ref="alice", channels=["bell"]),
                                                                              ResolvedTarget(kind="oncall", ref="ops", channels=["email"])])])
    r = expand_oncall_targets(routing, {"ops": OnCall(users=["alice"], source="shift")})
    assert len(r.steps[0].targets) == 1 and r.steps[0].targets[0].channels == ["bell", "email"]


# ---------------- validation -----------------

def test_a_sound_rota_has_no_errors_and_bad_ones_are_explained():
    assert validate_rota(Rota(shifts=[DAY])) == []
    assert "bad_time" in validate_rota(Rota(shifts=[Shift(days=[0], start="25:00", end="18:00", users=["a"])]))
    assert "bad_time" in validate_rota(Rota(shifts=[Shift(days=[0], start="09:30", end="09:30", users=["a"])]))           # empty shift
    assert "bad_day" in validate_rota(Rota(shifts=[Shift(days=[7], start="09:00", end="10:00", users=["a"])]))
    assert "shift_needs_people" in validate_rota(Rota(shifts=[Shift(days=[0], start="09:00", end="10:00", users=[])]))
    assert "unknown_rotation" in validate_rota(Rota(shifts=[Shift(days=[0], start="09:00", end="10:00", users=["a"], rotation="monthly")]))
    assert "rota_has_no_one" in validate_rota(Rota(shifts=[]))
    assert validate_rota(Rota(shifts=[], fallback=Fallback(users=["m"]))) == []
