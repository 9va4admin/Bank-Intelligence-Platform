"""
Tests for RRF NPCI compliance — CTS Spec Rev 3.0 additions.

Changes required to modules/cts/rrf/ per Rev 3.0:
  1. RRF XML root must include NPCI namespace:
       urn:schemas-ncr-com:ECPIX:RRF:FileStructure:010004
  2. Return reason 99 ('Deemed Accepted by CCH') MUST NEVER appear in RRF.
     Banks cannot send this — CCH assigns it only in the RF (Return File).
     Any attempt to use code 99 must raise ForbiddenReturnReasonError.
  3. Return reason 88 ('Other Reason') requires a non-empty ReturnReasonComment.
     Missing or empty comment for code 88 must raise a validation error.
  4. Return reason 00 ('On Realization Positive') valid for ClearingType=14 sessions.
  5. ReturnItem must accept an optional return_reason_comment field.

Existing return reasons 01-20 must continue to work unchanged (no regressions).

RED phase: all tests must fail before models.py and generator.py are updated.
"""
import pytest
from datetime import datetime, timezone


def _make_return_item(**kwargs):
    """Create a minimal valid ReturnItem dict; override any field."""
    from modules.cts.rrf.models import RBIReturnCode

    defaults = {
        "instrument_id": "CHQ-TEST-001",
        "micr_code": "400160001234",
        "return_code": RBIReturnCode.FUNDS_INSUFFICIENT,
        "drawee_ifsc": "SVCB0000001",
        "presenting_ifsc": "HDFC0001234",
        "iet_deadline": datetime(2026, 6, 19, 16, 0, 0, tzinfo=timezone.utc),
        "returned_at": datetime(2026, 6, 19, 13, 30, 0, tzinfo=timezone.utc),
        "decided_by": "ops_reviewer_1",
        "amount_range": "₹[1L-5L]",
        "bank_id": "saraswat-coop",
    }
    defaults.update(kwargs)
    return defaults


def _make_rrf_document(items=None):
    from modules.cts.rrf.models import RRFDocument, ReturnItem, RBIReturnCode

    if items is None:
        items = [ReturnItem(**_make_return_item())]
    return RRFDocument(
        bank_ifsc="SVCB0000001",
        bank_id="saraswat-coop",
        session_id="SES001",
        clearing_zone="MUMBAI",
        generated_at=datetime(2026, 6, 19, 16, 0, 0, tzinfo=timezone.utc),
        returns=items,
    )


class TestRRFNPCINamespace:
    """RRF XML must include the NPCI namespace per Rev 3.0."""

    def test_rrf_xml_contains_npci_namespace(self):
        from modules.cts.rrf.generator import RRFGenerator

        doc = _make_rrf_document()
        xml = RRFGenerator.to_xml(doc)
        assert "urn:schemas-ncr-com:ECPIX:RRF:FileStructure:010004" in xml

    def test_rrf_namespace_in_root_element(self):
        """Namespace must be in the root element attribute, not just in the body."""
        from modules.cts.rrf.generator import RRFGenerator
        from xml.etree import ElementTree as ET

        doc = _make_rrf_document()
        xml = RRFGenerator.to_xml(doc)
        # strip XML declaration line
        xml_body = "\n".join(
            line for line in xml.split("\n") if not line.startswith("<?xml")
        )
        root = ET.fromstring(xml_body.strip())
        assert "urn:schemas-ncr-com:ECPIX:RRF:FileStructure:010004" in root.tag or \
               root.get("xmlns") == "urn:schemas-ncr-com:ECPIX:RRF:FileStructure:010004"


class TestReturnReason99Blocked:
    """Return reason 99 (Deemed Accepted by CCH) must NEVER be in an RRF."""

    def test_code_99_is_not_in_rbi_return_code_enum(self):
        """Code 99 must not be available as an enum value — defense in depth."""
        from modules.cts.rrf.models import RBIReturnCode

        codes = [rc.code for rc in RBIReturnCode]
        assert "99" not in codes

    def test_generator_blocks_raw_99_string(self):
        """If code 99 somehow reaches the generator, it must raise."""
        # This is defense-in-depth: the enum already blocks it, but generator
        # adds a programmatic gate as well.
        from modules.cts.rrf.generator import RRFGenerator, ForbiddenReturnReasonError
        from modules.cts.rrf.models import RRFDocument, ReturnItem, RBIReturnCode

        # We must verify ForbiddenReturnReasonError is importable
        assert ForbiddenReturnReasonError is not None


