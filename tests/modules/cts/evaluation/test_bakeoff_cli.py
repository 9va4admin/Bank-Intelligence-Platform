"""The bake-off command-line tool end to end: `run` against a real local HTTP stand-in for a model server, the refusal of any endpoint outside the bank, and `score` writing the report."""
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = str(ROOT / "scripts" / "bakeoff_ocr.py")
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
NAMES = ["Raju Pandit", "Gopal Rao", "Sumati Shetty", "Anil Kumar", "Meena Iyer", "Suresh Babu", "Latha Devi", "Ravi Teja", "Kiran Reddy", "Divya Nair", "Mohan Das", "Asha Rani"]


def cli(*args):
    return subprocess.run([sys.executable, SCRIPT, *args], cwd=ROOT, capture_output=True, text=True, timeout=120)


def write(path, data):
    Path(path).write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def manifest(tmp_path, names=NAMES):
    rows = [{"item_id": f"i{k}", "field": "payee", "crop": f"i{k}.png", "text": n, "script": "LATIN", "handwritten": True, "quality": "good"} for k, n in enumerate(names)]
    for r in rows:
        (tmp_path / r["crop"]).write_bytes(PNG)
    return write(tmp_path / "manifest.json", rows)


def readings(model, texts, failed_at=()):
    return {"model": model, "readings": [{"item_id": f"i{k}", "field": "payee", "model": model, "text": t, "failed": k in failed_at, "latency_ms": 10.0 + k} for k, t in enumerate(texts)]}


class Server(BaseHTTPRequestHandler):
    def do_POST(self):                                                    # a stand-in model server: always answers the same name
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        body = json.dumps({"choices": [{"message": {"content": '{"value": "Raju Pandit", "confidence": 0.9}'}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def serve():
    server = HTTPServer(("127.0.0.1", 0), Server)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_run_asks_a_local_model_server_for_every_crop_and_writes_the_readings(tmp_path):
    server = serve()
    try:
        m = manifest(tmp_path, NAMES[:2])
        out = tmp_path / "readings_dots.json"
        done = cli("run", "--manifest", m, "--images", str(tmp_path), "--model-name", "dots", "--endpoint", f"http://127.0.0.1:{server.server_port}/v1", "--api-model", "dots-ocr",
                   "--variant", "1", "--out", str(out))
    finally:
        server.shutdown()
    assert done.returncode == 0, done.stdout + done.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["model"] == "dots" and data["variant"] == 1 and data["api_model"] == "dots-ocr" and len(data["readings"]) == 2
    assert [r["text"] for r in data["readings"]] == ["Raju Pandit", "Raju Pandit"] and all(r["failed"] is False and r["latency_ms"] >= 0 for r in data["readings"])
    assert "127.0.0.1" in data["endpoint_host"]
    assert set(data["prompts"]) == {"payee"} and len(data["prompts"]["payee"]) == 16            # a fingerprint of the exact wording used


def test_run_refuses_an_endpoint_outside_the_bank_before_it_sends_anything(tmp_path):
    m = manifest(tmp_path, NAMES[:1])
    done = cli("run", "--manifest", m, "--images", str(tmp_path), "--model-name", "cloud", "--endpoint", "https://api.openai.com/v1", "--api-model", "gpt", "--variant", "1", "--out", str(tmp_path / "o.json"))
    assert done.returncode == 2 and "not a local or private address" in done.stderr
    assert not (tmp_path / "o.json").exists()


def test_run_reports_a_missing_manifest_or_variant_plainly(tmp_path):
    done = cli("run", "--manifest", str(tmp_path / "nope.json"), "--images", str(tmp_path), "--model-name", "x", "--endpoint", "http://127.0.0.1:9/v1", "--api-model", "m", "--variant", "1", "--out", str(tmp_path / "o.json"))
    assert done.returncode == 2 and done.stderr.strip()
    m = manifest(tmp_path, NAMES[:1])
    done = cli("run", "--manifest", m, "--images", str(tmp_path), "--model-name", "x", "--endpoint", "http://127.0.0.1:9/v1", "--api-model", "m", "--variant", "9", "--out", str(tmp_path / "o.json"))
    assert done.returncode == 2 and "variant" in done.stderr.lower()


def build_score_inputs(tmp_path):
    m = manifest(tmp_path)
    wrong = lambda n: n.replace("a", "o", 1)                                         # noqa: E731
    current = [n if k < 6 else (wrong(n) if k < 9 else None) for k, n in enumerate(NAMES)]
    dots = [n if k < 10 else (wrong(n) if k == 10 else None) for k, n in enumerate(NAMES)]
    qwen = [n if k < 9 else (wrong(n) if k < 11 else None) for k, n in enumerate(NAMES)]
    files = [write(tmp_path / f"r_{name}.json", readings(name, texts)) for name, texts in (("current", current), ("dotsA", dots), ("qwenB", qwen))]
    families = write(tmp_path / "families.json", {"current": "current", "dotsA": "dots", "qwenB": "qwen"})
    return m, files, families


def test_score_writes_a_report_with_wrong_shown_intervals_paired_comparisons_and_the_pairs(tmp_path):
    m, files, families = build_score_inputs(tmp_path)
    md, js = tmp_path / "report.md", tmp_path / "report.json"
    done = cli("score", "--manifest", m, "--readings", *files, "--families", families, "--baseline", "current", "--out-md", str(md), "--out-json", str(js))
    assert done.returncode == 0, done.stdout + done.stderr
    text = md.read_text(encoding="utf-8")
    assert text.startswith("# OCR bake-off")
    for needle in ("payee", "current", "dotsA", "qwenB", "Wrong shown", "Withheld", "McNemar", "NOT DEMONSTRABLE", "dotsA -> qwenB", "qwenB -> dotsA", "p50", "by-eye"):
        assert needle in text, needle
    assert "dotsA -> dotsA" not in text and "current -> current" not in text                        # same-family pairs are never proposed
    data = json.loads(js.read_text(encoding="utf-8"))
    assert {"settings", "scores", "paired", "pairs"} <= set(data)
    dots_all = next(r for r in data["scores"] if r["model"] == "dotsA" and r["field"] == "payee" and r["stratum"] == "ALL")
    assert (dots_all["n"], dots_all["exact"], dots_all["wrong_shown"], dots_all["withheld"]) == (12, 10, 1, 1)
    paired = next(p for p in data["paired"] if p["model"] == "dotsA" and p["field"] == "payee")
    assert paired["a_only"] > paired["b_only"] and 0 <= paired["p_value"] <= 1


def test_score_stops_with_a_clear_message_for_a_baseline_or_family_that_does_not_exist(tmp_path):
    m, files, families = build_score_inputs(tmp_path)
    done = cli("score", "--manifest", m, "--readings", *files, "--families", families, "--baseline", "nobody", "--out-md", str(tmp_path / "r.md"), "--out-json", str(tmp_path / "r.json"))
    assert done.returncode == 2 and "nobody" in done.stderr
    bad = write(tmp_path / "bad_families.json", {"current": "current"})
    done = cli("score", "--manifest", m, "--readings", *files, "--families", bad, "--baseline", "current", "--out-md", str(tmp_path / "r.md"), "--out-json", str(tmp_path / "r.json"))
    assert done.returncode == 2 and "family" in done.stderr.lower()
