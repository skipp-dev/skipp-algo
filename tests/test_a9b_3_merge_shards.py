"""A9b.3 — unit tests for the shard-manifest reduce step.

Coverage strategy:
* 1 fixture pair from the real 2026-05-08 N=2 probe (regression baseline)
* synthetic edge cases the real artifact cannot exercise:
    - empty input
    - single shard (degenerate but legal)
    - missing-key in some shards (per-shard-partial branch)
    - explicit override fields (per-shard timestamps, basenames)
    - sum-across drift detection via disjoint-window violation
    - string drift on a non-PER_SHARD field (must raise)
    - nested-dict recursion
    - bool drift (must raise)
    - unknown shard-id in CLI directory parsing
    - ``main()`` exits 2 on ManifestMergeError, stderr non-empty
    - ``main()`` writes valid JSON to --output on success
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "databento_production_merge_shards.py"
_FIXTURE_SHARD1 = _THIS_DIR / "fixtures" / "a9b3_manifest_shard1.json"
_FIXTURE_SHARD2 = _THIS_DIR / "fixtures" / "a9b3_manifest_shard2.json"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "databento_production_merge_shards", _SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None, (
        f"importlib failed to build a loader-bearing spec for {_SCRIPT_PATH}; "
        "this should never happen for a present .py file."
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mod():
    return _load_module()


@pytest.fixture(scope="module")
def real_shards() -> list[dict]:
    return [
        json.loads(_FIXTURE_SHARD1.read_text()),
        json.loads(_FIXTURE_SHARD2.read_text()),
    ]


# ---------------------------------------------------------------------------
# Real-fixture regression baseline
# ---------------------------------------------------------------------------

def test_real_fixture_merges_without_error(mod, real_shards):
    merged = mod.merge_manifests(real_shards)
    # Provenance fields injected.
    assert merged["shard_count"] == 2
    assert merged["shard_ids"] == [1, 2]
    assert "merged_at" in merged
    assert merged["merge_script_version"] == mod.MERGE_SCRIPT_VERSION


def test_real_fixture_sums_rowcount_fields(mod, real_shards):
    merged = mod.merge_manifests(real_shards)
    s1, s2 = real_shards
    # full_universe_close_trade_detail_rows differs across shards in the
    # real fixture — verify blind sum.
    assert (
        merged["full_universe_close_trade_detail_rows"]
        == s1["full_universe_close_trade_detail_rows"]
        + s2["full_universe_close_trade_detail_rows"]
    )


def test_real_fixture_per_shard_timestamps(mod, real_shards):
    merged = mod.merge_manifests(real_shards)
    # *_fetched_at fields must be preserved per-shard (override table).
    assert "close_trade_detail_fetched_at_per_shard" in merged
    payload = merged["close_trade_detail_fetched_at_per_shard"]
    assert set(payload.keys()) == {"1", "2"}
    # Original key must NOT also leak through.
    assert "close_trade_detail_fetched_at" not in merged


def test_real_fixture_disjoint_trade_dates_are_unioned(mod, real_shards):
    merged = mod.merge_manifests(real_shards)
    s1, s2 = real_shards
    expected = sorted(set(s1["trade_dates_covered"]) | set(s2["trade_dates_covered"]))
    assert merged["trade_dates_covered"] == expected


def test_real_fixture_identical_fields_passthrough(mod, real_shards):
    merged = mod.merge_manifests(real_shards)
    s1 = real_shards[0]
    # An obviously-identical configuration field.
    assert merged["close_imbalance_window_et"] == s1["close_imbalance_window_et"]


# ---------------------------------------------------------------------------
# Synthetic edge cases
# ---------------------------------------------------------------------------

def test_empty_input_raises(mod):
    with pytest.raises(mod.ManifestMergeError, match="at least one shard"):
        mod.merge_manifests([])


def test_single_shard_is_legal(mod):
    merged = mod.merge_manifests([{"a": 1, "b": "x", "trade_dates_covered": ["2026-01-02"]}])
    assert merged["a"] == 1
    assert merged["shard_count"] == 1
    assert merged["shard_ids"] == [1]


def test_missing_key_in_some_shards_emits_partial(mod):
    shards = [{"a": 1, "rare": 7}, {"a": 1}]
    merged = mod.merge_manifests(shards)
    assert merged["a"] == 1
    assert "rare_per_shard_partial" in merged
    assert merged["rare_per_shard_partial"] == {
        "present": {"1": 7},
        "missing_shard_ids": [2],
    }


def test_per_shard_override_basename(mod):
    shards = [{"basename": "run_a"}, {"basename": "run_b"}]
    merged = mod.merge_manifests(shards)
    assert merged["basename_per_shard"] == {"1": "run_a", "2": "run_b"}
    assert "basename" not in merged


def test_disjoint_union_violation_raises(mod):
    shards = [
        {"trade_dates_covered": ["2026-01-02", "2026-01-05"]},
        {"trade_dates_covered": ["2026-01-05", "2026-01-06"]},  # overlap!
    ]
    with pytest.raises(mod.ManifestMergeError, match="Disjoint-union violation"):
        mod.merge_manifests(shards)


def test_string_drift_on_non_override_raises(mod):
    shards = [{"engine_version": "1.0"}, {"engine_version": "1.1"}]
    with pytest.raises(mod.ManifestMergeError, match="String drift"):
        mod.merge_manifests(shards)


def test_bool_drift_raises(mod):
    shards = [{"feature_flag": True}, {"feature_flag": False}]
    with pytest.raises(mod.ManifestMergeError, match="Boolean drift"):
        mod.merge_manifests(shards)


def test_nested_dict_recursive_merge(mod):
    shards = [
        {"counts": {"a": 10, "b": 5, "trade_dates_covered": ["2026-01-02"]}},
        {"counts": {"a": 7, "b": 5, "trade_dates_covered": ["2026-01-03"]}},
    ]
    merged = mod.merge_manifests(shards)
    assert merged["counts"]["a"] == 17  # int sum
    assert merged["counts"]["b"] == 5  # identical
    assert merged["counts"]["trade_dates_covered"] == ["2026-01-02", "2026-01-03"]


def test_explicit_shard_ids(mod):
    shards = [{"a": 1}, {"a": 2}]
    merged = mod.merge_manifests(shards, shard_ids=[3, 5])
    assert merged["shard_ids"] == [3, 5]
    assert merged["a"] == 3  # sum


def test_duplicate_shard_ids_raise(mod):
    with pytest.raises(mod.ManifestMergeError, match="duplicates"):
        mod.merge_manifests([{}, {}], shard_ids=[1, 1])


def test_non_positive_shard_ids_raise(mod):
    with pytest.raises(mod.ManifestMergeError, match="positive"):
        mod.merge_manifests([{}, {}], shard_ids=[0, 1])


def test_reserved_provenance_key_collision_raises(mod):
    with pytest.raises(mod.ManifestMergeError, match="Reserved key"):
        mod.merge_manifests([{"merged_at": "x"}, {"merged_at": "x"}])


def test_parse_shard_id_from_dir(mod):
    assert mod._parse_shard_id_from_dir("shard-1") == 1
    assert mod._parse_shard_id_from_dir("a9b-2b-shard-3-of-6") == 3
    assert mod._parse_shard_id_from_dir("not-shaped-like-shard") is None


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

def _run_cli(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_SCRIPT_PATH), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(_REPO_ROOT),
    )


def test_cli_writes_merged_json(tmp_path: Path) -> None:
    s1 = tmp_path / "shard-1"
    s2 = tmp_path / "shard-2"
    s1.mkdir()
    s2.mkdir()
    (s1 / "x_manifest.json").write_text(json.dumps({"a": 4, "trade_dates_covered": ["2026-01-02"]}))
    (s2 / "x_manifest.json").write_text(json.dumps({"a": 3, "trade_dates_covered": ["2026-01-03"]}))
    out = tmp_path / "merged.json"
    res = _run_cli(["--shard-dir", str(s1), "--shard-dir", str(s2), "--output", str(out)])
    assert res.returncode == 0, res.stderr
    payload = json.loads(out.read_text())
    assert payload["a"] == 7
    assert payload["shard_count"] == 2


def test_cli_returns_2_on_merge_error(tmp_path: Path) -> None:
    s1 = tmp_path / "shard-1"
    s2 = tmp_path / "shard-2"
    s1.mkdir()
    s2.mkdir()
    (s1 / "x_manifest.json").write_text(json.dumps({"trade_dates_covered": ["2026-01-02"]}))
    (s2 / "x_manifest.json").write_text(json.dumps({"trade_dates_covered": ["2026-01-02"]}))  # overlap
    out = tmp_path / "merged.json"
    res = _run_cli(["--shard-dir", str(s1), "--shard-dir", str(s2), "--output", str(out)])
    assert res.returncode == 2
    assert "Disjoint-union violation" in res.stderr


def test_cli_returns_2_when_manifest_missing(tmp_path: Path) -> None:
    s1 = tmp_path / "shard-1"
    s1.mkdir()  # no manifest inside
    out = tmp_path / "merged.json"
    res = _run_cli(["--shard-dir", str(s1), "--output", str(out)])
    assert res.returncode == 2
    assert "No *_manifest.json" in res.stderr


def test_cli_returns_2_on_multiple_manifests_per_shard(tmp_path: Path) -> None:
    s1 = tmp_path / "shard-1"
    s1.mkdir()
    (s1 / "a_manifest.json").write_text("{}")
    (s1 / "b_manifest.json").write_text("{}")
    out = tmp_path / "merged.json"
    res = _run_cli(["--shard-dir", str(s1), "--output", str(out)])
    assert res.returncode == 2
    assert "Multiple manifests" in res.stderr


# ---------------------------------------------------------------------------
# Partial-run telemetry (a9b.3.1: --allow-partial / --expected-shard-count)
# ---------------------------------------------------------------------------

def test_expected_shard_count_complete_no_partial_flag(mod):
    merged = mod.merge_manifests(
        [{"a": 1}, {"a": 2}], expected_shard_count=2
    )
    assert merged["partial_run"] is False
    assert merged["failed_shard_ids"] == []
    assert merged["expected_shard_count"] == 2


def test_expected_shard_count_missing_strict_raises(mod):
    with pytest.raises(mod.ManifestMergeError, match=r"Missing shard\(s\) \[2\]"):
        mod.merge_manifests([{"a": 1}], shard_ids=[1], expected_shard_count=2)


def test_expected_shard_count_missing_with_allow_partial(mod):
    merged = mod.merge_manifests(
        [{"a": 1}], shard_ids=[1], expected_shard_count=3, allow_partial=True
    )
    assert merged["partial_run"] is True
    assert merged["failed_shard_ids"] == [2, 3]
    assert merged["expected_shard_count"] == 3
    assert merged["shard_ids"] == [1]
    assert merged["a"] == 1  # passthrough single-shard


def test_expected_shard_count_invalid_raises(mod):
    with pytest.raises(mod.ManifestMergeError, match="expected_shard_count must be"):
        mod.merge_manifests([{"a": 1}], expected_shard_count=0)


def test_shard_id_outside_expected_range_raises(mod):
    with pytest.raises(mod.ManifestMergeError, match="outside the expected"):
        mod.merge_manifests(
            [{"a": 1}, {"a": 2}], shard_ids=[1, 5], expected_shard_count=3
        )


def test_cli_allow_partial_emits_telemetry(tmp_path: Path) -> None:
    s1 = tmp_path / "shard-1"
    s1.mkdir()
    (s1 / "x_manifest.json").write_text(
        json.dumps({"a": 4, "trade_dates_covered": ["2026-01-02"]})
    )
    out = tmp_path / "merged.json"
    res = _run_cli(
        [
            "--shard-dir", str(s1),
            "--output", str(out),
            "--expected-shard-count", "2",
            "--allow-partial",
        ]
    )
    assert res.returncode == 0, res.stderr
    payload = json.loads(out.read_text())
    assert payload["partial_run"] is True
    assert payload["failed_shard_ids"] == [2]
    assert payload["expected_shard_count"] == 2
    assert "WARNING" in res.stdout
    assert "[2]" in res.stdout


def test_cli_allow_partial_without_expected_count_returns_2(tmp_path: Path) -> None:
    s1 = tmp_path / "shard-1"
    s1.mkdir()
    (s1 / "x_manifest.json").write_text(json.dumps({"a": 1}))
    out = tmp_path / "merged.json"
    res = _run_cli(["--shard-dir", str(s1), "--output", str(out), "--allow-partial"])
    assert res.returncode == 2
    assert "--allow-partial requires --expected-shard-count" in res.stderr


def test_cli_strict_missing_shard_returns_2(tmp_path: Path) -> None:
    s1 = tmp_path / "shard-1"
    s1.mkdir()
    (s1 / "x_manifest.json").write_text(json.dumps({"a": 1}))
    out = tmp_path / "merged.json"
    res = _run_cli(
        ["--shard-dir", str(s1), "--output", str(out), "--expected-shard-count", "2"]
    )
    assert res.returncode == 2
    assert "Missing shard" in res.stderr


def test_version_bumped(mod):
    # Reminder: bump MERGE_SCRIPT_VERSION on any output-shape change so
    # downstream consumers (and reduce-job log greps) can detect it.
    assert mod.MERGE_SCRIPT_VERSION == "a9b.3.2"
