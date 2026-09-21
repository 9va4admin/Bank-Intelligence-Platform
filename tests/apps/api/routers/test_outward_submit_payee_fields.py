"""Teller-entered depositor details must be accepted by the scan-submit API and reach the workflow.
Gap found by the real API run: OutwardScanSubmitRequest had no payee fields, so via the API the payee
check could only rely on rear-image OCR (OutwardScanInput already supports the teller fields)."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from apps.api.routers.cts_outward_core import OutwardScanSubmitRequest, submit_outward_scan


def _body(**kw):
    base = dict(scan_id="s1", instrument_id="i1", bank_ifsc="KARB0000001", session_id="SES-1",
                image_front_url="s3://cts-images/kbl/outward/s1/front.tiff",
                image_rear_url="s3://cts-images/kbl/outward/s1/rear.tiff")
    base.update(kw)
    return OutwardScanSubmitRequest(**base)


def _request(temporal):
    req = MagicMock()
    req.app.state.temporal_client = temporal
    req.app.state.db_pool_cts = None
    return req


@pytest.mark.asyncio
async def test_teller_fields_reach_the_workflow_input():
    temporal = MagicMock(); temporal.start_workflow = AsyncMock()
    body = _body(payee_account_number="7001000024", payee_name_from_slip="JAGADISH V",
                 payee_mobile="9800000000", registered_drawee_ifsc="HDFC0000514",
                 registered_amount_str="1462500.00")
    await submit_outward_scan(body=body, request=_request(temporal), response=MagicMock(), bank_id="kbl")
    wf_input = temporal.start_workflow.await_args.args[1]
    assert wf_input.payee_account_number == "7001000024"
    assert wf_input.payee_name_from_slip == "JAGADISH V"
    assert wf_input.payee_mobile == "9800000000"
    assert wf_input.registered_drawee_ifsc == "HDFC0000514"
    assert wf_input.registered_amount_str == "1462500.00"


@pytest.mark.asyncio
async def test_fields_are_optional_so_existing_scanners_keep_working():
    temporal = MagicMock(); temporal.start_workflow = AsyncMock()
    await submit_outward_scan(body=_body(), request=_request(temporal), response=MagicMock(), bank_id="kbl")
    wf_input = temporal.start_workflow.await_args.args[1]
    assert wf_input.payee_account_number is None and wf_input.payee_name_from_slip is None
