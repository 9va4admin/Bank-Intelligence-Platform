"""TDD — xlit_benchmark: compare Brahmic transliterator vs indic-transliteration (ITRANS).

RED step: all tests fail until modules/cts/preprocessing/xlit_benchmark.py is created.

POC goal: empirically determine whether the indic-transliteration library (scholarly
ITRANS scheme) improves name-matching accuracy over our homegrown Brahmic engine.
"""
from __future__ import annotations

import pytest


# ── Module existence ──────────────────────────────────────────────────────────

class TestModuleImports:

    def test_module_importable(self):
        """xlit_benchmark module must be importable."""
        from modules.cts.preprocessing import xlit_benchmark  # noqa: F401

    def test_exports_run_benchmark(self):
        from modules.cts.preprocessing.xlit_benchmark import run_benchmark
        assert callable(run_benchmark)

    def test_exports_compare_approaches(self):
        from modules.cts.preprocessing.xlit_benchmark import compare_approaches
        assert callable(compare_approaches)

    def test_exports_benchmark_report(self):
        from modules.cts.preprocessing.xlit_benchmark import BenchmarkReport
        assert BenchmarkReport is not None

    def test_exports_name_row(self):
        from modules.cts.preprocessing.xlit_benchmark import NameRow
        assert NameRow is not None


# ── NameRow structure ─────────────────────────────────────────────────────────

class TestNameRow:

    def test_name_row_fields(self):
        from modules.cts.preprocessing.xlit_benchmark import NameRow
        row = NameRow(
            indic="रामेश्वर",
            english="Rameshwar",
            script="devanagari",
            language="Hindi",
        )
        assert row.indic == "रामेश्वर"
        assert row.english == "Rameshwar"
        assert row.script == "devanagari"
        assert row.language == "Hindi"


# ── compare_approaches ────────────────────────────────────────────────────────

class TestCompareApproaches:
    """compare_approaches(indic, english, script) → dict with both JW scores."""

    def test_returns_dict_with_required_keys(self):
        from modules.cts.preprocessing.xlit_benchmark import compare_approaches
        result = compare_approaches("रामेश्वर", "Rameshwar", "devanagari")
        assert "brahmic_latin" in result
        assert "brahmic_jw" in result
        assert "itrans_latin" in result
        assert "itrans_jw" in result
        assert "winner" in result

    def test_brahmic_jw_for_rameshwar(self):
        """रामेश्वर → rameshvara — JW vs 'rameshwar' ≥ 0.90."""
        from modules.cts.preprocessing.xlit_benchmark import compare_approaches
        r = compare_approaches("रामेश्वर", "Rameshwar", "devanagari")
        assert r["brahmic_jw"] >= 0.90

    def test_brahmic_beats_itrans_for_deshpande(self):
        """देशपांडे: anusvara handling — Brahmic gives 'deshpande', ITRANS 'deshapamde'."""
        from modules.cts.preprocessing.xlit_benchmark import compare_approaches
        r = compare_approaches("देशपांडे", "Deshpande", "devanagari")
        assert r["brahmic_jw"] > r["itrans_jw"], (
            f"Expected Brahmic ({r['brahmic_jw']:.3f}) > ITRANS ({r['itrans_jw']:.3f})"
        )

    def test_brahmic_beats_itrans_for_singh(self):
        """ਸਿੰਘ: tippi handling — Brahmic gives 'singha', ITRANS 'simgha'."""
        from modules.cts.preprocessing.xlit_benchmark import compare_approaches
        r = compare_approaches("ਸਿੰਘ", "Singh", "gurmukhi")
        assert r["brahmic_jw"] > r["itrans_jw"], (
            f"Expected Brahmic ({r['brahmic_jw']:.3f}) > ITRANS ({r['itrans_jw']:.3f})"
        )

    def test_winner_field_is_brahmic_or_itrans_or_tie(self):
        from modules.cts.preprocessing.xlit_benchmark import compare_approaches
        r = compare_approaches("रामेश्वर", "Rameshwar", "devanagari")
        assert r["winner"] in {"brahmic", "itrans", "tie"}

    def test_jw_scores_are_floats_in_range(self):
        from modules.cts.preprocessing.xlit_benchmark import compare_approaches
        r = compare_approaches("विश्वनाथ", "Vishwanath", "devanagari")
        assert isinstance(r["brahmic_jw"], float)
        assert isinstance(r["itrans_jw"], float)
        assert 0.0 <= r["brahmic_jw"] <= 1.0
        assert 0.0 <= r["itrans_jw"] <= 1.0


