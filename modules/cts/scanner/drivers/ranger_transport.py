"""
Canon Ranger Transport async TCP client.

Canon CR-120UV (and other Ranger-compatible scanners) run a Ranger daemon on the
branch network. ASTRA connects via a plain TCP socket, sends ASCII commands, and
receives binary image data.

When the Ranger daemon is running at the configured host:port, this client
connects and operates the scanner automatically — no driver install on the
ASTRA server required.

Protocol (ASCII/binary, CR-LF terminated):
  Send:   SCAN\\r\\n
  Recv:   FRONT_SIZE:<n>\\r\\n  → <n> bytes of JPEG (front grey)
          REAR_SIZE:<n>\\r\\n   → <n> bytes of JPEG (rear)
          UV_SIZE:<n>\\r\\n     → <n> bytes of UV image
          MICR:<micr_line>\\r\\n
          END_SCAN\\r\\n
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

from modules.cts.scanner.drivers import ScannerUnavailableError


@dataclass
class RangerScanResult:
    """Raw output from one Ranger scan pass."""
    front_image:        bytes
    rear_image:         bytes
    uv_image:           Optional[bytes]
    micr:               str
    dpi:                int              = 200
    imprinter_stamped:  bool             = False
    double_feed_detected: bool           = False


class RangerTransportClient:
    """
    Async TCP client for the Canon Ranger Transport protocol.

    Usage:
        async with RangerTransportClient(host="192.168.1.51", port=4242) as client:
            result = await client.scan()

    Or explicitly:
        client = RangerTransportClient(host=..., port=...)
        await client.connect()
        result = await client.scan()
        await client.disconnect()
    """

    def __init__(self, host: str, port: int = 4242, timeout: float = 30.0) -> None:
        self._host    = host
        self._port    = port
        self._timeout = timeout
        self._reader: Optional[asyncio.StreamReader]  = None
        self._writer: Optional[asyncio.StreamWriter]  = None

    # ── Context manager ───────────────────────────────────────────────────────

    async def __aenter__(self) -> "RangerTransportClient":
        await self.connect()
        return self

    async def __aexit__(self, *_) -> None:
        await self.disconnect()

    # ── Public API ────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """
        Open TCP connection to the Ranger daemon.
        Raises ScannerUnavailableError if the daemon is unreachable.
        """
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port),
                timeout=self._timeout,
            )
        except (asyncio.TimeoutError, ConnectionRefusedError, OSError) as exc:
            raise ScannerUnavailableError(
                f"Cannot connect to Canon Ranger daemon at {self._host}:{self._port}. "
                f"Ensure the Ranger Transport service is running. Detail: {exc}"
            ) from exc

    async def disconnect(self) -> None:
        """Close the TCP connection gracefully."""
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            finally:
                self._writer = None
                self._reader = None

    async def scan(self) -> RangerScanResult:
        """
        Send SCAN command and read back front+rear+UV images plus MICR.
        Returns a RangerScanResult with all image buffers populated.
        """
        if not self._reader or not self._writer:
            raise ScannerUnavailableError("Not connected — call connect() first")

        # Send scan trigger
        self._writer.write(b"SCAN\r\n")
        await self._writer.drain()

        front_image = await self._read_binary_block("FRONT_SIZE")
        rear_image  = await self._read_binary_block("REAR_SIZE")
        uv_image    = await self._read_binary_block("UV_SIZE")

        micr_raw = await self._read_tagged_line("MICR")

        # Consume END_SCAN
        end_line = await self._readline()
        if not end_line.strip().endswith(b"END_SCAN"):
            raise ScannerUnavailableError(
                f"Unexpected Ranger protocol terminator: {end_line!r}"
            )

        # Read imprinter / double-feed flags if present (optional lines before END_SCAN
        # already consumed above — flags are embedded in optional header lines in
        # extended Ranger protocol; default to False for CR-120UV base firmware)
        return RangerScanResult(
            front_image=front_image,
            rear_image=rear_image,
            uv_image=uv_image if uv_image else None,
            micr=micr_raw,
            dpi=200,
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _readline(self) -> bytes:
        assert self._reader
        return await asyncio.wait_for(self._reader.readline(), timeout=self._timeout)

    async def _read_binary_block(self, tag: str) -> bytes:
        """
        Read a size-prefixed binary block:
          <TAG>:<size>\\r\\n
          <size bytes of binary data>
        Returns empty bytes if size is 0 (UV absent on non-UV firmware).
        """
        size_line = await self._readline()
        prefix = f"{tag}:".encode()
        if not size_line.startswith(prefix):
            raise ScannerUnavailableError(
                f"Ranger protocol error: expected '{tag}:' line, got {size_line!r}"
            )
        size_str = size_line[len(prefix):].strip()
        size = int(size_str)
        if size == 0:
            return b""
        assert self._reader
        return await asyncio.wait_for(
            self._reader.readexactly(size), timeout=self._timeout
        )

    async def _read_tagged_line(self, tag: str) -> str:
        """Read a '<TAG>:<value>\\r\\n' line and return the value."""
        line = await self._readline()
        prefix = f"{tag}:".encode()
        if not line.startswith(prefix):
            raise ScannerUnavailableError(
                f"Ranger protocol error: expected '{tag}:' line, got {line!r}"
            )
        return line[len(prefix):].rstrip(b"\r\n").decode("utf-8", errors="replace")
