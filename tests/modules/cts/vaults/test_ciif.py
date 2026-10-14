"""NPCI PPS Interface File Specification v1.19 (Nov 2023): the CIIF (cheque issue information) file, CSV and XML.

Field rules are taken from the specification's attribute table (Appx 1.1.3.3 / 1.1.4); sample rows are the
specification's own samples.
"""
from datetime import date

import pytest

from modules.cts.vaults.ciif import parse_ciif_csv, parse_ciif_xml

TODAY = date(2015, 2, 10)      # the spec's XML sample is dated 15 Jan 2015
CSV_HEADER = ("PayeeAccountNumber,SerialNumber,IssueDate,Amount,Transactioncode,DraweeBankName,"
              "DraweeBranchRoutingNumber,PayeeName,San,Optional1,Optional2,Optional3")


def _csv(*rows):
    return "\n".join([CSV_HEADER, *rows])


GOOD = "50011,011231,14042016,390587,10,HDFC Bank,110240001,Xyz abc,123456,,,"


class TestCsv:
    def test_specification_sample_row_parses(self):
        recs, errs = parse_ciif_csv(_csv(GOOD), today=date(2016, 4, 20))
        assert not errs and len(recs) == 1
        r = recs[0]
        assert (r.drawer_account, r.serial_no, r.amount, r.transaction_code) == ("50011", "011231", 390587, "10")
        assert r.issue_date == date(2016, 4, 14) and r.drawee_routing_no == "110240001" and r.san == "123456"
        assert r.payee_name == "Xyz abc" and r.drawee_bank_name == "HDFC Bank"

    def test_a_bad_row_is_reported_with_its_line_and_does_not_hide_the_good_ones(self):
        recs, errs = parse_ciif_csv(_csv(GOOD, "50211,011232,31022016,150000,10,HDFC Bank,110240002,Xyz abc,123456,,,"), today=date(2016, 4, 20))
        assert len(recs) == 1 and len(errs) == 1
        assert errs[0].line == 3 and errs[0].field == "IssueDate"

    @pytest.mark.parametrize("row,field", [
        ("50011,011231,14042016,390587,10,HDFC Bank,11024000,Xyz abc,123456,,,", "DraweeBranchRoutingNumber"),   # 8 digits
        ("50011,011231,14042016,390587,10,HDFC Bank,000000000,Xyz abc,123456,,,", "DraweeBranchRoutingNumber"),   # must be > 0
        (",011231,14042016,390587,10,HDFC Bank,110240001,Xyz abc,123456,,,", "PayeeAccountNumber"),               # mandatory
        (" 50011,011231,14042016,390587,10,HDFC Bank,110240001,Xyz abc,123456,,,", "PayeeAccountNumber"),        # leading space
        ("50011,011231,14042016,,10,HDFC Bank,110240001,Xyz abc,123456,,,", "Amount"),
        ("50011,011231,14042016,12.50,10,HDFC Bank,110240001,Xyz abc,123456,,,", "Amount"),                       # N: digits only
        ("50011,011231,14042016,390587,1,HDFC Bank,110240001,Xyz abc,123456,,,", "Transactioncode"),              # 2-3 digits
        ("50011,011231,14042016,390587,10,HDFC Bank,110240001,,123456,,,", "PayeeName"),                          # mandatory
        ("50011,011231,14042016,390587,10,HDFC Bank,110240001,Xyz@abc,123456,,,", "PayeeName"),                   # '@' not allowed
        ("50011,011231,14042016,390587,10,HDFC Bank,110240001,Xyz abc,,,,", "San"),                                # mandatory
        ("50011,011231,14042016,390587,10,HDFC Bank,110240001,Xyz abc,12,,,", "San"),                              # 6-7 digits
        ("50011,000000,14042016,390587,10,HDFC Bank,110240001,Xyz abc,123456,,,", "SerialNumber"),                # must be > 0
        ("50011,1234,14042016,390587,10,HDFC Bank,110240001,Xyz abc,123456,,,", "SerialNumber"),                  # must be 6 digits
    ])
    def test_each_specification_rule_is_enforced(self, row, field):
        recs, errs = parse_ciif_csv(_csv(row), today=date(2016, 4, 20))
        assert not recs and errs and errs[0].field == field

    def test_issue_date_older_than_90_days_is_rejected(self):
        recs, errs = parse_ciif_csv(_csv(GOOD), today=date(2016, 9, 1))
        assert not recs and errs[0].field == "IssueDate" and "90" in errs[0].message

    def test_serial_number_is_optional(self):
        recs, errs = parse_ciif_csv(_csv("50011,,14042016,390587,10,HDFC Bank,110240001,Xyz abc,123456,,,"), today=date(2016, 4, 20))
        assert recs and not errs and recs[0].serial_no is None

    def test_san_default_000000_is_allowed_when_the_customer_has_none(self):
        recs, errs = parse_ciif_csv(_csv("50011,011231,14042016,390587,10,HDFC Bank,110240001,Xyz abc,000000,,,"), today=date(2016, 4, 20))
        assert recs and not errs

    def test_wrong_header_is_a_file_level_error(self):
        recs, errs = parse_ciif_csv("a,b,c\n1,2,3", today=TODAY)
        assert not recs and errs and errs[0].line == 1 and errs[0].field == "header"

    def test_error_messages_never_echo_the_account_number_or_name(self):
        _, errs = parse_ciif_csv(_csv("50011,011231,14042016,390587,1,HDFC Bank,110240001,Xyz abc,123456,,,"), today=date(2016, 4, 20))
        text = " ".join(e.message for e in errs)
        assert "50011" not in text and "Xyz" not in text


