"""
PolicyEngine — in-process Layer 4 business-policy evaluator (CLAUDE.md §2.6).

Replaces the OPA container: rules are Layer 3 config data (JSON list under
`cts.policy_rules`), so they hot-reload through config_service, are audited and
go through maker-checker like every other bank-configurable value. Same
`decide(OPAInput) -> OPAResult` contract as shared.opa_client.OPAClient.

Rule shape:
  {"id": "...", "when": [{"field": <OPAInput field>, "op": eq|ne|gt|gte|lt|lte|in,
                          "value": literal | "$cfg.<cts_config_key>"}, ...],   # AND
   "outcome": "HUMAN_REVIEW" | "AUTO_RETURN", "reason": "..."}

Safety invariants (structural, not configurable):
  * a rule can only produce HUMAN_REVIEW or AUTO_RETURN — never a confirm
  * HUMAN_REVIEW beats AUTO_RETURN when both match
  * rules unavailable or malformed -> HUMAN_REVIEW, never a silent PROCEED
  * no match -> PROCEED (downstream decision gates still apply)
"""
from __future__ import annotations

import operator
from typing import Any

import structlog

from shared.opa_client import OPAInput, OPAResult

log = structlog.get_logger()

_RULES_KEY = "cts.policy_rules"
_OUTCOMES = ("HUMAN_REVIEW", "AUTO_RETURN")
_OPS = {
    "eq": operator.eq, "ne": operator.ne, "gt": operator.gt, "gte": operator.ge,
    "lt": operator.lt, "lte": operator.le, "in": lambda a, b: a in b,
}
_FIELDS = frozenset(OPAInput.model_fields)


class _InvalidRule(Exception):
    pass


def _cfg_value(cfg: dict, key: str):
    """get_cts_config keys are module-prefixed ("cts.<key>"); accept either form."""
    return cfg[key] if key in cfg else cfg[f"cts.{key}"]


class PolicyEngine:
    def __init__(self, config_service: Any) -> None:
        self._config = config_service

    async def decide(self, inp: OPAInput) -> OPAResult:
        try:
            rules = await self._config.get(_RULES_KEY)
            cfg = await self._config.get_cts_config(inp.bank_id)
        except Exception as exc:
            log.warning("policy_engine.rules_unavailable", bank_id=inp.bank_id, error=str(exc))
            return OPAResult(decision="HUMAN_REVIEW", reason="policy_rules_unavailable")

        matched: list[tuple[str, str]] = []
        try:
            for rule in rules:
                outcome = rule["outcome"]
                if outcome not in _OUTCOMES:
                    raise _InvalidRule(f"outcome {outcome!r}")
                if self._matches(rule["when"], inp, cfg):
                    matched.append((outcome, rule.get("reason") or rule.get("id", "")))
        except (_InvalidRule, KeyError, TypeError) as exc:
            log.error("policy_engine.rule_invalid", bank_id=inp.bank_id, error=str(exc))
            return OPAResult(decision="HUMAN_REVIEW", reason="policy_rule_invalid")

        for wanted in _OUTCOMES:          # HUMAN_REVIEW first
            for outcome, reason in matched:
                if outcome == wanted:
                    return OPAResult(decision=outcome, reason=reason)
        return OPAResult(decision="PROCEED", reason="no_policy_rule_matched")

    @staticmethod
    def _matches(conditions: list[dict], inp: OPAInput, cfg: dict) -> bool:
        for c in conditions:
            field, op, want = c["field"], c["op"], c["value"]
            if field not in _FIELDS or op not in _OPS:
                raise _InvalidRule(f"field/op {field!r}/{op!r}")
            if isinstance(want, str) and want.startswith("$cfg."):
                want = _cfg_value(cfg, want[len("$cfg."):])
            if not _OPS[op](getattr(inp, field), want):
                return False
        return True
