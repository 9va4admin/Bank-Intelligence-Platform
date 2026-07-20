"""
CTS Scanner OEM Adapters + ScannerFactory.

Architecture:
  BranchScannerConfig  — Pydantic model; loaded from config_service per branch.
  ScannerAdapter (ABC) — normalised interface all OEM adapters implement.
  OEM adapters         — one per device family; absorb SDK/protocol differences.
  ScannerFactory       — reads config_service, returns the right adapter instance.

Integration paths by OEM:
  Digital Check TS240-UV / TS250 → SecureLink 2.0 HTTPS REST API
  Canon CR-120UV                 → Ranger Transport API (TCP)
  Panini Vision X / MVX          → Drop-folder (OEM software writes metadata + images)
  MagTek / Burroughs / Generic   → TWAIN/ISIS or drop-folder

Config keys (config_service, hot-reloadable Layer 3):
  cts.scanner.branch.{branch_id}      — branch-specific scanner config (dict)
  cts.scanner.bank.{bank_id}.default  — bank-wide fallback config (dict)
"""
from __future__ import annotations

import base64
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import structlog
from pydantic import BaseModel, ConfigDict

from modules.cts.scanner.models import IntegrationMode, ScanResult, ScannerOEM

log = structlog.get_logger()


# ── Exceptions ────────────────────────────────────────────────────────────────

class ScannerUnavailableError(Exception):
    """Raised when the physical scanner cannot be reached (network, USB, timeout)."""


class ScannerConfigNotFoundError(Exception):
    """Raised when no scanner config exists for the requested branch or bank."""


# ── Branch-level scanner configuration ───────────────────────────────────────

class BranchScannerConfig(BaseModel):
    """
    Per-branch scanner configuration — loaded from config_service (Layer 3, hot-reload).

    Stored in cts.scanner_branch_configs (YugabyteDB).
    Served via config_service.get("cts.scanner.branch.{branch_id}").

    Fields are optional per integration mode:
      SECURELINK       → securelink_url (required), securelink_timeout_seconds
      RANGER_TRANSPORT → ranger_host (required), ranger_port (required)
      DROP_FOLDER      → drop_folder_path (optional — falls back to WatcherConfig)
      DCC_API / TWAIN  → no additional fields needed (USB-local)
    """
    model_config = ConfigDict(frozen=True)

    bank_id:          str
    branch_id:        str
    scanner_oem:      ScannerOEM
    scanner_model:    str
    integration_mode: IntegrationMode

    # Digital Check SecureLink 2.0
    securelink_url:             Optional[str] = None
    securelink_timeout_seconds: int           = 30

    # Canon Ranger Transport
    ranger_host: Optional[str] = None
    ranger_port: Optional[int] = None

    # Drop-folder (Panini, legacy Canon, MagTek)
    drop_folder_path: Optional[str] = None


# ── SecureLink 2.0 client (Digital Check HTTPS REST) ─────────────────────────

