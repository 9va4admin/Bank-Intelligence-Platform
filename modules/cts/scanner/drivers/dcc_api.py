"""
Digital Check TellerScan DCC API ctypes wrapper (USB mode).

Digital Check supplies usd.dll as part of their DCC API (Device Control and
Communication API v12+). Place usd.dll in the bin/ search path and this driver
connects to the physical TS240-UV or TS250 automatically — no other setup required.

This is the USB-mode alternative to SecureLink 2.0. Both yield identical scan
results; USB is preferred in single-teller kiosk deployments; SecureLink is
preferred in multi-teller or network appliance deployments.

DLL search order:
  1. dll_search_path parameter (if supplied)
  2. bin/          (relative to CWD — production location)
  3. C:/ASTRA/bin/ (absolute fallback)

API functions wrapped (DCC API v12+ one-call scan pattern):
  USD_OpenScanner()                        → c_int  (handle, -1 on error)
  USD_ScanItem(handle)                     → c_int  (0 = SCAN_OK)
  USD_GetImageData(handle, image_type, buf, size_ptr) → c_int
    image_type: 0 = front grey, 1 = rear, 2 = front UV
  USD_GetMICR(handle, buf, size_ptr)       → c_int
  USD_CloseScanner(handle)                 → c_int

Reference: Digital Check DCC API Programmer Reference, Section 4 "One-Call Scan".
"""
from __future__ import annotations

import ctypes
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from modules.cts.scanner.drivers import ScannerDriverNotFoundError, ScannerUnavailableError


_IMAGE_BUF_SIZE = 4 * 1024 * 1024   # 4 MB — well above any real scan image
_MICR_BUF_SIZE  = 512

# DCC API image type constants
_IMG_FRONT_GREY = 0
_IMG_REAR       = 1
_IMG_FRONT_UV   = 2

_DLL_NAME       = "usd.dll"
_FALLBACK_PATHS = ["bin", "C:/ASTRA/bin"]


@dataclass
class DCCScanResult:
    """Raw images and MICR from one DCC API scan pass."""
    front_image: bytes
    rear_image:  bytes
    uv_image:    Optional[bytes]
    micr:        str


class DCCAPIDriver:
    """
    ctypes wrapper for the Digital Check DCC API (USB mode).

    When usd.dll is placed in the dll_search_path, this driver calls into the
    real TS240-UV or TS250 hardware. No code changes needed.

    Usage:
        driver = DCCAPIDriver()                   # searches bin/usd.dll
        result = driver.scan_item()               # no UV
        result = driver.scan_item(capture_uv=True)
    """

    def __init__(self, dll_search_path: Optional[str] = None) -> None:
        self._dll = self._load_dll(dll_search_path)

    # ── Public API ────────────────────────────────────────────────────────────

    def scan_item(self, capture_uv: bool = False) -> DCCScanResult:
        """
        Open scanner, scan one item, read images + MICR, close scanner.
        Raises ScannerUnavailableError on hardware or DLL error.
        """
        handle = self._dll.USD_OpenScanner()
        if handle <= 0:
            raise ScannerUnavailableError(
                f"USD_OpenScanner() returned {handle}. "
                "Check scanner power, USB connection, and usd.dll version."
            )
        try:
            rc = self._dll.USD_ScanItem(ctypes.c_int(handle))
            if rc != 0:
                raise ScannerUnavailableError(
                    f"USD_ScanItem() returned error code {rc}. "
                    "Ensure a cheque is placed in the feed tray."
                )

            front_image = self._get_image(handle, _IMG_FRONT_GREY)
            rear_image  = self._get_image(handle, _IMG_REAR)
            uv_image    = self._get_image(handle, _IMG_FRONT_UV) if capture_uv else None
            micr        = self._get_micr(handle)
        finally:
            self._dll.USD_CloseScanner(ctypes.c_int(handle))

        return DCCScanResult(
            front_image=front_image,
            rear_image=rear_image,
            uv_image=uv_image,
            micr=micr,
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    def _get_image(self, handle: int, image_type: int) -> bytes:
        buf      = (ctypes.c_ubyte * _IMAGE_BUF_SIZE)()
        size_ptr = (ctypes.c_int * 1)(0)
        rc = self._dll.USD_GetImageData(
            ctypes.c_int(handle), ctypes.c_int(image_type), buf, size_ptr
        )
        if rc != 0:
            raise ScannerUnavailableError(
                f"USD_GetImageData(image_type={image_type}) returned error {rc}"
            )
        return bytes(buf[: size_ptr[0]])

    def _get_micr(self, handle: int) -> str:
        buf      = (ctypes.c_char * _MICR_BUF_SIZE)()
        size_ptr = (ctypes.c_int * 1)(0)
        self._dll.USD_GetMICR(ctypes.c_int(handle), buf, size_ptr)
        return buf.value.decode("utf-8", errors="replace")

    @staticmethod
    def _load_dll(search_path: Optional[str]) -> ctypes.CDLL:
        """
        Locate usd.dll and load it.
        Raises ScannerDriverNotFoundError with install instructions if absent.
        """
        search_dirs: list[Path] = []
        if search_path:
            search_dirs.append(Path(search_path))
        search_dirs.extend(Path(p) for p in _FALLBACK_PATHS)

        for directory in search_dirs:
            candidate = directory / _DLL_NAME
            if candidate.exists():
                return ctypes.WinDLL(str(candidate))

        searched = ", ".join(str(d / _DLL_NAME) for d in search_dirs)
        raise ScannerDriverNotFoundError(
            f"Digital Check DCC API DLL not found. "
            f"Place usd.dll in the bin/ folder. "
            f"Searched: {searched}. "
            f"usd.dll ships with the Digital Check DCC API SDK — obtain from "
            f"Digital Check support (digitalcheck.com) and copy to bin/usd.dll."
        )
