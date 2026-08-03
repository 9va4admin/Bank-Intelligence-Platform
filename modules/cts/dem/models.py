"""
DEM data models — NPCI Data Exchange Module Spec v20.

The DEM is the transport layer that moves CXF/CIBF/RRF files between the
bank's ASTRA system and NPCI's Central Clearing House (CCH).

Protocol overview:
  Outward (bank → CCH): sign + encrypt → HTTPS RU/R handshake → SFTP upload
  Inward (CCH → bank):  HTTPS FL poll → SFTP batch download → HTTPS ACK → verify + decrypt
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List


class DEMFileType(str, Enum):
    """File types exchanged in the DEM protocol."""
    # Outward (bank → CCH)
    CXF = "CXF"           # Cheque Exchange Format (outward clearing)
    CIBF = "CIBF"         # Cheque Image Bundle Format (image archive)
    RRF = "RRF"           # Return Reason File
    RECONCIL = "RECONCIL" # Reconciliation CSV (every 30 seconds)
    # Inward (CCH → bank)
    PXF = "PXF"           # Presentment Exchange File (inward cheques)
    PIBF = "PIBF"         # Presentment Image Bundle File (inward images)
    RF = "RF"             # Return File
    RES = "RES"           # Response file (NGCH status)
    OACK = "OACK"         # Outward Acknowledgement
    EF = "EF"             # Exception File
    EOS = "EOS"           # End of Session
    RESEND = "RESEND"     # Resend trigger from CCH
    SWITCHOVER = "SWITCHOVER"  # DR switchover trigger


# Download priority per DEM spec §2.c: lower number = download first
_INWARD_PRIORITY: dict[DEMFileType, int] = {
    DEMFileType.PXF: 1,
    DEMFileType.PIBF: 2,
    DEMFileType.RF: 3,
    DEMFileType.RES: 4,
    DEMFileType.RECONCIL: 5,
    DEMFileType.EF: 7,
    DEMFileType.OACK: 8,
    DEMFileType.EOS: 9,
}


def inward_download_priority(file_type: DEMFileType) -> int:
    """Return download priority for an inward file type (lower = higher priority)."""
    return _INWARD_PRIORITY.get(file_type, 99)


class FileClearingType(str, Enum):
    """CCH-returned FileClearingType codes from Reqtype=RU response."""
    CXF_14 = "CXF_14"    # CXF On Realization (CT=14)
    CXF_01 = "CXF_01"    # CXF Normal (CT=01)
    CXF_99 = "CXF_99"    # CXF Express (CT=99)
    CIBF_14 = "CIBF_14"
    CIBF_01 = "CIBF_01"
    CIBF_99 = "CIBF_99"
    RRF = "RRF"
    PPS_0 = "PPS_0"


class DEMEncryptionAlgo(str, Enum):
    """Symmetric encryption algorithm for DEM file transport."""
    AES = "AES"      # AES-256-CBC (preferred, default for new banks)
    DES3 = "3DES"    # Triple-DES (legacy — use AES if bank has a choice)


@dataclass(frozen=True)
class CCHKeyBundle:
    """CCH's RSA public key, retrieved via Reqtype=W every 4 hours.

    Used for:
      - OUTWARD: encrypt the random AES-256 symmetric key
      - INWARD: verify CCH's RSA-SHA256 signature on received files
    """
    modulus: int              # RSA modulus N (parsed from hex string in Reqtype=W response)
    exponent: int             # RSA public exponent e (typically 65537)
    valid_from: str           # e.g. "01/01/2026"
    valid_to: str             # e.g. "31/12/2026"
    dem_key_alias_name: str   # alias name CCH embeds in DEM headers
    retrieved_at: float       # Unix timestamp of retrieval


@dataclass(frozen=True)
class DEMConfig:
    """Per-bank DEM configuration — populated from config_service.

    All secrets (SFTP password, mTLS certs) come from Vault via config_service.
    This dataclass holds non-secret operational parameters from Layer 2 Helm values.
    """
    bank_id: str
    bank_routing_no: str           # 9-digit NPCI routing number
    dem_id: str                    # DEM identifier assigned by NPCI at registration
    hsm_key_alias: str             # Bank's HSM key alias (DEM signing key)
    cch_https_url: str             # https://CCH_IP:PORT/CCHBank/api/ftp
    cch_sftp_primary: str          # Primary CCH SFTP IP address
    cch_sftp_secondary: str        # Secondary CCH SFTP IP (DR/switchover)
    sftp_username: str             # SFTP username assigned at DEM registration
    sftp_local_backup_dir: str     # Local backup dir for resend capability
    encryption_algo: DEMEncryptionAlgo = DEMEncryptionAlgo.AES
    key_refresh_interval_hours: int = 4
    inward_poll_interval_seconds: int = 30
    reconcil_interval_seconds: int = 30
    sftp_max_batch_size: int = 5   # DEM spec: max 5 files per SFTP session


@dataclass
class DEMInwardFileInfo:
    """File information returned from Reqtype=FL (file list query)."""
    filename: str
    file_type: DEMFileType
    size_bytes: int
    priority: int = field(init=False)

    def __post_init__(self) -> None:
        self.priority = inward_download_priority(self.file_type)


@dataclass(frozen=True)
class DEMOutwardHandshakeResult:
    """Result of the Reqtype=RU + Reqtype=R two-phase outward handshake."""
    sftp_host: str
    sftp_port: int
    allowed_clearing_types: List[FileClearingType]
    session_ref: str   # opaque reference returned by CCH for this upload session
