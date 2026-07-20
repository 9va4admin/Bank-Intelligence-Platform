"""
Tests for CTS scanner hardware drivers.

Covers:
  RangerTransportClient   — Canon CR-120UV async TCP protocol
  PaniniSDKDriver         — Panini Vision X / MVX ctypes DLL wrapper
  DCCAPIDriver            — Digital Check TellerScan USB mode (DCC API ctypes wrapper)
  ScannerDriverNotFoundError — raised when DLL absent, with helpful message

All hardware I/O is mocked (asyncio streams, ctypes.WinDLL).
When the real DLL is placed in bin/ at runtime, these same code paths execute
against the physical scanner with no code changes required.
"""
import asyncio
import ctypes
import platform
import struct
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock


# ── RangerTransportClient (Canon CR-120UV TCP) ────────────────────────────────

class TestRangerTransportClient:

    def _make_client(self):
        from modules.cts.scanner.drivers.ranger_transport import RangerTransportClient
        return RangerTransportClient(host="192.168.1.51", port=4242, timeout=10.0)

    @pytest.mark.asyncio
    async def test_connect_opens_tcp_connection(self):
        from modules.cts.scanner.drivers.ranger_transport import RangerTransportClient
        client = self._make_client()

        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)) as mock_conn:
            await client.connect()
            mock_conn.assert_called_once_with("192.168.1.51", 4242)

    @pytest.mark.asyncio
    async def test_disconnect_closes_writer(self):
        from modules.cts.scanner.drivers.ranger_transport import RangerTransportClient
        client = self._make_client()

        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            await client.connect()
            await client.disconnect()
            mock_writer.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_scan_sends_scan_command_and_returns_result(self):
        from modules.cts.scanner.drivers.ranger_transport import RangerTransportClient, RangerScanResult
        client = self._make_client()

        front_bytes = b'\xff\xd8\xff' + b'\x00' * 500
        rear_bytes  = b'\xff\xd8\xff' + b'\x00' * 300
        uv_bytes    = b'\xAB\xCD' * 100
        micr_line   = "⑆123456789⑆ 100001⑈ 012300⑉"

        front_size_line = f"FRONT_SIZE:{len(front_bytes)}\r\n".encode()
        rear_size_line  = f"REAR_SIZE:{len(rear_bytes)}\r\n".encode()
        uv_size_line    = f"UV_SIZE:{len(uv_bytes)}\r\n".encode()
        micr_line_enc   = f"MICR:{micr_line}\r\n".encode()
        end_line        = b"END_SCAN\r\n"

        # readline is called for: front_size, rear_size, uv_size, micr, end_scan
        # readexactly is called for: front_bytes, rear_bytes, uv_bytes
        mock_reader = AsyncMock()
        mock_reader.readline = AsyncMock(side_effect=[
            front_size_line, rear_size_line, uv_size_line, micr_line_enc, end_line,
        ])
        mock_reader.readexactly = AsyncMock(side_effect=[front_bytes, rear_bytes, uv_bytes])

        mock_writer = MagicMock()
        mock_writer.drain = AsyncMock()
        mock_writer.wait_closed = AsyncMock()

        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            await client.connect()
            result = await client.scan()

        assert isinstance(result, RangerScanResult)
        assert result.micr == micr_line
        assert result.front_image == front_bytes
        assert result.rear_image  == rear_bytes
        assert result.uv_image    == uv_bytes

    @pytest.mark.asyncio
    async def test_connect_timeout_raises_scanner_unavailable(self):
        from modules.cts.scanner.drivers.ranger_transport import RangerTransportClient
        from modules.cts.scanner.adapters import ScannerUnavailableError
        client = self._make_client()

        with patch("asyncio.open_connection", side_effect=asyncio.TimeoutError()):
            with pytest.raises(ScannerUnavailableError, match="192.168.1.51:4242"):
                await client.connect()

    @pytest.mark.asyncio
    async def test_connect_refused_raises_scanner_unavailable(self):
        from modules.cts.scanner.drivers.ranger_transport import RangerTransportClient
        from modules.cts.scanner.adapters import ScannerUnavailableError
        client = self._make_client()

        with patch("asyncio.open_connection", side_effect=ConnectionRefusedError()):
            with pytest.raises(ScannerUnavailableError):
                await client.connect()

    @pytest.mark.asyncio
    async def test_context_manager_auto_connects_and_disconnects(self):
        from modules.cts.scanner.drivers.ranger_transport import RangerTransportClient
        client = self._make_client()

        mock_reader = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            async with client:
                pass
            mock_writer.close.assert_called_once()


