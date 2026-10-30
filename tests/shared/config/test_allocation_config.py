"""Allocation settings must actually reach the code that reads them.

Found 2026-10-28: get_cts_config() returned only seven dotted 'cts.*' keys, so the queue router and the review
consumer, which read the bare key 'allocation_mode', always saw the SELF default. The AUTO and HYBRID modes could
never be switched on from configuration."""
import pytest

from shared.config.config_service import ConfigService, _LAYER3_DEFAULTS

ALLOCATION_KEYS = {
    "cts.allocation_mode": "SELF",
    "cts.allocation_lock_ttl_minutes": 10,
    "cts.hybrid_auto_assign_timeout_minutes": 5,
    "cts.allocation_strategy": "LEAST_LOADED",
    "cts.allocation_max_per_reviewer": 10,
    "cts.allocation_urgent_margin_minutes": 30,
    "cts.allocation_rebalance_enabled": True,
    "cts.allocation_rebalance_interval_seconds": 60,
    "cts.allocation_rebalance_max_moves": 20,
    "cts.allocation_retry_seconds": 60,
}


@pytest.mark.parametrize("key,default", ALLOCATION_KEYS.items())
def test_every_allocation_key_has_a_builtin_default(key, default):
    assert _LAYER3_DEFAULTS[key] == default


@pytest.mark.asyncio
async def test_get_cts_config_exposes_allocation_settings_under_their_bare_names():
    svc = ConfigService.__new__(ConfigService)
    svc._bank_id = "kbl"
    svc._ready = True
    svc._redis = None
    svc._db_pool = None
    cfg = await svc.get_cts_config("kbl")
    for key, default in ALLOCATION_KEYS.items():
        assert cfg[key.removeprefix("cts.")] == default
    assert cfg["cts.iet_minutes"] == 180          # the existing dotted keys are unchanged
