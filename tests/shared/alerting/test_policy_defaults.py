"""The default policy (what a bank that configured nothing new gets, built from today's flat settings) and the calendar read from configuration."""
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from shared.alerting.policy_defaults import build_default_bank_policy, load_calendar
from shared.alerting.routing_policy import IncidentFacts, resolve_routing

IST = ZoneInfo("Asia/Kolkata")
NOON = datetime(2026, 11, 18, 12, 0, tzinfo=IST)


class Cfg:
    def __init__(self, **v):
        self.v = v

    async def get(self, key):
        from shared.config.config_service import ConfigKeyNotFoundError
        if key not in self.v:
            raise ConfigKeyNotFoundError(key)
        return self.v[key]


def _route(policy, severity):
    from shared.alerting.routing_policy import Calendar
    return resolve_routing(IncidentFacts(severity=severity, component="redis"), {"BANK": policy}, Calendar(timezone="Asia/Kolkata"), NOON)


def _channels(routing):
    return sorted((t.kind, t.ref, tuple(t.channels)) for t in routing.steps[0].targets)


def test_the_flat_settings_become_the_same_audience_as_before():
    p = asyncio.run(build_default_bank_policy(Cfg(**{"alerts.email_recipients": "ops@x.in, dba@x.in", "alerts.whatsapp_recipients": "+919800000001",
                                                    "alerting.bell_roles": '["ops_manager", "bank_it_admin"]'})))
    p0 = _channels(_route(p, "P0"))
    assert ("external", "ops@x.in", ("email",)) in p0 and ("external", "dba@x.in", ("email",)) in p0
    assert ("external", "+919800000001", ("whatsapp",)) in p0                                  # WhatsApp floor defaults to P0
    assert ("role", "ops_manager", ("bell",)) in p0 and ("role", "bank_it_admin", ("bell",)) in p0
    p1 = _channels(_route(p, "P1"))
    assert not any(c == ("whatsapp",) for _, _, c in p1) and ("external", "ops@x.in", ("email",)) in p1


def test_the_whatsapp_and_bell_floors_from_configuration_are_respected():
    cfg = Cfg(**{"alerts.email_recipients": "ops@x.in", "alerts.whatsapp_recipients": "+919800000001", "alerts.whatsapp_min_priority": "P1",
                 "alerting.bell_roles": '["ops_manager"]', "alerting.bell_min_priority": "P1"})
    p = asyncio.run(build_default_bank_policy(cfg))
    assert any(c == ("whatsapp",) for _, _, c in _channels(_route(p, "P1")))
    assert not any(c == ("whatsapp",) for _, _, c in _channels(_route(p, "P2")))
    assert not any(c == ("bell",) for _, _, c in _channels(_route(p, "P2")))
    assert any(c == ("bell",) for _, _, c in _channels(_route(p, "P1")))


def test_with_nothing_configured_no_address_or_phone_is_invented_only_the_default_bell_roles_remain():
    p = asyncio.run(build_default_bank_policy(Cfg()))
    named = _channels(_route(p, "P0"))
    assert named and all(kind == "role" and c == ("bell",) for kind, _, c in named)          # the bell roles have always had defaults; nothing else
    assert sorted(ref for _, ref, _ in named) == ["bank_it_admin", "ops_manager"]


def test_the_calendar_comes_from_configuration():
    cal = asyncio.run(load_calendar(Cfg(**{"alerting.timezone": "Asia/Kolkata", "alerting.business_hours": '{"days": [0,1,2,3,4,5], "start": "10:00", "end": "17:00"}',
                                           "alerting.holidays": '["2026-11-19", "2026-12-25"]'})))
    assert cal.timezone == "Asia/Kolkata" and cal.business.days == [0, 1, 2, 3, 4, 5] and cal.business.start == "10:00" and cal.holidays == ["2026-11-19", "2026-12-25"]


def test_a_missing_or_malformed_calendar_falls_back_to_safe_defaults():
    cal = asyncio.run(load_calendar(Cfg(**{"alerting.business_hours": "{nope", "alerting.holidays": "not json"})))
    assert cal.business.days == [0, 1, 2, 3, 4] and cal.holidays == [] and cal.timezone
