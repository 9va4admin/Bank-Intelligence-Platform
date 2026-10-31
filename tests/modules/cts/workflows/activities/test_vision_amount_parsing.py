"""run_vision_presentment_check promises never to raise. A model that answers in the platform's own per-field format
({"value": ..., "confidence": ...} - the shape ai-inference.md mandates) used to put a dict where a string belongs and fail the
whole outward workflow with a ValidationError (found on the first live outward run, 2026-10-31)."""
import pytest

from modules.cts.workflows.activities.outward_scan_activities import _amount_from_vision_text


@pytest.mark.parametrize("reply,expected", [
    ('{"amount_figures": "95000"}', "95000"),
    ('{"amount_figures": 95000}', "95000"),
    ('{"amount_figures": 950.5}', "950.5"),
    ('{"amount_figures": {"value": "95000", "confidence": 0.96}}', "95000"),
    ('{"amount_figures": {"value": 95000, "altered": false, "confidence": 0.9}}', "95000"),
    ('```json\n{"amount_figures": {"value": "1,25,000", "confidence": 0.9}}\n```', "1,25,000"),
])
def test_amount_is_always_returned_as_a_string(reply, expected):
    assert _amount_from_vision_text(reply) == expected


@pytest.mark.parametrize("reply", [None, "", "no json here", '{"amount_figures": null}', '{"amount_figures": {"confidence": 0.9}}',
                                   '{"amount_figures": []}', '{"other": 1}', "{bad json}"])
def test_nothing_usable_is_none_not_an_exception(reply):
    assert _amount_from_vision_text(reply) is None
