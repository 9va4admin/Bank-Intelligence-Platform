"""Mail-domain DNS check for the Go-Live readiness: does the sending domain publish an SPF record, a DMARC record and (for the selectors the bank lists) DKIM keys.

The lookup is a plain function so the rules are tested without the network; `txt_lookup` is the real one (dnspython). A lookup that fails is reported in the
result, never raised. Mail goes out without these records, but a receiving mail server may then treat an alert as spam: that is what this warns about.
"""
from __future__ import annotations

import re
from typing import Awaitable, Callable, Optional

import structlog
from pydantic import BaseModel, ConfigDict, Field

log = structlog.get_logger()

Lookup = Callable[[str], Awaitable[list[str]]]


class DnsFinding(BaseModel):
    model_config = ConfigDict(frozen=True)
    domain: str
    spf: bool = False
    dmarc: bool = False
    dkim: dict[str, bool] = Field(default_factory=dict)
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.spf and self.dmarc and all(self.dkim.values())


def domain_of(address: Optional[str]) -> Optional[str]:
    """The domain of a sending address, with or without a display name ("Alerts <a@bank.example>")."""
    match = re.search(r"@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b", address or "")
    return match.group(1).lower() if match else None


async def txt_lookup(name: str, *, timeout: float = 5.0) -> list[str]:
    """The TXT records of a name. A name with no such record is an empty list; any other failure raises."""
    import dns.asyncresolver
    import dns.exception
    import dns.resolver
    try:
        answer = await dns.asyncresolver.resolve(name, "TXT", lifetime=timeout)
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return []
    return ["".join(part.decode("utf-8", "replace") for part in rdata.strings) for rdata in answer]


def _has(records: list[str], prefix: str) -> bool:
    return any(r.strip().lower().startswith(prefix) for r in records)


async def check_mail_domain(domain: str, dkim_selectors: list[str], lookup: Lookup) -> DnsFinding:
    try:
        spf = _has(await lookup(domain), "v=spf1")
        dmarc = _has(await lookup(f"_dmarc.{domain}"), "v=dmarc1")
        dkim = {}
        for selector in dkim_selectors:
            records = await lookup(f"{selector}._domainkey.{domain}")
            dkim[selector] = any("v=dkim1" in r.lower() or re.search(r"\bp=", r) for r in records)
    except Exception as exc:  # noqa: BLE001
        log.warning("alert_proof.dns_lookup_failed", domain=domain, error_type=type(exc).__name__)
        return DnsFinding(domain=domain, error="lookup_failed")
    return DnsFinding(domain=domain, spf=spf, dmarc=dmarc, dkim=dkim)
