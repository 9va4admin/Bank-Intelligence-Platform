"""
MICR Line Parser.

Parses the E-13B MICR encoding returned by scanner hardware.
MICR special characters:
  ⑆ = Transit symbol (routing number delimiter)
  ⑈ = Amount symbol (separates cheque number from account)
  ⑉ = On-Us symbol (end-of-field)
  ⑇ = Dash symbol

PII rule: Only the last 4 digits of account_number_fragment are stored.
The full account number is never returned or logged.
"""
from __future__ import annotations

import re
from typing import Optional


_TRANSIT = '⑆'
_ON_US   = '⑉'
_AMOUNT  = '⑈'


class MICRParser:
    @staticmethod
    def parse(raw: str) -> dict:
        """
        Returns dict with keys: routing_number, cheque_number, account_number_fragment.
        account_number_fragment contains ONLY the last 4 digits — never the full account.
        All values are None if raw is empty or unparseable.
        """
        if not raw or not raw.strip():
            return {
                'routing_number': None,
                'cheque_number': None,
                'account_number_fragment': None,
            }

        routing   = MICRParser._extract_routing(raw)
        cheque    = MICRParser._extract_cheque(raw)
        acct_last4 = MICRParser._extract_account_last4(raw)

        return {
            'routing_number': routing,
            'cheque_number': cheque,
            'account_number_fragment': acct_last4,
        }

    @staticmethod
    def _extract_routing(raw: str) -> Optional[str]:
        # Routing number is between the two ⑆ symbols
        match = re.search(rf'{re.escape(_TRANSIT)}(\d+){re.escape(_TRANSIT)}', raw)
        return match.group(1) if match else None

    @staticmethod
    def _extract_cheque(raw: str) -> Optional[str]:
        # Cheque number follows second ⑆ up to the ⑈ symbol
        match = re.search(rf'{re.escape(_TRANSIT)}\s*(\d+)\s*{re.escape(_AMOUNT)}', raw)
        return match.group(1).strip() if match else None

    @staticmethod
    def _extract_account_last4(raw: str) -> Optional[str]:
        # Account number follows ⑈ up to the ⑉ symbol — store only last 4 digits (PII rule)
        match = re.search(rf'{re.escape(_AMOUNT)}\s*(\d+)\s*{re.escape(_ON_US)}', raw)
        if not match:
            return None
        full = match.group(1).strip()
        return full[-4:] if len(full) >= 4 else full
