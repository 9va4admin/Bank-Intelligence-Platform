"""PII masking utilities — use these for all logging and API responses.

Never log raw account numbers, exact amounts, or full customer names.
Import from here; never write ad-hoc masking logic inline.
"""


def mask_account_number(account_number: str) -> str:
    """Return ****{last4} — last 4 digits only."""
    if not account_number:
        return "****"
    return f"****{account_number[-4:]}"


def mask_customer_name(name: str) -> str:
    """Return {first-initial}*** — first letter only."""
    if not name or not name.strip():
        return "***"
    return f"{name.strip()[0]}***"


def mask_amount(amount: float) -> str:
    """Return a range bucket — never the exact amount."""
    if amount < 100_000:
        return "₹[<1L]"
    elif amount < 500_000:
        return "₹[1L-5L]"
    elif amount < 1_000_000:
        return "₹[5L-10L]"
    elif amount < 10_000_000:
        return "₹[10L-1Cr]"
    else:
        return "₹[>1Cr]"


def mask_phone(phone: str) -> str:
    """Return ******{last4} — last 4 digits only."""
    if not phone:
        return "******"
    return f"******{phone[-4:]}"
