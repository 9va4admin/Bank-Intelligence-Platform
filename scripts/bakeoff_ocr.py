"""OCR / vision-language model bake-off tool (docs/research/ocr-bakeoff-plan.md).

  run    ask ONE model, served on the bank's own network, to read every crop in a manifest; writes a readings file.
  score  read the manifest (truth) and the readings of several models; write a report (Markdown and JSON).

    python scripts/bakeoff_ocr.py run --manifest m.json --images crops/ --model-name dots --endpoint http://gpu01.internal:8000/v1 \\
        --api-model rednote-hilab/dots.ocr --variant 1 --out readings_dots_v1.json
    python scripts/bakeoff_ocr.py score --manifest m.json --readings readings_*.json --families families.json --baseline current \\
        --out-md report.md --out-json report.json

The manifest is a JSON list of {item_id, field, crop, text, script, handwritten, quality, [scoreable]}; the crops and the truth are real customer data: keep them
in a git-ignored folder, never commit them. Thresholds come from the shipped settings (cts.bakeoff_*), and any can be overridden with a flag.
Exit codes: 0 done, 2 a problem with the inputs or a refused endpoint (the message is on stderr).
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import hashlib
import json
import os
import statistics
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from modules.cts.evaluation.bakeoff_runner import (  # noqa: E402
    EndpointNotAllowed, ManifestError, OpenAICompatReader, build_prompt, load_manifest, resolve_settings, run_model,
)
from modules.cts.evaluation.ocr_bakeoff import (  # noqa: E402
    Reading, classify, cross_family_pairs, mcnemar, pair_analysis, paired_bootstrap_diff, score,
)
from modules.cts.evaluation.stats import verdict, wilson_interval  # noqa: E402
from shared.config.config_service import _LAYER3_DEFAULTS  # noqa: E402

DIMENSION_NAMES = {"script": "Script", "handwritten": "Writing", "quality": "Scan quality"}
OVERRIDE_FLAGS = ("guard_multiple", "guard_min_chars", "min_similarity", "resamples", "seed", "wrong_shown_target", "timeout", "max_tokens", "alpha")


class UsageError(Exception):
    pass


def fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 2


async def _settings(args):
    async def getter(key):                                  # an offline tool: the shipped defaults; a flag overrides any of them
        return _LAYER3_DEFAULTS[key]
    return await resolve_settings(getter, {name: getattr(args, name, None) for name in OVERRIDE_FLAGS})


# ------------------------------------------------------------------------------------------ run

async def cmd_run(args) -> int:
    settings = await _settings(args)
    try:
        build_prompt("payee", args.variant)                 # refuses a variant that does not exist before anything is sent
        truths, crops = load_manifest(args.manifest)
        reader = OpenAICompatReader(args.endpoint, api_model=args.api_model, timeout=settings.timeout, max_tokens=settings.max_tokens, allowed_hosts=args.allow_host or [])
    except (EndpointNotAllowed, ManifestError, ValueError, OSError) as exc:
        return fail(str(exc))
    try:
        readings = await run_model(truths, crops, args.images, reader, model_name=args.model_name, variant=args.variant)
    finally:
        await reader.aclose()
    prompts = {f: hashlib.sha256(build_prompt(f, args.variant).encode("utf-8")).hexdigest()[:16] for f in sorted({t.field for t in truths})}     # which wording was used, so a result can be reproduced
    payload = {"model": args.model_name, "variant": args.variant, "api_model": args.api_model, "endpoint_host": urlparse(args.endpoint).netloc, "count": len(readings), "prompts": prompts,
               "readings": [{"item_id": r.item_id, "field": r.field, "model": r.model, "text": r.text, "failed": r.failed, "latency_ms": r.latency_ms} for r in readings]}
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    failed = sum(r.failed for r in readings)
    print(f"{args.model_name}: {len(readings)} crops read, {failed} failed, wrote {args.out}")
    return 0


# ------------------------------------------------------------------------------------------ score

def _percentile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


def _load_readings(paths):
    readings, models = [], []
    for p in paths:
        data = json.loads(Path(p).read_text(encoding="utf-8"))
        name = data["model"]
        if name in models:
            raise UsageError(f"two readings files are for the model {name}")
        models.append(name)
        for r in data["readings"]:
            readings.append(Reading(r["item_id"], r["field"], r.get("model", name), r.get("text"), failed=bool(r.get("failed")), latency_ms=r.get("latency_ms")))
    return readings, models


def _pct(x):
    return f"{x * 100:.1f}%"


def _ci(k, n):
    lo, hi = wilson_interval(k, n)
    return f"{k}/{n} = {_pct(k / n) if n else '-'} ({_pct(lo)} - {_pct(hi)})"


def _score_table(rows, latencies, target):
    out = ["| Model | n | Exact (95% CI) | Wrong shown (95% CI) | Withheld | Runaway output | Wrong script | Mean CER | Latency p50 / p95 ms | Wrong shown vs target |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lat = latencies.get(r.model, [])
        p50, p95 = _percentile(lat, 0.5), _percentile(lat, 0.95)
        out.append(f"| {r.model} | {r.n} | {_ci(r.exact, r.n)} | {_ci(r.wrong_shown, r.n)} | {r.withheld} | {r.guard_tripped} | {r.script_wrong} | {r.mean_cer:.3f} | "
                   f"{'-' if p50 is None else f'{p50:.0f} / {p95:.0f}'} | {verdict(r.wrong_shown, r.n, target, higher_is_better=False)} |")
    return out


async def cmd_score(args) -> int:
    settings = await _settings(args)
    try:
        truths, _ = load_manifest(args.manifest)
        readings, models = _load_readings(args.readings)
        families = json.loads(Path(args.families).read_text(encoding="utf-8"))
    except (ManifestError, UsageError, OSError, ValueError, KeyError) as exc:
        return fail(str(exc))
    if args.baseline not in models:
        return fail(f"the baseline {args.baseline} has no readings file (models given: {', '.join(models)})")
    missing = [m for m in models if m not in families]
    if missing:
        return fail(f"no family given for: {', '.join(missing)}")
    guard = dict(guard_multiple=settings.guard_multiple, guard_min_chars=settings.guard_min_chars)
    by = tuple(args.by)
    rows = score(truths, readings, models=models, by=by, **guard)
    latencies = {m: [r.latency_ms for r in readings if r.model == m and not r.failed and r.latency_ms is not None] for m in models}
    fields = sorted({t.field for t in truths if t.scoreable})
    index = {(r.model, r.item_id, r.field): r for r in readings}

    lines = ["# OCR bake-off report", "",
             f"Generated {datetime.date.today()} by `scripts/bakeoff_ocr.py` from {len({t.item_id for t in truths if t.scoreable})} scoreable items, {len(models)} models: {', '.join(models)}.", "",
             "**Ground truth is by-eye reading and can itself be wrong.** With a small number of items this report can rank models and show large differences; it cannot prove a target "
             "(showing an error rate below 1% needs 299 error-free samples). A verdict of NOT DEMONSTRABLE means exactly that.", "",
             f"Settings: runaway-output guard {settings.guard_multiple}x the expected length (minimum {settings.guard_min_chars} characters); two readers agree at similarity "
             f">= {settings.min_similarity}; wrong-value-shown target {_pct(settings.wrong_shown_target)}; significance level {settings.alpha}; bootstrap {settings.resamples} resamples, seed {settings.seed}.", ""]
    for field in fields:
        lines += [f"## Field: {field}", ""]
        for dimension, stratum in [("all", "ALL")] + sorted({(r.dimension, r.stratum) for r in rows if r.field == field and r.dimension != "all"}):
            subset = [r for r in rows if r.field == field and r.dimension == dimension and r.stratum == stratum]
            if not subset:
                continue
            title = "All items" if dimension == "all" else f"{DIMENSION_NAMES[dimension]}: {stratum.title() if dimension != 'script' else stratum}"
            lines += [f"### {title}", "", *_score_table(subset, latencies if dimension == "all" else {}, settings.wrong_shown_target), ""]

    lines += [f"## Paired comparison against the baseline `{args.baseline}`", "",
              "Same items, so the comparison is paired: McNemar's exact test on the items where exactly one model is right, and a bootstrap interval on the difference in the "
              "wrong-value-shown rate (model minus baseline; negative is better).", "",
              "| Field | Model | Right only for model | Right only for baseline | McNemar p | Wrong-shown difference (95% CI) | Reading |", "|---|---|---|---|---|---|---|"]
    paired_json = []
    for field in fields:
        items = [t for t in truths if t.scoreable and t.field == field]
        outcomes = {m: {t.item_id: classify(t, index.get((m, t.item_id, field)), **guard) for t in items} for m in models}
        for m in models:
            if m == args.baseline:
                continue
            ok_m = {i: c.outcome == "EXACT" for i, c in outcomes[m].items()}
            ok_b = {i: c.outcome == "EXACT" for i, c in outcomes[args.baseline].items()}
            mc = mcnemar(ok_m, ok_b)
            order = sorted(outcomes[m])
            diff = paired_bootstrap_diff([int(outcomes[m][i].outcome == "WRONG_SHOWN") for i in order], [int(outcomes[args.baseline][i].outcome == "WRONG_SHOWN") for i in order],
                                         resamples=settings.resamples, seed=settings.seed)
            reading = ("better" if mc.a_only > mc.b_only else "worse") if mc.p_value < settings.alpha else "not distinguishable"
            lines.append(f"| {field} | {m} | {mc.a_only} | {mc.b_only} | {mc.p_value:.3f} | {diff.diff:+.3f} ({diff.lo:+.3f} to {diff.hi:+.3f}) | {reading} |")
            paired_json.append({"field": field, "model": m, "baseline": args.baseline, "a_only": mc.a_only, "b_only": mc.b_only, "pairs": mc.pairs, "p_value": mc.p_value,
                                "wrong_shown_diff": diff.diff, "lo": diff.lo, "hi": diff.hi, "reading": reading})
    lines += ["", "## Primary reader plus an independent second reader (different model families only)", "",
              "A primary read is shown only when the second reader agrees. *Wrong shown* is the dangerous case: both agree on a wrong value. *Sent to a human* is the cost.", "",
              "| Field | Pair (primary -> second) | n | Shown correct | Wrong shown (95% CI) | Human: primary right | Human: primary wrong | Human: primary unread | Review rate | Wrong shown vs target |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    pairs_json = []
    pairs = cross_family_pairs({m: families[m] for m in models})
    for field in fields:
        results = [pair_analysis(truths, readings, readings, primary_model=p, second_model=s, field=field, min_similarity=settings.min_similarity, **guard) for p, s in pairs]
        for r in sorted(results, key=lambda r: (r.wrong_shown_rate, r.review_rate)):
            v = verdict(r.wrong_shown, r.n, settings.wrong_shown_target, higher_is_better=False)
            lines.append(f"| {field} | {r.primary_model} -> {r.second_model} | {r.n} | {r.agree_correct} | {_ci(r.wrong_shown, r.n)} | {r.review_primary_correct} | {r.review_primary_wrong} | "
                         f"{r.review_primary_unread} | {_pct(r.review_rate)} | {v} |")
            pairs_json.append({"field": field, "primary": r.primary_model, "second": r.second_model, "n": r.n, "agree_correct": r.agree_correct, "wrong_shown": r.wrong_shown,
                               "review_primary_correct": r.review_primary_correct, "review_primary_wrong": r.review_primary_wrong, "review_primary_unread": r.review_primary_unread,
                               "wrong_shown_rate": r.wrong_shown_rate, "review_rate": r.review_rate, "verdict": v})
    Path(args.out_md).write_text("\n".join(lines) + "\n", encoding="utf-8")
    Path(args.out_json).write_text(json.dumps({
        "settings": settings.__dict__, "models": models, "families": {m: families[m] for m in models},
        "scores": [{**r.__dict__, "exact_ci": list(r.exact_ci), "wrong_shown_ci": list(r.wrong_shown_ci)} for r in rows], "paired": paired_json, "pairs": pairs_json,
        "latency_ms": {m: {"p50": _percentile(v, 0.5), "p95": _percentile(v, 0.95), "median": statistics.median(v) if v else None} for m, v in latencies.items()}},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {args.out_md} and {args.out_json}")
    return 0


# ------------------------------------------------------------------------------------------ command line

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    def overrides(p):
        for name, typ in (("guard_multiple", int), ("guard_min_chars", int), ("min_similarity", float), ("resamples", int), ("seed", int), ("wrong_shown_target", float),
                          ("timeout", float), ("max_tokens", int), ("alpha", float)):
            p.add_argument("--" + name.replace("_", "-"), dest=name, type=typ, default=None)
    run = sub.add_parser("run")
    run.add_argument("--manifest", required=True)
    run.add_argument("--images", required=True)
    run.add_argument("--model-name", required=True)
    run.add_argument("--endpoint", required=True)
    run.add_argument("--api-model", required=True)
    run.add_argument("--variant", type=int, required=True)
    run.add_argument("--out", required=True)
    run.add_argument("--allow-host", action="append", help="a named host on the bank's network that may be used (repeatable)")
    overrides(run)
    sc = sub.add_parser("score")
    sc.add_argument("--manifest", required=True)
    sc.add_argument("--readings", nargs="+", required=True)
    sc.add_argument("--families", required=True)
    sc.add_argument("--baseline", required=True)
    sc.add_argument("--by", nargs="*", default=["script", "handwritten", "quality"], choices=["script", "handwritten", "quality"])
    sc.add_argument("--out-md", required=True)
    sc.add_argument("--out-json", required=True)
    overrides(sc)
    return ap


def main() -> int:
    args = build_parser().parse_args()
    try:
        return asyncio.run(cmd_run(args) if args.command == "run" else cmd_score(args))
    except FileNotFoundError as exc:
        return fail(f"file not found: {exc.filename}")


if __name__ == "__main__":
    sys.exit(main())
