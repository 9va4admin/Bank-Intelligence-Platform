"""The return-file (RRF) code table must be the real clearing-house code list.

Found 2026-10-14 when the primary documents (RBI/NPCI CTS Specifications for Continuous Clearing, Rev 3.0 (26 Mar 2025), Chennai CTS guidelines v2.1) were
finally read: RBIReturnCode had invented codes ('06' signature differs, '14' post-dated, '15' stale, '16' words and
figures, '20' image quality ...) and called them "the ONLY codes accepted by NGCH". A return filed with one of them
carries a wrong legal reason. Master data: docs/npci/return_reason_codes.json.
"""
import json
from pathlib import Path

import pytest

from modules.cts.rrf.models import RBIReturnCode, ReturnItem

ROOT = Path(__file__).resolve().parents[4]
MASTER = json.loads((ROOT / "docs/npci/return_reason_codes.json").read_text(encoding="utf-8"))["codes"]


def _desc(code):
    return (MASTER[code]["chi_spec_description"] or MASTER[code]["description"]).lower()


def test_every_code_the_return_file_can_carry_exists_in_the_current_specification():
    for rc in RBIReturnCode:
        assert rc.code in MASTER and MASTER[rc.code]["in_chi_spec"], (rc.name, rc.code)


@pytest.mark.parametrize("member,code,phrase", [
    ("FUNDS_INSUFFICIENT", "01", "funds insufficient"),
    ("SIGNATURE_DIFFERS", "12", "signature differs"),
    ("ALTERATION_REQUIRES_AUTH", "17", "alteration"),
    ("PAYMENT_STOPPED", "20", "stopped by drawer"),
    ("CHEQUE_POST_DATED", "30", "post dated"),
    ("CHEQUE_STALE", "31", "stale"),
    ("CHEQUE_UNDATED", "32", "undated"),
    ("WORDS_FIGURES_DIFFER", "34", "words and figures"),
    ("IMAGE_NOT_CLEAR", "39", "image not clear"),
    ("ITEM_LISTED_TWICE", "41", "listed twice"),
    ("ACCOUNT_CLOSED", "50", "account closed"),
    ("NO_SUCH_ACCOUNT", "52", "no such account"),
    ("FAKE_FORGED_STOLEN", "86", "forged"),
    ("OTHER_REASON", "88", "other reasons"),
])
def test_code_means_what_the_specification_says(member, code, phrase):
    rc = RBIReturnCode[member]
    assert rc.code == code
    assert phrase in _desc(code)


def test_description_on_the_enum_matches_the_specification_meaning():
    for rc in RBIReturnCode:
        first = _desc(rc.code).split()[0]
        assert first[:4] in rc.description.lower() or first[:4] in _desc(rc.code), (rc.name, rc.description, _desc(rc.code))


def test_deemed_accepted_99_is_never_sendable_by_a_drawee():
    assert "99" not in {rc.code for rc in RBIReturnCode}


def test_the_ui_reason_mapping_lands_on_real_codes():
    assert RBIReturnCode.from_ui_reason("signature mismatch").code == "12"
    assert RBIReturnCode.from_ui_reason("cheque is post-dated").code == "30"
    assert RBIReturnCode.from_ui_reason("stale cheque").code == "31"
    assert RBIReturnCode.from_ui_reason("poor image quality").code == "39"
    assert RBIReturnCode.from_ui_reason("words and figures differ").code == "34"


def _item(comment):
    from datetime import datetime
    return ReturnItem(instrument_id="I", micr_code="000052000", return_code=RBIReturnCode.OTHER_REASON, drawee_ifsc="KARB0000001",
                      presenting_ifsc="SRCB0000001", iet_deadline=datetime(2026, 1, 1), returned_at=datetime(2026, 1, 1),
                      decided_by="u", amount_range="x", bank_id="kbl", return_reason_comment=comment)


@pytest.mark.parametrize("bad", [None, "", "   ", " leading space", "123 starts with a number", "9"])
def test_code_88_comment_rules_from_the_specification(bad):
    with pytest.raises(ValueError):
        _item(bad)


def test_code_88_with_a_valid_comment_is_accepted():
    assert _item("Instrument shows a foreign-currency amount").return_reason_comment
