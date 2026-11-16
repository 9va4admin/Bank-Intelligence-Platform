"""The model stand-in can be told what a specific image 'reads' as, so a test cheque reads as the cheque it is declared to be."""
import base64
import hashlib

from fastapi.testclient import TestClient

from tests.integration.stubs import ocr_server


def _post(client, raw: bytes):
    url = "data:image/jpeg;base64," + base64.b64encode(raw).decode()
    body = {"model": "m", "messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": url}}]}]}
    import json
    return json.loads(client.post("/v1/chat/completions", json=body).json()["choices"][0]["message"]["content"])


def test_unregistered_image_reads_as_the_default_cheque():
    c = TestClient(ocr_server.app)
    assert _post(c, b"unregistered-bytes")["micr_line"]["value"] == "500025033290062"


def test_registered_image_reads_as_declared_and_others_are_unaffected():
    c = TestClient(ocr_server.app)
    raw = b"cheque-one-bytes"
    r = c.post("/register", json={"sha256": hashlib.sha256(raw).hexdigest(),
                                  "fields": {"micr_line": {"value": "600001033290062", "confidence": 0.97}}})
    assert r.status_code == 200
    got = _post(c, raw)
    assert got["micr_line"]["value"] == "600001033290062"
    assert got["amount_figures"]["value"] == "95000"            # fields not overridden keep the default reading
    assert _post(c, b"another")["micr_line"]["value"] == "500025033290062"


def test_signature_detection_prompt_gets_a_signature_answer_not_an_ocr_payload():
    """detect_signatures asks the vision model for signature_count/bboxes; the stand-in must answer that shape."""
    import json
    c = TestClient(ocr_server.app)
    body = {"model": "m", "messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        {"type": "text", "text": 'Return JSON with exactly these fields: {"signature_count": <integer>, "signature_bboxes": []}'}]}]}
    got = json.loads(c.post("/v1/chat/completions", json=body).json()["choices"][0]["message"]["content"])
    assert got["signature_count"] == 1 and len(got["signature_bboxes"][0]) == 4 and got["signature_fraud_flags"] == []


def test_security_features_prompt_gets_all_four_features_present():
    import json
    c = TestClient(ocr_server.app)
    body = {"model": "m", "messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAAA"}},
        {"type": "text", "text": "report whether each security feature is present: 1. void_pantograph 2. rupee_symbol"}]}]}
    got = json.loads(c.post("/v1/chat/completions", json=body).json()["choices"][0]["message"]["content"])
    assert {k: v["present"] for k, v in got.items()} == {"void_pantograph": True, "rupee_symbol": True, "micro_lettering": True, "printer_name_cts2010": True}