# ── run_benchmark ─────────────────────────────────────────────────────────────

class TestRunBenchmark:
    """run_benchmark() returns a BenchmarkReport with per-language and overall stats."""

    def test_returns_benchmark_report(self):
        from modules.cts.preprocessing.xlit_benchmark import run_benchmark, BenchmarkReport
        report = run_benchmark()
        assert isinstance(report, BenchmarkReport)

    def test_report_has_rows(self):
        from modules.cts.preprocessing.xlit_benchmark import run_benchmark
        report = run_benchmark()
        assert len(report.rows) >= 10, "Corpus must have at least 10 name pairs"

    def test_brahmic_avg_higher_than_itrans_avg(self):
        """Across the full corpus, Brahmic JW average must beat ITRANS JW average."""
        from modules.cts.preprocessing.xlit_benchmark import run_benchmark
        report = run_benchmark()
        assert report.brahmic_avg_jw > report.itrans_avg_jw, (
            f"Brahmic avg {report.brahmic_avg_jw:.3f} should beat ITRANS avg {report.itrans_avg_jw:.3f}"
        )

    def test_brahmic_wins_majority(self):
        """Brahmic engine wins more individual name pairs than ITRANS."""
        from modules.cts.preprocessing.xlit_benchmark import run_benchmark
        report = run_benchmark()
        assert report.brahmic_wins > report.itrans_wins, (
            f"Brahmic wins {report.brahmic_wins} vs ITRANS wins {report.itrans_wins}"
        )

    def test_per_language_breakdown_present(self):
        """per_language dict maps language name → {brahmic_avg, itrans_avg}."""
        from modules.cts.preprocessing.xlit_benchmark import run_benchmark
        report = run_benchmark()
        assert isinstance(report.per_language, dict)
        assert "Hindi" in report.per_language or "Devanagari" in report.per_language

    def test_known_failure_case_identified(self):
        """George in Malayalam is a known failure — must appear in known_failures."""
        from modules.cts.preprocessing.xlit_benchmark import run_benchmark
        report = run_benchmark()
        failing_english = {r.english.lower() for r in report.known_failures}
        assert "george" in failing_english, (
            "George (Malayalam Christian name) must be flagged as a known failure"
        )

    def test_known_failures_below_threshold(self):
        """All known_failures have brahmic_jw < 0.75."""
        from modules.cts.preprocessing.xlit_benchmark import run_benchmark
        report = run_benchmark()
        for row in report.known_failures:
            assert row.brahmic_jw < 0.75, (
                f"Known failure {row.english} has brahmic_jw={row.brahmic_jw:.3f} "
                "— should be < 0.75 to qualify as failure"
            )

    def test_recommendation_present(self):
        """Report must include a recommendation string summarizing findings."""
        from modules.cts.preprocessing.xlit_benchmark import run_benchmark
        report = run_benchmark()
        assert report.recommendation
        assert len(report.recommendation) > 20


# ── BenchmarkReport structure ─────────────────────────────────────────────────

class TestBenchmarkReport:

    def test_report_fields_accessible(self):
        from modules.cts.preprocessing.xlit_benchmark import run_benchmark
        r = run_benchmark()
        _ = r.brahmic_avg_jw
        _ = r.itrans_avg_jw
        _ = r.brahmic_wins
        _ = r.itrans_wins
        _ = r.ties
        _ = r.per_language
        _ = r.known_failures
        _ = r.recommendation

    def test_wins_plus_ties_equals_total_rows(self):
        from modules.cts.preprocessing.xlit_benchmark import run_benchmark
        r = run_benchmark()
        assert r.brahmic_wins + r.itrans_wins + r.ties == len(r.rows)
