import re
from typing import Optional

from .models import PrincipalTag, SubMemberBank

# MICR E-13B special characters
_TRANSIT_SYMBOL = "⑆"
_ON_US_SYMBOL = "⑉"
_AMOUNT_SYMBOL = "⑈"


class MICRPrefixRouter:
    """
    Identifies whether a cheque belongs to a Direct NGCH member or a Sub-Member Bank
    by matching the MICR band routing number against a configured prefix table.

    Routing table is loaded from Admin UI (Layer 3 config) and passed at construction.
    """

    def __init__(self, routing_table: dict[str, SubMemberBank]):
        self._table = routing_table

    def identify(self, micr_band: str) -> tuple[PrincipalTag, Optional[SubMemberBank]]:
        """
        Parse the MICR band and look up the routing number prefix.
        Returns (PrincipalTag, SubMemberBank) — SubMemberBank is None for DIRECT.
        """
        routing_number = self._extract_routing_number(micr_band)
        if not routing_number:
            return PrincipalTag.DIRECT, None

        smb = self._match_prefix(routing_number)
        if smb:
            return PrincipalTag.SUB_MEMBER, smb
        return PrincipalTag.DIRECT, None

    def tag_principal(self, micr_band: str) -> PrincipalTag:
        tag, _ = self.identify(micr_band)
        return tag

    def lookup(self, prefix: str) -> Optional[SubMemberBank]:
        return self._table.get(prefix)

    def _extract_routing_number(self, micr_band: str) -> Optional[str]:
        # Routing number is the digits before the first transit symbol ⑆
        parts = micr_band.split(_TRANSIT_SYMBOL)
        if len(parts) >= 2:
            # Left of ⑆ is routing number, strip leading whitespace/zeros for prefix match
            return parts[0].strip()
        # Fallback: first token of space-delimited band
        tokens = micr_band.strip().split()
        return tokens[0] if tokens else None

    def _match_prefix(self, routing_number: str) -> Optional[SubMemberBank]:
        # Try longest prefix first (6, then 5, 4, 3 digits)
        for length in (6, 5, 4, 3):
            prefix = routing_number[:length]
            if prefix in self._table:
                return self._table[prefix]
        return None

    @classmethod
    async def from_config_service(cls, bank_id: str, config_service) -> "MICRPrefixRouter":
        """
        Load routing table from config_service (Layer 3 — YugabyteDB via config-service).
        Falls back to empty table on error — routes everything as DIRECT.
        """
        try:
            raw = await config_service.get(f"cts.micr_routing.{bank_id}")
            # raw is expected to be a dict[prefix_str -> SubMemberBank dict]
            table = {
                prefix: SubMemberBank(**smb_data)
                for prefix, smb_data in (raw or {}).items()
            }
            return cls(table)
        except Exception:
            import structlog
            structlog.get_logger().warning(
                "micr_router.config_load_failed",
                bank_id=bank_id,
            )
            return cls({})
