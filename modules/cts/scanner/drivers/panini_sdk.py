"""
Panini Vision X / MVX Windows DLL ctypes wrapper.

Panini supplies panini64.dll (64-bit) and panini.dll (32-bit) as part of their
SDK. Place either DLL in the bin/ search path and this driver connects to the
physical scanner automatically — no other install required on the ASTRA server.

DLL search order:
  1. dll_search_path parameter (if supplied)
  2. bin/          (relative to CWD — typical production location)
  3. C:/ASTRA/bin/ (absolute fallback)

API functions wrapped:
  panini_connect(model_str: c_char_p) → c_int  (handle, -1 on error)
  panini_start_scan(handle: c_int) → c_int      (0 = OK)
  panini_get_image(handle, side, buf, size_ptr) → c_int  (side 0=front, 1=rear)
  panini_get_uv_image(handle, buf, size_ptr) → c_int
  panini_get_micr(handle, buf, size_ptr) → c_int
  panini_disconnect(handle: c_int) → None
"""
from __future__ import annotations

import ctypes
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from modules.cts.scanner.drivers import ScannerDriverNotFoundError, ScannerUnavailableError


# Maximum buffer sizes — well above any real scan output
_IMAGE_BUF_SIZE = 4 * 1024 * 1024   # 4 MB per side
_MICR_BUF_SIZE  = 512                # MICR line is at most ~50 chars


@dataclass
class PaniniScanResult:
    """Raw images and MICR from one Panini scan pass."""
    front_image: bytes
    rear_image:  bytes
    uv_image:    Optional[bytes]
    micr:        str


_DLL_NAMES = ["panini64.dll", "panini.dll"]
_FALLBACK_PATHS = ["bin", "C:/ASTRA/bin"]


class PaniniSDKDriver:
    """
    ctypes wrapper for the Panini Vision X / MVX SDK DLL.

    When panini64.dll (or panini.dll) is placed in the dll_search_path,
    this driver calls into the real hardware. No code changes needed.

    Usage:
        driver = PaniniSDKDriver()        # searches bin/ automatically
        result = driver.scan()
        result = driver.scan(capture_uv=True)
    """

    def __init__(
        self,
        dll_search_path: Optional[str] = None,
        scanner_model: str = "VisionX",
    ) -> None:
        self._scanner_model = scanner_model
        self._dll = self._load_dll(dll_search_path)

    # ── Public API ────────────────────────────────────────────────────────────

    def scan(self, capture_uv: bool = False) -> PaniniScanResult:
        """
        Connect to scanner, run one scan pass, disconnect.
        Returns PaniniScanResult with front/rear/UV images and MICR.
        Raises ScannerUnavailableError on hardware or DLL error.
        """
        handle = self._dll.panini_connect(
            ctypes.c_char_p(self._scanner_model.encode("utf-8"))
        )
        if handle <= 0:
            raise ScannerUnavailableError(
                f"Panini panini_connect() returned {handle}. "
                "Check scanner power, USB cable, and DLL version."
            )
        try:
            rc = self._dll.panini_start_scan(ctypes.c_int(handle))
            if rc != 0:
                raise ScannerUnavailableError(
                    f"Panini panini_start_scan() returned error code {rc}. "
                    "Ensure a cheque is placed in the feeder."
                )

            front_image = self._get_image(handle, side=0)
            rear_image  = self._get_image(handle, side=1)
            uv_image    = self._get_uv_image(handle) if capture_uv else None
            micr        = self._get_micr(handle)
        finally:
            self._dll.panini_disconnect(ctypes.c_int(handle))

        return PaniniScanResult(
            front_image=front_image,
            rear_image=rear_image,
            uv_image=uv_image,
            micr=micr,
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    def _get_image(self, handle: int, side: int) -> bytes:
        buf      = (ctypes.c_ubyte * _IMAGE_BUF_SIZE)()
        size_ptr = (ctypes.c_int * 1)(0)
        rc = self._dll.panini_get_image(
            ctypes.c_int(handle), ctypes.c_int(side), buf, size_ptr
        )
        if rc != 0:
            raise ScannerUnavailableError(
                f"panini_get_image(side={side}) returned error {rc}"
            )
        return bytes(buf[: size_ptr[0]])

    def _get_uv_image(self, handle: int) -> bytes:
        buf      = (ctypes.c_ubyte * _IMAGE_BUF_SIZE)()
        size_ptr = (ctypes.c_int * 1)(0)
        self._dll.panini_get_uv_image(ctypes.c_int(handle), buf, size_ptr)
        return bytes(buf[: size_ptr[0]])

    def _get_micr(self, handle: int) -> str:
        buf      = (ctypes.c_char * _MICR_BUF_SIZE)()
        size_ptr = (ctypes.c_int * 1)(0)
        self._dll.panini_get_micr(ctypes.c_int(handle), buf, size_ptr)
        return buf.value.decode("utf-8", errors="replace")

    @staticmethod
    def _load_dll(search_path: Optional[str]) -> ctypes.CDLL:
        """
        Search for the Panini DLL in priority order and load it.
        Raises ScannerDriverNotFoundError with install instructions if not found.
        """
        search_dirs: list[Path] = []
        if search_path:
            search_dirs.append(Path(search_path))
        search_dirs.extend(Path(p) for p in _FALLBACK_PATHS)

        for directory in search_dirs:
            for dll_name in _DLL_NAMES:
                candidate = directory / dll_name
                if candidate.exists():
                    return ctypes.WinDLL(str(candidate))

        searched = ", ".join(
            str(d / n) for d in search_dirs for n in _DLL_NAMES
        )
        raise ScannerDriverNotFoundError(
            f"Panini SDK DLL not found. "
            f"Place panini64.dll (64-bit) or panini.dll (32-bit) in the bin/ folder. "
            f"Searched: {searched}. "
            f"Download from Panini support portal and copy to bin/panini64.dll."
        )
