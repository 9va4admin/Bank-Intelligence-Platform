"""Generic DI binder. Temporal drops parameter type hints when an activity has more
parameters than payloads, so any bare activity with extra DI params (db_pool,
lot_store, event_producer ...) received a dict and no dependencies. bind_di_activity
turns such a function into a single-`inp` activity with dependencies injected."""
import inspect
from typing import Optional

import pytest
from pydantic import BaseModel
from temporalio import activity
from unittest.mock import MagicMock


class _Inp(BaseModel):
    x: int


@activity.defn
async def _needs_deps(inp: _Inp, db_pool=None, event_producer=None) -> dict:
    return {"x": inp.x, "pool": db_pool, "prod": event_producer}


@activity.defn
async def _no_deps(inp: _Inp) -> int:
    return inp.x


def _deps(**kw):
    return kw


def test_wrapper_keeps_name_and_single_param_with_model_hint():
    from modules.cts.worker_activities import bind_di_activity
    w = bind_di_activity(_needs_deps, _deps(db_pool=object(), event_producer=object()))
    assert w.__name__ == "_needs_deps"
    assert list(inspect.signature(w).parameters) == ["inp"]
    from typing import get_type_hints
    assert get_type_hints(w)["inp"] is _Inp


@pytest.mark.asyncio
async def test_dependencies_are_injected_and_dict_input_is_coerced():
    from modules.cts.worker_activities import bind_di_activity
    pool, prod = object(), object()
    w = bind_di_activity(_needs_deps, _deps(db_pool=pool, event_producer=prod))
    out = await w({"x": 7})
    assert out == {"x": 7, "pool": pool, "prod": prod}


@pytest.mark.asyncio
async def test_missing_dependency_is_passed_as_none():
    from modules.cts.worker_activities import bind_di_activity
    out = await bind_di_activity(_needs_deps, _deps(db_pool=None))(_Inp(x=1))
    assert out["pool"] is None and out["prod"] is None


def test_single_param_activity_is_left_alone():
    from modules.cts.worker_activities import split_di_activities
    bound, plain = split_di_activities([_needs_deps, _no_deps], _deps())
    assert [b.__name__ for b in bound] == ["_needs_deps"]
    assert plain == [_no_deps]


def test_every_registered_activity_takes_only_inp():
    """Guard: after binding, NO registered CTS activity may keep extra parameters."""
    from modules.cts.worker import NO_DI_ACTIVITIES
    from modules.cts.worker_activities import BoundCTSActivities, split_di_activities
    b = BoundCTSActivities(bank_id="kbl")
    wrapped, plain = split_di_activities(list(NO_DI_ACTIVITIES), b.di_dependencies())
    for fn in wrapped + plain:
        params = list(inspect.signature(fn).parameters)
        assert len(params) <= 1, f"{fn.__name__} still has extra params: {params}"
