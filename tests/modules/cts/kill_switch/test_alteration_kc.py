"""
Tests for KC checkpoint in modules/cts/workflows/activities/alteration.py

Kill Complete (KC): Vision AI (Qwen2-VL) must NOT be called.
  → returns AlterationActivityResult(kill_switch_mode="KC", requires_human_review=True)

Kill Partial (KP): Vision AI still runs.
  → returns normal result with kill_switch_mode="KP" (decision backstop handles HUMAN_REVIEW)

NONE: normal processing, no kill_switch_mode set.
"""
import json
from unittest.mock import AsyncMock, MagicMock
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_input(smb_id=None):
    from modules.cts.workflows.activities.alteration import AlterationActivityInput
    return AlterationActivityInput(
        image_url="s3://bucket/INST001.jpg",
        instrument_id="INST001",
        bank_id="test-bank",
        smb_id=smb_id,
    )


def _kill_status(mode: str, scope: str = "GLOBAL", smb_id: str | None = None):
    from modules.cts.kill_switch.vision_ai_kill_switch import KillMode, KillScope, KillSwitchStatus
    if mode == "NONE":
        return KillSwitchStatus(mode=KillMode.NONE)
    return KillSwitchStatus(
        mode=KillMode(mode),
        scope=KillScope(scope),
        smb_id=smb_id,
    )


def _mock_vllm(payload: dict | None = None):
    payload = payload or {
        "fields": [{"field_name": "amount_figures", "altered": False, "confidence": 0.97, "current_value": "50000"}],
        "overall_tamper_risk": 0.02,
        "physical_anomaly_score": 0.01,
    }
    response = MagicMock()
    response.choices[0].message.content = json.dumps(payload)
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(return_value=response)
    return client


# ---------------------------------------------------------------------------
# KC checkpoint — Vision AI must NOT run
# ---------------------------------------------------------------------------

class TestKCCheckpoint:
    @pytest.mark.asyncio
    async def test_kc_skips_vllm_call_entirely(self):
        """When KC is active, vLLM must not be called at all."""
        from modules.cts.workflows.activities.alteration import detect_alteration
        vllm = _mock_vllm()
        await detect_alteration(_make_input(), vllm_client=vllm, kill_switch_status=_kill_status("KC"))
        vllm.chat.completions.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_kc_returns_kill_switch_mode_kc(self):
        from modules.cts.workflows.activities.alteration import detect_alteration
        result = await detect_alteration(
            _make_input(), vllm_client=_mock_vllm(), kill_switch_status=_kill_status("KC")
        )
        assert result.kill_switch_mode == "KC"

    @pytest.mark.asyncio
    async def test_kc_sets_requires_human_review(self):
        from modules.cts.workflows.activities.alteration import detect_alteration
        result = await detect_alteration(
            _make_input(), vllm_client=_mock_vllm(), kill_switch_status=_kill_status("KC")
        )
        assert result.requires_human_review is True

    @pytest.mark.asyncio
    async def test_kc_does_not_set_degraded_flag(self):
        """KC is deliberate — it's not a degradation. degraded must be False."""
        from modules.cts.workflows.activities.alteration import detect_alteration
        result = await detect_alteration(
            _make_input(), vllm_client=_mock_vllm(), kill_switch_status=_kill_status("KC")
        )
        assert result.degraded is False

    @pytest.mark.asyncio
    async def test_kc_records_scope_in_result(self):
        from modules.cts.workflows.activities.alteration import detect_alteration
        result = await detect_alteration(
            _make_input(smb_id="ucb-001"),
            vllm_client=_mock_vllm(),
            kill_switch_status=_kill_status("KC", scope="SMB", smb_id="ucb-001"),
        )
        assert result.kill_switch_scope == "SMB"

    @pytest.mark.asyncio
    async def test_kc_alteration_detected_is_false(self):
        """KC skips AI — alteration_detected must be False (undetermined, not tampered)."""
        from modules.cts.workflows.activities.alteration import detect_alteration
        result = await detect_alteration(
            _make_input(), vllm_client=_mock_vllm(), kill_switch_status=_kill_status("KC")
        )
        assert result.alteration_detected is False


