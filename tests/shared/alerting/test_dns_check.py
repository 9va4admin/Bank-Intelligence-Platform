"""Mail-domain DNS check: SPF, DMARC and DKIM records for the sending domain (the DNS lookup is injected so the rules are tested without the network)."""
import asyncio

from shared.alerting.dns_check import check_mail_domain, domain_of, txt_lookup


def fake(records, fail=()):
    async def lookup(name):
        if name in fail:
            raise TimeoutError("dns timeout")
        return records.get(name, [])
    return lookup


def check(records, selectors=(), **kw):
    return asyncio.run(check_mail_domain("bank.example", list(selectors), fake(records, **kw)))


GOOD = {"bank.example": ["google-site-verification=x", "v=spf1 include:_spf.google.com ~all"], "_dmarc.bank.example": ["v=DMARC1; p=quarantine; rua=mailto:d@bank.example"],
        "google._domainkey.bank.example": ["v=DKIM1; k=rsa; p=MIGf"]}


def test_all_three_records_present_is_a_pass_with_each_found():
    r = check(GOOD, ["google"])
    assert r.spf and r.dmarc and r.dkim == {"google": True} and r.error is None and r.ok


def test_a_missing_spf_or_dmarc_fails_and_says_which():
    no_spf = {k: v for k, v in GOOD.items() if k != "bank.example"}
    r = check(no_spf, ["google"])
    assert not r.ok and not r.spf and r.dmarc
    no_dmarc = {k: v for k, v in GOOD.items() if k != "_dmarc.bank.example"}
    r = check(no_dmarc, ["google"])
    assert not r.ok and r.spf and not r.dmarc


def test_a_txt_record_that_is_not_spf_or_dmarc_does_not_count():
    r = check({"bank.example": ["some other text"], "_dmarc.bank.example": ["hello"]})
    assert not r.spf and not r.dmarc


def test_dkim_is_checked_only_for_the_selectors_the_bank_lists_and_every_one_must_exist():
    assert check(GOOD, []).ok                                   # no selector listed: DKIM is not judged
    r = check(GOOD, ["google", "selector2"])
    assert r.dkim == {"google": True, "selector2": False} and not r.ok


def test_a_lookup_that_fails_is_reported_not_raised():
    r = check(GOOD, ["google"], fail={"_dmarc.bank.example"})
    assert not r.ok and r.error == "lookup_failed"


def test_the_domain_is_taken_from_the_sending_address():
    assert domain_of("Alerts <alerts@Bank.Example>") == "bank.example"
    assert domain_of("alerts@bank.example") == "bank.example"
    assert domain_of("nonsense") is None and domain_of("") is None and domain_of(None) is None


def test_the_real_resolver_returns_an_empty_list_for_a_name_that_does_not_exist():
    assert asyncio.run(txt_lookup("this-name-does-not-exist.invalid", timeout=3)) == []
