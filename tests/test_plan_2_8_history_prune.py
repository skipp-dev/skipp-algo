"""Tests for ``scripts/plan_2_8_history_prune.py``."""

from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_history_prune.py"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_history_prune", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_history_prune"] = mod
    spec.loader.exec_module(mod)
    return mod


hp = _load()


NOW = _dt.datetime(2026, 4, 22, tzinfo=_dt.UTC)


def _line(day: str, extra: str = "x") -> str:
    return json.dumps({"captured_at": f"{day}T00:00:00+00:00",
                       "payload":      extra})


def test_prune_drops_stale() -> None:
    lines = [
        _line("2025-01-01"),  # stale (>365d)
        _line("2026-04-01"),  # kept
    ]
    rep = hp.prune_lines(lines, keep_days=365, now=NOW)
    assert rep["counts"]["kept"] == 1
    assert rep["counts"]["dropped_stale"] == 1


def test_prune_keeps_undated_by_default() -> None:
    lines = [
        json.dumps({"no_captured_at": 1}),
        _line("2026-04-01"),
    ]
    rep = hp.prune_lines(lines, keep_days=365, now=NOW)
    assert rep["counts"]["kept"] == 2
    assert rep["counts"]["dropped_undated"] == 0


def test_prune_drops_undated_when_requested() -> None:
    lines = [
        json.dumps({"no_captured_at": 1}),
        _line("2026-04-01"),
    ]
    rep = hp.prune_lines(lines, keep_days=365, now=NOW, drop_undated=True)
    assert rep["counts"]["kept"] == 1
    assert rep["counts"]["dropped_undated"] == 1


def test_prune_counts_malformed() -> None:
    lines = ["not-json", "[1,2,3]", _line("2026-04-01")]
    rep = hp.prune_lines(lines, keep_days=365, now=NOW)
    assert rep["counts"]["malformed"] == 2
    assert rep["counts"]["kept"] == 1


def test_prune_empty_blank_lines_ignored() -> None:
    lines = ["", "   ", _line("2026-04-01")]
    rep = hp.prune_lines(lines, keep_days=365, now=NOW)
    assert rep["counts"]["kept"] == 1
    assert rep["counts"]["malformed"] == 0


def test_prune_bad_timestamp_treated_as_undated() -> None:
    lines = [
        json.dumps({"captured_at": "not-a-date"}),
        _line("2026-04-01"),
    ]
    rep = hp.prune_lines(lines, keep_days=365, now=NOW)
    assert rep["counts"]["kept"] == 2
    rep2 = hp.prune_lines(lines, keep_days=365, now=NOW, drop_undated=True)
    assert rep2["counts"]["dropped_undated"] == 1


def test_atomic_write_and_cli(tmp_path: Path) -> None:
    hist = tmp_path / "history.jsonl"
    hist.write_text(
        "\n".join([_line("2025-01-01"), _line("2026-04-01")]) + "\n",
        encoding="utf-8",
    )
    rc = hp.main([
        "--history", str(hist), "--keep-days", "365", "--quiet",
    ])
    assert rc == 0
    kept = hist.read_text(encoding="utf-8").splitlines()
    assert len(kept) == 1
    assert "2026-04-01" in kept[0]


def test_cli_dry_run_does_not_rewrite(tmp_path: Path) -> None:
    hist = tmp_path / "history.jsonl"
    original = "\n".join([_line("2025-01-01"), _line("2026-04-01")]) + "\n"
    hist.write_text(original, encoding="utf-8")
    rc = hp.main([
        "--history", str(hist), "--keep-days", "365", "--dry-run", "--quiet",
    ])
    assert rc == 0
    assert hist.read_text(encoding="utf-8") == original


def test_cli_output_path(tmp_path: Path) -> None:
    hist = tmp_path / "history.jsonl"
    hist.write_text(_line("2026-04-01") + "\n", encoding="utf-8")
    out = tmp_path / "pruned.jsonl"
    rc = hp.main([
        "--history", str(hist), "--output", str(out), "--quiet",
    ])
    assert rc == 0
    assert out.exists()
    # Original is untouched.
    assert hist.read_text(encoding="utf-8").strip() == _line("2026-04-01")


def test_cli_missing_history(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = hp.main(["--history", str(tmp_path / "nope.jsonl")])
    assert rc == 1
    assert "history not found" in capsys.readouterr().err
