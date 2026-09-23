"""notify_representation_pending / re_submit_to_ngch_for_representation are hand-written
bound-method activities (BoundCTSActivities), bypassing the generic bind_di_activity
dict->model wrapper -- confirmed live 2026-09-23 that Temporal can deliver `inp` as a
plain dict here, and the pre-fix code crashed on inp.bank_id with AttributeError."""
import pytest

from modules.cts.workflows.activities.representation_activities import (
    notify_representation_pending, re_submit_to_ngch_for_representation,
)


@pytest.mark.asyncio
async def test_notify_representation_pending_accepts_dict_input():
    class _FakeDispatcher:
        def __init__(self):
            self.sent = []

        async def send(self, **kwargs):
            self.sent.append(kwargs)

    inp_dict = {
        "instrument_id": "IW-1", "bank_id": "kbl", "return_reason_code": "RETURN_INSUFFICIENT_FUNDS",
        "original_session_id": "sess-1", "clearing_date": "2026-09-22",
        "representation_window_hours": 24,
    }
    dispatcher = _FakeDispatcher()
    result = await notify_representation_pending(inp_dict, dispatcher=dispatcher)
    assert result.notified is True
    assert len(dispatcher.sent) == 1


@pytest.mark.asyncio
async def test_notify_representation_pending_degrades_without_dispatcher_dict_input():
    inp_dict = {
        "instrument_id": "IW-1", "bank_id": "kbl", "return_reason_code": "RETURN_INSUFFICIENT_FUNDS",
        "original_session_id": "sess-1", "clearing_date": "2026-09-22",
        "representation_window_hours": 24,
    }
    result = await notify_representation_pending(inp_dict, dispatcher=None)
    assert result.notified is False and result.degraded is True


@pytest.mark.asyncio
async def test_re_submit_to_ngch_for_representation_accepts_dict_input():
    class _FakeNgchClient:
        async def submit_representation(self, **kwargs):
            return "NGCH-DEV-REP-ABC123"

    inp_dict = {
        "instrument_id": "IW-1", "bank_id": "kbl", "bank_ifsc": "KARB0000001",
        "return_reason_code": "RETURN_INSUFFICIENT_FUNDS", "original_session_id": "sess-1",
        "clearing_date": "2026-09-22",
    }
    result = await re_submit_to_ngch_for_representation(inp_dict, ngch_client=_FakeNgchClient())
    assert result.submitted is True
    assert result.ngch_reference == "NGCH-DEV-REP-ABC123"
