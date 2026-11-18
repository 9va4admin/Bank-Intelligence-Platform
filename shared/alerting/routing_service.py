"""The routing service: an incident (or just its facts) in, the final routing out (docs/design/alerting-1b-plan.md).

It combines what the other pieces know: the stored Bank/PU/SMB policies (or, for a bank with no policy of its own, the default built from today's flat settings),
the calendar, and the people on call right now. Escalation, the send path and the "who would be told" simulator all call this one place, so they cannot disagree.
A policy store that cannot be read degrades to the default with a warning; it never leaves an incident without an audience.

Setting (Layer 3): alerting.component_teams, a JSON map of component to owning team (used by rules that match on team).
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

import structlog
from pydantic import BaseModel, ConfigDict

from shared.alerting.oncall import expand_oncall_targets
from shared.alerting.policy_defaults import build_default_bank_policy, load_calendar
from shared.alerting.routing_policy import IncidentFacts, Routing, resolve_routing

log = structlog.get_logger()


class RoutedIncident(BaseModel):
    model_config = ConfigDict(frozen=False)
    routing: Routing
    facts: IncidentFacts
    used_default: bool = False


class RoutingService:
    def __init__(self, *, config_service: Any, bank_id: str, policy_store: Any = None, oncall_store: Any = None) -> None:
        self._cfg, self._bank, self._policies, self._oncall = config_service, bank_id, policy_store, oncall_store

    async def _teams(self) -> dict[str, str]:
        try:
            raw = await self._cfg.get("alerting.component_teams")
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            return {str(k): str(v) for k, v in parsed.items()} if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    async def facts_for(self, incident: dict) -> IncidentFacts:
        component = str(incident.get("component") or "")
        return IncidentFacts(severity=incident["severity"], component=component, owning_team=(await self._teams()).get(component, ""),
                             pu_id=incident.get("pu_id"), smb_id=incident.get("smb_id"))

    async def route_incident(self, incident: dict, now: datetime) -> RoutedIncident:
        return await self.route_facts(await self.facts_for(incident), now)

    async def route_facts(self, facts: IncidentFacts, now: datetime) -> RoutedIncident:
        warnings: list[str] = []
        policies: dict = {}
        if self._policies is not None:
            try:
                policies = await self._policies.effective(self._bank, facts)
            except Exception as exc:  # noqa: BLE001
                log.warning("routing_service.policy_store_unavailable", bank_id=self._bank, error=type(exc).__name__)
                warnings.append("policy_store_unavailable")
        used_default = "BANK" not in policies
        if used_default:
            policies = {**policies, "BANK": [await build_default_bank_policy(self._cfg)]}
        calendar = await load_calendar(self._cfg)
        routing = resolve_routing(facts, policies, calendar, now)
        names = sorted({t.ref for step in routing.steps for t in step.targets if t.kind == "oncall"})
        if names:
            try:
                on_call = await self._oncall.current_many(self._bank, names, now, calendar) if self._oncall is not None else {}
            except Exception as exc:  # noqa: BLE001
                log.warning("routing_service.oncall_unavailable", bank_id=self._bank, error=type(exc).__name__)
                warnings.append("oncall_unavailable")
                on_call = {}
            routing = expand_oncall_targets(routing, on_call)
        routing.warnings.extend(w for w in warnings if w not in routing.warnings)
        return RoutedIncident(routing=routing, facts=facts, used_default=used_default)
