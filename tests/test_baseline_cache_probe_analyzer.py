"""Unit tests for ``scripts/baseline_cache_probe.py`` (Phase-B analyzer).

Covers the four numbers (lookups, unique_paths, set-overlap, lookup-weighted)
and the coverage guards that were added to make partial-artifact runs fail
loud instead of silently producing a Phase-C go/no-go decision.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import baseline_cache_probe as bcp


def _write_shard(dir_: Path, shard_id: int, paths: list[str]) -> Path:
    dir_.mkdir(parents=True, exist_ok=True)
    fp = dir_ / f"cache_probe_shard_{shard_id}.jsonl"
    fp.write_text(
        "\n".join(json.dumps({"path": p}) for p in paths) + "\n",
        encoding="utf-8",
    )
    return fp


def test_happy_path_metrics_and_per_shard_counts(tmp_path: Path) -> None:
    run1 = tmp_path / "run1"
    run2 = tmp_path / "run2"
    _write_shard(run1, 0, ["a", "b", "a"])
    _write_shard(run1, 1, ["c"])
    _write_shard(run2, 0, ["a", "a", "d"])
    _write_shard(run2, 1, ["c", "e"])

    result = bcp.analyze(run1, run2, expected_shards=2, require_same_shards=True, min_lookups=1)

    assert result["run1"]["lookups"] == 4
    assert result["run1"]["unique_paths"] == 3
    assert result["run1"]["per_shard_lookups"] == {0: 3, 1: 1}
    assert result["run2"]["lookups"] == 5
    assert result["run2"]["unique_paths"] == 4
    # set-overlap: {a, c} ∩ {a, c, d, e} / |run2_unique| = 2/4
    assert result["hit_rate_set_overlap"] == pytest.approx(0.5)
    # lookup-weighted: run2 lookups in run1_unique = a,a,c = 3 of 5
    assert result["hit_rate_lookup_weighted"] == pytest.approx(0.6)
    assert result["phase_c_gate_60pct"] is True


def test_expected_shards_guard_fails_on_missing_shard(tmp_path: Path) -> None:
    run1 = tmp_path / "run1"
    run2 = tmp_path / "run2"
    _write_shard(run1, 0, ["a"])
    _write_shard(run1, 1, ["b"])
    _write_shard(run2, 0, ["a"])  # missing shard 1
    with pytest.raises(SystemExit) as exc:
        bcp.analyze(run1, run2, expected_shards=2)
    assert "expected 2 shard files" in str(exc.value)


def test_require_same_shards_fails_on_mismatched_coverage(tmp_path: Path) -> None:
    run1 = tmp_path / "run1"
    run2 = tmp_path / "run2"
    _write_shard(run1, 0, ["a"])
    _write_shard(run1, 1, ["b"])
    _write_shard(run2, 0, ["a"])
    _write_shard(run2, 2, ["c"])  # different shard id
    with pytest.raises(SystemExit) as exc:
        bcp.analyze(run1, run2, require_same_shards=True)
    assert "different shard-id sets" in str(exc.value)


def test_min_lookups_guard_fails_on_empty_jsonl(tmp_path: Path) -> None:
    run1 = tmp_path / "run1"
    run2 = tmp_path / "run2"
    (run1 / "cache_probe_shard_0.jsonl").parent.mkdir(parents=True, exist_ok=True)
    (run1 / "cache_probe_shard_0.jsonl").write_text("", encoding="utf-8")
    _write_shard(run2, 0, ["a"])
    with pytest.raises(SystemExit) as exc:
        bcp.analyze(run1, run2, min_lookups=1)
    assert "total lookups 0" in str(exc.value)


def test_strict_json_default_aborts_on_malformed_line(tmp_path: Path) -> None:
    run1 = tmp_path / "run1"
    run2 = tmp_path / "run2"
    (run1).mkdir(parents=True, exist_ok=True)
    (run1 / "cache_probe_shard_0.jsonl").write_text(
        '{"path": "a"}\nnot-json\n', encoding="utf-8"
    )
    _write_shard(run2, 0, ["a"])
    with pytest.raises(SystemExit) as exc:
        bcp.analyze(run1, run2)
    assert "malformed JSON" in str(exc.value)


def test_no_strict_json_tolerates_malformed_lines(tmp_path: Path) -> None:
    run1 = tmp_path / "run1"
    run2 = tmp_path / "run2"
    (run1).mkdir(parents=True, exist_ok=True)
    (run1 / "cache_probe_shard_0.jsonl").write_text(
        '{"path": "a"}\nnot-json\n{"path": "b"}\n', encoding="utf-8"
    )
    _write_shard(run2, 0, ["a"])
    result = bcp.analyze(run1, run2, strict_json=False)
    assert result["run1"]["lookups"] == 2
    assert result["run1"]["unique_paths"] == 2


def test_missing_run_dir_raises(tmp_path: Path) -> None:
    run2 = tmp_path / "run2"
    _write_shard(run2, 0, ["a"])
    with pytest.raises(SystemExit) as exc:
        bcp.analyze(tmp_path / "nope", run2)
    assert "run dir not found" in str(exc.value)


def test_empty_run_dir_raises_helpful_message(tmp_path: Path) -> None:
    run1 = tmp_path / "run1"
    run1.mkdir()
    run2 = tmp_path / "run2"
    _write_shard(run2, 0, ["a"])
    with pytest.raises(SystemExit) as exc:
        bcp.analyze(run1, run2)
    assert "no cache_probe_shard_*.jsonl" in str(exc.value)


def test_phase_c_gate_false_below_threshold(tmp_path: Path) -> None:
    run1 = tmp_path / "run1"
    run2 = tmp_path / "run2"
    _write_shard(run1, 0, ["a"])
    _write_shard(run2, 0, ["a", "b", "c"])  # 1/3 weighted ≈ 33 %
    result = bcp.analyze(run1, run2)
    assert result["hit_rate_lookup_weighted"] == pytest.approx(1 / 3)
    assert result["phase_c_gate_60pct"] is False


def test_main_json_mode_writes_decision(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run1 = tmp_path / "run1"
    run2 = tmp_path / "run2"
    _write_shard(run1, 0, ["a", "b"])
    _write_shard(run2, 0, ["a", "b"])
    rc = bcp.main([str(run1), str(run2), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["phase_c_gate_60pct"] is True
    assert payload["run1"]["per_shard_lookups"] == {"0": 2}  # JSON stringifies int keys
