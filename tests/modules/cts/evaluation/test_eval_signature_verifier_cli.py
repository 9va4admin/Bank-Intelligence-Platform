"""The command-line tool end to end, with a toy embedder whose 'image' files hold their own vector as text."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


class VectorFromText:
    def embed(self, image_bytes, bank_id=None):
        return [float(x) for x in image_bytes.decode().split(",")]


def _manifest(tmp_path):
    rows = ["path,writer_id,label"]
    n = 0
    for w, centre in (("A", (1, 0, 0)), ("B", (0, 1, 0)), ("C", (0, 0, 1))):
        for i in range(5):
            v = [c + 0.01 * i for c in centre]
            f = tmp_path / f"{w}{i}.txt"
            f.write_text(",".join(str(x) for x in v))
            rows.append(f"{f.name},{w},GENUINE")
            n += 1
    m = tmp_path / "m.csv"
    m.write_text("\n".join(rows) + "\n")
    return m


def test_runs_and_writes_a_json_report(tmp_path):
    out = tmp_path / "r.json"
    spec = "tests.modules.cts.evaluation.test_eval_signature_verifier_cli:VectorFromText"
    proc = subprocess.run(
        [sys.executable, "scripts/eval_signature_verifier.py", "--manifest", str(_manifest(tmp_path)), "--embedder", spec,
         "--k-enrol", "2", "--threshold", "0.9", "--max-far", "0.05", "--out", str(out)],
        cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    report = json.loads(out.read_text())[spec]
    rnd = report["by_kind"]["RANDOM_FORGERY"]
    assert rnd["far"]["k"] == 0 and rnd["frr"]["k"] == 0 and report["writers_evaluated"] == 3
    assert "NOT DEMONSTRABLE" in rnd["verdict"]
    assert "FAR" in proc.stdout


def test_a_bad_manifest_is_a_clear_error_not_a_traceback(tmp_path):
    bad = tmp_path / "m.csv"
    bad.write_text("path,writer_id,label\nmissing.png,W1,GENUINE\n")
    proc = subprocess.run(
        [sys.executable, "scripts/eval_signature_verifier.py", "--manifest", str(bad), "--embedder",
         "tests.modules.cts.evaluation.test_eval_signature_verifier_cli:VectorFromText", "--threshold", "0.9"],
        cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 2 and "line 2" in proc.stderr and "Traceback" not in proc.stderr
