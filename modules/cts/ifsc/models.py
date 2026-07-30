"""
IFSC Registry domain models.

IFSCEntry    — read model (from DB row)
IFSCCreateRequest  — write model (API → repository)
IFSCListResponse   — paginated list response

SB entries:  bank_type='SB',  smb_id=None
SMB entries: bank_type='SMB', smb_id=<sub_member_id>

Status lifecycle:
  PENDING  → ops_manager creates (maker)
  ACTIVE   → bank_it_admin approves (checker) — is_active flipped to True
  INACTIVE → bank_it_admin deactivates — is_active flipped to False
"""
from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class IFSCEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    bank_id: str
    bank_type: Literal["SB", "SMB"]
    smb_id: Optional[str] = None

    ifsc_code: str
    branch_name: Optional[str] = None
    branch_city: Optional[str] = None
    micr_code: Optional[str] = None

    is_active: bool = False
    effective_from: date
    effective_till: Optional[date] = None

    status: Literal["PENDING", "ACTIVE", "INACTIVE"] = "PENDING"

    created_by: str
    approved_by: Optional[str] = None


class IFSCCreateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    bank_type: Literal["SB", "SMB"]
    smb_id: Optional[str] = None

    ifsc_code: str
    branch_name: Optional[str] = None
    branch_city: Optional[str] = None
    micr_code: Optional[str] = None
    effective_from: date = date.today()

    @field_validator("ifsc_code")
    @classmethod
    def ifsc_format(cls, v: str) -> str:
        import re
        v = v.strip().upper()
        if not re.match(r"^[A-Z]{4}[0-9A-Z]{7}$", v):
            raise ValueError(f"Invalid IFSC format: {v!r}. Expected 4 alpha + 7 alphanumeric.")
        return v

    @model_validator(mode="after")
    def smb_consistency(self) -> "IFSCCreateRequest":
        if self.bank_type == "SMB" and not self.smb_id:
            raise ValueError("smb_id is required when bank_type is SMB")
        if self.bank_type == "SB" and self.smb_id:
            raise ValueError("smb_id must be None when bank_type is SB")
        return self


class IFSCListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    items: list[IFSCEntry]
    total: int
    bank_id: str
