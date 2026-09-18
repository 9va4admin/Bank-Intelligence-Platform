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

    @staticmethod
    def parse_ocr_text(raw: str) -> dict:
        """
        Tolerant MICR parse for image-OCR text (GOT-OCR2/Tesseract/HF vision),
        which reads printed MICR digits but has no way to reproduce the E-13B
        delimiter glyphs (⑆ ⑈ ⑉) a physical MICR-reader head outputs — those
        symbols only exist on the scanner-hardware path (see parse() above).

        Indian CTS-2010 MICR band is a fixed-width digit string, standard
        layout: 6 (cheque number) + 9 (city-bank-branch code) + 6 (account
        number) + 2 (transaction code) = 23 digits. OCR noise (stray letters,
        punctuation, misreads) is stripped first; the longest resulting
        digit run is used. Positions are only trusted when the run is
        exactly 23 digits — a shorter/longer run means OCR corruption, and
        guessing positions on a corrupted run would fabricate an account
        number, so all fields are returned as None instead.

        Returns dict with keys: cheque_number, bank_branch_code,
        account_number_fragment (last 4 digits only — PII rule, same as
        parse() above), all None if no exactly-23-digit run is found.
        """
        empty = {
            'cheque_number': None,
            'bank_branch_code': None,
            'account_number_fragment': None,
        }
        if not raw or not raw.strip():
            return empty

        # OCR/vision models frequently insert spaces between the MICR band's
        # printed digit groups (cheque no. / city-bank-branch / account /
        # transaction code) even though no space exists on the physical
        # cheque -- strip everything non-digit and treat the whole line as
        # one run rather than picking the single longest contiguous run.
        run = re.sub(r'\D', '', raw)
        if len(run) != 23:
            return empty

        cheque_number = run[0:6]
        bank_branch_code = run[6:15]
        account_number = run[15:21]
        return {
            'cheque_number': cheque_number,
            'bank_branch_code': bank_branch_code,
            'account_number_fragment': account_number[-4:],
        }
