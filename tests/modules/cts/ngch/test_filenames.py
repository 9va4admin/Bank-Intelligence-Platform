"""
Tests for CTS NGCH filename generation — CHI Spec Rev 3.00 Appendix 4.1.1 (CXF)
and Appendix 4.2.1 (CIBF).

CXF filename format (Appx 4.1.1):
    CXF_{RoutingNo}_{DDMMYYYY}_{HHMMSS}_{ClearingType}_{FileID}.XML
    e.g. CXF_000550050_08072026_103000_14_0001.XML

CIBF filename format (Appx 4.2.1):
    CIBF_{RoutingNo}_{DDMMYYYY}_{HHMMSS}_{ClearingType}_{FileID}_{nn}.img
    e.g. CIBF_000550050_08072026_103000_14_0001_01.img

Rules from spec:
  - FileType prefix comes FIRST (CXF_ or CIBF_)
  - Extension: .XML (uppercase) for CXF, .img (lowercase) for CIBF
  - RoutingNo: 9-digit NPCI routing number, zero-padded
  - DDMMYYYY: date, always 8 digits
  - HHMMSS: time, always 6 digits
  - ClearingType: 2 chars ("14" or "99")
  - FileID: 1–10 alphanumeric (unique per bank per day)
  - _nn: CIBF modifier, 2-digit counter "01", "02", etc.

RED phase: all tests must fail before filenames.py is created.
"""
import pytest


class TestCXFFilename:
    """CXF filename must follow spec format exactly."""

    def test_cxf_filename_starts_with_cxf_prefix(self):
        from modules.cts.ngch.filenames import make_cxf_filename

        name = make_cxf_filename(
            routing_no="000550050",
            date_ddmmyyyy="08072026",
            time_hhmmss="103000",
            clearing_type="14",
            file_id="0001",
        )
        assert name.startswith("CXF_")

    def test_cxf_filename_ends_with_xml_uppercase(self):
        from modules.cts.ngch.filenames import make_cxf_filename

        name = make_cxf_filename(
            routing_no="000550050",
            date_ddmmyyyy="08072026",
            time_hhmmss="103000",
            clearing_type="14",
            file_id="0001",
        )
        assert name.endswith(".XML")

    def test_cxf_filename_exact_format(self):
        """Full filename must match spec format exactly."""
        from modules.cts.ngch.filenames import make_cxf_filename

        name = make_cxf_filename(
            routing_no="000550050",
            date_ddmmyyyy="08072026",
            time_hhmmss="103000",
            clearing_type="14",
            file_id="0001",
        )
        assert name == "CXF_000550050_08072026_103000_14_0001.XML"

    def test_cxf_filename_clearing_type_99(self):
        from modules.cts.ngch.filenames import make_cxf_filename

        name = make_cxf_filename(
            routing_no="110002000",
            date_ddmmyyyy="01042026",
            time_hhmmss="160000",
            clearing_type="99",
            file_id="5",
        )
        assert name == "CXF_110002000_01042026_160000_99_5.XML"

    def test_cxf_filename_routing_no_embedded(self):
        from modules.cts.ngch.filenames import make_cxf_filename

        name = make_cxf_filename(
            routing_no="110229001",
            date_ddmmyyyy="08072026",
            time_hhmmss="090000",
            clearing_type="14",
            file_id="A1B2",
        )
        assert "110229001" in name

    def test_cxf_filename_date_embedded(self):
        from modules.cts.ngch.filenames import make_cxf_filename

        name = make_cxf_filename(
            routing_no="000550050",
            date_ddmmyyyy="31122026",
            time_hhmmss="235959",
            clearing_type="14",
            file_id="001",
        )
        assert "31122026" in name
        assert "235959" in name

    def test_cxf_filename_rejects_invalid_clearing_type(self):
        """Only clearing types 14 and 99 are valid (types 01/02/03/11 removed Sep 2024)."""
        from modules.cts.ngch.filenames import make_cxf_filename

        with pytest.raises(ValueError, match="clearing_type"):
            make_cxf_filename(
                routing_no="000550050",
                date_ddmmyyyy="08072026",
                time_hhmmss="103000",
                clearing_type="01",  # removed from spec
                file_id="0001",
            )

    def test_cxf_filename_rejects_clearing_type_02(self):
        from modules.cts.ngch.filenames import make_cxf_filename

        with pytest.raises(ValueError, match="clearing_type"):
            make_cxf_filename(
                routing_no="000550050",
                date_ddmmyyyy="08072026",
                time_hhmmss="103000",
                clearing_type="02",
                file_id="0001",
            )

    def test_cxf_filename_returns_string(self):
        from modules.cts.ngch.filenames import make_cxf_filename

        name = make_cxf_filename(
            routing_no="000550050",
            date_ddmmyyyy="08072026",
            time_hhmmss="103000",
            clearing_type="14",
            file_id="0001",
        )
        assert isinstance(name, str)


