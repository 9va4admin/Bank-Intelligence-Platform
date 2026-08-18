"""
CBSConnector — abstract base class for all Core Banking System adapters.

Concrete implementations: FinacleCBSConnector, BaNCSCBSConnector, FlexCubeCBSConnector.
The correct implementation is selected at startup based on config_service.get_platform("cbs.connector.type").

PII rules enforced at this layer:
  - Raw account numbers are NEVER stored in AccountInfo — only hash + last4
  - Balance is returned as float (exact amount — used only in CTS decision, never logged)
  - Status mapping normalises CBS-specific strings to AccountStatus enum
"""
from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict

from shared.utils.pii_crypto import hash_account_number


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


class BeneficiaryValidationResult(BaseModel):
    """
    Result of outward CTS payee/beneficiary account validation.

    Raw account holder name is NEVER stored here — fuzzy match is done inside
    the CBS connector where the name is fetched, and only the score + masked
    display value are returned.
    """
    model_config = ConfigDict(frozen=True)

    outcome: str                        # PROCEED | ACCOUNT_NOT_FOUND | NAME_MISMATCH | ACCOUNT_INACTIVE | CBS_UNAVAILABLE
    account_status: Optional[AccountStatus] = None
    name_match_score: Optional[float] = None    # 0.0–1.0; token-sort fuzzy ratio
    name_match_confidence: str = "UNKNOWN"      # HIGH | MEDIUM | LOW | UNKNOWN
    payee_display: Optional[str] = None         # "R***" — first initial only, for UI / audit
    degraded: bool = False


class CBSConnector(ABC):
    """Abstract interface for CBS adapters. All methods are async."""

    # ── Name-matching helper ──────────────────────────────────────────────────

    @staticmethod
    def _name_match_score(a: str, b: str) -> float:
        """
        Token-sort fuzzy ratio using difflib (stdlib, no extra dep).
        Sorting tokens handles Indian name order variations:
          "RAJESH KUMAR" vs "KUMAR RAJESH" → same score as exact match.
        """
        from difflib import SequenceMatcher
        a_norm = " ".join(sorted(a.upper().split()))
        b_norm = " ".join(sorted(b.upper().split()))
        return SequenceMatcher(None, a_norm, b_norm).ratio()

    @staticmethod
    def _payee_display(name: str) -> str:
        """Mask: first initial + *** (e.g. 'RAJESH KUMAR' → 'R***')."""
        clean = name.strip()
        return f"{clean[0]}***" if clean else "***"

    # ── Abstract methods ──────────────────────────────────────────────────────

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

    @abstractmethod
    async def validate_beneficiary(
        self,
        account_number: str,
        inquiry_name: str,
        bank_id: str,
        name_match_threshold: float = 0.80,
    ) -> BeneficiaryValidationResult:
        """
        Outward CTS — validate the payee's account before presenting to NGCH.

        The CBS connector fetches the account holder name from its CBS API,
        performs the fuzzy name match internally, and returns only the outcome
        + score + masked display. Raw account holder name never leaves this method.

        name_match_threshold: minimum token-sort ratio to consider a match.
        Outcome routing:
          PROCEED           → account active and name matches above threshold
          ACCOUNT_NOT_FOUND → account does not exist in this bank's CBS
          NAME_MISMATCH     → account exists but name confidence below threshold → human review
          ACCOUNT_INACTIVE  → FROZEN / CLOSED / NPA / DORMANT → reject
          CBS_UNAVAILABLE   → CBS unreachable → proceed degraded (teller notified)
        """

    @staticmethod
    def _hash_account(account_number: str, bank_id: str = "", pepper: str = "") -> str:
        """HMAC-SHA256 hash of account number via canonical pii_crypto utility."""
        return hash_account_number(account_number, bank_id, pepper)

    @abstractmethod
    async def list_issued_leaves(self, bank_id: str) -> list[dict]:
        """
        List all issued cheque leaves for bulk vault sync.

        Each dict must have: account_number, cheque_number, status.
        Optional: issued_date (str), series_end (str).
        Status values: ACTIVE | LOST | STOLEN | CANCELLED | USED.

        Raises CBSUnavailableError on connection failure.
        Used only by VaultSyncWorkflow.sync_cheque_leaves.
        """

    @abstractmethod
    async def get_branch_contacts(
        self,
        branch_code: str,
        bank_id: str,
    ) -> "BranchContactProfile":
        """
        Fetch branch contact details from CBS using the branch code.

        Returns BranchContactProfile with branch manager email + ops contact.
        Called by VaultSyncWorkflow — deduplicated per branch_code, so one call
        serves all accounts at the same branch.

        Raises CBSUnavailableError on connection failure.
        """

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


class BranchContactProfile(BaseModel):
    """
    Branch contact details fetched from CBS — stored in AccountVault.
    branch_manager_name must already be masked (N*** format) before reaching this model.
    """
    model_config = ConfigDict(frozen=True)

    branch_code: str
    branch_name: str
    branch_ifsc: str
    branch_manager_name: str          # "N***" — never full name
    branch_manager_email: str
    branch_contact_email: str
    branch_contact_phone: str
    last_updated_in_cbs: str          # ISO datetime string


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
