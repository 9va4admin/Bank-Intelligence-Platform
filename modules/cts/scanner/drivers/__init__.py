"""
CTS Scanner hardware driver package.

Each driver wraps a vendor-specific protocol or SDK. When the corresponding
binary (DLL, shared library) or network service is present, the driver works
automatically — no code changes required.

  ranger_transport  — Canon CR-120UV Ranger Transport TCP protocol (port 4242)
  panini_sdk        — Panini Vision X / MVX Windows DLL (panini64.dll / panini.dll)
  dcc_api           — Digital Check TellerScan USB mode (usd.dll, DCC API v12+)

Exceptions are defined here (not in adapters.py) so drivers can import them
without creating a circular dependency with the adapter layer.
"""


class ScannerUnavailableError(Exception):
    """Raised when the physical scanner cannot be reached (network, USB, timeout)."""


class ScannerConfigNotFoundError(Exception):
    """Raised when no scanner config exists for the requested branch or bank."""


class ScannerDriverNotFoundError(RuntimeError):
    """
    Raised when a required scanner DLL / shared library is not found on disk.

    The error message tells the operator exactly where to place the binary.
    Once placed, the same code path runs against the physical scanner with no
    changes required.
    """
