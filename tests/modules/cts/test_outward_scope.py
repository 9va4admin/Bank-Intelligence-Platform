"""Who may make or check an outward decision: branch staff, central staff, or branch first with central as fallback.
Set per bank (cts.outward_maker_scope / outward_checker_scope); a user with no branches is central staff."""
from modules.cts.outward_scope import checker_allowed, maker_allowed

FALLBACK = 10 * 60


def cfg(scope="CENTRAL", checker="ANY"):
    return {"outward_maker_scope": scope, "outward_branch_first_fallback_minutes": 10, "outward_checker_scope": checker}


def test_central_scope_lets_only_central_staff_make_decisions():
    assert maker_allowed(cfg("CENTRAL"), [], "B1", 0) is True
    assert maker_allowed(cfg("CENTRAL"), ["B1"], "B1", 0) is False


def test_branch_scope_lets_only_the_items_branch_staff_make_decisions():
    assert maker_allowed(cfg("BRANCH"), ["B1"], "B1", 0) is True
    assert maker_allowed(cfg("BRANCH"), ["B2"], "B1", 0) is False
    assert maker_allowed(cfg("BRANCH"), [], "B1", 10_000) is False             # central staff never, however long it waits


def test_branch_first_gives_the_branch_a_head_start_then_central_may_take_it():
    c = cfg("BRANCH_FIRST")
    assert maker_allowed(c, ["B1"], "B1", 0) is True                            # the branch can always take it
    assert maker_allowed(c, [], "B1", FALLBACK - 1) is False                    # central waits
    assert maker_allowed(c, [], "B1", FALLBACK) is True                         # then central may take it too
    assert maker_allowed(c, ["B2"], "B1", 10_000) is False                      # another branch's staff never


def test_the_default_is_central_so_existing_reviewers_keep_working():
    assert maker_allowed({}, [], "B1", 0) is True


def test_an_unknown_scope_value_falls_back_to_central():
    assert maker_allowed(cfg("SOMETHING"), [], "B1", 0) is True and maker_allowed(cfg("SOMETHING"), ["B1"], "B1", 0) is False


def test_checkers_may_be_anyone_or_central_only():
    assert checker_allowed(cfg(checker="ANY"), ["B1"]) is True
    assert checker_allowed(cfg(checker="CENTRAL"), ["B1"]) is False
    assert checker_allowed(cfg(checker="CENTRAL"), []) is True