# ---------------------------------------------------------------------------
# KP checkpoint — Vision AI still runs, mode recorded
# ---------------------------------------------------------------------------

class TestKPCheckpoint:
    @pytest.mark.asyncio
    async def test_kp_still_calls_vllm(self):
        """KP does not block Vision AI — Qwen2-VL must be called."""
        from modules.cts.workflows.activities.alteration import detect_alteration
        vllm = _mock_vllm()
        await detect_alteration(_make_input(), vllm_client=vllm, kill_switch_status=_kill_status("KP"))
        vllm.chat.completions.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_kp_records_kill_switch_mode_on_result(self):
        """Result must carry kill_switch_mode='KP' so decision backstop can act."""
        from modules.cts.workflows.activities.alteration import detect_alteration
        result = await detect_alteration(
            _make_input(), vllm_client=_mock_vllm(), kill_switch_status=_kill_status("KP")
        )
        assert result.kill_switch_mode == "KP"

    @pytest.mark.asyncio
    async def test_kp_records_scope_on_result(self):
        from modules.cts.workflows.activities.alteration import detect_alteration
        result = await detect_alteration(
            _make_input(), vllm_client=_mock_vllm(),
            kill_switch_status=_kill_status("KP", scope="SB_OWN"),
        )
        assert result.kill_switch_scope == "SB_OWN"


# ---------------------------------------------------------------------------
# NONE — normal processing
# ---------------------------------------------------------------------------

class TestNoneMode:
    @pytest.mark.asyncio
    async def test_none_mode_calls_vllm(self):
        from modules.cts.workflows.activities.alteration import detect_alteration
        vllm = _mock_vllm()
        await detect_alteration(_make_input(), vllm_client=vllm, kill_switch_status=_kill_status("NONE"))
        vllm.chat.completions.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_none_mode_kill_switch_mode_is_none_string(self):
        from modules.cts.workflows.activities.alteration import detect_alteration
        result = await detect_alteration(
            _make_input(), vllm_client=_mock_vllm(), kill_switch_status=_kill_status("NONE")
        )
        assert result.kill_switch_mode == "NONE"

    @pytest.mark.asyncio
    async def test_no_kill_switch_status_passed_is_treated_as_none(self):
        """Callers that don't pass kill_switch_status get normal processing."""
        from modules.cts.workflows.activities.alteration import detect_alteration
        vllm = _mock_vllm()
        result = await detect_alteration(_make_input(), vllm_client=vllm)
        vllm.chat.completions.create.assert_called_once()
        assert result.kill_switch_mode == "NONE"

    @pytest.mark.asyncio
    async def test_smb_id_field_accepted_on_input(self):
        """AlterationActivityInput must accept smb_id without error."""
        from modules.cts.workflows.activities.alteration import AlterationActivityInput
        inp = AlterationActivityInput(
            image_url="s3://bucket/X.jpg",
            instrument_id="X001",
            bank_id="sbi",
            smb_id="ucb-999",
        )
        assert inp.smb_id == "ucb-999"


# ---------------------------------------------------------------------------
# Immudb write on KC path — per-instrument CTS_KILL_SWITCH_APPLIED audit record
# ---------------------------------------------------------------------------

