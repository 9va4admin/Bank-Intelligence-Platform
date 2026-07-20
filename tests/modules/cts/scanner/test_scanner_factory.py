"""
Tests for ScannerFactory, BranchScannerConfig, and OEM-specific adapters.

Coverage targets:
  - ScannerOEM extended values (DIGITAL_CHECK, MAGTEK, BURROUGHS)
  - IntegrationMode enum
  - BranchScannerConfig validation
  - ScannerFactory: correct adapter class per OEM/model combination
  - ScannerFactory: bank-wide default fallback when branch has no config
  - DigitalCheckTS240UVAdapter: ingest with and without UV
  - DigitalCheckTS240UVAdapter: scan_via_securelink happy path
  - DigitalCheckTS240UVAdapter: scan_via_securelink scanner unavailable
  - DigitalCheckTS250Adapter: OEM property
  - PaniniVisionXAdapter: ingest
  - CanonCR120UVAdapter: ingest with UV + imprinter flag
  - mapper.py backward compat: ScannerOEM still importable from mapper
"""
import base64
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── ScannerOEM extended values ────────────────────────────────────────────────

def test_scanner_oem_has_digital_check():
    from modules.cts.scanner.models import ScannerOEM
    assert ScannerOEM.DIGITAL_CHECK.value == "DIGITAL_CHECK"


def test_scanner_oem_has_magtek():
    from modules.cts.scanner.models import ScannerOEM
    assert ScannerOEM.MAGTEK.value == "MAGTEK"


def test_scanner_oem_has_burroughs():
    from modules.cts.scanner.models import ScannerOEM
    assert ScannerOEM.BURROUGHS.value == "BURROUGHS"


def test_scanner_oem_has_rdm():
    from modules.cts.scanner.models import ScannerOEM
    assert ScannerOEM.RDM.value == "RDM"


def test_scanner_oem_preserves_existing_values():
    from modules.cts.scanner.models import ScannerOEM
    assert ScannerOEM.PANINI.value == "PANINI"
    assert ScannerOEM.CANON.value == "CANON"
    assert ScannerOEM.GENERIC.value == "GENERIC"


# ── IntegrationMode ───────────────────────────────────────────────────────────

def test_integration_mode_securelink():
    from modules.cts.scanner.models import IntegrationMode
    assert IntegrationMode.SECURELINK.value == "SECURELINK"


def test_integration_mode_dcc_api():
    from modules.cts.scanner.models import IntegrationMode
    assert IntegrationMode.DCC_API.value == "DCC_API"


def test_integration_mode_ranger_transport():
    from modules.cts.scanner.models import IntegrationMode
    assert IntegrationMode.RANGER_TRANSPORT.value == "RANGER_TRANSPORT"


def test_integration_mode_drop_folder():
    from modules.cts.scanner.models import IntegrationMode
    assert IntegrationMode.DROP_FOLDER.value == "DROP_FOLDER"


def test_integration_mode_twain():
    from modules.cts.scanner.models import IntegrationMode
    assert IntegrationMode.TWAIN.value == "TWAIN"


# ── BranchScannerConfig ───────────────────────────────────────────────────────

def test_branch_scanner_config_digital_check_securelink():
    from modules.cts.scanner.adapters import BranchScannerConfig
    from modules.cts.scanner.models import ScannerOEM, IntegrationMode
    cfg = BranchScannerConfig(
        bank_id="saraswat-coop",
        branch_id="branch-parel-001",
        scanner_oem=ScannerOEM.DIGITAL_CHECK,
        scanner_model="TS240-UV",
        integration_mode=IntegrationMode.SECURELINK,
        securelink_url="https://192.168.1.50:8443",
        securelink_timeout_seconds=30,
    )
    assert cfg.bank_id == "saraswat-coop"
    assert cfg.scanner_oem == ScannerOEM.DIGITAL_CHECK
    assert cfg.securelink_url == "https://192.168.1.50:8443"
    assert cfg.securelink_timeout_seconds == 30


