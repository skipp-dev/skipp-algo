"""Regression tests for the backlog resilience trio (2026-06-12).

Covers three failure modes that previously degraded silently:

1. ``scripts/start_open_prep_suite.py::_run_open_prep`` truncated
   ``latest_open_prep_run.json`` at process start by redirecting stdout
   straight into the target file — a crash left an empty/partial file for
   the monitor.  Now stdout goes to a tmp file that only replaces the
   target after a successful run.

2. ``open_prep/run_open_prep.py`` swallowed outcome-storage failures with
   ``logger.warning`` — the daily workflow turned green without producing
   its primary artifact (``outcomes_<date>.json``).  Now the error is
   recorded in the payload and ``main()`` exits non-zero.

3. ``open_prep/outcomes.py::_load_outcomes_range`` silently dropped
   outcome files whose top-level JSON was not a list.  Now it logs a
   warning naming the offending file and type.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Fix 1: suite orchestrator must not truncate the target file on crash
# ---------------------------------------------------------------------------


def _load_suite_module() -> ModuleType:
    path = REPO_ROOT / "scripts" / "start_open_prep_suite.py"
    spec = importlib.util.spec_from_file_location("_suite_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_run_open_prep_preserves_target_on_crash(tmp_path, monkeypatch):
    suite = _load_suite_module()
    out_file = tmp_path / "artifacts" / "open_prep" / "latest" / "latest_open_prep_run.json"
    out_file.parent.mkdir(parents=True)
    out_file.write_text('{"previous": "run"}', encoding="utf-8")

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated crash")

    monkeypatch.setattr(suite.subprocess, "run", _boom)
    with pytest.raises(RuntimeError, match="simulated crash"):
        suite._run_open_prep(tmp_path, sys.executable)

    # Previous snapshot untouched, tmp file cleaned up.
    assert json.loads(out_file.read_text(encoding="utf-8")) == {"previous": "run"}
    assert not list(out_file.parent.glob("*.stdout.tmp"))


def test_run_open_prep_replaces_target_on_success(tmp_path, monkeypatch):
    suite = _load_suite_module()
    out_file = tmp_path / "artifacts" / "open_prep" / "latest" / "latest_open_prep_run.json"
    out_file.parent.mkdir(parents=True)
    out_file.write_text('{"previous": "run"}', encoding="utf-8")

    def _fake_run(cmd, *, cwd, stdout, check):
        stdout.write('{"fresh": "run"}')

    monkeypatch.setattr(suite.subprocess, "run", _fake_run)
    suite._run_open_prep(tmp_path, sys.executable)

    assert json.loads(out_file.read_text(encoding="utf-8")) == {"fresh": "run"}
    assert not list(out_file.parent.glob("*.stdout.tmp"))


# ---------------------------------------------------------------------------
# Fix 2: main() exits non-zero when outcome storage failed
# ---------------------------------------------------------------------------


def _patch_main_collaborators(monkeypatch, error: str | None):
    from open_prep import run_open_prep as rop

    class _Args:
        symbols = ""
        universe_source = "STATIC"
        fmp_min_market_cap = 1
        fmp_max_symbols = 1
        mover_seed_max_symbols = 0
        days_ahead = 1
        top = 1
        trade_cards = 1
        max_macro_events = 1
        pre_open_only = False
        pre_open_cutoff_utc = None
        gap_mode = "auto"
        gap_scope = "TOP"
        atr_lookback_days = 1
        atr_period = 1
        atr_parallel_workers = 1
        analyst_catalyst_limit = 0

    monkeypatch.setattr(rop, "_parse_args", lambda: _Args())
    monkeypatch.setattr(rop, "_parse_symbols", lambda raw: [])
    monkeypatch.setattr(
        rop,
        "generate_open_prep_result",
        lambda **kwargs: {"outcome_storage_error": error},
    )
    return rop


def test_main_exits_nonzero_on_outcome_storage_error(monkeypatch, capsys):
    rop = _patch_main_collaborators(monkeypatch, "ValueError: disk full")
    with pytest.raises(SystemExit) as excinfo:
        rop.main()
    assert excinfo.value.code == 1
    # Payload must still be fully rendered before the exit.
    payload = json.loads(capsys.readouterr().out)
    assert payload["outcome_storage_error"] == "ValueError: disk full"


def test_main_completes_normally_without_storage_error(monkeypatch, capsys):
    rop = _patch_main_collaborators(monkeypatch, None)
    rop.main()  # must not raise SystemExit
    payload = json.loads(capsys.readouterr().out)
    assert payload["outcome_storage_error"] is None


# ---------------------------------------------------------------------------
# Fix 3: non-list outcome files are skipped loudly, not silently
# ---------------------------------------------------------------------------


def test_load_outcomes_range_warns_on_non_list(tmp_path, monkeypatch, caplog):
    from open_prep import outcomes

    monkeypatch.setattr(outcomes, "OUTCOMES_DIR", tmp_path)
    (tmp_path / "outcomes_2026-06-10.json").write_text(
        json.dumps([{"symbol": "AAA"}]), encoding="utf-8"
    )
    (tmp_path / "outcomes_2026-06-11.json").write_text(
        json.dumps({"not": "a list"}), encoding="utf-8"
    )

    with caplog.at_level("WARNING", logger=outcomes.logger.name):
        records = outcomes._load_outcomes_range(lookback_days=20)

    assert records == [{"symbol": "AAA"}]
    assert any(
        "expected list" in message and "outcomes_2026-06-11.json" in message
        for message in caplog.messages
    )
