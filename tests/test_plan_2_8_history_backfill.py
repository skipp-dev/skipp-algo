"""Tests for ``scripts/plan_2_8_history_backfill.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_history_backfill.py"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_history_backfill", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_history_backfill"] = mod
    spec.loader.exec_module(mod)
    return mod


bf = _load()


def _rec(ca: str, sr: str = "out/x") -> dict:
    return {"captured_at": ca, "scoring_root": sr,
            "files_scanned": 1, "per_tf": {}}


def _write(p: Path, recs: list[dict]) -> None:
    p.write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")


def test_merge_dedupes_on_captured_and_scoring_root() -> None:
    base = [_rec("2026-04-14T07:00:00Z"), _rec("2026-04-15T07:00:00Z")]
    inc = [_rec("2026-04-15T07:00:00Z"), _rec("2026-04-16T07:00:00Z")]
    r = bf.merge(base, inc)
    assert r["counts"]["final"] == 3
    assert r["counts"]["incoming_new"] == 1
    assert r["counts"]["incoming_duplicate"] == 1
    assert [m["captured_at"] for m in r["merged"]] == [
        "2026-04-14T07:00:00Z", "2026-04-15T07:00:00Z", "2026-04-16T07:00:00Z",
    ]


def test_merge_keeps_base_order_for_chronological_sort() -> None:
    base = [_rec("2026-04-20T07:00:00Z"), _rec("2026-04-10T07:00:00Z")]
    r = bf.merge(base, [])
    assert [m["captured_at"] for m in r["merged"]] == [
        "2026-04-10T07:00:00Z", "2026-04-20T07:00:00Z",
    ]


def test_malformed_records_are_counted_not_raised() -> None:
    base = [{"no": "keys"}, _rec("2026-04-14T07:00:00Z")]
    r = bf.merge(base, [])
    assert r["counts"]["base_malformed"] == 1
    assert r["counts"]["base_kept"] == 1


def test_different_scoring_root_is_not_duplicate() -> None:
    base = [_rec("2026-04-14T07:00:00Z", sr="out/a")]
    inc = [_rec("2026-04-14T07:00:00Z", sr="out/b")]
    r = bf.merge(base, inc)
    assert r["counts"]["final"] == 2
    assert r["counts"]["incoming_duplicate"] == 0


def test_cli_writes_output(tmp_path: Path) -> None:
    base = tmp_path / "base.jsonl"
    inc = tmp_path / "inc.jsonl"
    out = tmp_path / "out.jsonl"
    _write(base, [_rec("2026-04-14T07:00:00Z")])
    _write(inc, [_rec("2026-04-15T07:00:00Z")])
    rc = bf.main([
        "--base", str(base), "--incoming", str(inc), "--output", str(out),
        "--quiet",
    ])
    assert rc == 0
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2


def test_cli_dry_run_does_not_write(tmp_path: Path) -> None:
    base = tmp_path / "base.jsonl"
    inc = tmp_path / "inc.jsonl"
    out = tmp_path / "out.jsonl"
    _write(base, [_rec("2026-04-14T07:00:00Z")])
    _write(inc, [_rec("2026-04-15T07:00:00Z")])
    rc = bf.main([
        "--base", str(base), "--incoming", str(inc), "--output", str(out),
        "--dry-run", "--quiet",
    ])
    assert rc == 0
    assert not out.exists()


def test_cli_emits_json_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    base = tmp_path / "base.jsonl"
    inc = tmp_path / "inc.jsonl"
    out = tmp_path / "out.jsonl"
    _write(base, [_rec("2026-04-14T07:00:00Z")])
    _write(inc, [_rec("2026-04-14T07:00:00Z"), _rec("2026-04-15T07:00:00Z")])
    rc = bf.main([
        "--base", str(base), "--incoming", str(inc), "--output", str(out),
    ])
    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["counts"]["final"] == 2
    assert summary["counts"]["incoming_duplicate"] == 1


def test_missing_base_treated_as_empty(tmp_path: Path) -> None:
    inc = tmp_path / "inc.jsonl"
    out = tmp_path / "out.jsonl"
    _write(inc, [_rec("2026-04-15T07:00:00Z")])
    rc = bf.main([
        "--base", str(tmp_path / "none.jsonl"),
        "--incoming", str(inc), "--output", str(out), "--quiet",
    ])
    assert rc == 0
    assert out.read_text(encoding="utf-8").count("\n") == 1


def test_sort_handles_unparseable_timestamp_gracefully() -> None:
    base = [
        {"captured_at": "garbage", "scoring_root": "x",
         "files_scanned": 1, "per_tf": {}},
        _rec("2026-04-14T07:00:00Z"),
    ]
    r = bf.merge(base, [])
    # Both kept; garbage sorts to the front because parser returns min.
    assert r["counts"]["final"] == 2
    assert r["merged"][0]["captured_at"] == "garbage"
