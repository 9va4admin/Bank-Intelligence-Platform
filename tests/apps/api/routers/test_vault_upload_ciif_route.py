"""POST /v1/cts/vault/upload/pps/ciif — load an NPCI CIIF file into the PPS vault."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.auth.rbac import BankType, PermissionLevel, Role, UserContext

HEADER = ("PayeeAccountNumber,SerialNumber,IssueDate,Amount,Transactioncode,DraweeBankName,"
          "DraweeBranchRoutingNumber,PayeeName,San,Optional1,Optional2,Optional3")


def _app(role=Role.OPS_MANAGER):
    from apps.api.routers.vault_upload import router_v1, get_current_user_context
    app = FastAPI()
    app.include_router(router_v1)
    app.dependency_overrides[get_current_user_context] = lambda: UserContext(
        user_id="u1", role=role, bank_id="kbl", bank_type=BankType.SB, permission_level=PermissionLevel.EDIT)
    pps = MagicMock()
    pps.store_pps = AsyncMock()
    app.state.pps_vault_factory = lambda bank: pps
    return app, pps


def _row():
    from datetime import date, timedelta
    d = (date.today() - timedelta(days=2)).strftime("%d%m%Y")
    return f"{HEADER}\n50011,011231,{d},390587,10,HDFC Bank,110240001,Xyz abc,123456,,,"


def _post(client, body):
    return client.post("/v1/cts/vault/upload/pps/ciif", files={"file": ("c.csv", body.encode(), "text/csv")})


def test_upload_loads_the_record_when_the_unit_is_configured():
    app, pps = _app()
    with patch("apps.api.routers.vault_upload.config_service") as cs:
        cs.get_platform.return_value = "RUPEES"
        r = _post(TestClient(app), _row())
    assert r.status_code == 200 and r.json()["rows_processed"] == 1
    assert pps.store_pps.call_args.kwargs["amount_paise"] == 39058700


def test_unit_not_configured_is_422_not_a_guess():
    from shared.config.config_service import ConfigKeyNotFoundError
    app, pps = _app()
    with patch("apps.api.routers.vault_upload.config_service") as cs:
        cs.get_platform.side_effect = ConfigKeyNotFoundError("unset")
        r = _post(TestClient(app), _row())
    assert r.status_code == 422 and r.json()["detail"]["error_code"] == "CIIF_AMOUNT_UNIT_NOT_SET"
    pps.store_pps.assert_not_called()


def test_wrong_role_is_403():
    app, _ = _app(role=Role.OPS_REVIEWER)
    r = _post(TestClient(app), _row())
    assert r.status_code == 403


def test_bad_header_is_422_with_error_code():
    app, _ = _app()
    with patch("apps.api.routers.vault_upload.config_service") as cs:
        cs.get_platform.return_value = "RUPEES"
        r = _post(TestClient(app), "a,b\n1,2")
    assert r.status_code == 422 and r.json()["detail"]["error_code"] == "VAULT_UPLOAD_INVALID"