# ── PaniniSDKDriver (ctypes DLL wrapper) ──────────────────────────────────────

class TestPaniniSDKDriver:

    def _make_mock_dll(self):
        # No spec — panini functions are added dynamically by the SDK
        dll = MagicMock()
        dll.panini_connect.return_value = 1   # handle = 1
        dll.panini_start_scan.return_value = 0
        dll.panini_disconnect.return_value = None
        return dll

    def test_driver_loads_dll_from_bin_folder(self, tmp_path):
        from modules.cts.scanner.drivers.panini_sdk import PaniniSDKDriver

        fake_dll = tmp_path / "panini64.dll"
        fake_dll.write_bytes(b"MZ")  # minimal PE header marker

        with patch("ctypes.WinDLL", return_value=self._make_mock_dll()) as mock_load:
            driver = PaniniSDKDriver(dll_search_path=str(tmp_path))
            mock_load.assert_called_once_with(str(fake_dll))

    def test_driver_raises_not_found_when_dll_absent(self, tmp_path):
        from modules.cts.scanner.drivers.panini_sdk import PaniniSDKDriver
        from modules.cts.scanner.drivers import ScannerDriverNotFoundError

        with pytest.raises(ScannerDriverNotFoundError, match="panini"):
            PaniniSDKDriver(dll_search_path=str(tmp_path))

    def test_not_found_error_includes_install_instructions(self, tmp_path):
        from modules.cts.scanner.drivers.panini_sdk import PaniniSDKDriver
        from modules.cts.scanner.drivers import ScannerDriverNotFoundError

        with pytest.raises(ScannerDriverNotFoundError) as exc_info:
            PaniniSDKDriver(dll_search_path=str(tmp_path))

        msg = str(exc_info.value)
        assert "bin/" in msg or "dll_search_path" in msg  # tells user where to place DLL

    def test_scan_calls_connect_then_scan_then_returns_images(self, tmp_path):
        from modules.cts.scanner.drivers.panini_sdk import PaniniSDKDriver, PaniniScanResult

        fake_dll_path = tmp_path / "panini64.dll"
        fake_dll_path.write_bytes(b"MZ")

        mock_dll = self._make_mock_dll()

        front_bytes = b'\xff\xd8\xff' + b'\x00' * 500
        rear_bytes  = b'\xff\xd8\xff' + b'\x00' * 300
        micr_str    = "⑆111222333⑆ 000001⑈ 012300⑉"

        # Mock panini_get_image: copies bytes into ctypes buffer
        # ctypes passes c_int objects — extract .value to get plain int
        def fake_get_image(handle, side, buf, size_ptr):
            side_int = side.value if hasattr(side, "value") else int(side)
            data = front_bytes if side_int == 0 else rear_bytes
            ctypes.memmove(buf, data, len(data))
            size_ptr[0] = len(data)
            return 0

        # Mock panini_get_micr: copies MICR string into buffer
        def fake_get_micr(handle, buf, size_ptr):
            encoded = micr_str.encode("utf-8")
            ctypes.memmove(buf, encoded, len(encoded))
            size_ptr[0] = len(encoded)
            return 0

        mock_dll.panini_get_image.side_effect = fake_get_image
        mock_dll.panini_get_micr.side_effect  = fake_get_micr

        with patch("ctypes.WinDLL", return_value=mock_dll):
            driver = PaniniSDKDriver(dll_search_path=str(tmp_path))
            result = driver.scan()

        assert isinstance(result, PaniniScanResult)
        assert result.front_image == front_bytes
        assert result.rear_image  == rear_bytes
        assert result.micr        == micr_str
        mock_dll.panini_connect.assert_called_once()
        mock_dll.panini_start_scan.assert_called_once()
        mock_dll.panini_disconnect.assert_called_once()

    def test_scan_failure_raises_scanner_unavailable(self, tmp_path):
        from modules.cts.scanner.drivers.panini_sdk import PaniniSDKDriver
        from modules.cts.scanner.adapters import ScannerUnavailableError

        fake_dll_path = tmp_path / "panini64.dll"
        fake_dll_path.write_bytes(b"MZ")

        mock_dll = self._make_mock_dll()
        mock_dll.panini_start_scan.return_value = -1  # error code

        with patch("ctypes.WinDLL", return_value=mock_dll):
            driver = PaniniSDKDriver(dll_search_path=str(tmp_path))
            with pytest.raises(ScannerUnavailableError, match="Panini"):
                driver.scan()

    def test_scan_with_uv_calls_uv_image_function(self, tmp_path):
        from modules.cts.scanner.drivers.panini_sdk import PaniniSDKDriver

        fake_dll_path = tmp_path / "panini64.dll"
        fake_dll_path.write_bytes(b"MZ")

        mock_dll = self._make_mock_dll()
        uv_bytes = b'\xAB\xCD' * 50

        def fake_get_image(handle, side, buf, size_ptr):
            data = b'\xff\xd8\xff' + b'\x00' * 200
            ctypes.memmove(buf, data, len(data))
            size_ptr[0] = len(data)
            return 0  # side ignored — both front and rear return stub data

        def fake_get_uv(handle, buf, size_ptr):
            ctypes.memmove(buf, uv_bytes, len(uv_bytes))
            size_ptr[0] = len(uv_bytes)
            return 0

        def fake_get_micr(handle, buf, size_ptr):
            size_ptr[0] = 0
            return 0

        mock_dll.panini_get_image.side_effect = fake_get_image
        mock_dll.panini_get_uv_image.side_effect = fake_get_uv
        mock_dll.panini_get_micr.side_effect = fake_get_micr

        with patch("ctypes.WinDLL", return_value=mock_dll):
            driver = PaniniSDKDriver(dll_search_path=str(tmp_path))
            result = driver.scan(capture_uv=True)

        assert result.uv_image == uv_bytes
        mock_dll.panini_get_uv_image.assert_called_once()