def test_branch_scanner_config_canon_ranger():
    from modules.cts.scanner.adapters import BranchScannerConfig
    from modules.cts.scanner.models import ScannerOEM, IntegrationMode
    cfg = BranchScannerConfig(
        bank_id="saraswat-coop",
        branch_id="branch-dadar-001",
        scanner_oem=ScannerOEM.CANON,
        scanner_model="CR-120UV",
        integration_mode=IntegrationMode.RANGER_TRANSPORT,
        ranger_host="192.168.1.51",
        ranger_port=4242,
    )
    assert cfg.ranger_host == "192.168.1.51"
    assert cfg.ranger_port == 4242


def test_branch_scanner_config_panini_drop_folder():
    from modules.cts.scanner.adapters import BranchScannerConfig
    from modules.cts.scanner.models import ScannerOEM, IntegrationMode
    cfg = BranchScannerConfig(
        bank_id="saraswat-coop",
        branch_id="branch-bandra-001",
        scanner_oem=ScannerOEM.PANINI,
        scanner_model="Vision X",
        integration_mode=IntegrationMode.DROP_FOLDER,
        drop_folder_path="/mnt/scanner/drop",
    )
    assert cfg.drop_folder_path == "/mnt/scanner/drop"


def test_branch_scanner_config_optional_fields_default_none():
    from modules.cts.scanner.adapters import BranchScannerConfig
    from modules.cts.scanner.models import ScannerOEM, IntegrationMode
    cfg = BranchScannerConfig(
        bank_id="saraswat-coop",
        branch_id="branch-001",
        scanner_oem=ScannerOEM.DIGITAL_CHECK,
        scanner_model="TS240-UV",
        integration_mode=IntegrationMode.SECURELINK,
        securelink_url="https://192.168.1.50:8443",
    )
    assert cfg.ranger_host is None
    assert cfg.ranger_port is None
    assert cfg.drop_folder_path is None


# ── ScannerFactory — correct adapter per OEM/model ───────────────────────────

def _make_factory_with_config(raw_config: dict):
    from modules.cts.scanner.adapters import ScannerFactory
    mock_config = AsyncMock()
    mock_config.get = AsyncMock(return_value=raw_config)
    return ScannerFactory(config_service=mock_config)


@pytest.mark.asyncio
async def test_factory_returns_ts240uv_for_digital_check_ts240():
    from modules.cts.scanner.adapters import ScannerFactory, DigitalCheckTS240UVAdapter
    factory = _make_factory_with_config({
        "scanner_oem": "DIGITAL_CHECK",
        "scanner_model": "TS240-UV",
        "integration_mode": "SECURELINK",
        "securelink_url": "https://192.168.1.50:8443",
    })
    adapter = await factory.get_adapter(bank_id="saraswat-coop", branch_id="branch-001", operator_id="op1")
    assert isinstance(adapter, DigitalCheckTS240UVAdapter)


@pytest.mark.asyncio
async def test_factory_returns_ts250_for_digital_check_ts250():
    from modules.cts.scanner.adapters import ScannerFactory, DigitalCheckTS250Adapter
    factory = _make_factory_with_config({
        "scanner_oem": "DIGITAL_CHECK",
        "scanner_model": "TS250",
        "integration_mode": "SECURELINK",
        "securelink_url": "https://192.168.1.51:8443",
    })
    adapter = await factory.get_adapter(bank_id="saraswat-coop", branch_id="branch-002", operator_id="op1")
    assert isinstance(adapter, DigitalCheckTS250Adapter)


@pytest.mark.asyncio
async def test_factory_returns_panini_visionx_for_vision_x():
    from modules.cts.scanner.adapters import ScannerFactory, PaniniVisionXAdapter
    factory = _make_factory_with_config({
        "scanner_oem": "PANINI",
        "scanner_model": "Vision X",
        "integration_mode": "DROP_FOLDER",
        "drop_folder_path": "/mnt/scanner/drop",
    })
    adapter = await factory.get_adapter(bank_id="saraswat-coop", branch_id="branch-003", operator_id="op1")
    assert isinstance(adapter, PaniniVisionXAdapter)


