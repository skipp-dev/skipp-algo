"""Candidate discovery + age horizon for the Databento bundle restore.

Two regressions live here:

* 2026-07-13 — the then 3-page (300-artifact) window of the repo-wide artifact
  index did not reach back to the last good producer bundle. The fallback had
  to look further back, but never restore a bundle older than the age horizon.
* 2026-10-01 — that repo-wide index itself answers HTTP 500 since 2026-09-25,
  which killed the restore step of the rolling benchmark and of
  smc-library-refresh outright. Discovery now asks the canonical PRODUCER
  workflow for its runs and each run for its artifacts; the index is never
  touched again, and paging depth stops being a heuristic.
"""
from __future__ import annotations

import json
import re
import urllib.error

import pytest

from scripts import restore_databento_export_bundle as rb

_RUNS_PATH = re.compile(
    r"repos/o/r/actions/workflows/smc-databento-production-export-sharded\.yml/runs"
    r"\?branch=main&created=%3E%3D(\d{4}-\d{2}-\d{2})&per_page=100&page=(\d+)"
)
_RUN_ARTIFACTS_PATH = re.compile(r"repos/o/r/actions/runs/(\d+)/artifacts\?per_page=100")


def _artifact(name: str, created_at: str, run_id: int = 1) -> dict:
    return {
        "id": run_id,
        "name": name,
        "created_at": created_at,
        "expired": False,
        "size_in_bytes": 0,
        "workflow_run": {"id": run_id, "head_branch": "main"},
    }


def _serve(
    monkeypatch,
    artifacts: list[dict],
    requested: list[str],
    *,
    extra_run_ids: tuple[int, ...] = (),
    broken_run_ids: tuple[int, ...] = (),
):
    """Fake the two endpoints the helper may use — and ONLY those.

    Every artifact belongs to the producer run named in its ``workflow_run``;
    ``extra_run_ids`` are producer runs without any artifact. Any other path
    (above all the repo-wide ``/actions/artifacts`` index) is an error.
    """
    by_run: dict[int, list[dict]] = {run_id: [] for run_id in extra_run_ids}
    for item in artifacts:
        by_run.setdefault(int(item["workflow_run"]["id"]), []).append(item)
    run_ids = sorted(by_run, reverse=True)  # the API lists newest first

    def fake_api(token: str, path: str) -> dict:
        requested.append(path)
        runs = _RUNS_PATH.fullmatch(path)
        if runs:
            page = int(runs.group(2))
            chunk = run_ids[(page - 1) * 100 : page * 100]
            return {"workflow_runs": [{"id": run_id} for run_id in chunk]}
        run_artifacts = _RUN_ARTIFACTS_PATH.fullmatch(path)
        if run_artifacts:
            run_id = int(run_artifacts.group(1))
            if run_id in broken_run_ids:
                raise urllib.error.HTTPError(path, 500, "Internal Server Error", None, None)
            return {"artifacts": by_run[run_id]}
        raise AssertionError(f"unexpected API path: {path}")

    monkeypatch.setattr(rb, "_api_get_json", fake_api)


def test_horizon_iso_is_run_date_minus_age_days() -> None:
    assert rb._horizon_iso("2026-07-20") == "2026-07-06T00:00:00Z"


def test_discovery_never_touches_the_repo_wide_artifact_index(monkeypatch) -> None:
    """Regression 2026-10-01: that index answers HTTP 500 — do not go there.

    ``_serve`` already raises on any unknown path; this test states the
    contract in the positive: the run listing is scoped to the canonical
    producer FILE, to ``main`` and to the horizon date, and artifacts are read
    per run.
    """
    requested: list[str] = []
    _serve(
        monkeypatch,
        [_artifact("smc-databento-production-export-2026-07-10-29128686705", "2026-07-10T22:47:26Z", run_id=29128686705)],
        requested,
    )
    got = rb._list_candidates(
        "tok", "o/r", "smc-databento-production-export-2026-07-13-", rb._horizon_iso("2026-07-13")
    )
    assert [item["name"] for item in got] == [
        "smc-databento-production-export-2026-07-10-29128686705"
    ]
    assert not [path for path in requested if "/actions/artifacts" in path], requested
    first = _RUNS_PATH.fullmatch(requested[0])
    assert first is not None, requested[0]
    assert first.group(1) == "2026-06-29"  # run date minus the 14-day horizon
    assert requested[1:] == ["repos/o/r/actions/runs/29128686705/artifacts?per_page=100"]


