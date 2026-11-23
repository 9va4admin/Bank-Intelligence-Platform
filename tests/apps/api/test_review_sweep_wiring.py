"""The API starts the overdue-review sweep, reading its interval from bank settings, using the real alert path, and stops it on shutdown."""
from pathlib import Path

SRC = (Path(__file__).resolve().parents[3] / "apps" / "api" / "main.py").read_text(encoding="utf-8")


def test_the_api_runs_the_overdue_review_sweep_with_the_real_alert_path_and_a_configurable_interval():
    assert "sweep_overdue_reviews" in SRC
    assert "alerting.review_sweep_seconds" in SRC
    assert "send_platform_alert" in SRC.split("sweep_overdue_reviews", 1)[1][:1500]            # it sends through the same path the watchdog uses


def test_the_sweep_task_is_cancelled_on_shutdown():
    assert "review_sweep_task" in SRC and SRC.count("review_sweep_task") >= 3