@pytest.mark.asyncio
async def test_factory_returns_panini_visionx_for_mvx():
    from modules.cts.scanner.adapters import ScannerFactory, PaniniVisionXAdapter
    factory = _make_factory_with_config({
        "scanner_oem": "PANINI",
        "scanner_model": "My Vision X",
        "integration_mode": "DROP_FOLDER",
    })
    adapter = await factory.get_adapter(bank_id="saraswat-coop", branch_id="branch-004", operator_id="op1")
    assert isinstance(adapter, PaniniVisionXAdapter)


@pytest.mark.asyncio
async def test_factory_returns_canon_cr120uv_for_cr120():
    from modules.cts.scanner.adapters import ScannerFactory, CanonCR120UVAdapter
    factory = _make_factory_with_config({
        "scanner_oem": "CANON",
        "scanner_model": "CR-120UV",
        "integration_mode": "RANGER_TRANSPORT",
        "ranger_host": "192.168.1.51",
        "ranger_port": 4242,
    })
    adapter = await factory.get_adapter(bank_id="saraswat-coop", branch_id="branch-005", operator_id="op1")
    assert isinstance(adapter, CanonCR120UVAdapter)


@pytest.mark.asyncio
async def test_factory_returns_generic_twain_for_unknown_oem():
    from modules.cts.scanner.adapters import ScannerFactory, GenericTWAINAdapter
    factory = _make_factory_with_config({
        "scanner_oem": "GENERIC",
        "scanner_model": "Unknown Model",
        "integration_mode": "TWAIN",
    })
    adapter = await factory.get_adapter(bank_id="saraswat-coop", branch_id="branch-006", operator_id="op1")
    assert isinstance(adapter, GenericTWAINAdapter)


@pytest.mark.asyncio
async def test_factory_falls_back_to_bank_default_when_branch_returns_none():
    """When branch config is None, factory uses bank-wide default."""
    from modules.cts.scanner.adapters import ScannerFactory, DigitalCheckTS240UVAdapter

    bank_default = {
        "scanner_oem": "DIGITAL_CHECK",
        "scanner_model": "TS240-UV",
        "integration_mode": "SECURELINK",
        "securelink_url": "https://10.0.0.50:8443",
    }

    mock_config = AsyncMock()

    async def _get(key: str):
        if "branch" in key:
            return None
        return bank_default

    mock_config.get = AsyncMock(side_effect=_get)

    factory = ScannerFactory(config_service=mock_config)
    adapter = await factory.get_adapter(
        bank_id="saraswat-coop", branch_id="branch-no-scanner-config", operator_id="op1"
    )
    assert isinstance(adapter, DigitalCheckTS240UVAdapter)


@pytest.mark.asyncio
async def test_factory_raises_when_no_config_at_all():
    """ScannerConfigNotFoundError raised when both branch and bank config are absent."""
    from modules.cts.scanner.adapters import ScannerFactory, ScannerConfigNotFoundError

    mock_config = AsyncMock()
    mock_config.get = AsyncMock(return_value=None)

    factory = ScannerFactory(config_service=mock_config)
    with pytest.raises(ScannerConfigNotFoundError):
        await factory.get_adapter(
            bank_id="saraswat-coop", branch_id="branch-no-config", operator_id="op1"
        )


# ── DigitalCheckTS240UVAdapter ────────────────────────────────────────────────

def _make_ts240uv_adapter():
    from modules.cts.scanner.adapters import BranchScannerConfig, DigitalCheckTS240UVAdapter
    from modules.cts.scanner.models import ScannerOEM, IntegrationMode
    cfg = BranchScannerConfig(
        bank_id="saraswat-coop",
        branch_id="branch-parel-001",
        scanner_oem=ScannerOEM.DIGITAL_CHECK,
        scanner_model="TS240-UV",
        integration_mode=IntegrationMode.SECURELINK,
        securelink_url="https://192.168.1.50:8443",
        securelink_timeout_seconds=30,
    )
    return DigitalCheckTS240UVAdapter(cfg=cfg, operator_id="op1")