def test_a_good_bundle_is_found_however_many_other_artifacts_the_run_carries(monkeypatch) -> None:
    """2026-07-13, restated: depth is no longer a heuristic.

    The producer uploads eight sibling artifacts per run (shards, plan, merged
    manifest — measured 2026-10-01 on run 36836565487). Only the export bundle
    is a candidate; the siblings neither hide it nor become candidates.
    """
    requested: list[str] = []
    siblings = [
        _artifact(f"a9b-2b-shard-{idx}-of-6", "2026-07-10T22:40:00Z", run_id=5) for idx in range(1, 7)
    ] + [
        _artifact("a9b-2b-merged-manifest", "2026-07-10T22:46:00Z", run_id=5),
        _artifact("a9b-2a-shard-plan", "2026-07-10T22:00:00Z", run_id=5),
    ]
    bundle = _artifact("smc-databento-production-export-2026-07-10-5", "2026-07-10T22:47:26Z", run_id=5)
    _serve(monkeypatch, [*siblings, bundle], requested)
    got = rb._list_candidates(
        "tok", "o/r", "smc-databento-production-export-2026-07-13-", rb._horizon_iso("2026-07-13")
    )
    assert [item["name"] for item in got] == ["smc-databento-production-export-2026-07-10-5"]


def test_candidates_older_than_horizon_are_skipped(monkeypatch) -> None:
    requested: list[str] = []
    _serve(
        monkeypatch,
        [_artifact("smc-databento-production-export-2026-06-01-1", "2026-06-01T10:00:00Z")],
        requested,
    )
    got = rb._list_candidates(
        "tok", "o/r", "smc-databento-production-export-2026-07-13-", rb._horizon_iso("2026-07-13")
    )
    assert got == []


def test_expired_and_non_main_artifacts_are_skipped(monkeypatch) -> None:
    requested: list[str] = []
    expired = _artifact("smc-databento-production-export-2026-07-12-3", "2026-07-12T10:00:00Z", run_id=3)
    expired["expired"] = True
    off_main = _artifact("smc-databento-production-export-2026-07-12-4", "2026-07-12T11:00:00Z", run_id=4)
    off_main["workflow_run"]["head_branch"] = "feature/x"
    _serve(monkeypatch, [expired, off_main], requested)
    got = rb._list_candidates(
        "tok", "o/r", "smc-databento-production-export-2026-07-13-", rb._horizon_iso("2026-07-13")
    )
    assert got == []


def test_run_listing_pages_until_a_short_page(monkeypatch) -> None:
    """More than 100 producer runs inside the horizon: page 2 is read too."""
    requested: list[str] = []
    oldest = _artifact("smc-databento-production-export-2026-07-01-1", "2026-07-01T09:00:00Z", run_id=1)
    _serve(monkeypatch, [oldest], requested, extra_run_ids=tuple(range(1000, 1149)))
    got = rb._list_candidates(
        "tok", "o/r", "smc-databento-production-export-2026-07-13-", rb._horizon_iso("2026-07-13")
    )
    assert [item["id"] for item in got] == [1]
    pages = [int(m.group(2)) for m in map(_RUNS_PATH.fullmatch, requested) if m]
    assert pages == [1, 2]


def test_one_unreadable_run_does_not_cost_the_whole_restore(monkeypatch, capsys) -> None:
    requested: list[str] = []
    good = _artifact("smc-databento-production-export-2026-07-12-7", "2026-07-12T22:00:00Z", run_id=7)
    lost = _artifact("smc-databento-production-export-2026-07-13-8", "2026-07-13T08:00:00Z", run_id=8)
    _serve(monkeypatch, [good, lost], requested, broken_run_ids=(8,))
    got = rb._list_candidates(
        "tok", "o/r", "smc-databento-production-export-2026-07-13-", rb._horizon_iso("2026-07-13")
    )
    assert [item["id"] for item in got] == [7]
    assert "::warning::Could not list artifacts of producer run 8" in capsys.readouterr().out


def test_an_unreadable_run_list_is_not_swallowed(monkeypatch) -> None:
    """Without the producer's run list there is nothing to restore from.

    Returning ``[]`` here would read as "no candidates" and hand the decision
    to a later step; the honest outcome is this step's own red.
    """

    def fake_api(token: str, path: str) -> dict:
        raise urllib.error.HTTPError(path, 500, "Internal Server Error", None, None)

    monkeypatch.setattr(rb, "_api_get_json", fake_api)
    with pytest.raises(urllib.error.HTTPError):
        rb._list_candidates(
            "tok", "o/r", "smc-databento-production-export-2026-07-13-", rb._horizon_iso("2026-07-13")
        )


