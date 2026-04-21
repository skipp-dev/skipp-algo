"""Tests for scripts/f2_append_rollback_history.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.f2_append_rollback_history import (
    DEFAULT_MAX_LEN,
    DEFAULT_METRIC,
    append_history,
    main,
)


def _report(*, brier_delta: float = -0.01, ece_delta: float = -0.01) -> dict:
    return {
        "schema_version": 1,
        "decision": "hold",
        "kpi_metrics": [
            {"metric": "calibrated_brier", "delta": brier_delta},
            {"metric": "calibrated_ece", "delta": ece_delta},
            {"metric": "hit_rate_pct", "delta": 0.5},
        ],
    }


# ---------------------------------------------------------------------------
# append_history()
# ---------------------------------------------------------------------------


def test_append_creates_new_history(tmp_path: Path) -> None:
    history = tmp_path / "history.json"
    out = append_history(report=_report(brier_delta=-0.02), history_path=history)
    assert out == [-0.02]
    assert json.loads(history.read_text(encoding="utf-8")) == [-0.02]


def test_append_extends_existing_history(tmp_path: Path) -> None:
    history = tmp_path / "history.json"
    history.write_text(json.dumps([0.01, -0.02]), encoding="utf-8")
    out = append_history(report=_report(brier_delta=0.005), history_path=history)
    assert out == [0.01, -0.02, 0.005]


def test_append_bounds_to_max_len(tmp_path: Path) -> None:
    history = tmp_path / "history.json"
    history.write_text(json.dumps([0.0] * DEFAULT_MAX_LEN), encoding="utf-8")
    out = append_history(report=_report(brier_delta=0.01), history_path=history)
    assert len(out) == DEFAULT_MAX_LEN
    assert out[-1] == 0.01
    # Oldest dropped.
    assert out[0] == 0.0


def test_append_uses_alternate_metric(tmp_path: Path) -> None:
    history = tmp_path / "history.json"
    out = append_history(
        report=_report(brier_delta=-0.01, ece_delta=0.03),
        history_path=history,
        metric="calibrated_ece",
    )
    assert out == [0.03]


def test_append_raises_on_missing_metric(tmp_path: Path) -> None:
    history = tmp_path / "history.json"
    with pytest.raises(ValueError, match="metric='nonexistent'"):
        append_history(
            report=_report(),
            history_path=history,
            metric="nonexistent",
        )


def test_append_validates_max_len(tmp_path: Path) -> None:
    history = tmp_path / "history.json"
    with pytest.raises(ValueError, match="max_len must be >= 1"):
        append_history(report=_report(), history_path=history, max_len=0)


def test_append_rejects_non_list_history(tmp_path: Path) -> None:
    history = tmp_path / "history.json"
    history.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    with pytest.raises(ValueError, match="must contain a JSON list"):
        append_history(report=_report(), history_path=history)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _write_report(path: Path, **kwargs) -> None:
    path.write_text(json.dumps(_report(**kwargs)), encoding="utf-8")


def test_cli_appends_and_returns_0(tmp_path: Path, capsys) -> None:
    report_path = tmp_path / "r.json"
    history_path = tmp_path / "h.json"
    _write_report(report_path, brier_delta=-0.005)
    rc = main(["--report", str(report_path), "--history", str(history_path)])
    assert rc == 0
    assert json.loads(history_path.read_text(encoding="utf-8")) == [-0.005]


def test_cli_returns_1_on_missing_report(tmp_path: Path) -> None:
    rc = main([
        "--report", str(tmp_path / "missing.json"),
        "--history", str(tmp_path / "h.json"),
    ])
    assert rc == 1


def test_cli_returns_1_on_malformed_report(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json}", encoding="utf-8")
    rc = main([
        "--report", str(bad),
        "--history", str(tmp_path / "h.json"),
    ])
    assert rc == 1


def test_cli_returns_1_on_missing_metric(tmp_path: Path) -> None:
    report_path = tmp_path / "r.json"
    _write_report(report_path)
    rc = main([
        "--report", str(report_path),
        "--history", str(tmp_path / "h.json"),
        "--metric", "nope",
    ])
    assert rc == 1


def test_default_metric_is_calibrated_brier() -> None:
    assert DEFAULT_METRIC == "calibrated_brier"
