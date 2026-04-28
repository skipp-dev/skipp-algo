"""Tests for terminal_tabs.drift_loader (C8/T6)."""

from __future__ import annotations

import json
from pathlib import Path

from terminal_tabs.drift_loader import (
    DRIFT_FILENAME_PATTERN,
    DRIFT_SCHEMA_MAX_COMPATIBLE_MAJOR,
    DRIFT_SCHEMA_MIN_COMPATIBLE,
    DriftSchemaError,
    _check_drift_schema_version,
    _filter_excluded_variants,
    list_drift_dates,
    load_drift_artifact,
    resolve_drift_path,
)


def _write(path: Path, payload: dict | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")


def test_filename_pattern_matches_canonical() -> None:
    assert DRIFT_FILENAME_PATTERN.match("drift_2026-04-26.json")
    assert not DRIFT_FILENAME_PATTERN.match("drift_2026-4-26.json")
    assert not DRIFT_FILENAME_PATTERN.match("drift_latest.json")
    assert not DRIFT_FILENAME_PATTERN.match("backtest_2026-04-26.json")


def test_list_drift_dates_returns_empty_when_no_dir(tmp_path: Path) -> None:
    assert list_drift_dates(tmp_path) == []


def test_list_drift_dates_skips_non_matching(tmp_path: Path) -> None:
    live = tmp_path / "live"
    live.mkdir()
    (live / "drift_2026-04-25.json").write_text("{}")
    (live / "drift_2026-04-26.json").write_text("{}")
    (live / "README.md").write_text("nope")
    (live / "drift_latest.json").write_text("{}")
    assert list_drift_dates(tmp_path) == ["2026-04-25", "2026-04-26"]


def test_resolve_drift_path_explicit_date(tmp_path: Path) -> None:
    _write(tmp_path / "live" / "drift_2026-04-26.json", {})
    p = resolve_drift_path(tmp_path, as_of_date="2026-04-26")
    assert p is not None
    assert p.name == "drift_2026-04-26.json"


def test_resolve_drift_path_explicit_missing_returns_none(tmp_path: Path) -> None:
    _write(tmp_path / "live" / "drift_2026-04-26.json", {})
    assert resolve_drift_path(tmp_path, as_of_date="2026-04-30") is None


def test_resolve_drift_path_picks_newest(tmp_path: Path) -> None:
    _write(tmp_path / "live" / "drift_2026-04-25.json", {})
    _write(tmp_path / "live" / "drift_2026-04-27.json", {})
    _write(tmp_path / "live" / "drift_2026-04-26.json", {})
    p = resolve_drift_path(tmp_path)
    assert p is not None and p.name == "drift_2026-04-27.json"


def test_resolve_drift_path_none_when_empty(tmp_path: Path) -> None:
    assert resolve_drift_path(tmp_path) is None


def test_load_drift_artifact_returns_payload(tmp_path: Path) -> None:
    payload = {
        "computed_at": "2026-04-26T09:00:00Z",
        "live_window_days": 90,
        "variants": [
            {
                "variant": "v01",
                "n_live_trades": 30,
                "live_sharpe": 0.7,
                "backtest_sharpe": 0.8,
                "drift_score": 0.92,
                "verdict": "pass",
            }
        ],
    }
    _write(tmp_path / "live" / "drift_2026-04-26.json", payload)
    out = load_drift_artifact(tmp_path)
    assert out == payload


def test_load_drift_artifact_returns_none_on_corrupt(tmp_path: Path) -> None:
    _write(tmp_path / "live" / "drift_2026-04-26.json", "{not json")
    assert load_drift_artifact(tmp_path) is None


def test_load_drift_artifact_returns_none_on_non_object(tmp_path: Path) -> None:
    _write(tmp_path / "live" / "drift_2026-04-26.json", "[1,2,3]")
    assert load_drift_artifact(tmp_path) is None


def test_load_drift_artifact_none_on_empty_dir(tmp_path: Path) -> None:
    assert load_drift_artifact(tmp_path) is None


def test_load_drift_artifact_feeds_build_live_view(tmp_path: Path) -> None:
    """Smoke: loader output is consumed by the C7 tab without errors."""
    from terminal_tabs.tab_live_incubation import build_live_view

    _write(
        tmp_path / "live" / "drift_2026-04-26.json",
        {
            "computed_at": "2026-04-26T09:00:00Z",
            "live_window_days": 90,
            "variants": [
                {
                    "variant": "v01",
                    "n_live_trades": 30,
                    "live_sharpe": 0.7,
                    "backtest_sharpe": 0.8,
                    "drift_score": 0.92,
                    "verdict": "pass",
                }
            ],
        },
    )
    payload = load_drift_artifact(tmp_path)
    view = build_live_view(payload)
    assert view["status"] != "awaiting_c8"
    assert len(view["rows"]) == 1


def test_filter_excluded_variants_drops_listed(tmp_path: Path) -> None:
    payload = {"variants": [{"variant": "v01"}, {"variant": "v02"}]}
    out = _filter_excluded_variants(payload, excluded=["v01"])
    assert out is not None
    assert [v["variant"] for v in out["variants"]] == ["v02"]


def test_filter_excluded_variants_passthrough_when_none() -> None:
    payload = {"variants": [{"variant": "v01"}]}
    assert _filter_excluded_variants(payload, excluded=None) is payload
    assert _filter_excluded_variants(None, excluded=["v01"]) is None


# --- Schema-version range check (Deep-Review C8 fix 2026-04-27) ---


def test_check_drift_schema_version_accepts_missing_field() -> None:
    """Pre-bump artifacts on disk during rollout must still be loadable."""
    _check_drift_schema_version({"variants": []})


def test_check_drift_schema_version_accepts_minimum() -> None:
    _check_drift_schema_version({"schema_version": DRIFT_SCHEMA_MIN_COMPATIBLE})


def test_check_drift_schema_version_accepts_additive_minor() -> None:
    """A producer ahead by MINOR must be accepted (additive contract)."""
    _check_drift_schema_version({"schema_version": "1.99.0"})


def test_check_drift_schema_version_rejects_higher_major() -> None:
    bad = f"{DRIFT_SCHEMA_MAX_COMPATIBLE_MAJOR + 1}.0.0"
    try:
        _check_drift_schema_version({"schema_version": bad})
    except DriftSchemaError as exc:
        assert "MAJOR" in str(exc)
    else:
        raise AssertionError(f"expected DriftSchemaError for {bad}")


def test_check_drift_schema_version_rejects_unparseable() -> None:
    try:
        _check_drift_schema_version({"schema_version": "not-a-version"})
    except DriftSchemaError as exc:
        assert "semver" in str(exc).lower()
    else:
        raise AssertionError("expected DriftSchemaError for unparseable version")


def test_check_drift_schema_version_rejects_non_string() -> None:
    try:
        _check_drift_schema_version({"schema_version": 1})
    except DriftSchemaError:
        pass
    else:
        raise AssertionError("expected DriftSchemaError for non-string version")


def test_load_drift_artifact_returns_none_on_incompatible_major(
    tmp_path: Path,
) -> None:
    """End-to-end: incompatible MAJOR makes the loader silent-skip."""
    bad_major = f"{DRIFT_SCHEMA_MAX_COMPATIBLE_MAJOR + 1}.0.0"
    _write(
        tmp_path / "live" / "drift_2026-04-26.json",
        {"schema_version": bad_major, "variants": []},
    )
    assert load_drift_artifact(tmp_path) is None


def test_load_drift_artifact_accepts_current_major(tmp_path: Path) -> None:
    _write(
        tmp_path / "live" / "drift_2026-04-26.json",
        {"schema_version": "1.0.0", "variants": []},
    )
    out = load_drift_artifact(tmp_path)
    assert out is not None and out["variants"] == []


def test_compute_live_drift_emits_schema_version() -> None:
    """Producer-side: the artifact carries the schema version."""
    from scripts.compute_live_drift import (
        DRIFT_SCHEMA_VERSION,
        compute_live_drift,
    )

    payload = compute_live_drift(
        live_rows=[],
        backtest_reference={},
    )
    assert payload["schema_version"] == DRIFT_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# C13/T2 — load_recent_drift_artifacts (rolling history loader)
# ---------------------------------------------------------------------------


def _write_drift(live: Path, date_str: str, payload: dict | None = None) -> None:
    payload = payload or {"schema_version": "1.0.0", "computed_at": date_str}
    _write(live / f"drift_{date_str}.json", payload)


def test_load_recent_drift_artifacts_empty_dir(tmp_path: Path) -> None:
    from terminal_tabs.drift_loader import load_recent_drift_artifacts

    assert load_recent_drift_artifacts(tmp_path) == []


def test_load_recent_drift_artifacts_n_zero_returns_empty(tmp_path: Path) -> None:
    from terminal_tabs.drift_loader import load_recent_drift_artifacts

    _write_drift(tmp_path / "live", "2026-04-26")
    assert load_recent_drift_artifacts(tmp_path, n=0) == []


def test_load_recent_drift_artifacts_negative_n_raises(tmp_path: Path) -> None:
    import pytest

    from terminal_tabs.drift_loader import load_recent_drift_artifacts

    with pytest.raises(ValueError, match="non-negative"):
        load_recent_drift_artifacts(tmp_path, n=-1)


def test_load_recent_drift_artifacts_returns_newest_first(tmp_path: Path) -> None:
    from terminal_tabs.drift_loader import load_recent_drift_artifacts

    live = tmp_path / "live"
    _write_drift(live, "2026-04-25")
    _write_drift(live, "2026-04-27")
    _write_drift(live, "2026-04-26")
    out = load_recent_drift_artifacts(tmp_path, n=7)
    assert [d["as_of_date"] for d in out] == [
        "2026-04-27",
        "2026-04-26",
        "2026-04-25",
    ]


def test_load_recent_drift_artifacts_caps_at_n(tmp_path: Path) -> None:
    from terminal_tabs.drift_loader import load_recent_drift_artifacts

    live = tmp_path / "live"
    for day in range(1, 11):  # 04-01 .. 04-10
        _write_drift(live, f"2026-04-{day:02d}")
    out = load_recent_drift_artifacts(tmp_path, n=7)
    assert len(out) == 7
    assert out[0]["as_of_date"] == "2026-04-10"
    assert out[-1]["as_of_date"] == "2026-04-04"


def test_load_recent_drift_artifacts_skips_corrupt(tmp_path: Path) -> None:
    from terminal_tabs.drift_loader import load_recent_drift_artifacts

    live = tmp_path / "live"
    _write_drift(live, "2026-04-25")
    _write(live / "drift_2026-04-26.json", "{not json")
    _write_drift(live, "2026-04-27")
    out = load_recent_drift_artifacts(tmp_path, n=10)
    assert [d["as_of_date"] for d in out] == ["2026-04-27", "2026-04-25"]


def test_load_recent_drift_artifacts_default_n_is_seven(tmp_path: Path) -> None:
    from terminal_tabs.drift_loader import (
        DRIFT_HISTORY_DEFAULT_N,
        load_recent_drift_artifacts,
    )

    assert DRIFT_HISTORY_DEFAULT_N == 7
    live = tmp_path / "live"
    for day in range(1, 11):
        _write_drift(live, f"2026-04-{day:02d}")
    out = load_recent_drift_artifacts(tmp_path)  # default n
    assert len(out) == DRIFT_HISTORY_DEFAULT_N
