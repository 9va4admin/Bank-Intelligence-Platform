"""PolicyEngine — in-process Layer 4 business-policy evaluator (replaces the OPA
container; see CLAUDE.md §2.6). Rules are Layer 3 config data (JSON), hot-reloaded
via config_service; same decide(OPAInput) -> OPAResult contract as OPAClient."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from shared.opa_client import OPAInput


def _inp(**kw):
    base = dict(instrument_id="i1", bank_id="kbl", cheque_type="STANDARD", amount=1000.0,
                account_status="ACTIVE", is_first_clearing_day=False,
                has_government_flag=False, has_court_order_flag=False)
    base.update(kw)
    return OPAInput(**base)


def _engine(rules, cfg=None):
    from shared.policy_engine import PolicyEngine
    cs = MagicMock()
    cs.get = AsyncMock(return_value=rules)
    cs.get_cts_config = AsyncMock(return_value=cfg or {"high_value_amount_threshold": 500000})
    return PolicyEngine(cs)


R_GOV = {"id": "gov", "when": [{"field": "has_government_flag", "op": "eq", "value": True}],
         "outcome": "HUMAN_REVIEW", "reason": "government_cheque"}
R_CLOSED = {"id": "closed", "when": [{"field": "account_status", "op": "eq", "value": "CLOSED"}],
            "outcome": "AUTO_RETURN", "reason": "account_closed"}
R_FIRSTDAY = {"id": "fd", "when": [
    {"field": "amount", "op": "gt", "value": "$cfg.high_value_amount_threshold"},
    {"field": "is_first_clearing_day", "op": "eq", "value": True}],
    "outcome": "HUMAN_REVIEW", "reason": "high_value_first_day"}


@pytest.mark.asyncio
async def test_no_rule_matches_proceeds():
    r = await _engine([R_GOV, R_CLOSED]).decide(_inp())
    assert (r.decision, r.reason) == ("PROCEED", "no_policy_rule_matched")


@pytest.mark.asyncio
async def test_matching_rule_returns_its_outcome_and_reason():
    r = await _engine([R_GOV]).decide(_inp(has_government_flag=True))
    assert (r.decision, r.reason) == ("HUMAN_REVIEW", "government_cheque")


@pytest.mark.asyncio
async def test_all_conditions_must_hold_and_cfg_reference_resolves():
    eng = _engine([R_FIRSTDAY], cfg={"high_value_amount_threshold": 5000})
    assert (await eng.decide(_inp(amount=9000, is_first_clearing_day=True))).decision == "HUMAN_REVIEW"
    assert (await eng.decide(_inp(amount=9000, is_first_clearing_day=False))).decision == "PROCEED"
    assert (await eng.decide(_inp(amount=100, is_first_clearing_day=True))).decision == "PROCEED"


@pytest.mark.asyncio
async def test_human_review_beats_auto_return_when_both_match():
    r = await _engine([R_CLOSED, R_GOV]).decide(_inp(account_status="CLOSED", has_government_flag=True))
    assert r.decision == "HUMAN_REVIEW"     # never auto-return over a review trigger


@pytest.mark.asyncio
async def test_in_operator():
    rule = {"id": "x", "when": [{"field": "account_status", "op": "in", "value": ["FROZEN", "DORMANT"]}],
            "outcome": "HUMAN_REVIEW", "reason": "acct_state"}
    assert (await _engine([rule]).decide(_inp(account_status="DORMANT"))).decision == "HUMAN_REVIEW"


@pytest.mark.asyncio
async def test_rules_unavailable_fails_safe_to_human_review():
    from shared.policy_engine import PolicyEngine
    cs = MagicMock(); cs.get = AsyncMock(side_effect=RuntimeError("db down"))
    r = await PolicyEngine(cs).decide(_inp())
    assert (r.decision, r.reason) == ("HUMAN_REVIEW", "policy_rules_unavailable")


@pytest.mark.asyncio
async def test_malformed_rule_fails_safe_to_human_review():
    bad = {"id": "bad", "when": [{"field": "nonexistent", "op": "eq", "value": 1}],
           "outcome": "AUTO_RETURN", "reason": "x"}
    r = await _engine([bad]).decide(_inp())
    assert (r.decision, r.reason) == ("HUMAN_REVIEW", "policy_rule_invalid")


@pytest.mark.asyncio
async def test_outcome_can_never_be_anything_but_review_or_return():
    bad = {"id": "b", "when": [], "outcome": "STP_CONFIRM", "reason": "x"}
    assert (await _engine([bad]).decide(_inp())).decision == "HUMAN_REVIEW"


def test_default_rules_cover_the_rego_triggers():
    from shared.config.config_service import _LAYER3_DEFAULTS
    ids = {r["id"] for r in _LAYER3_DEFAULTS["cts.policy_rules"]}
    assert {"government_cheque", "court_order", "high_value_first_day",
            "account_frozen", "account_closed"} <= ids