XML = """<?xml version="1.0" encoding="utf-8"?>
<ciif-root Version="1.0" Fileid="1" Testfileindicator="P" draweebranchroutingno="110011111">
 <records>
  <item payeeaccno="123456789" serialno="000001" issue-date="15012015" amount="1500" transcode="123" draweebankname="State Bank of India" draweebranchroutingno="110101111" payeename="Mr. Adesh Shah" san="1235437" />
  <item payeeaccno="123456789" serialno="324548" issue-date="26022016" amount="1200" draweebankname="State Bank of India" draweebranchroutingno="110011111" san="123453" />
 </records>
</ciif-root>"""


class TestXml:
    def test_specification_sample_first_item_parses_with_its_file_metadata(self):
        recs, errs, meta = parse_ciif_xml(XML, today=TODAY)
        assert len(recs) == 1
        assert meta == {"version": "1.0", "file_id": "1", "test_file": False, "drawee_routing_no": "110011111"}
        assert recs[0].payee_name == "Mr. Adesh Shah" and recs[0].issue_date == date(2015, 1, 15) and recs[0].san == "1235437"

    def test_specification_sample_second_item_is_rejected_for_the_missing_mandatory_payee_name(self):
        _, errs, _ = parse_ciif_xml(XML, today=date(2016, 3, 1))
        assert any(e.field == "payeename" for e in errs)

    def test_test_file_indicator_t_is_recognised(self):
        _, _, meta = parse_ciif_xml(XML.replace('Testfileindicator="P"', 'Testfileindicator="T"'), today=TODAY)
        assert meta["test_file"] is True

    def test_malformed_xml_is_a_file_level_error_not_a_crash(self):
        recs, errs, _ = parse_ciif_xml("<ciif-root><records>", today=TODAY)
        assert not recs and errs and errs[0].field == "file"

    def test_xml_with_an_external_entity_is_refused(self):
        evil = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><ciif-root><records><item payeeaccno="&e;"/></records></ciif-root>'
        recs, errs, _ = parse_ciif_xml(evil, today=TODAY)
        assert not recs and errs