class TestKCImmudbWrite:
    @pytest.mark.asyncio
    async def test_kc_writes_to_immudb(self):
        """KC path must write CTS_KILL_SWITCH_APPLIED to Immudb."""
        from modules.cts.workflows.activities.alteration import detect_alteration
        from unittest.mock import AsyncMock, MagicMock
        immudb = MagicMock()
        immudb.write_event = AsyncMock(return_value={"tx_id": "tx-kc-001"})
        hsm = MagicMock()
        hsm.sign = MagicMock(side_effect=lambda data: b"sig-" + data[:4])

        await detect_alteration(
            _make_input(),
            vllm_client=_mock_vllm(),
            kill_switch_status=_kill_status("KC"),
            immudb_client=immudb,
            hsm=hsm,
        )
        immudb.write_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_kc_immudb_event_type_is_applied(self):
        """The audit event type written on KC must be CTS_KILL_SWITCH_APPLIED."""
        import json
        from modules.cts.workflows.activities.alteration import detect_alteration
        from shared.audit.audit_event import AuditEventType
        from unittest.mock import AsyncMock, MagicMock
        immudb = MagicMock()
        written_bytes = []
        async def _capture(data):
            written_bytes.append(data)
            return {"tx_id": "tx-001"}
        immudb.write_event = _capture
        hsm = MagicMock()
        hsm.sign = MagicMock(side_effect=lambda d: b"sig")

        await detect_alteration(
            _make_input(),
            vllm_client=_mock_vllm(),
            kill_switch_status=_kill_status("KC"),
            immudb_client=immudb,
            hsm=hsm,
        )
        assert len(written_bytes) == 1
        data = json.loads(written_bytes[0])
        assert data["event_type"] == AuditEventType.CTS_KILL_SWITCH_APPLIED.value

    @pytest.mark.asyncio
    async def test_kc_immudb_payload_contains_instrument_id(self):
        """The Immudb payload must include instrument_id for per-instrument tracing."""
        import json
        from modules.cts.workflows.activities.alteration import detect_alteration
        from unittest.mock import AsyncMock, MagicMock
        immudb = MagicMock()
        written_bytes = []
        async def _capture(data):
            written_bytes.append(data)
            return {"tx_id": "tx-001"}
        immudb.write_event = _capture
        hsm = MagicMock()
        hsm.sign = MagicMock(side_effect=lambda d: b"sig")

        await detect_alteration(
            _make_input(),
            vllm_client=_mock_vllm(),
            kill_switch_status=_kill_status("KC"),
            immudb_client=immudb,
            hsm=hsm,
        )
        data = json.loads(written_bytes[0])
        assert data["payload"]["instrument_id"] == "INST001"

    @pytest.mark.asyncio
    async def test_kc_immudb_payload_contains_mode(self):
        import json
        from modules.cts.workflows.activities.alteration import detect_alteration
        from unittest.mock import AsyncMock, MagicMock
        immudb = MagicMock()
        written_bytes = []
        async def _capture(data):
            written_bytes.append(data)
            return {}
        immudb.write_event = _capture
        hsm = MagicMock()
        hsm.sign = MagicMock(side_effect=lambda d: b"sig")

        await detect_alteration(
            _make_input(),
            vllm_client=_mock_vllm(),
            kill_switch_status=_kill_status("KC"),
            immudb_client=immudb,
            hsm=hsm,
        )
        data = json.loads(written_bytes[0])
        assert data["payload"]["kill_switch_mode"] == "KC"

    @pytest.mark.asyncio
    async def test_kc_without_immudb_does_not_raise(self):
        """When no immudb_client is passed, KC path must still succeed (backward compat)."""
        from modules.cts.workflows.activities.alteration import detect_alteration
        result = await detect_alteration(
            _make_input(),
            vllm_client=_mock_vllm(),
            kill_switch_status=_kill_status("KC"),
            immudb_client=None,
            hsm=None,
        )
        assert result.kill_switch_mode == "KC"


# ---------------------------------------------------------------------------
# Immudb write on KP backstop (decision.py writes it, not alteration.py)
# Alteration.py with KP does NOT write — that's decision.py's job
# ---------------------------------------------------------------------------

class TestKPNoImmudbInAlteration:
    @pytest.mark.asyncio
    async def test_kp_does_not_write_to_immudb_in_alteration(self):
        """KP: alteration.py does NOT write Immudb — decision.py backstop does."""
        from modules.cts.workflows.activities.alteration import detect_alteration
        from unittest.mock import AsyncMock, MagicMock
        immudb = MagicMock()
        immudb.write_event = AsyncMock()
        hsm = MagicMock()
        hsm.sign = MagicMock(side_effect=lambda d: b"sig")

        await detect_alteration(
            _make_input(),
            vllm_client=_mock_vllm(),
            kill_switch_status=_kill_status("KP"),
            immudb_client=immudb,
            hsm=hsm,
        )
        immudb.write_event.assert_not_called()