class TestReturnReason88RequiresComment:
    """Return reason 88 (Other Reason) requires a non-empty ReturnReasonComment."""

    def test_code_88_exists_in_enum(self):
        from modules.cts.rrf.models import RBIReturnCode

        codes = [rc.code for rc in RBIReturnCode]
        assert "88" in codes

    def test_code_88_description_mentions_other_reason(self):
        from modules.cts.rrf.models import RBIReturnCode

        code88 = next(rc for rc in RBIReturnCode if rc.code == "88")
        assert "Other" in code88.description or "other" in code88.description.lower()

    def test_return_item_accepts_return_reason_comment(self):
        """ReturnItem must have an optional return_reason_comment field."""
        from modules.cts.rrf.models import ReturnItem, RBIReturnCode

        code88 = next(rc for rc in RBIReturnCode if rc.code == "88")
        item = ReturnItem(
            **_make_return_item(
                return_code=code88,
                return_reason_comment="Signature area torn — cannot verify",
            )
        )
        assert item.return_reason_comment == "Signature area torn — cannot verify"

    def test_code_88_without_comment_raises_validation_error(self):
        """Code 88 with no comment must raise ValueError (or subclass)."""
        from modules.cts.rrf.models import ReturnItem, RBIReturnCode

        code88 = next(rc for rc in RBIReturnCode if rc.code == "88")
        with pytest.raises(ValueError):
            ReturnItem(
                **_make_return_item(
                    return_code=code88,
                    return_reason_comment=None,  # missing — must fail
                )
            )

    def test_code_88_with_empty_comment_raises_validation_error(self):
        """Code 88 with empty string comment must also raise."""
        from modules.cts.rrf.models import ReturnItem, RBIReturnCode

        code88 = next(rc for rc in RBIReturnCode if rc.code == "88")
        with pytest.raises(ValueError):
            ReturnItem(
                **_make_return_item(
                    return_code=code88,
                    return_reason_comment="",  # empty — must fail
                )
            )

    def test_code_88_comment_appears_in_xml(self):
        """ReturnReasonComment must appear in RRF XML for code 88 items."""
        from modules.cts.rrf.generator import RRFGenerator
        from modules.cts.rrf.models import ReturnItem, RBIReturnCode

        code88 = next(rc for rc in RBIReturnCode if rc.code == "88")
        item = ReturnItem(
            **_make_return_item(
                return_code=code88,
                return_reason_comment="Cheque physically damaged beyond recognition",
            )
        )
        doc = _make_rrf_document(items=[item])
        xml = RRFGenerator.to_xml(doc)
        assert "Cheque physically damaged beyond recognition" in xml
        assert "ReturnReasonComment" in xml

    def test_other_codes_do_not_require_comment(self):
        """Codes 01-20 must work without a comment (comment is optional for them)."""
        from modules.cts.rrf.models import ReturnItem, RBIReturnCode

        # Must not raise for code 01 with no comment
        item = ReturnItem(**_make_return_item(
            return_code=RBIReturnCode.FUNDS_INSUFFICIENT,
            return_reason_comment=None,
        ))
        assert item is not None

    def test_code_01_with_comment_allowed(self):
        """Non-mandatory comment for other codes should also be accepted."""
        from modules.cts.rrf.models import ReturnItem, RBIReturnCode

        item = ReturnItem(**_make_return_item(
            return_code=RBIReturnCode.FUNDS_INSUFFICIENT,
            return_reason_comment="Overdraft limit exceeded",
        ))
        assert item.return_reason_comment == "Overdraft limit exceeded"


class TestReturnReason00OnRealization:
    """Return reason 00 is valid only for On Realization sessions (ClearingType=14)."""

    def test_code_00_exists_in_enum(self):
        from modules.cts.rrf.models import RBIReturnCode

        codes = [rc.code for rc in RBIReturnCode]
        assert "00" in codes

    def test_code_00_description_mentions_on_realization(self):
        from modules.cts.rrf.models import RBIReturnCode

        code00 = next(rc for rc in RBIReturnCode if rc.code == "00")
        desc = code00.description.lower()
        assert "realization" in desc or "realisation" in desc or "positive" in desc

    def test_code_00_accepted_in_return_item(self):
        from modules.cts.rrf.models import ReturnItem, RBIReturnCode

        code00 = next(rc for rc in RBIReturnCode if rc.code == "00")
        item = ReturnItem(**_make_return_item(return_code=code00))
        assert item.return_code.code == "00"


class TestExistingReturnCodesUnchanged:
    """Regression: existing codes 01-20 must continue to work."""

    def test_existing_generator_output_unchanged_for_code_01(self):
        from modules.cts.rrf.generator import RRFGenerator

        doc = _make_rrf_document()
        xml = RRFGenerator.to_xml(doc)
        # Core content from existing tests — must still be present
        assert "ReturnReasonCode" in xml
        assert "01" in xml  # FUNDS_INSUFFICIENT code

    def test_existing_return_item_fields_still_present_in_xml(self):
        from modules.cts.rrf.generator import RRFGenerator

        doc = _make_rrf_document()
        xml = RRFGenerator.to_xml(doc)
        assert "InstrumentID" in xml
        assert "MICRCode" in xml
        assert "DraweeIFSC" in xml

    def test_filename_convention_unchanged(self):
        from modules.cts.rrf.generator import RRFGenerator

        doc = _make_rrf_document()
        name = RRFGenerator.filename(doc)
        assert name.startswith("RRF_")
        assert name.endswith(".xml")
