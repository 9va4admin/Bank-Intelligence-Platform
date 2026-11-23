"""The bake-off runner: it refuses any model endpoint outside the bank's own network, asks every model the same question, reads the answer safely, and never lets one failed call stop the run.
No real model or network: the HTTP side is a stand-in."""
import asyncio
import base64
import json

import httpx
import pytest

from modules.cts.evaluation.bakeoff_runner import (
    EndpointNotAllowed, ManifestError, OpenAICompatReader, build_prompt, ensure_on_prem_endpoint, load_manifest, parse_model_value, resolve_settings, run_model,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- the endpoint must be inside the bank

@pytest.mark.parametrize("url", ["http://localhost:8000/v1", "http://127.0.0.1:8000/v1", "http://10.1.2.3:8000/v1", "http://192.168.1.5/v1", "http://172.20.0.4:9000/v1",
                                 "http://gpu01.internal:8000/v1", "http://gpu01.local/v1", "http://[::1]:8000/v1", "http://169.254.10.10/v1"])
def test_local_and_private_network_endpoints_are_allowed(url):
    assert ensure_on_prem_endpoint(url) == url.rstrip("/")


@pytest.mark.parametrize("url", ["https://api.openai.com/v1", "http://8.8.8.8/v1", "http://gpu.example.com/v1", "http://172.32.0.1/v1", "http://localhost.evil.com/v1",
                                 "http://10.0.0.1.evil.com/v1", "ftp://localhost/v1", "localhost:8000", ""])
def test_anything_outside_the_bank_network_is_refused_without_resolving_a_name(url):
    with pytest.raises(EndpointNotAllowed):
        ensure_on_prem_endpoint(url)


def test_a_named_host_can_be_allowed_explicitly_and_only_that_host():
    assert ensure_on_prem_endpoint("http://gpu.bank.example:8000/v1", allowed_hosts=["gpu.bank.example"]) == "http://gpu.bank.example:8000/v1"
    with pytest.raises(EndpointNotAllowed):
        ensure_on_prem_endpoint("http://other.bank.example/v1", allowed_hosts=["gpu.bank.example"])


# ---------------------------------------------------------------- the same question for every model

def test_each_field_has_three_prompt_wordings_that_differ_and_ask_for_the_same_json_answer():
    for field in ("payee", "amount_words", "amount_figures", "date", "micr_band"):
        prompts = [build_prompt(field, v) for v in (1, 2, 3)]
        assert len(set(prompts)) == 3
        assert all('"value"' in p and '"confidence"' in p for p in prompts)
    assert "do not guess" in build_prompt("payee", 1).lower() or "do not guess" in build_prompt("payee", 2).lower() or "do not guess" in build_prompt("payee", 3).lower()
    with pytest.raises(ValueError):
        build_prompt("signature", 1)
    with pytest.raises(ValueError):
        build_prompt("payee", 4)


# ---------------------------------------------------------------- reading the answer safely

def test_the_answer_is_read_from_json_with_or_without_fences_and_chatter_and_anything_else_is_no_answer():
    assert parse_model_value('{"value": "Raju Pandit", "confidence": 0.9}') == "Raju Pandit"
    assert parse_model_value('```json\n{"value": "ರಾಜು", "confidence": 0.5}\n```') == "ರಾಜು"
    assert parse_model_value('Sure! Here it is: {"value": "30000", "confidence": 1}. Hope that helps') == "30000"
    assert parse_model_value('{"payee": {"value": "Raju"}}') == "Raju"
    assert parse_model_value('{"value": null, "confidence": 0}') is None
    assert parse_model_value('{"value": "  "}') is None
    assert parse_model_value("I cannot read this image") is None
    assert parse_model_value("{broken json") is None
    assert parse_model_value("") is None and parse_model_value(None) is None
    assert parse_model_value('{"value": 30000}') == "30000"


# ---------------------------------------------------------------- the reader

def reader_with(handler, **kw):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenAICompatReader("http://localhost:8000/v1", api_model="dots-ocr", timeout=30.0, max_tokens=256, client=client, **kw)


def test_the_request_is_a_deterministic_chat_call_with_the_crop_as_a_data_url_and_the_answer_is_timed():
    seen = {}

    def handler(request):
        seen["url"], seen["body"] = str(request.url), json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"value": "Raju Pandit", "confidence": 0.8}'}}]})
    res = run(reader_with(handler).read(PNG, "payee", 1))
    assert seen["url"] == "http://localhost:8000/v1/chat/completions"
    body = seen["body"]
    assert body["model"] == "dots-ocr" and body["temperature"] == 0 and body["max_tokens"] == 256
    parts = body["messages"][0]["content"]
    image = next(p for p in parts if p["type"] == "image_url")["image_url"]["url"]
    assert image.startswith("data:image/png;base64,") and base64.b64decode(image.split(",", 1)[1]) == PNG
    assert any(p["type"] == "text" and "payee" in p["text"].lower() for p in parts)
    assert res.text == "Raju Pandit" and res.failed is False and res.latency_ms is not None and res.latency_ms >= 0


