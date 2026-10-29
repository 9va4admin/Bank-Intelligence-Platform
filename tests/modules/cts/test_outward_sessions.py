"""Outward clearing session cut-offs: configurable per bank (a list of local times), never hard-coded."""
from datetime import datetime, timezone, timedelta

from modules.cts.outward_sessions import next_cutoff, parse_cutoffs, seconds_to_cutoff

IST = timezone(timedelta(hours=5, minutes=30))


def ist(h, m=0, day=29):
    return datetime(2026, 10, day, h, m, tzinfo=IST).timestamp()


CFG = {"outward_session_cutoffs": ["14:30"], "outward_session_timezone": "Asia/Kolkata"}


def test_the_default_cutoff_is_the_banks_configured_time_not_a_constant_in_code():
    assert next_cutoff(ist(10), CFG) == ist(14, 30)
    assert next_cutoff(ist(10), {**CFG, "outward_session_cutoffs": ["15:00"]}) == ist(15, 0)       # another bank, another time


def test_after_the_cutoff_the_next_one_is_tomorrows():
    assert next_cutoff(ist(15), CFG) == ist(14, 30, day=30)
    assert next_cutoff(ist(14, 30), CFG) == ist(14, 30, day=30)                    # exactly at the cut-off: that session is closed


def test_several_sessions_a_day_pick_the_next_one():
    cfg = {**CFG, "outward_session_cutoffs": ["11:00", "14:30"]}
    assert next_cutoff(ist(9), cfg) == ist(11)
    assert next_cutoff(ist(12), cfg) == ist(14, 30)
    assert next_cutoff(ist(16), cfg) == ist(11, day=30)


def test_the_list_is_forgiving_but_never_empty():
    assert parse_cutoffs(["14:30", "bad", "9:05", ""]) == [(9, 5), (14, 30)]
    assert parse_cutoffs('["10:15"]') == [(10, 15)]                              # stored as JSON text
    assert parse_cutoffs(None) == [(14, 30)] and parse_cutoffs([]) == [(14, 30)] and parse_cutoffs(["x"]) == [(14, 30)]


def test_a_bad_timezone_falls_back_to_india_time():
    assert next_cutoff(ist(10), {**CFG, "outward_session_timezone": "Not/AZone"}) == ist(14, 30)


def test_seconds_to_cutoff():
    assert seconds_to_cutoff(ist(14, 0), CFG) == 1800.0
