"""
CBSConnector — abstract base class for all Core Banking System adapters.

Concrete implementations: FinacleCBSConnector, BaNCSCBSConnector, FlexCubeCBSConnector.
The correct implementation is selected at startup based on config_service.get_platform("cbs.connector.type").

PII rules enforced at this layer:
  - Raw account numbers are NEVER stored in AccountInfo — only hash + last4
  - Balance is returned as float (exact amount — used only in CTS decision, never logged)
  - Status mapping normalises CBS-specific strings to AccountStatus enum
"""
import hashlib
import hmac
from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"
    DORMANT = "DORMANT"
    NPA = "NPA"           # Non-Performing Asset


class AccountInfo(BaseModel):
    """
    Normalised account information returned by any CBS adapter.

    account_number_hash: HMAC-SHA256 of account number (for vault key derivation)
    account_number_last4: last 4 digits only (for display/logging)
    Raw account number is never stored here.
    """
    model_config = ConfigDict(frozen=True)

    account_number_hash: str
    account_number_last4: str
    status: AccountStatus
    bank_id: str
    available_balance: Optional[float] = None
    currency: str = "INR"
    cbs_account_id: Optional[str] = None   # internal CBS ref, not PII


class StopPaymentResult(BaseModel):
    """Result of a stop payment inquiry."""
    model_config = ConfigDict(frozen=True)
    is_stopped: bool
    reason: Optional[str] = None
    stopped_at: Optional[str] = None


class PPSEntry(BaseModel):
    """A single Positive Pay System registration record."""
    model_config = ConfigDict(frozen=True)
    cheque_series_start: str
    cheque_series_end: str
    amount: float
    is_active: bool


class CBSConnector(ABC):
    """Abstract interface for CBS adapters. All methods are async."""

    @abstractmethod
    async def get_account_info(self, account_number: str, bank_id: str) -> AccountInfo:
        """
        Fetch account status and balance.

        Raises AccountNotFoundError if the account does not exist.
        Raises CBSUnavailableError if CBS is unreachable or returns an error.
        """

    @abstractmethod
    async def get_signature_specimens(self, account_number: str, bank_id: str) -> list[bytes]:
        """
        Fetch all registered signature specimen images for an account.

        Returns list of raw image bytes (JPEG/PNG). Empty list if none on file.
        Raises CBSUnavailableError on connection failure.
        """

    @abstractmethod
    async def check_stop_payment(
        self, account_number: str, cheque_number: str, bank_id: str
    ) -> StopPaymentResult:
        """
        Check whether a payment stop instruction exists for a cheque.

        Returns StopPaymentResult. Never raises on 'not stopped' — raises
        CBSUnavailableError only on CBS connection failure.
        """

    @abstractmethod
    async def get_pps_entries(self, account_number: str, bank_id: str) -> list[PPSEntry]:
        """
        Fetch all active Positive Pay System registrations for an account.

        Returns empty list if PPS not registered for this account.
        Raises CBSUnavailableError on connection failure.
        """

    @abstractmethod
    async def get_cheque_status(
        self, account_number: str, cheque_number: str, bank_id: str
    ) -> str:
        """
        Get the CBS status of a specific cheque leaf.

        Returns status string: ACTIVE | LOST | STOLEN | USED | CANCELLED.
        Raises CBSUnavailableError on connection failure.
        """

    @staticmethod
    def _hash_account(account_number: str, pepper: str = "") -> str:
        """HMAC-SHA256 hash of account number. pepper from Vault in production."""
        return hmac.new(
            pepper.encode() if pepper else b"",
            account_number.encode(),
            hashlib.sha256,
        ).hexdigest()

    @abstractmethod
    async def get_signatory_data(
        self,
        account_number: str,
        bank_id: str,
    ) -> list["CBSSignatoryData"]:
        """
        Return all authorized signatories for the account with their specimen images.

        CBSSignatoryData.specimen_images is a list[bytes], one per specimen image.
        The MSV enrollment pipeline embeds these immediately and discards the bytes.

        Raises AccountNotFoundError if account does not exist.
        Raises CBSUnavailableError if CBS is unreachable.
        """


class CBSSignatoryData(BaseModel):
    """
    Raw signatory data from CBS — thin transfer object for MSV enrollment.

    specimen_images: list[bytes] of raw image bytes (JPEG/PNG), one per specimen.
    Images are transient — caller (AccountEnroller) embeds them immediately and discards.
    name_masked must already be masked (P*** format) before reaching this model.
    """
    model_config = ConfigDict(frozen=True)

    signatory_id: str
    role: str
    name_masked: str                   # "P***" — never full name
    specimen_images: list[bytes]       # raw image bytes, one per specimen
    operation_type: str