def test_a_server_error_a_timeout_and_an_unreadable_answer_never_raise_and_are_marked_correctly():
    server_error = run(reader_with(lambda r: httpx.Response(500, text="boom")).read(PNG, "payee", 1))
    assert server_error.failed is True and server_error.text is None

    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)
    assert run(reader_with(timeout).read(PNG, "payee", 1)).failed is True

    chatter = run(reader_with(lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "no idea"}}]})).read(PNG, "payee", 1))
    assert chatter.failed is False and chatter.text is None                         # the call worked, the model gave no usable value: withheld, not a failure

    malformed = run(reader_with(lambda r: httpx.Response(200, json={"unexpected": True})).read(PNG, "payee", 1))
    assert malformed.failed is True


# ---------------------------------------------------------------- the manifest and the run

def write_manifest(tmp_path, rows):
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(rows), encoding="utf-8")
    return p


ROW = {"item_id": "i1", "field": "payee", "crop": "i1_payee.png", "text": "Raju Pandit", "script": "LATIN", "handwritten": True, "quality": "good"}


def test_the_manifest_gives_truth_and_crop_paths_and_rejects_missing_or_duplicate_entries(tmp_path):
    m = write_manifest(tmp_path, [ROW, {**ROW, "item_id": "i2", "scoreable": False}])
    truths, crops = load_manifest(m)
    assert [t.item_id for t in truths] == ["i1", "i2"] and truths[0].scoreable is True and truths[1].scoreable is False
    assert crops[("i1", "payee")] == "i1_payee.png"
    with pytest.raises(ManifestError):
        load_manifest(write_manifest(tmp_path, [ROW, ROW]))
    with pytest.raises(ManifestError):
        load_manifest(write_manifest(tmp_path, [{k: v for k, v in ROW.items() if k != "script"}]))
    with pytest.raises(ManifestError):
        load_manifest(write_manifest(tmp_path, {"not": "a list"}))


def test_a_run_asks_every_item_and_a_missing_crop_or_a_failing_call_is_recorded_not_fatal(tmp_path):
    (tmp_path / "i1_payee.png").write_bytes(PNG)
    (tmp_path / "i3_payee.png").write_bytes(PNG)
    rows = [ROW, {**ROW, "item_id": "i2", "crop": "missing.png"}, {**ROW, "item_id": "i3", "crop": "i3_payee.png"}]
    truths, crops = load_manifest(write_manifest(tmp_path, rows))
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        if len(calls) == 2:
            return httpx.Response(503, text="busy")
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"value": "Raju Pandit", "confidence": 0.7}'}}]})
    readings = run(run_model(truths, crops, tmp_path, reader_with(handler), model_name="dots", variant=1))
    by = {r.item_id: r for r in readings}
    assert len(readings) == 3 and all(r.model == "dots" for r in readings)
    assert by["i1"].text == "Raju Pandit" and by["i1"].failed is False
    assert by["i2"].failed is True and by["i2"].text is None                         # no crop file: recorded, and the model was not asked
    assert by["i3"].failed is True                                                    # the second call (for i3) failed with 503
    assert len(calls) == 2


# ---------------------------------------------------------------- settings come from the bank's settings, not from code

def test_settings_come_from_the_getter_and_a_flag_wins_and_a_missing_setting_is_a_clear_error():
    values = {"cts.bakeoff_length_guard_multiple": 3, "cts.bakeoff_length_guard_min_chars": 20, "cts.payee_reread_min_similarity": 0.99, "cts.bakeoff_bootstrap_resamples": 2000, "cts.bakeoff_seed": 7,
              "cts.bakeoff_wrong_shown_target": 0.01, "cts.bakeoff_request_timeout_seconds": 120, "cts.bakeoff_max_output_tokens": 256, "cts.bakeoff_alpha": 0.05}

    async def getter(key):
        if key not in values:
            raise KeyError(key)
        return values[key]
    s = run(resolve_settings(getter, {}))
    assert (s.guard_multiple, s.guard_min_chars, s.min_similarity, s.resamples, s.seed, s.wrong_shown_target, s.timeout, s.max_tokens, s.alpha) == (3, 20, 0.99, 2000, 7, 0.01, 120.0, 256, 0.05)
    assert run(resolve_settings(getter, {"min_similarity": 0.9})).min_similarity == 0.9
    del values["cts.bakeoff_seed"]
    with pytest.raises(KeyError):
        run(resolve_settings(getter, {}))
