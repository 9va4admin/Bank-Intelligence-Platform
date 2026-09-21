"""API-side audit writes never reached ImmuDB:
 1. apps/api/main.py never created app.state.immudb_client, and every router guards with `if immudb:`
 2. routers called immudb.write_event(event.to_json()) where to_json() is BYTES but write_event needs a dict.
So every branch / PU / scanner-config audit event the API should write was silently dropped."""
import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared.audit.audit_event import AuditEvent, AuditEventType


def test_to_record_is_a_json_safe_dict_with_bank_id_for_write_event():
    ev = AuditEvent(event_type=AuditEventType.BRANCH_CREATED, bank_id="kbl", payload={"branch_ifsc": "KARB0000001"})
    rec = ev.to_record()
    assert isinstance(rec, dict)
    assert rec["bank_id"] == "kbl" and rec["event_type"] == "BRANCH_CREATED"
    assert rec["payload"] == {"branch_ifsc": "KARB0000001"}
    json.dumps(rec)                                            # serialisable


def test_routers_never_pass_to_json_bytes_to_write_event():
    offenders = []
    for f in Path("apps/api/routers").glob("*.py"):
        if re.search(r"write_event\(\s*\w+\.to_json\(\)", f.read_text(encoding="utf-8")):
            offenders.append(f.name)
    assert not offenders, offenders


@pytest.mark.asyncio
async def test_bootstrap_builds_a_connected_sync_client():
    from shared.audit.immudb_bootstrap import build_sync_immudb_client
    cfg = MagicMock()
    cfg.get_platform = MagicMock(side_effect=lambda k: {"immudb.host": "h", "immudb.port": "3322"}[k])
    cfg.get_secret = AsyncMock(side_effect=lambda k: {"immudb.username": "u", "immudb.password": "p"}[k])
    with patch("shared.audit.immudb_client.ImmudbClient") as cls:
        client = await build_sync_immudb_client(cfg, "kbl")
    cls.return_value.connect.assert_called_once()
    assert client is cls.return_value


@pytest.mark.asyncio
async def test_bootstrap_returns_none_when_unreachable_or_unconfigured():
    from shared.audit.immudb_bootstrap import build_sync_immudb_client
    cfg = MagicMock(); cfg.get_platform = MagicMock(side_effect=KeyError("immudb.host"))
    assert await build_sync_immudb_client(cfg, "kbl") is None