class TestCIBFFilename:
    """CIBF filename derives from CXF name — same tokens + _nn suffix + .img."""

    def test_cibf_filename_starts_with_cibf_prefix(self):
        from modules.cts.ngch.filenames import make_cibf_filename

        name = make_cibf_filename(
            routing_no="000550050",
            date_ddmmyyyy="08072026",
            time_hhmmss="103000",
            clearing_type="14",
            file_id="0001",
            modifier="01",
        )
        assert name.startswith("CIBF_")

    def test_cibf_filename_ends_with_img_lowercase(self):
        from modules.cts.ngch.filenames import make_cibf_filename

        name = make_cibf_filename(
            routing_no="000550050",
            date_ddmmyyyy="08072026",
            time_hhmmss="103000",
            clearing_type="14",
            file_id="0001",
            modifier="01",
        )
        assert name.endswith(".img")

    def test_cibf_filename_exact_format(self):
        from modules.cts.ngch.filenames import make_cibf_filename

        name = make_cibf_filename(
            routing_no="000550050",
            date_ddmmyyyy="08072026",
            time_hhmmss="103000",
            clearing_type="14",
            file_id="0001",
            modifier="01",
        )
        assert name == "CIBF_000550050_08072026_103000_14_0001_01.img"

    def test_cibf_filename_modifier_02(self):
        from modules.cts.ngch.filenames import make_cibf_filename

        name = make_cibf_filename(
            routing_no="110002000",
            date_ddmmyyyy="01042026",
            time_hhmmss="160000",
            clearing_type="99",
            file_id="5",
            modifier="02",
        )
        assert name == "CIBF_110002000_01042026_160000_99_5_02.img"

    def test_cibf_cxf_share_same_core_tokens(self):
        """CXF and CIBF tokens match — only prefix and extension differ."""
        from modules.cts.ngch.filenames import make_cxf_filename, make_cibf_filename

        cxf = make_cxf_filename("000550050", "08072026", "103000", "14", "0001")
        cibf = make_cibf_filename("000550050", "08072026", "103000", "14", "0001", "01")

        # Core tokens between prefix and extension must match
        cxf_core = cxf[len("CXF_"):].replace(".XML", "")
        cibf_core = cibf[len("CIBF_"):].replace(".img", "")
        # cibf_core ends with _01 (modifier), trim it
        cibf_core_no_mod = cibf_core.rsplit("_", 1)[0]
        assert cxf_core == cibf_core_no_mod

    def test_cibf_filename_rejects_invalid_clearing_type(self):
        from modules.cts.ngch.filenames import make_cibf_filename

        with pytest.raises(ValueError, match="clearing_type"):
            make_cibf_filename(
                routing_no="000550050",
                date_ddmmyyyy="08072026",
                time_hhmmss="103000",
                clearing_type="03",
                file_id="0001",
                modifier="01",
            )