# ── DCCAPIDriver (Digital Check USB / DCC API ctypes) ────────────────────────

class TestDCCAPIDriver:

    def _make_mock_dll(self):
        dll = MagicMock()
        dll.USD_OpenScanner.return_value   = 1    # handle = 1
        dll.USD_ScanItem.return_value      = 0    # 0 = SCAN_OK
        dll.USD_CloseScanner.return_value  = 0
        return dll

    def test_driver_loads_usd_dll_from_bin_folder(self, tmp_path):
        from modules.cts.scanner.drivers.dcc_api import DCCAPIDriver

        fake_dll = tmp_path / "usd.dll"
        fake_dll.write_bytes(b"MZ")

        with patch("ctypes.WinDLL", return_value=self._make_mock_dll()) as mock_load:
            driver = DCCAPIDriver(dll_search_path=str(tmp_path))
            mock_load.assert_called_once_with(str(fake_dll))

    def test_driver_raises_not_found_when_usd_dll_absent(self, tmp_path):
        from modules.cts.scanner.drivers.dcc_api import DCCAPIDriver
        from modules.cts.scanner.drivers import ScannerDriverNotFoundError

        with pytest.raises(ScannerDriverNotFoundError, match="usd.dll"):
            DCCAPIDriver(dll_search_path=str(tmp_path))

    def test_not_found_message_tells_user_where_to_place_dll(self, tmp_path):
        from modules.cts.scanner.drivers.dcc_api import DCCAPIDriver
        from modules.cts.scanner.drivers import ScannerDriverNotFoundError

        with pytest.raises(ScannerDriverNotFoundError) as exc_info:
            DCCAPIDriver(dll_search_path=str(tmp_path))

        assert "usd.dll" in str(exc_info.value)

    def test_scan_item_calls_open_scan_close(self, tmp_path):
        from modules.cts.scanner.drivers.dcc_api import DCCAPIDriver, DCCScanResult

        fake_dll = tmp_path / "usd.dll"
        fake_dll.write_bytes(b"MZ")

        mock_dll = self._make_mock_dll()

        front_bytes = b'\xff\xd8\xff' + b'\x00' * 600
        rear_bytes  = b'\xff\xd8\xff' + b'\x00' * 300
        uv_bytes    = b'\xAB\xCD' * 100
        micr_str    = "⑆987654321⑆ 200002⑈ 098700⑉"

        def fake_get_image(handle, image_type, buf, size_ptr):
            # ctypes passes c_int objects — extract .value for dict lookup
            img_type = image_type.value if hasattr(image_type, "value") else int(image_type)
            data = {0: front_bytes, 1: rear_bytes, 2: uv_bytes}.get(img_type, b"")
            ctypes.memmove(buf, data, len(data))
            size_ptr[0] = len(data)
            return 0

        def fake_get_micr(handle, buf, size_ptr):
            encoded = micr_str.encode("utf-8")
            ctypes.memmove(buf, encoded, len(encoded))
            size_ptr[0] = len(encoded)
            return 0

        mock_dll.USD_GetImageData.side_effect = fake_get_image
        mock_dll.USD_GetMICR.side_effect      = fake_get_micr

        with patch("ctypes.WinDLL", return_value=mock_dll):
            driver = DCCAPIDriver(dll_search_path=str(tmp_path))
            result = driver.scan_item(capture_uv=True)

        assert isinstance(result, DCCScanResult)
        assert result.front_image == front_bytes
        assert result.rear_image  == rear_bytes
        assert result.uv_image    == uv_bytes
        assert result.micr        == micr_str
        mock_dll.USD_OpenScanner.assert_called_once()
        mock_dll.USD_ScanItem.assert_called_once()
        mock_dll.USD_CloseScanner.assert_called_once()

    def test_scan_item_failure_code_raises_scanner_unavailable(self, tmp_path):
        from modules.cts.scanner.drivers.dcc_api import DCCAPIDriver
        from modules.cts.scanner.adapters import ScannerUnavailableError

        fake_dll = tmp_path / "usd.dll"
        fake_dll.write_bytes(b"MZ")

        mock_dll = self._make_mock_dll()
        mock_dll.USD_ScanItem.return_value = -1  # error

        with patch("ctypes.WinDLL", return_value=mock_dll):
            driver = DCCAPIDriver(dll_search_path=str(tmp_path))
            with pytest.raises(ScannerUnavailableError, match="USD_ScanItem"):
                driver.scan_item()

    def test_open_scanner_failure_raises_scanner_unavailable(self, tmp_path):
        from modules.cts.scanner.drivers.dcc_api import DCCAPIDriver
        from modules.cts.scanner.adapters import ScannerUnavailableError

        fake_dll = tmp_path / "usd.dll"
        fake_dll.write_bytes(b"MZ")

        mock_dll = self._make_mock_dll()
        mock_dll.USD_OpenScanner.return_value = -1  # failed to open

        with patch("ctypes.WinDLL", return_value=mock_dll):
            driver = DCCAPIDriver(dll_search_path=str(tmp_path))
            with pytest.raises(ScannerUnavailableError, match="USD_OpenScanner"):
                driver.scan_item()


