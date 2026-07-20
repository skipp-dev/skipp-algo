"""Fallback search depth + age horizon for the Databento bundle restore.

Regression for 2026-07-13: the 3-page (300-artifact) listing window did not
reach back to the last good producer bundle after one weekend plus a red
producer morning, so the rolling benchmark aborted although a usable 3-day-old
fallback existed. The fallback must page deeper — but never restore a bundle
older than the age horizon.
"""
from __future__ import annotations

import json

from scripts import restore_databento_export_bundle as rb


def _artifact(name: str, created_at: str, run_id: int = 1) -> dict:
    return {
        "id": run_id,
        "name": name,
        "created_at": created_at,
        "expired": False,
        "size_in_bytes": 0,
        "workflow_run": {"id": run_id, "head_branch": "main"},
    }


def _filler(page: int, idx: int, created_at: str) -> dict:
    return {
        "id": page * 1000 + idx,
        "name": f"unrelated-artifact-{page}-{idx}",
        "created_at": created_at,
        "expired": False,
        "workflow_run": {"id": page * 1000 + idx, "head_branch": "main"},
    }


def _serve_pages(monkeypatch, pages: dict[int, list[dict]], requested: list[int]):
    def fake_api(token: str, path: str) -> dict:
        page = int(path.rsplit("page=", 1)[1])
        requested.append(page)
        return {"artifacts": pages.get(page, [])}

    monkeypatch.setattr(rb, "_api_get_json", fake_api)
    monkeypatch.setattr(rb, "_is_canonical_producer_run", lambda *a, **k: True)


def test_horizon_iso_is_run_date_minus_age_days() -> None:
    assert rb._horizon_iso("2026-07-20") == "2026-07-06T00:00:00Z"


def test_fallback_beyond_page_three_is_found(monkeypatch) -> None:
    # 4 full pages of unrelated same-day artifacts, the good bundle on page 5:
    # the old 3-page window returned nothing here.
    requested: list[int] = []
    pages = {
        page: [_filler(page, idx, "2026-07-13T10:00:00Z") for idx in range(100)]
        for page in range(1, 5)
    }
    pages[5] = [
        _artifact("smc-databento-production-export-2026-07-10-29128686705", "2026-07-10T22:47:26Z")
    ]
    _serve_pages(monkeypatch, pages, requested)
    got = rb._list_candidates(
        "tok", "o/r", "smc-databento-production-export-2026-07-13-", rb._horizon_iso("2026-07-13")
    )
    assert [item["name"] for item in got] == [
        "smc-databento-production-export-2026-07-10-29128686705"
    ]
    assert 5 in requested


def test_candidates_older_than_horizon_are_skipped(monkeypatch) -> None:
    requested: list[int] = []
    pages = {
        1: [_artifact("smc-databento-production-export-2026-06-01-1", "2026-06-01T10:00:00Z")]
    }
    _serve_pages(monkeypatch, pages, requested)
    got = rb._list_candidates(
        "tok", "o/r", "smc-databento-production-export-2026-07-13-", rb._horizon_iso("2026-07-13")
    )
    assert got == []


def test_paging_stops_once_a_full_page_predates_the_horizon(monkeypatch) -> None:
    requested: list[int] = []
    pages = {
        1: [_filler(1, idx, "2026-07-12T10:00:00Z") for idx in range(100)],
        2: [_filler(2, idx, "2026-06-01T10:00:00Z") for idx in range(100)],
        3: [_artifact("smc-databento-production-export-2026-05-01-9", "2026-05-01T10:00:00Z")],
    }
    _serve_pages(monkeypatch, pages, requested)
    got = rb._list_candidates(
        "tok", "o/r", "smc-databento-production-export-2026-07-13-", rb._horizon_iso("2026-07-13")
    )
    assert got == []
    assert requested == [1, 2]  # page 3 never fetched


def test_today_artifact_preferred_over_newer_fallback_name(monkeypatch) -> None:
    requested: list[int] = []
    pages = {
        1: [
            _artifact("smc-databento-production-export-2026-07-12-7", "2026-07-12T22:00:00Z", run_id=7),
            _artifact("smc-databento-production-export-2026-07-13-8", "2026-07-13T08:00:00Z", run_id=8),
        ]
    }
    _serve_pages(monkeypatch, pages, requested)
    got = rb._list_candidates(
        "tok", "o/r", "smc-databento-production-export-2026-07-13-", rb._horizon_iso("2026-07-13")
    )
    assert [item["name"] for item in got] == [
        "smc-databento-production-export-2026-07-13-8",
        "smc-databento-production-export-2026-07-12-7",
    ]


def test_larger_full_window_is_preferred_within_today(monkeypatch) -> None:
    requested: list[int] = []
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
    _serve_pages(monkeypatch, {1: [delta, full]}, requested)

    got = rb._list_candidates(
        "tok",
        "o/r",
        "smc-databento-production-export-2026-07-20-",
        rb._horizon_iso("2026-07-20"),
    )

    assert [item["id"] for item in got] == [8]


def test_fallback_keeps_largest_candidate_per_day_in_recency_order(monkeypatch) -> None:
    requested: list[int] = []
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
    _serve_pages(monkeypatch, {1: [newest_delta, newest_smaller_delta, older_full]}, requested)

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