def test_ts240uv_oem_is_digital_check():
    from modules.cts.scanner.models import ScannerOEM
    adapter = _make_ts240uv_adapter()
    assert adapter.oem == ScannerOEM.DIGITAL_CHECK


def test_ts240uv_ingest_with_uv_image():
    from modules.cts.scanner.models import ScanResult
    adapter = _make_ts240uv_adapter()
    uv_bytes = b'\xAB\xCD' * 500
    result = adapter.ingest(
        front_image=b'\xff\xd8\xff' + b'\x00' * 1000,
        rear_image=b'\xff\xd8\xff' + b'\x00' * 500,
        front_dpi=200,
        rear_dpi=200,
        micr_raw="⑆123456789⑆ 100001⑈ 012300⑉",
        uv_image=uv_bytes,
    )
    assert isinstance(result, ScanResult)
    assert result.uv_image == uv_bytes
    assert result.oem.value == "DIGITAL_CHECK"
    assert result.scan_id.startswith("SCAN-")


def test_ts240uv_ingest_without_uv_defaults_none():
    adapter = _make_ts240uv_adapter()
    result = adapter.ingest(
        front_image=b'\xff\xd8\xff' + b'\x00' * 800,
        rear_image=b'\xff\xd8\xff' + b'\x00' * 400,
        front_dpi=200,
        rear_dpi=200,
        micr_raw="",
    )
    assert result.uv_image is None


def test_ts240uv_max_speed_dpm():
    adapter = _make_ts240uv_adapter()
    assert adapter.max_speed_dpm == 100


@pytest.mark.asyncio
async def test_ts240uv_scan_via_securelink_happy_path():
    """SecureLink returns images + MICR → ScanResult with UV populated."""
    adapter = _make_ts240uv_adapter()

    front_b64 = base64.b64encode(b'\xff\xd8\xff' + b'\x00' * 600).decode()
    rear_b64  = base64.b64encode(b'\xff\xd8\xff' + b'\x00' * 300).decode()
    uv_b64    = base64.b64encode(b'\xAB\xCD' * 150).decode()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "OK",
        "micr": "⑆123456789⑆ 100001⑈ 012300⑉",
        "images": {
            "front_grey": front_b64,
            "rear":       rear_b64,
            "front_uv":   uv_b64,
        },
        "dpi": 200,
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_cls.return_value = mock_client

        result = await adapter.scan_via_securelink()

    assert result.micr_raw == "⑆123456789⑆ 100001⑈ 012300⑉"
    assert result.uv_image is not None
    assert len(result.uv_image) > 0
    assert result.scan_id.startswith("SCAN-")
    assert result.front_dpi == 200


@pytest.mark.asyncio
async def test_ts240uv_scan_via_securelink_connect_error_raises_unavailable():
    """ConnectError from httpx → ScannerUnavailableError (not a crash)."""
    import httpx
    from modules.cts.scanner.adapters import ScannerUnavailableError
    adapter = _make_ts240uv_adapter()

    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_cls.return_value = mock_client

        with pytest.raises(ScannerUnavailableError) as exc_info:
            await adapter.scan_via_securelink()

    assert "TS240-UV" in str(exc_info.value)


