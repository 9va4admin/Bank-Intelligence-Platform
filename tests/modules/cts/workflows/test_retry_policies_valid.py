"""Every module-level RetryPolicy in the CTS workflow modules must be valid for the Temporal SDK.
Found live: RetryPolicy(maximum_attempts=None) passes construction but raises TypeError when the workflow
schedules the activity, so the workflow task fails and retries forever (0 = unlimited in this SDK)."""
import importlib
import pkgutil

import pytest
from temporalio.api.common.v1 import RetryPolicy as ProtoRetryPolicy
from temporalio.common import RetryPolicy

import modules.cts.workflows as wf_pkg


def _all_policies():
    found = []
    mods = ["modules.cts.worker"] + [m.name for m in pkgutil.iter_modules(wf_pkg.__path__, wf_pkg.__name__ + ".")]
    for name in mods:
        try:
            mod = importlib.import_module(name)
        except Exception:
            continue
        for attr, val in vars(mod).items():
            if isinstance(val, RetryPolicy):
                found.append((f"{name}.{attr}", val))
    return found


def test_found_some_policies():
    assert len(_all_policies()) > 5


@pytest.mark.parametrize("name,policy", _all_policies(), ids=lambda v: v if isinstance(v, str) else "")
def test_policy_is_valid_for_the_sdk(name, policy):
    policy.apply_to_proto(ProtoRetryPolicy())      # raises TypeError/ValueError for invalid values
