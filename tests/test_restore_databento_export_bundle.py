"""Fallback search depth + age horizon for the Databento bundle restore.

Regression for 2026-07-13: the 3-page (300-artifact) listing window did not
reach back to the last good producer bundle after one weekend plus a red
producer morning, so the rolling benchmark aborted although a usable 3-day-old
fallback existed. The fallback must page deeper — but never restore a bundle
older than the age horizon.
"""
from __future__ import annotations

from scripts import restore_databento_export_bundle as rb


def _artifact(name: str, created_at: str, run_id: int = 1) -> dict:
    return {
        "id": run_id,
        "name": name,
        "created_at": created_at,
        "expired": False,
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
    assert rb._horizon_iso("2026-07-13") == "2026-07-06T00:00:00Z"


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