@pytest.mark.asyncio
async def test_ts240uv_scan_via_securelink_timeout_raises_unavailable():
    """TimeoutException from httpx → ScannerUnavailableError."""
    import httpx
    from modules.cts.scanner.adapters import ScannerUnavailableError
    adapter = _make_ts240uv_adapter()

    with patch("httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_cls.return_value = mock_client

        with pytest.raises(ScannerUnavailableError):
            await adapter.scan_via_securelink()


# ── DigitalCheckTS250Adapter ──────────────────────────────────────────────────

def _make_ts250_adapter():
    from modules.cts.scanner.adapters import BranchScannerConfig, DigitalCheckTS250Adapter
    from modules.cts.scanner.models import ScannerOEM, IntegrationMode
    cfg = BranchScannerConfig(
        bank_id="saraswat-coop",
        branch_id="branch-001",
        scanner_oem=ScannerOEM.DIGITAL_CHECK,
        scanner_model="TS250",
        integration_mode=IntegrationMode.SECURELINK,
        securelink_url="https://192.168.1.52:8443",
    )
    return DigitalCheckTS250Adapter(cfg=cfg, operator_id="op1")


def test_ts250_oem_is_digital_check():
    from modules.cts.scanner.models import ScannerOEM
    adapter = _make_ts250_adapter()
    assert adapter.oem == ScannerOEM.DIGITAL_CHECK


def test_ts250_max_speed_dpm():
    adapter = _make_ts250_adapter()
    assert adapter.max_speed_dpm == 120


def test_ts250_resolution_dpi():
    adapter = _make_ts250_adapter()
    assert adapter.native_dpi == 600


def test_ts250_supports_color_id_scan():
    adapter = _make_ts250_adapter()
    assert adapter.supports_color_id_scan is True


def test_ts250_ingest_returns_scan_result():
    from modules.cts.scanner.models import ScanResult, ScannerOEM
    adapter = _make_ts250_adapter()
    result = adapter.ingest(
        front_image=b'\xff\xd8\xff' + b'\x00' * 1200,
        rear_image=b'\xff\xd8\xff' + b'\x00' * 600,
        front_dpi=600,
        rear_dpi=600,
        micr_raw="⑆987654321⑆ 200002⑈ 098700⑉",
    )
    assert isinstance(result, ScanResult)
    assert result.oem == ScannerOEM.DIGITAL_CHECK


# ── PaniniVisionXAdapter ──────────────────────────────────────────────────────

def _make_panini_visionx_adapter(model="Vision X"):
    from modules.cts.scanner.adapters import BranchScannerConfig, PaniniVisionXAdapter
    from modules.cts.scanner.models import ScannerOEM, IntegrationMode
    cfg = BranchScannerConfig(
        bank_id="saraswat-coop",
        branch_id="branch-bandra-001",
        scanner_oem=ScannerOEM.PANINI,
        scanner_model=model,
        integration_mode=IntegrationMode.DROP_FOLDER,
        drop_folder_path="/mnt/scanner/drop",
    )
    return PaniniVisionXAdapter(cfg=cfg, operator_id="op1")


def test_panini_visionx_oem_is_panini():
    from modules.cts.scanner.models import ScannerOEM
    adapter = _make_panini_visionx_adapter()
    assert adapter.oem == ScannerOEM.PANINI


def test_panini_mvx_also_uses_visionx_adapter():
    from modules.cts.scanner.adapters import PaniniVisionXAdapter
    adapter = _make_panini_visionx_adapter("My Vision X")
    assert isinstance(adapter, PaniniVisionXAdapter)


def test_panini_visionx_ingest_returns_scan_result():
    from modules.cts.scanner.models import ScanResult, ScannerOEM
    adapter = _make_panini_visionx_adapter()
    result = adapter.ingest(
        front_image=b'\xff\xd8\xff' + b'\x00' * 900,
        rear_image=b'\xff\xd8\xff' + b'\x00' * 450,
        front_dpi=200,
        rear_dpi=200,
        micr_raw="⑆111222333⑆ 000001⑈ 012300⑉",
    )
    assert isinstance(result, ScanResult)
    assert result.oem == ScannerOEM.PANINI
    assert result.scanner_model == "Vision X"


def test_panini_visionx_scanner_model_stored():
    adapter = _make_panini_visionx_adapter()
    assert adapter.scanner_model == "Vision X"


# ── CanonCR120UVAdapter ───────────────────────────────────────────────────────

def _make_canon_cr120uv_adapter():
    from modules.cts.scanner.adapters import BranchScannerConfig, CanonCR120UVAdapter
    from modules.cts.scanner.models import ScannerOEM, IntegrationMode
    cfg = BranchScannerConfig(
        bank_id="saraswat-coop",
        branch_id="branch-csmt-001",
        scanner_oem=ScannerOEM.CANON,
        scanner_model="CR-120UV",
        integration_mode=IntegrationMode.RANGER_TRANSPORT,
        ranger_host="192.168.1.51",
        ranger_port=4242,
    )
    return CanonCR120UVAdapter(cfg=cfg, operator_id="op1")


def test_canon_cr120uv_oem_is_canon():
    from modules.cts.scanner.models import ScannerOEM
    adapter = _make_canon_cr120uv_adapter()
    assert adapter.oem == ScannerOEM.CANON


def test_canon_cr120uv_ingest_with_uv_and_imprinter():
    from modules.cts.scanner.models import ScanResult
    adapter = _make_canon_cr120uv_adapter()
    uv_bytes = b'\xAB\xCD' * 200

    result = adapter.ingest(
        front_image=b'\xff\xd8\xff' + b'\x00' * 900,
        rear_image=b'\xff\xd8\xff' + b'\x00' * 450,
        front_dpi=200,
        rear_dpi=200,
        micr_raw="⑆111222333⑆ 000001⑈ 012300⑉",
        uv_image=uv_bytes,
        imprinter_stamped=True,
        double_feed_detected=False,
    )
    assert isinstance(result, ScanResult)
    assert result.uv_image == uv_bytes
    assert result.imprinter_stamped is True
    assert result.double_feed_detected is False


def test_canon_cr120uv_ingest_double_feed_flag():
    adapter = _make_canon_cr120uv_adapter()
    result = adapter.ingest(
        front_image=b'\xff\xd8\xff',
        rear_image=b'\xff\xd8\xff',
        front_dpi=200,
        rear_dpi=200,
        micr_raw="",
        double_feed_detected=True,
    )
    assert result.double_feed_detected is True


def test_canon_cr120uv_ranger_connection_info():
    adapter = _make_canon_cr120uv_adapter()
    assert adapter.ranger_host == "192.168.1.51"
    assert adapter.ranger_port == 4242


# ── mapper.py backward compatibility ─────────────────────────────────────────

def test_scanner_oem_importable_from_mapper():
    """mapper.py must still export ScannerOEM after consolidation."""
    from modules.cts.scanner.mapper import ScannerOEM
    assert ScannerOEM.PANINI.value == "PANINI"
    assert ScannerOEM.DIGITAL_CHECK.value == "DIGITAL_CHECK"
    assert ScannerOEM.CANON.value == "CANON"


def test_mapper_scanneroem_is_same_object_as_models_scanneroem():
    """Must be the same enum — not a copy — so isinstance checks work across modules."""
    from modules.cts.scanner.mapper import ScannerOEM as MapperOEM
    from modules.cts.scanner.models import ScannerOEM as ModelsOEM
    assert MapperOEM is ModelsOEM


# ── backward compat: existing get_adapter() function still works ──────────────

def test_get_adapter_panini_still_works():
    from modules.cts.scanner.adapters import get_adapter, PaniniAdapter
    a = get_adapter("PANINI", "Panini I:Deal", "saraswat-coop", "op1")
    assert isinstance(a, PaniniAdapter)


def test_get_adapter_canon_still_works():
    from modules.cts.scanner.adapters import get_adapter, CanonAdapter
    a = get_adapter("CANON", "Canon CR-190i", "saraswat-coop", "op1")
    assert isinstance(a, CanonAdapter)


def test_get_adapter_unknown_returns_generic():
    from modules.cts.scanner.adapters import get_adapter, GenericTWAINAdapter
    a = get_adapter("FUJIFILM", "X100", "saraswat-coop", "op1")
    assert isinstance(a, GenericTWAINAdapter)
