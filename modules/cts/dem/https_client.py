"""
DEM HTTPS Client — NPCI DEM Spec v20 §2.

All CCH interactions use form-encoded HTTPS POST to a single endpoint.
The Reqtype field in the POST body selects the operation:

  Reqtype=RU  → Register Upload intent; CCH returns SFTP host + allowed file types
  Reqtype=R   → Confirm upload session; CCH returns session_ref
  Reqtype=FL  → File List query; CCH returns list of inward files awaiting download
  Reqtype=A   → Acknowledge receipt of one inward file (after SFTP download)
  Reqtype=W   → Key exchange (handled by DEMKeyManager, not here)

Response format: key=value text lines; StatusCode=00 = success.

Production: uses httpx with mTLS cert from Vault via config_service.
Test seam: patch _post() with AsyncMock.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from modules.cts.dem.models import (
    DEMConfig,
    DEMFileType,
    DEMInwardFileInfo,
    DEMOutwardHandshakeResult,
    FileClearingType,
    inward_download_priority,
)


class DEMHTTPSError(Exception):
    """Raised when CCH returns a non-zero StatusCode or the request fails."""


def _parse_kv(body: str) -> Dict[str, str]:
    """Parse a key=value response body into a dict. Handles duplicate keys by last-wins."""
    result: Dict[str, str] = {}
    for line in body.splitlines():
        line = line.strip()
        if "=" in line:
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip()
    return result


def _check_status(fields: Dict[str, str]) -> None:
    """Raise DEMHTTPSError if StatusCode != '00'."""
    code = fields.get("StatusCode", "")
    if code != "00":
        desc = fields.get("StatusDesc", "unknown error")
        raise DEMHTTPSError(f"CCH returned StatusCode={code!r}: {desc}")


class DEMHTTPSClient:
    """Wraps all CCH HTTPS POST operations for the DEM protocol.

    Production instantiation loads mTLS certs from Vault via config_service.
    Tests patch _post() to inject mock CCH responses.
    """

    def __init__(self, config: DEMConfig) -> None:
        self._config = config

    async def _post(self, payload: Dict[str, str]) -> str:
        """POST form-encoded payload to CCH HTTPS endpoint. Returns response body.

        Production: httpx with mTLS (cert from Vault).
        """
        import httpx
        from shared.config.config_service import config_service

        bank_id = self._config.bank_id
        tls_cert = config_service.get_secret(f"banks.{bank_id}.ngch.tls.cert")
        tls_key = config_service.get_secret(f"banks.{bank_id}.ngch.tls.key")

        async with httpx.AsyncClient(
            cert=(tls_cert, tls_key),
            timeout=30.0,
        ) as client:
            response = await client.post(
                self._config.cch_https_url,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            return response.text

    def _base_payload(self, reqtype: str) -> Dict[str, str]:
        return {
            "Reqtype": reqtype,
            "DEMID": self._config.dem_id,
            "Date": datetime.utcnow().strftime("%d%m%Y"),
            "Routing_Number": self._config.bank_routing_no,
        }

    async def reqtype_ru(
        self, *, file_type: DEMFileType, clearing_type: str
    ) -> DEMOutwardHandshakeResult:
        """Reqtype=RU: register outward upload intent with CCH.

        CCH responds with the SFTP host to use and which FileClearingTypes
        are allowed in this clearing session.

        Args:
            file_type: The type of file about to be uploaded (e.g. DEMFileType.CXF).
            clearing_type: Clearing type code (e.g. "14" for on-realisation).

        Returns:
            DEMOutwardHandshakeResult with sftp_host, sftp_port, allowed_clearing_types.

        Raises:
            DEMHTTPSError on non-zero StatusCode.
        """
        payload = self._base_payload("RU")
        payload["FileType"] = file_type.value
        payload["ClearingType"] = clearing_type

        body = await self._post(payload)
        fields = _parse_kv(body)
        _check_status(fields)

        sftp_host = fields.get("SFTPHost", "")
        sftp_port = int(fields.get("SFTPPort", "22"))
        session_ref = fields.get("SessionRef", "")

        # Parse comma-separated FileClearingType values
        fct_raw = fields.get("FileClearingType", "")
        allowed: List[FileClearingType] = []
        for token in fct_raw.split(","):
            token = token.strip()
            try:
                allowed.append(FileClearingType(token))
            except ValueError:
                pass  # Unknown type — skip

        return DEMOutwardHandshakeResult(
            sftp_host=sftp_host,
            sftp_port=sftp_port,
            allowed_clearing_types=allowed,
            session_ref=session_ref,
        )

    async def reqtype_r(self, *, session_ref: str, filename: str) -> str:
        """Reqtype=R: confirm upload session after SFTP transfer completes.

        Returns the session reference string from CCH.

        Raises:
            DEMHTTPSError on non-zero StatusCode.
        """
        payload = self._base_payload("R")
        payload["SessionRef"] = session_ref
        payload["FileName"] = filename

        body = await self._post(payload)
        fields = _parse_kv(body)
        _check_status(fields)

        return fields.get("SessionRef", session_ref)

    async def reqtype_fl(self) -> List[DEMInwardFileInfo]:
        """Reqtype=FL: query CCH for inward files awaiting download.

        Returns list of DEMInwardFileInfo sorted by download priority
        (PXF first, then PIBF, RF, RES, etc. per DEM spec §2.c).

        Raises:
            DEMHTTPSError on non-zero StatusCode.
        """
        payload = self._base_payload("FL")

        body = await self._post(payload)
        fields = _parse_kv(body)
        _check_status(fields)

        file_count = int(fields.get("FileCount", "0"))
        if file_count == 0:
            return []

        files: List[DEMInwardFileInfo] = []
        for i in range(1, file_count + 1):
            filename = fields.get(f"File{i}", "")
            file_type_str = fields.get(f"File{i}Type", "")
            size_str = fields.get(f"File{i}Size", "0")

            try:
                file_type = DEMFileType(file_type_str)
            except ValueError:
                continue  # Unknown file type — skip

            files.append(DEMInwardFileInfo(
                filename=filename,
                file_type=file_type,
                size_bytes=int(size_str),
            ))

        # Sort by download priority (lower number = higher priority)
        files.sort(key=lambda f: f.priority)
        return files

    async def reqtype_a(self, *, filename: str) -> bool:
        """Reqtype=A: acknowledge successful download of one inward file.

        CCH removes the file from the pending list on receipt of ACK.

        Returns:
            True on success.

        Raises:
            DEMHTTPSError on non-zero StatusCode.
        """
        payload = self._base_payload("A")
        payload["FileName"] = filename

        body = await self._post(payload)
        fields = _parse_kv(body)
        _check_status(fields)

        return True