# ── Canon adapter wired to Ranger client ──────────────────────────────────────

class TestCanonCR120UVAdapterWithRanger:

    def _make_adapter(self):
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

    @pytest.mark.asyncio
    async def test_scan_via_ranger_returns_scan_result(self):
        from modules.cts.scanner.drivers.ranger_transport import RangerScanResult
        from modules.cts.scanner.models import ScanResult

        adapter = self._make_adapter()

        fake_ranger_result = RangerScanResult(
            front_image=b'\xff\xd8\xff' + b'\x00' * 500,
            rear_image=b'\xff\xd8\xff'  + b'\x00' * 250,
            uv_image=b'\xAB\xCD' * 100,
            micr="⑆111222333⑆ 000001⑈ 012300⑉",
            dpi=200,
            imprinter_stamped=True,
            double_feed_detected=False,
        )

        with patch(
            "modules.cts.scanner.adapters.RangerTransportClient"
        ) as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__  = AsyncMock(return_value=None)
            mock_client.scan       = AsyncMock(return_value=fake_ranger_result)
            mock_cls.return_value  = mock_client

            result = await adapter.scan_via_ranger()

        assert isinstance(result, ScanResult)
        assert result.uv_image         == fake_ranger_result.uv_image
        assert result.micr_raw         == fake_ranger_result.micr
        assert result.imprinter_stamped is True
        assert result.oem.value        == "CANON"

    @pytest.mark.asyncio
    async def test_scan_via_ranger_unavailable_raises_scanner_unavailable(self):
        from modules.cts.scanner.adapters import ScannerUnavailableError

        adapter = self._make_adapter()

        with patch(
            "modules.cts.scanner.adapters.RangerTransportClient"
        ) as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(side_effect=ScannerUnavailableError("refused"))
            mock_client.__aexit__  = AsyncMock(return_value=None)
            mock_cls.return_value  = mock_client

            with pytest.raises(ScannerUnavailableError):
                await adapter.scan_via_ranger()