def test_today_artifact_preferred_over_newer_fallback_name(monkeypatch) -> None:
    requested: list[str] = []
    artifacts = [
        _artifact("smc-databento-production-export-2026-07-12-7", "2026-07-12T22:00:00Z", run_id=7),
        _artifact("smc-databento-production-export-2026-07-13-8", "2026-07-13T08:00:00Z", run_id=8),
    ]
    _serve(monkeypatch, artifacts, requested)
    got = rb._list_candidates(
        "tok", "o/r", "smc-databento-production-export-2026-07-13-", rb._horizon_iso("2026-07-13")
    )
    assert [item["name"] for item in got] == [
        "smc-databento-production-export-2026-07-13-8",
        "smc-databento-production-export-2026-07-12-7",
    ]


def test_larger_full_window_is_preferred_within_today(monkeypatch) -> None:
    requested: list[str] = []
    delta = _artifact(
        "smc-databento-production-export-2026-07-20-9",
        "2026-07-20T22:00:00Z",
        run_id=9,
    )
    delta["size_in_bytes"] = 6_000_000
    full = _artifact(
        "smc-databento-production-export-2026-07-20-8",
        "2026-07-20T09:00:00Z",
        run_id=8,
    )
    full["size_in_bytes"] = 80_000_000
    _serve(monkeypatch, [delta, full], requested)

    got = rb._list_candidates(
        "tok",
        "o/r",
        "smc-databento-production-export-2026-07-20-",
        rb._horizon_iso("2026-07-20"),
    )

    assert [item["id"] for item in got] == [8]


def test_fallback_keeps_largest_candidate_per_day_in_recency_order(monkeypatch) -> None:
    requested: list[str] = []
    newest_delta = _artifact(
        "smc-databento-production-export-2026-07-19-12",
        "2026-07-19T22:00:00Z",
        run_id=12,
    )
    newest_delta["size_in_bytes"] = 7_000_000
    newest_smaller_delta = _artifact(
        "smc-databento-production-export-2026-07-19-11",
        "2026-07-19T20:00:00Z",
        run_id=11,
    )
    newest_smaller_delta["size_in_bytes"] = 6_000_000
    older_full = _artifact(
        "smc-databento-production-export-2026-07-18-10",
        "2026-07-18T09:00:00Z",
        run_id=10,
    )
    older_full["size_in_bytes"] = 80_000_000
    _serve(monkeypatch, [newest_delta, newest_smaller_delta, older_full], requested)

    got = rb._list_candidates(
        "tok",
        "o/r",
        "smc-databento-production-export-2026-07-20-",
        rb._horizon_iso("2026-07-20"),
    )

    assert [item["id"] for item in got] == [12, 10]


def test_trade_days_covered_requires_one_valid_manifest(tmp_path) -> None:
    manifest = tmp_path / "databento_volatility_production_merged_manifest.json"
    manifest.write_text(
        json.dumps({"trade_dates_covered": ["2026-07-17", "2026-07-18", "2026-07-18", None]}),
        encoding="utf-8",
    )
    assert rb._trade_days_covered(tmp_path) == 2

    manifest.write_text("not json", encoding="utf-8")
    assert rb._trade_days_covered(tmp_path) == 0


def test_trade_days_covered_rejects_declared_delta_even_when_deep(tmp_path) -> None:
    manifest = tmp_path / "databento_volatility_production_merged_manifest.json"
    dates = [f"2026-07-{day:02d}" for day in range(1, 21)]
    manifest.write_text(
        json.dumps(
            {
                "artifact_contract_version": 1,
                "artifact_scope": "delta",
                "coverage_trade_days": len(dates),
                "trade_dates_covered": dates,
            }
        ),
        encoding="utf-8",
    )

    assert rb._trade_days_covered(tmp_path) == 0


def test_trade_days_covered_rejects_inconsistent_declared_coverage(tmp_path) -> None:
    manifest = tmp_path / "databento_volatility_production_merged_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "artifact_contract_version": 1,
                "artifact_scope": "full_window",
                "coverage_trade_days": 20,
                "trade_dates_covered": ["2026-07-17", "2026-07-18"],
            }
        ),
        encoding="utf-8",
    )

    assert rb._trade_days_covered(tmp_path) == 0
