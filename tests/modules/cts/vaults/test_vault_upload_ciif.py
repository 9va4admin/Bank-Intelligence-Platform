"""CIIF (NPCI PPS interface file) -> PPS vault upload.

The spec does not say whether Amount is rupees or paise, so the unit is an explicit deployment setting with no
default: an upload with no unit is refused rather than guessed (a wrong guess is a 100x error on a positive-pay amount).
"""
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

HEADER = ("PayeeAccountNumber,SerialNumber,IssueDate,Amount,Transactioncode,DraweeBankName,"
          "DraweeBranchRoutingNumber,PayeeName,San,Optional1,Optional2,Optional3")
GOOD = "50011,011231,14042016,390587,10,HDFC Bank,110240001,Xyz abc,123456,,,"
TODAY = date(2016, 4, 20)


def _proc():
    from modules.cts.vaults.vault_upload_processor import VaultUploadProcessor
    pps = MagicMock()
    pps.store_pps = AsyncMock(return_value=None)
    return VaultUploadProcessor(bank_id="kbl", db_pool=None, pps_vault=pps), pps


def _csv(*rows):
    return "\n".join([HEADER, *rows]).encode()


@pytest.mark.asyncio
async def test_valid_record_is_stored_in_rupees_when_unit_is_rupees():
    proc, pps = _proc()
    res = await proc.process_ciif(_csv(GOOD), "user:a", amount_unit="RUPEES", today=TODAY)
    assert res.rows_processed == 1 and res.rows_failed == 0
    kw = pps.store_pps.call_args.kwargs
    assert kw["amount_paise"] == 390587 * 100 and kw["cheque_number"] == "011231"


@pytest.mark.asyncio
async def test_amount_is_taken_as_paise_when_unit_is_paise():
    proc, pps = _proc()
    await proc.process_ciif(_csv(GOOD), "user:a", amount_unit="PAISE", today=TODAY)
    assert pps.store_pps.call_args.kwargs["amount_paise"] == 390587


@pytest.mark.asyncio
@pytest.mark.parametrize("unit", [None, "", "rupee", "GUESS"])
async def test_missing_or_unknown_amount_unit_is_refused(unit):
    proc, pps = _proc()
    with pytest.raises(ValueError, match="amount unit"):
        await proc.process_ciif(_csv(GOOD), "user:a", amount_unit=unit, today=TODAY)
    pps.store_pps.assert_not_called()


@pytest.mark.asyncio
async def test_spec_rejects_are_counted_and_do_not_block_good_rows_or_leak_values():
    proc, pps = _proc()
    bad = "50211,011232,31022016,150000,10,HDFC Bank,110240002,Xyz abc,123456,,,"
    res = await proc.process_ciif(_csv(GOOD, bad), "user:a", amount_unit="RUPEES", today=TODAY)
    assert (res.rows_total, res.rows_processed, res.rows_failed) == (2, 1, 1)
    assert res.errors[0]["row"] == 3 and "50211" not in str(res.errors)


@pytest.mark.asyncio
async def test_record_without_serial_number_is_rejected_because_pps_is_keyed_by_cheque_number():
    proc, pps = _proc()
    res = await proc.process_ciif(_csv("50011,,14042016,390587,10,HDFC Bank,110240001,Xyz abc,123456,,,"),
                                  "user:a", amount_unit="RUPEES", today=TODAY)
    assert res.rows_failed == 1 and res.rows_processed == 0 and "serial" in res.errors[0]["error"].lower()
    pps.store_pps.assert_not_called()


@pytest.mark.asyncio
async def test_xml_file_is_detected_and_loaded():
    proc, pps = _proc()
    xml = ('<ciif-root Version="1.0" Fileid="1" Testfileindicator="P" draweebranchroutingno="110011111"><records>'
           '<item payeeaccno="123456789" serialno="000001" issue-date="15042016" amount="1500" transcode="123" '
           'draweebranchroutingno="110101111" payeename="Mr. Adesh Shah" san="1235437"/></records></ciif-root>')
    res = await proc.process_ciif(xml.encode(), "user:a", amount_unit="RUPEES", today=TODAY)
    assert res.rows_processed == 1 and pps.store_pps.call_args.kwargs["amount_paise"] == 150000


@pytest.mark.asyncio
async def test_test_file_indicator_loads_nothing():
    proc, pps = _proc()
    xml = ('<ciif-root Version="1.0" Fileid="1" Testfileindicator="T" draweebranchroutingno="110011111"><records>'
           '<item payeeaccno="123456789" serialno="000001" issue-date="15042016" amount="1500" transcode="123" '
           'draweebranchroutingno="110101111" payeename="Mr. Adesh Shah" san="1235437"/></records></ciif-root>')
    with pytest.raises(ValueError, match="test file"):
        await proc.process_ciif(xml.encode(), "user:a", amount_unit="RUPEES", today=TODAY)
    pps.store_pps.assert_not_called()


@pytest.mark.asyncio
async def test_file_level_failure_is_a_value_error():
    proc, _ = _proc()
    with pytest.raises(ValueError):
        await proc.process_ciif(b"a,b,c\n1,2,3", "user:a", amount_unit="RUPEES", today=TODAY)


@pytest.mark.asyncio
async def test_paise_are_converted_exactly_no_float_rounding_loss():
    """int(float('0.29') * 100) == 28; the amount must survive as 29 paise."""
    proc, pps = _proc()
    await proc.process_ciif(_csv("50011,011231,14042016,29,10,HDFC Bank,110240001,Xyz abc,123456,,,"),
                            "user:a", amount_unit="PAISE", today=TODAY)
    assert pps.store_pps.call_args.kwargs["amount_paise"] == 29
