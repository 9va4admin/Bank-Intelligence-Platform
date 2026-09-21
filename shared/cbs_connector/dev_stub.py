"""
DevStubCBSConnector — DEV/TEST STAND-IN, NOT A CBS INTEGRATION.

Serves seeded fixture data (JSON file) so the full inward pipeline can run
without Finacle/BaNCS/FlexCube. Selected with cbs.connector.type=dev_stub and
refuses to connect unless ASTRA_ENV=development, so it can never front a real bank.

Fixture shape:
  {"accounts": {acct: {"status": "ACTIVE", "balance": 1.0, "holder": "NAME"}},
   "stopped_cheques": {acct: ["000777"]},
   "pps": {acct: [{"start": "000100", "end": "000199", "amount": 100.0}]}}
"""
import json
import os

from shared.cbs_connector.base import (
    AccountInfo, AccountStatus, BeneficiaryValidationResult, CBSConnector,
    PPSEntry, StopPaymentResult,
)
from shared.cbs_connector.exceptions import AccountNotFoundError


class DevStubCBSConnector(CBSConnector):
    def __init__(self, base_url: str, bank_id: str, pepper: str = "") -> None:
        self._pepper = pepper
        self._path = base_url          # for the stub, "base_url" is the fixture file path
        self._bank_id = bank_id
        self._data: dict = {}

    def connect(self) -> None:
        if os.environ.get("ASTRA_ENV", "").lower() != "development":
            raise RuntimeError("DevStubCBSConnector may only run with ASTRA_ENV=development")
        with open(self._path, encoding="utf-8") as f:
            self._data = json.load(f)

    def _acct(self, account_number: str) -> dict:
        try:
            return self._data.get("accounts", {})[account_number]
        except KeyError:
            raise AccountNotFoundError(account_number[-4:]) from None

    async def get_account_info(self, account_number: str, bank_id: str) -> AccountInfo:
        a = self._acct(account_number)
        return AccountInfo(
            account_number_hash=self._hash_account(account_number, bank_id, self._pepper),
            account_number_last4=account_number[-4:],
            status=AccountStatus(a.get("status", "ACTIVE")),
            bank_id=bank_id,
            available_balance=a.get("balance"),
        )

    async def get_signature_specimens(self, account_number: str, bank_id: str) -> list[bytes]:
        return []

    async def check_stop_payment(self, account_number: str, cheque_number: str, bank_id: str) -> StopPaymentResult:
        hit = cheque_number in self._data.get("stopped_cheques", {}).get(account_number, [])
        return StopPaymentResult(is_stopped=hit, reason="dev_stub_fixture" if hit else None)

    async def get_pps_entries(self, account_number: str, bank_id: str) -> list[PPSEntry]:
        return [PPSEntry(cheque_series_start=e["start"], cheque_series_end=e["end"],
                         amount=e["amount"], is_active=True)
                for e in self._data.get("pps", {}).get(account_number, [])]

    async def get_cheque_status(self, account_number: str, cheque_number: str, bank_id: str) -> str:
        return "ACTIVE"

    async def validate_beneficiary(self, account_number, inquiry_name, bank_id,
                                   name_match_threshold=0.80, high_confidence_threshold=None):
        try:
            a = self._acct(account_number)
        except AccountNotFoundError:
            return BeneficiaryValidationResult(outcome="ACCOUNT_NOT_FOUND")
        score = self._name_match_score(inquiry_name, a.get("holder", ""))
        return BeneficiaryValidationResult(
            outcome="PROCEED" if score >= name_match_threshold else "NAME_MISMATCH",
            account_status=AccountStatus(a.get("status", "ACTIVE")),
            name_match_score=score, payee_display=self._payee_display(inquiry_name),
        )

    async def list_issued_leaves(self, bank_id: str) -> list[dict]:
        return []

    async def get_branch_contacts(self, branch_code: str, bank_id: str):
        raise NotImplementedError("dev stub has no branch directory")

    async def get_signatory_data(self, account_number: str, bank_id: str):
        return []