# ── Panini adapter wired to SDK driver ───────────────────────────────────────

class TestPaniniVisionXAdapterWithSDK:

    def _make_adapter(self, tmp_path):
        from modules.cts.scanner.adapters import BranchScannerConfig, PaniniVisionXAdapter
        from modules.cts.scanner.models import ScannerOEM, IntegrationMode
        cfg = BranchScannerConfig(
            bank_id="saraswat-coop",
            branch_id="branch-bandra-001",
            scanner_oem=ScannerOEM.PANINI,
            scanner_model="Vision X",
            integration_mode=IntegrationMode.DROP_FOLDER,
            drop_folder_path=str(tmp_path),
        )
        return PaniniVisionXAdapter(cfg=cfg, operator_id="op1")

    def test_scan_via_sdk_returns_scan_result(self, tmp_path):
        from modules.cts.scanner.drivers.panini_sdk import PaniniScanResult
        from modules.cts.scanner.models import ScanResult

        adapter = self._make_adapter(tmp_path)

        fake_sdk_result = PaniniScanResult(
            front_image=b'\xff\xd8\xff' + b'\x00' * 400,
            rear_image=b'\xff\xd8\xff'  + b'\x00' * 200,
            uv_image=b'\xAB\xCD' * 80,
            micr="⑆111222333⑆ 000001⑈ 012300⑉",
        )

        with patch(
            "modules.cts.scanner.adapters.PaniniSDKDriver"
        ) as mock_cls:
            mock_driver = MagicMock()
            mock_driver.scan.return_value = fake_sdk_result
            mock_cls.return_value = mock_driver

            result = adapter.scan_via_sdk(dll_search_path=str(tmp_path))

        assert isinstance(result, ScanResult)
        assert result.uv_image == fake_sdk_result.uv_image
        assert result.micr_raw == fake_sdk_result.micr
        assert result.oem.value == "PANINI"


# ── Digital Check adapter wired to DCC API (USB mode) ────────────────────────

class TestDigitalCheckTS240UVAdapterWithDCCAPI:

    def _make_adapter(self):
        from modules.cts.scanner.adapters import BranchScannerConfig, DigitalCheckTS240UVAdapter
        from modules.cts.scanner.models import ScannerOEM, IntegrationMode
        cfg = BranchScannerConfig(
            bank_id="saraswat-coop",
            branch_id="branch-parel-001",
            scanner_oem=ScannerOEM.DIGITAL_CHECK,
            scanner_model="TS240-UV",
            integration_mode=IntegrationMode.DCC_API,
        )
        return DigitalCheckTS240UVAdapter(cfg=cfg, operator_id="op1")

    def test_scan_via_dcc_api_returns_scan_result(self, tmp_path):
        from modules.cts.scanner.drivers.dcc_api import DCCScanResult
        from modules.cts.scanner.models import ScanResult

        adapter = self._make_adapter()

        fake_dcc_result = DCCScanResult(
            front_image=b'\xff\xd8\xff' + b'\x00' * 600,
            rear_image=b'\xff\xd8\xff'  + b'\x00' * 300,
            uv_image=b'\xAB\xCD' * 120,
            micr="⑆987654321⑆ 200002⑈ 098700⑉",
        )

        with patch(
            "modules.cts.scanner.adapters.DCCAPIDriver"
        ) as mock_cls:
            mock_driver = MagicMock()
            mock_driver.scan_item.return_value = fake_dcc_result
            mock_cls.return_value = mock_driver

            result = adapter.scan_via_dcc_api(dll_search_path=str(tmp_path))

        assert isinstance(result, ScanResult)
        assert result.uv_image == fake_dcc_result.uv_image
        assert result.micr_raw == fake_dcc_result.micr
        assert result.oem.value == "DIGITAL_CHECK"
