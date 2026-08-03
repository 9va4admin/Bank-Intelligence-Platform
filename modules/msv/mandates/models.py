"""
MSV Mandate models — core data types for Multi-Signature Validation.

These models define:
  - MandateRuleType: which BRE algorithm applies
  - SignatoryRecord: enrolled signatory with specimen embeddings (read from registry)
  - MandateRule: the mandate configuration for an account
  - AccountMandateMeta: full context needed to validate an instrument
  - MSVInput / MSVOutput: API boundary models
  - MatchedSignatory: assignment result from greedy cosine matching

PII rules enforced here:
  - name_masked is always in P*** format — full names are never stored
  - account_number is never a field in any of these models — only account_hash
  - MSVInput carries raw account_number only transiently; it is hashed before any
    storage or lookup by the signatory registry
"""
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict


class MandateRuleType(str, Enum):
    ALL_OF = "ALL_OF"
    ANY_N_OF = "ANY_N_OF"
    MANDATORY_PLUS_QUORUM = "MANDATORY_PLUS_QUORUM"
    THRESHOLD_SPLIT = "THRESHOLD_SPLIT"
    ROLE_BASED = "ROLE_BASED"


class MSVOutcome(str, Enum):
    GREEN = "GREEN"
    AMBER = "AMBER"
    RED = "RED"


class SignatoryRecord(BaseModel):
    """
    An authorized signatory for an account, with their enrolled specimen embeddings.

    embeddings: list of 512-dim float32 vectors (one per specimen, usually 3).
    name_masked: always in P*** format — the registry never stores full names.
    """
    model_config = ConfigDict(frozen=True)

    signatory_id: str
    role: str                             # CFO, DIRECTOR, TRUSTEE, MD, etc.
    name_masked: str                      # "P***" — first initial + asterisks
    specimen_count: int                   # how many specimens enrolled (usually 3)
    embeddings: list[list[float]]         # list of 512-dim vectors (one per specimen)


class MandateRule(BaseModel):
    """
    The mandate configuration controlling how many / which signatories must sign.

    All threshold values (min_score) come from the account's mandate record — they
    originate from CBS and are stored in msv.mandate_rules. The BRE reads them
    from here, never from config_service (mandate rules are per-account, not per-bank).
    """
    model_config = ConfigDict(frozen=True)

    rule_type: MandateRuleType
    mandatory_ids: list[str] = []         # for MANDATORY_PLUS_QUORUM
    required_count: int = 1               # for ANY_N_OF / quorum part / ROLE_BASED
    required_roles: list[str] = []        # for ROLE_BASED and THRESHOLD_SPLIT role keys
    min_score: float = 0.80               # per-signatory match threshold


class AccountMandateMeta(BaseModel):
    """
    Full mandate context for a single account — loaded before MSV evaluation begins.

    account_hash: HMAC-SHA256 of account number (pepper from Vault).
    Raw account number is never stored here.
    """
    model_config = ConfigDict(frozen=True)

    account_hash: str
    bank_id: str
    operation_type: str                   # S/E/F/A/J/JAS/L/T/P
    mandate: MandateRule
    signatories: list[SignatoryRecord]


class MSVInput(BaseModel):
    """
    Input from the CTS pipeline / API. account_number is raw — it will be hashed
    by SignatoryRegistry._hash_account() before any storage or Redis lookup.
    """
    model_config = ConfigDict(frozen=True)

    instrument_id: str
    bank_id: str
    account_number: str                   # raw — hashed before any storage/lookup
    cheque_image_url: str


class MatchedSignatory(BaseModel):
    """
    Result of greedy assignment for one signatory.

    best_score: max cosine similarity across all specimens for this signatory.
    specimen_idx: which of the signatory's specimen embeddings produced the best match.
    """
    model_config = ConfigDict(frozen=True)

    signatory_id: str
    role: str
    name_masked: str
    best_score: float
    specimen_idx: int                     # which specimen matched best (0, 1, or 2)


class MSVOutput(BaseModel):
    """
    Final output from the MSV pipeline. Returned by the API and stored in audit trail.

    outcome: GREEN (confirmed) / AMBER (routed to human review) / RED (rejected)
    confidence: overall confidence score for the outcome determination
    reason_code: machine-readable code (e.g. "ALL_MATCHED", "MISSING_MANDATORY")
    reason_message: human-readable text (from messages.yaml MSV_* keys)
    """
    model_config = ConfigDict(frozen=True)

    outcome: MSVOutcome
    confidence: float
    reason_code: str
    reason_message: str
    matched_signatories: list[MatchedSignatory]
    detected_sig_count: int
    mandate_rule_type: str