class _SecureLinkClient:
    """
    Async HTTPS client for the Digital Check SecureLink 2.0 API.

    SecureLink runs either embedded in the scanner (newer TS240/TS250 SKUs)
    or on an external appliance (170000-04) connected via USB→LAN.

    API contract (modelled from DCC SecureLink 2.0 documentation):
      POST {base_url}/api/v1/scan
        Body:     {"capture_uv": bool, "dpi": int, "sides": "both"|"front"}
        Response: {
          "status": "OK",
          "micr":   "<E13B line>",
          "images": {
            "front_grey": "<base64>",
            "rear":       "<base64>",
            "front_uv":   "<base64>"   # only when capture_uv=true
          },
          "dpi": int
        }

      GET {base_url}/api/v1/status
        Response: {"ready": bool, "paper_jam": bool, "hopper_empty": bool}
    """

    _SCAN_PATH   = "/api/v1/scan"
    _STATUS_PATH = "/api/v1/status"

    def __init__(self, base_url: str, api_key: str, timeout_seconds: int = 30) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key  = api_key
        self._timeout  = timeout_seconds

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type":  "application/json",
            "Accept":        "application/json",
        }

    async def scan(self, *, capture_uv: bool = True, dpi: int = 200) -> dict:
        """
        Trigger a scan and return the raw SecureLink JSON response.
        Raises ScannerUnavailableError on connectivity or timeout failures.
        """
        payload = {"capture_uv": capture_uv, "dpi": dpi, "sides": "both"}
        url = f"{self._base_url}{self._SCAN_PATH}"
        try:
            async with httpx.AsyncClient(verify=True, timeout=self._timeout) as client:
                resp = await client.post(url, json=payload, headers=self._headers())
                resp.raise_for_status()
                return resp.json()
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise ScannerUnavailableError(
                f"SecureLink unreachable at {self._base_url}: {exc}"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise ScannerUnavailableError(
                f"SecureLink returned HTTP {exc.response.status_code}: {exc}"
            ) from exc

    async def get_status(self) -> dict:
        url = f"{self._base_url}{self._STATUS_PATH}"
        try:
            async with httpx.AsyncClient(verify=True, timeout=10) as client:
                resp = await client.get(url, headers=self._headers())
                resp.raise_for_status()
                return resp.json()
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as exc:
            raise ScannerUnavailableError(
                f"SecureLink status check failed at {self._base_url}: {exc}"
            ) from exc


# ── Abstract base adapter ─────────────────────────────────────────────────────

class ScannerAdapter(ABC):
    """
    Abstract base for all OEM scanner adapters.

    ingest() is the universal entry point — it accepts pre-captured bytes
    (from an SDK callback, SecureLink response, or file) and returns a
    normalised ScanResult. The rest of the CTS pipeline only sees ScanResult.
    """

    def __init__(self, scanner_model: str, bank_id: str, operator_id: str) -> None:
        self.scanner_model = scanner_model
        self.bank_id       = bank_id
        self.operator_id   = operator_id

    @property
    @abstractmethod
    def oem(self) -> ScannerOEM: ...

    def ingest(
        self,
        *,
        front_image:          bytes,
        rear_image:           bytes,
        front_dpi:            int,
        rear_dpi:             int,
        micr_raw:             str,
        uv_image:             Optional[bytes] = None,
        micr_hardware_raw:    Optional[str]   = None,
        imprinter_stamped:    bool            = False,
        double_feed_detected: bool            = False,
    ) -> ScanResult:
        return ScanResult(
            scan_id=self._generate_scan_id(),
            oem=self.oem,
            scanner_model=self.scanner_model,
            front_image=front_image,
            rear_image=rear_image,
            front_dpi=front_dpi,
            rear_dpi=rear_dpi,
            front_file_size_kb=len(front_image) / 1024,
            rear_file_size_kb=len(rear_image)   / 1024,
            front_colour_depth=24,
            rear_colour_depth=24,
            micr_raw=micr_raw,
            bank_id=self.bank_id,
            operator_id=self.operator_id,
            uv_image=uv_image,
            micr_hardware_raw=micr_hardware_raw,
            imprinter_stamped=imprinter_stamped,
            double_feed_detected=double_feed_detected,
        )

    def _generate_scan_id(self) -> str:
        date_str = datetime.now(tz=timezone.utc).strftime('%Y%m%d')
        short    = str(uuid.uuid4()).split('-')[0].upper()
        return f'SCAN-{date_str}-{short}'


# ── Panini adapters ───────────────────────────────────────────────────────────

class PaniniAdapter(ScannerAdapter):
    """Base adapter for the Panini scanner family (I:Deal, MyMicr, i:DEAL)."""

    @property
    def oem(self) -> ScannerOEM:
        return ScannerOEM.PANINI


class PaniniVisionXAdapter(ScannerAdapter):
    """
    Adapter for Panini Vision X and My Vision X (MVX) scanners.

    Integration: DROP_FOLDER — Panini's BancTec/OmniPage software writes a
    per-batch metadata CSV + TIFF images to a configured drop folder.
    The ScannerDropFolderMapper picks these up; this adapter handles the
    live-capture path where the Panini SDK is called directly.

    Capabilities vs base Panini:
      - Ultrasonic double-feed detection
      - UV image capture (UV-LED pass)
      - 200 DPI greyscale + 100 DPI B&W in a single transport pass
    """

    def __init__(self, cfg: BranchScannerConfig, operator_id: str) -> None:
        super().__init__(
            scanner_model=cfg.scanner_model,
            bank_id=cfg.bank_id,
            operator_id=operator_id,
        )
        self._cfg = cfg

    @property
    def oem(self) -> ScannerOEM:
        return ScannerOEM.PANINI


# ── Canon adapters ────────────────────────────────────────────────────────────

class CanonAdapter(ScannerAdapter):
    """Base adapter for Canon imageFormula / CR-series scanners."""

    @property
    def oem(self) -> ScannerOEM:
        return ScannerOEM.CANON


class CanonCR120UVAdapter(ScannerAdapter):
    """
    Adapter for the Canon CR-120UV cheque scanner.

    Integration: RANGER_TRANSPORT — Canon's Ranger Transport API (TCP, typically
    port 4242) exposes: Open/Close transport, Scan, TransportGetMICR(), and
    hardware imprinter control. ASTRA connects to ranger_host:ranger_port.

    CR-120UV capabilities:
      - UV image in a separate LED pass (uv_image populated when present)
      - Hardware MICR E13B via TransportGetMICR() — authoritative over image OCR
      - Rear endorsement imprinter (imprinter_stamped flag)
      - Ultrasonic double-feed detection
    """

    def __init__(self, cfg: BranchScannerConfig, operator_id: str) -> None:
        super().__init__(
            scanner_model=cfg.scanner_model,
            bank_id=cfg.bank_id,
            operator_id=operator_id,
        )
        self._cfg = cfg

    @property
    def oem(self) -> ScannerOEM:
        return ScannerOEM.CANON

    @property
    def ranger_host(self) -> Optional[str]:
        return self._cfg.ranger_host

    @property
    def ranger_port(self) -> Optional[int]:
        return self._cfg.ranger_port


# ── Digital Check adapters ────────────────────────────────────────────────────

class DigitalCheckAdapter(ScannerAdapter):
    """
    Base adapter for all Digital Check scanners using SecureLink 2.0.

    SecureLink runs as an HTTPS REST service embedded in the scanner (newer
    TS240/TS250 SKUs) or on an external appliance (170000-04). ASTRA calls it
    over LAN — no USB driver or DCC API install required on the teller PC.
    """

    def __init__(self, cfg: BranchScannerConfig, operator_id: str) -> None:
        super().__init__(
            scanner_model=cfg.scanner_model,
            bank_id=cfg.bank_id,
            operator_id=operator_id,
        )
        self._cfg = cfg

    @property
    def oem(self) -> ScannerOEM:
        return ScannerOEM.DIGITAL_CHECK

    def _make_securelink_client(self, api_key: str) -> _SecureLinkClient:
        return _SecureLinkClient(
            base_url=self._cfg.securelink_url,
            api_key=api_key,
            timeout_seconds=self._cfg.securelink_timeout_seconds,
        )

    def _parse_securelink_response(self, data: dict) -> ScanResult:
        """Parse a SecureLink scan JSON response into a ScanResult."""
        images = data.get("images", {})
        dpi    = int(data.get("dpi", 200))

        front_bytes = base64.b64decode(images.get("front_grey", ""))
        rear_bytes  = base64.b64decode(images.get("rear", ""))
        uv_b64      = images.get("front_uv")
        uv_bytes    = base64.b64decode(uv_b64) if uv_b64 else None

        return self.ingest(
            front_image=front_bytes,
            rear_image=rear_bytes,
            front_dpi=dpi,
            rear_dpi=dpi,
            micr_raw=data.get("micr", ""),
            uv_image=uv_bytes,
        )


class DigitalCheckTS240UVAdapter(DigitalCheckAdapter):
    """
    Adapter for the Digital Check TellerScan TS240-UV.

    Hardware facts:
      - 50 / 75 / 100 DPM (documents per minute) — model variant dependent
      - UV + optical captured in one pass (no speed penalty)
      - MICR E13B and CMC-7 with OCR-enhanced read
      - Entry/exit pocket: 100 items each
      - Document range: 54–108 mm height, 121–228 mm length, 60–105 gsm

    Integration: SecureLink 2.0 HTTPS REST (preferred) or DCC API v12.12+ (USB).
    ASTRA uses SecureLink so no teller-PC driver installation is required.
    """

    max_speed_dpm: int = 100

    async def scan_via_securelink(self, *, api_key: str = "") -> ScanResult:
        """
        Trigger a live scan over SecureLink 2.0.

        api_key should be fetched from config_service.get_secret() by the caller.
        An empty key is accepted in test/dev — SecureLink appliance can be
        configured without auth in isolated branch LANs.

        Raises ScannerUnavailableError on connectivity or timeout failures —
        callers should route to human review (never crash the workflow).
        """
        client = self._make_securelink_client(api_key)
        try:
            data = await client.scan(capture_uv=True, dpi=200)
        except ScannerUnavailableError:
            log.warning(
                "scanner.securelink_unavailable",
                scanner_model=self.scanner_model,
                bank_id=self.bank_id,
                securelink_url=self._cfg.securelink_url,
            )
            raise ScannerUnavailableError(
                f"{self.scanner_model} at {self._cfg.securelink_url} is unreachable"
            )
        return self._parse_securelink_response(data)


class DigitalCheckTS250Adapter(DigitalCheckAdapter):
    """
    Adapter for the Digital Check TellerScan TS250 (next-gen, launched Oct 2023).

    Hardware facts vs TS240:
      - 55 / 75 / 120 DPM
      - 600 DPI dual contact image sensors (4× raw resolution of TS240)
      - Full-colour front ID card scanning
      - Automatic cleaning mode
      - SimpleSwitch: button toggles between USB/DCC-API and SecureLink/network modes
      - UV capture planned for international market variants

    Integration: SecureLink 2.0 HTTPS REST (SimpleSwitch in network mode).
    """

    max_speed_dpm:      int  = 120
    native_dpi:         int  = 600
    supports_color_id_scan: bool = True

    async def scan_via_securelink(self, *, api_key: str = "") -> ScanResult:
        client = self._make_securelink_client(api_key)
        try:
            data = await client.scan(capture_uv=False, dpi=600)
        except ScannerUnavailableError:
            log.warning(
                "scanner.securelink_unavailable",
                scanner_model=self.scanner_model,
                bank_id=self.bank_id,
                securelink_url=self._cfg.securelink_url,
            )
            raise ScannerUnavailableError(
                f"{self.scanner_model} at {self._cfg.securelink_url} is unreachable"
            )
        return self._parse_securelink_response(data)


# ── MagTek adapter ────────────────────────────────────────────────────────────

class MagTekAdapter(ScannerAdapter):
    """Adapter for MagTek MICR reader/scanner devices."""

    @property
    def oem(self) -> ScannerOEM:
        return ScannerOEM.MAGTEK


# ── Burroughs adapter ─────────────────────────────────────────────────────────

class BurroughsAdapter(ScannerAdapter):
    """Adapter for Burroughs Spectrum / Itec high-volume transport scanners."""

    @property
    def oem(self) -> ScannerOEM:
        return ScannerOEM.BURROUGHS


# ── Generic TWAIN/ISIS fallback ───────────────────────────────────────────────

class GenericTWAINAdapter(ScannerAdapter):
    """
    Fallback adapter for any scanner exposing a TWAIN or ISIS driver.

    Used when the OEM is unknown or when the bank has deployed a scanner not
    yet covered by a dedicated adapter. All images must be pre-captured by
    the TWAIN layer and passed in via ingest() — ASTRA does not call TWAIN
    directly from Python.
    """

    @property
    def oem(self) -> ScannerOEM:
        return ScannerOEM.GENERIC


# Keep GenericAdapter as alias so existing code importing it still works.
GenericAdapter = GenericTWAINAdapter


# ── ScannerFactory ────────────────────────────────────────────────────────────

class ScannerFactory:
    """
    Returns the correct ScannerAdapter for a branch based on config_service.

    Config lookup order:
      1. cts.scanner.branch.{branch_id}     — branch-specific config (dict)
      2. cts.scanner.bank.{bank_id}.default — bank-wide fallback (dict)
      3. ScannerConfigNotFoundError if both are absent

    All config values are served by config_service (Layer 3, hot-reloadable).
    Scanner secrets (SecureLink API keys, Ranger auth) are fetched separately
    via config_service.get_secret() at scan time — never stored in the adapter.

    Usage:
        factory = ScannerFactory(config_service=config_service)
        adapter = await factory.get_adapter(bank_id, branch_id, operator_id)
        # adapter is the right OEM class — call adapter.ingest() or
        # adapter.scan_via_securelink() depending on integration_mode
    """

    def __init__(self, config_service: Any) -> None:
        self._config = config_service

    async def get_adapter(
        self, *, bank_id: str, branch_id: str, operator_id: str
    ) -> ScannerAdapter:
        cfg = await self._load_config(bank_id=bank_id, branch_id=branch_id)
        return self._build(cfg=cfg, operator_id=operator_id)

    async def _load_config(self, *, bank_id: str, branch_id: str) -> BranchScannerConfig:
        raw = await self._config.get(f"cts.scanner.branch.{branch_id}")
        if raw is None:
            raw = await self._config.get(f"cts.scanner.bank.{bank_id}.default")
        if raw is None:
            raise ScannerConfigNotFoundError(
                f"No scanner config found for branch '{branch_id}' "
                f"or bank '{bank_id}' default. "
                f"Set cts.scanner.branch.{branch_id} in Admin UI."
            )
        # bank_id and branch_id come from the call-site, not the stored config dict,
        # so we inject them before constructing BranchScannerConfig.
        merged = {**raw, "bank_id": bank_id, "branch_id": branch_id}
        return BranchScannerConfig(**merged)

    def _build(self, *, cfg: BranchScannerConfig, operator_id: str) -> ScannerAdapter:
        oem   = cfg.scanner_oem
        model = cfg.scanner_model.upper()

        if oem == ScannerOEM.DIGITAL_CHECK:
            if "TS250" in model:
                return DigitalCheckTS250Adapter(cfg=cfg, operator_id=operator_id)
            # TS240, TS240-UV, TS240-100IJ, etc. → UV adapter
            return DigitalCheckTS240UVAdapter(cfg=cfg, operator_id=operator_id)

        if oem == ScannerOEM.CANON:
            if "CR-120" in model or "CR120" in model:
                return CanonCR120UVAdapter(cfg=cfg, operator_id=operator_id)
            return CanonAdapter(
                scanner_model=cfg.scanner_model,
                bank_id=cfg.bank_id,
                operator_id=operator_id,
            )

        if oem == ScannerOEM.PANINI:
            if "VISION" in model or "MVX" in model or "MY VISION" in model:
                return PaniniVisionXAdapter(cfg=cfg, operator_id=operator_id)
            return PaniniAdapter(
                scanner_model=cfg.scanner_model,
                bank_id=cfg.bank_id,
                operator_id=operator_id,
            )

        if oem == ScannerOEM.MAGTEK:
            return MagTekAdapter(
                scanner_model=cfg.scanner_model,
                bank_id=cfg.bank_id,
                operator_id=operator_id,
            )

        if oem == ScannerOEM.BURROUGHS:
            return BurroughsAdapter(
                scanner_model=cfg.scanner_model,
                bank_id=cfg.bank_id,
                operator_id=operator_id,
            )

        return GenericTWAINAdapter(
            scanner_model=cfg.scanner_model,
            bank_id=cfg.bank_id,
            operator_id=operator_id,
        )


# ── Legacy function — keep for backward compatibility ─────────────────────────

def get_adapter(
    oem_name: str, scanner_model: str, bank_id: str, operator_id: str
) -> ScannerAdapter:
    """
    Simple synchronous factory for callers that already know the OEM.
    Preserved for backward compatibility; prefer ScannerFactory for new code.
    """
    mapping: dict[str, type[ScannerAdapter]] = {
        "PANINI":        PaniniAdapter,
        "CANON":         CanonAdapter,
        "MAGTEK":        MagTekAdapter,
        "BURROUGHS":     BurroughsAdapter,
        "GENERIC":       GenericTWAINAdapter,
    }
    cls = mapping.get(oem_name.upper(), GenericTWAINAdapter)
    return cls(scanner_model=scanner_model, bank_id=bank_id, operator_id=operator_id)
