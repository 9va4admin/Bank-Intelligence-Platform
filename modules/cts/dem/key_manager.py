"""
DEM CCH Key Manager — NPCI DEM Spec v20 §2.b (Reqtype=W).

Fetches CCH's RSA public key every 4 hours via HTTPS POST and caches it.
The CCH key is required for:
  - Outward: encrypting the random AES-256 key before SFTP upload
  - Inward: verifying CCH's RSA-SHA256 signature on received files

Key exchange request (form-encoded POST):
  Reqtype=W
  DEMID=<bank_dem_id>
  Date=<DDMMYYYY>
  Routing_Number=<bank_routing_no>

Response format (key=value, one per line):
  StatusCode=00              ← must be "00" for success
  StatusDesc=Success
  TransactionId=<txn>
  Modulus=<uppercase hex>   ← RSA modulus N
  Exponent=<uppercase hex>  ← RSA exponent e
  ValidFrom=DD/MM/YYYY
  ValidTo=DD/MM/YYYY
  DEM_keyaliasname=<alias>
"""
from __future__ import annotations

import time
from datetime import datetime

from modules.cts.dem.models import CCHKeyBundle, DEMConfig


class DEMKeyError(Exception):
    """Raised when CCH key retrieval or parsing fails."""


def _parse_w_response(response_body: str) -> CCHKeyBundle:
    """Parse a Reqtype=W response body into a CCHKeyBundle.

    Raises:
        DEMKeyError if StatusCode != "00" or required fields are missing.
    """
    fields: dict[str, str] = {}
    for line in response_body.splitlines():
        line = line.strip()
        if "=" in line:
            k, _, v = line.partition("=")
            fields[k.strip()] = v.strip()

    status = fields.get("StatusCode", "")
    if status != "00":
        desc = fields.get("StatusDesc", "unknown error")
        raise DEMKeyError(
            f"CCH Reqtype=W returned StatusCode={status!r}: {desc}"
        )

    mod_hex = fields.get("Modulus", "")
    if not mod_hex:
        raise DEMKeyError("CCH Reqtype=W response missing 'Modulus' field")

    exp_hex = fields.get("Exponent", "")
    if not exp_hex:
        raise DEMKeyError("CCH Reqtype=W response missing 'Exponent' field")

    try:
        modulus = int(mod_hex, 16)
    except ValueError as exc:
        raise DEMKeyError(f"Modulus is not valid hex: {mod_hex!r}") from exc

    try:
        exponent = int(exp_hex, 16)
    except ValueError as exc:
        raise DEMKeyError(f"Exponent is not valid hex: {exp_hex!r}") from exc

    return CCHKeyBundle(
        modulus=modulus,
        exponent=exponent,
        valid_from=fields.get("ValidFrom", ""),
        valid_to=fields.get("ValidTo", ""),
        dem_key_alias_name=fields.get("DEM_keyaliasname", ""),
        retrieved_at=time.time(),
    )


class DEMKeyManager:
    """Manages CCH's RSA public key with 4-hour cache and force-refresh support.

    Usage:
        manager = DEMKeyManager(config=dem_config)
        bundle = await manager.get_cch_key()
        # Use bundle.modulus + bundle.exponent to build CCH's public key for encryption
    """

    def __init__(self, config: DEMConfig) -> None:
        self._config = config
        self._cached_bundle: CCHKeyBundle | None = None

    def _is_cache_valid(self) -> bool:
        if self._cached_bundle is None:
            return False
        age_hours = (time.time() - self._cached_bundle.retrieved_at) / 3600
        return age_hours < self._config.key_refresh_interval_hours

    async def _fetch_from_cch(self) -> str:
        """POST Reqtype=W to CCH HTTPS endpoint. Returns response body as string.

        Production: uses httpx with mTLS cert loaded from Vault via config_service.
        This method is a seam — tests patch it with a mock.
        """
        import httpx
        from shared.config.config_service import config_service

        date_str = datetime.utcnow().strftime("%d%m%Y")
        payload = {
            "Reqtype": "W",
            "DEMID": self._config.dem_id,
            "Date": date_str,
            "Routing_Number": self._config.bank_routing_no,
        }

        # mTLS cert from Vault — never from disk
        tls_cert = config_service.get_secret(f"banks.{self._config.bank_id}.ngch.tls.cert")
        tls_key = config_service.get_secret(f"banks.{self._config.bank_id}.ngch.tls.key")

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

    async def get_cch_key(self, *, force_refresh: bool = False) -> CCHKeyBundle:
        """Return CCH's current RSA public key bundle.

        Uses cached value if within key_refresh_interval_hours unless force_refresh=True.

        Raises:
            DEMKeyError on HTTPS failure or invalid response from CCH.
        """
        if not force_refresh and self._is_cache_valid():
            return self._cached_bundle  # type: ignore[return-value]

        try:
            response_body = await self._fetch_from_cch()
        except DEMKeyError:
            raise
        except Exception as exc:
            raise DEMKeyError(f"Failed to fetch CCH key (Reqtype=W): {exc}") from exc

        bundle = _parse_w_response(response_body)
        self._cached_bundle = bundle
        return bundle
