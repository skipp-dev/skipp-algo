"""Tests for ``scripts.emit_fvg_context_pine`` (Q3/Q4 §D2)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.emit_fvg_context_pine import (
    DEFAULT_MIN_EVENTS,
    LEDGER_GLOB,
    PINE_HEADER,
    PINE_STATUS_KEY,
    _discover_ledger_paths,
    _normalise_event,
    build_pine_snippet,
    collect_fvg_events,
    main,
    write_outputs,
)

# ── _normalise_event ─────────────────────────────────────────────


def test_normalise_event_top_level_fields() -> None:
    record = {
        "family": "FVG",
        "session": "RTH",
        "htf_bias": "BULL",
        "vol_regime": "NORMAL",
        "hit": True,
    }
    out = _normalise_event(record)
    assert out == {"hit": True, "session": "RTH", "htf_bias": "BULL", "vol_regime": "NORMAL"}


def test_normalise_event_context_block_fallback() -> None:
    record = {
        "family": "FVG",
        "context": {"session": "ETH", "htf_bias": "BEAR", "vol_regime": "HIGH"},
        "hit": 0,
    }
    out = _normalise_event(record)
    assert out["hit"] is False
    assert out["session"] == "ETH"
    assert out["htf_bias"] == "BEAR"
    assert out["vol_regime"] == "HIGH"


def test_normalise_event_drops_non_fvg() -> None:
    record = {"family": "OB", "hit": True, "session": "RTH"}
    assert _normalise_event(record) is None


def test_normalise_event_drops_missing_hit() -> None:
    record = {"family": "FVG", "session": "RTH"}
    assert _normalise_event(record) is None


def test_normalise_event_accepts_outcome_alias() -> None:
    record = {"family": "FVG", "outcome": True, "session": "RTH"}
    out = _normalise_event(record)
    assert out is not None and out["hit"] is True


def test_normalise_event_handles_garbage() -> None:
    assert _normalise_event("not a dict") is None  # type: ignore[arg-type]
    assert _normalise_event({"family": "FVG", "context": "broken", "hit": True}) == {
        "hit": True, "session": None, "htf_bias": None, "vol_regime": None,
    }


# ── _discover_ledger_paths / collect_fvg_events ──────────────────


def test_discover_ledger_paths_returns_empty_when_dir_missing(tmp_path: Path) -> None:
    assert _discover_ledger_paths(tmp_path / "missing") == []


def test_discover_ledger_paths_finds_recursive(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "events_AAPL_5m.jsonl").write_text("")
    (tmp_path / "events_TSLA_1m.jsonl").write_text("")
    (tmp_path / "ignored.txt").write_text("")
    found = _discover_ledger_paths(tmp_path)
    names = sorted(p.name for p in found)
    assert names == ["events_AAPL_5m.jsonl", "events_TSLA_1m.jsonl"]


def _write_ledger(path: Path, records: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def test_collect_fvg_events_filters_and_normalises(tmp_path: Path) -> None:
    ledger = tmp_path / "events_AAPL_5m.jsonl"
    _write_ledger(ledger, [
        {"family": "FVG", "session": "RTH", "htf_bias": "BULL", "vol_regime": "NORMAL", "hit": True},
        {"family": "OB",  "session": "RTH", "hit": True},  # filtered
        {"family": "FVG", "context": {"session": "ETH", "htf_bias": "BEAR", "vol_regime": "HIGH"}, "hit": False},
    ])
    events = collect_fvg_events([ledger])
    assert len(events) == 2
    sessions = sorted(e["session"] for e in events)
    assert sessions == ["ETH", "RTH"]


# ── build_pine_snippet ───────────────────────────────────────────


def test_build_pine_snippet_awaiting_when_report_none() -> None:
    snippet = build_pine_snippet(
        None,
        generated_at="2026-04-23T22:00:00+00:00",
        source_commit_sha=None,
        source_workflow_run=None,
        ledger_count=0,
    )
    assert snippet.startswith(PINE_HEADER)
    assert f'{PINE_STATUS_KEY} = "awaiting_first_run"' in snippet


def test_build_pine_snippet_awaiting_when_no_events() -> None:
    snippet = build_pine_snippet(
        {"total_events": 0, "buckets": []},
        generated_at="2026-04-23T22:00:00+00:00",
        source_commit_sha="abc",
        source_workflow_run="42",
        ledger_count=3,
    )
    assert f'{PINE_STATUS_KEY} = "awaiting_first_run"' in snippet
    assert "ledger_files_consumed: 3" in snippet


def test_build_pine_snippet_emits_health_constants_when_data_present() -> None:
    report = {
        "min_events": 2,
        "total_events": 4,
        "buckets": [
            {"session": "RTH", "htf_bias": "BULL", "vol_regime": "NORMAL",
             "n_events": 4, "hits": 3, "hit_rate": 0.75, "insufficient": False},
        ],
        "actionable_buckets": [],
    }
    snippet = build_pine_snippet(
        report,
        generated_at="2026-04-23T22:00:00+00:00",
        source_commit_sha="deadbee",
        source_workflow_run="99",
        ledger_count=1,
    )
    assert f'{PINE_STATUS_KEY} = "ok"' in snippet
    assert "FVG_HEALTH_RTH_NORMAL" in snippet
    assert "75% (n=4)" in snippet
    assert "_STATUS = \"OK\"" in snippet


def test_build_pine_snippet_is_deterministic() -> None:
    report = {
        "min_events": 2, "total_events": 4,
        "buckets": [
            {"session": "RTH", "htf_bias": "BULL", "vol_regime": "NORMAL",
             "n_events": 4, "hits": 3, "hit_rate": 0.75, "insufficient": False},
        ],
        "actionable_buckets": [],
    }
    a = build_pine_snippet(report, generated_at="t", source_commit_sha="x", source_workflow_run="y", ledger_count=1)
    b = build_pine_snippet(report, generated_at="t", source_commit_sha="x", source_workflow_run="y", ledger_count=1)
    assert a == b


# ── write_outputs ────────────────────────────────────────────────


def test_write_outputs_writes_pine_and_sidecar(tmp_path: Path) -> None:
    out = tmp_path / "fvg_context_health.pine"
    sidecar = write_outputs("//@version=6\n", {"total_events": 0}, out)
    assert out.exists() and out.read_text(encoding="utf-8") == "//@version=6\n"
    assert sidecar == out.with_suffix(".json")
    assert sidecar.exists()
    assert json.loads(sidecar.read_text(encoding="utf-8")) == {"total_events": 0}
    # No .tmp leftovers
    assert not out.with_suffix(out.suffix + ".tmp").exists()


def test_write_outputs_sidecar_awaiting_when_report_none(tmp_path: Path) -> None:
    out = tmp_path / "x.pine"
    sidecar = write_outputs("//@version=6\n", None, out)
    assert json.loads(sidecar.read_text(encoding="utf-8")) == {"status": "awaiting_first_run"}


# ── main() integration ───────────────────────────────────────────


def test_main_emits_awaiting_with_no_ledgers(tmp_path: Path) -> None:
    out = tmp_path / "out" / "fvg_context_health.pine"
    rc = main([
        "--search-dir", str(tmp_path / "missing"),
        "--output", str(out),
        "--commit-sha", "abc1234",
        "--workflow-run", "0",
    ])
    assert rc == 0
    txt = out.read_text(encoding="utf-8")
    assert f'{PINE_STATUS_KEY} = "awaiting_first_run"' in txt
    sidecar = out.with_suffix(".json")
    assert sidecar.exists()
    assert json.loads(sidecar.read_text(encoding="utf-8")) == {"status": "awaiting_first_run"}


def test_main_with_real_ledger_emits_ok(tmp_path: Path) -> None:
    ledger = tmp_path / "events_AAPL_5m.jsonl"
    rows = [
        {"family": "FVG", "session": "RTH", "htf_bias": "BULL", "vol_regime": "NORMAL", "hit": True}
    ] * 12
    _write_ledger(ledger, rows)
    out = tmp_path / "out" / "fvg_context_health.pine"
    rc = main([
        "--ledger", str(ledger),
        "--output", str(out),
        "--min-events", "12",
        "--commit-sha", "abc",
        "--workflow-run", "1",
    ])
    assert rc == 0
    txt = out.read_text(encoding="utf-8")
    assert f'{PINE_STATUS_KEY} = "ok"' in txt
    assert "FVG_HEALTH_RTH_NORMAL" in txt
    sidecar = out.with_suffix(".json")
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["total_events"] == 12
    assert payload["min_events"] == 12


def test_main_under_min_events_marks_insufficient(tmp_path: Path) -> None:
    ledger = tmp_path / "events_AAPL_5m.jsonl"
    rows = [
        {"family": "FVG", "session": "RTH", "htf_bias": "BULL", "vol_regime": "NORMAL", "hit": True}
    ] * 5  # below the default 12 floor
    _write_ledger(ledger, rows)
    out = tmp_path / "out" / "fvg_context_health.pine"
    rc = main(["--ledger", str(ledger), "--output", str(out)])
    assert rc == 0
    txt = out.read_text(encoding="utf-8")
    assert f'{PINE_STATUS_KEY} = "ok"' in txt
    # bucket exists but renders as "insufficient" string from emit_fvg_pine_constants
    assert "insufficient (n=5)" in txt
    assert "_STATUS = \"INSUF\"" in txt


def test_main_returns_one_on_malformed_ledger(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ledger = tmp_path / "events_bad_5m.jsonl"
    ledger.write_text("{not-json\n")
    out = tmp_path / "out" / "fvg_context_health.pine"
    rc = main(["--ledger", str(ledger), "--output", str(out)])
    assert rc == 1
    assert "ERROR" in capsys.readouterr().err


def test_default_min_events_matches_plan() -> None:
    assert DEFAULT_MIN_EVENTS == 12
    assert LEDGER_GLOB == "events_*_*.jsonl"
