"""Tests for ``scripts/check_workflow_freshness.py``.

Exercises every classification path (``fresh`` / ``stale`` / ``missing``
/ ``api_error``), the CLI arg parser, and the exit-code contract.
All network calls are stubbed via the injected ``fetcher`` callable —
zero real HTTP.
"""

from __future__ import annotations

import json
import urllib.error
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts.check_workflow_freshness import (
    FreshnessReport,
    _parse_workflow_spec,
    check_all,
    check_workflow,
    main,
)

NOW = datetime(2026, 5, 29, 12, 0, 0, tzinfo=UTC)


def _ok_fetcher(age_hours: float):
    finished = (NOW - timedelta(hours=age_hours)).isoformat().replace("+00:00", "Z")

    def fetcher(url: str, headers: dict[str, str]) -> dict:
        # Sanity: the URL we build should target the right endpoint.
        assert "/actions/workflows/" in url
        assert "status=" in url
        assert headers["Authorization"].startswith("Bearer ")
        return {
            "workflow_runs": [
                {
                    "id": 9999,
                    "html_url": "https://github.com/owner/repo/actions/runs/9999",
                    "updated_at": finished,
                    "conclusion": "success",
                }
            ]
        }

    return fetcher


def _empty_fetcher(url: str, headers: dict[str, str]) -> dict:
    return {"workflow_runs": []}


def _broken_fetcher(url: str, headers: dict[str, str]) -> dict:
    raise urllib.error.URLError("connection refused")


# -- check_workflow ---------------------------------------------------------


def test_fresh_when_age_within_budget() -> None:
    r = check_workflow(
        repo="o/r",
        workflow_file="smc-library-refresh.yml",
        budget_hours=30.0,
        token="t",
        now=NOW,
        fetcher=_ok_fetcher(age_hours=12.0),
    )
    assert r.status == "fresh"
    assert r.age_hours == 12.0
    assert r.budget_hours == 30.0
    assert r.run_id == 9999
    assert r.run_url is not None


def test_stale_when_age_exceeds_budget() -> None:
    r = check_workflow(
        repo="o/r",
        workflow_file="smc-library-refresh.yml",
        budget_hours=24.0,
        token="t",
        now=NOW,
        fetcher=_ok_fetcher(age_hours=72.0),
    )
    assert r.status == "stale"
    assert r.age_hours == 72.0


def test_missing_when_no_runs_returned() -> None:
    r = check_workflow(
        repo="o/r",
        workflow_file="never-ran.yml",
        budget_hours=24.0,
        token="t",
        now=NOW,
        fetcher=_empty_fetcher,
    )
    assert r.status == "missing"
    assert r.last_success_at is None
    assert r.age_hours is None


def test_api_error_classified_distinct() -> None:
    r = check_workflow(
        repo="o/r",
        workflow_file="x.yml",
        budget_hours=24.0,
        token="t",
        now=NOW,
        fetcher=_broken_fetcher,
    )
    assert r.status == "api_error"
    assert r.detail is not None and "URLError" in r.detail


def test_api_error_when_run_missing_timestamp() -> None:
    def fetcher(url: str, headers: dict[str, str]) -> dict:
        return {"workflow_runs": [{"id": 1, "html_url": "x"}]}

    r = check_workflow(
        repo="o/r",
        workflow_file="x.yml",
        budget_hours=24.0,
        token="t",
        now=NOW,
        fetcher=fetcher,
    )
    assert r.status == "api_error"
    assert "updated_at" in (r.detail or "")


def test_any_conclusion_queries_status_completed() -> None:
    """When any_conclusion=True, the API query uses status=completed."""
    captured_urls: list[str] = []

    def fetcher(url: str, headers: dict[str, str]) -> dict:
        captured_urls.append(url)
        finished = (NOW - timedelta(hours=2.0)).isoformat().replace("+00:00", "Z")
        return {
            "workflow_runs": [
                {
                    "id": 1234,
                    "html_url": "https://github.com/o/r/actions/runs/1234",
                    "updated_at": finished,
                    "conclusion": "failure",
                }
            ]
        }

    r = check_workflow(
        repo="o/r",
        workflow_file="gate.yml",
        budget_hours=30.0,
        token="t",
        now=NOW,
        fetcher=fetcher,
        any_conclusion=True,
    )
    assert r.status == "fresh"
    assert r.age_hours == 2.0
    assert len(captured_urls) == 1
    assert "status=completed" in captured_urls[0]
    assert "status=success" not in captured_urls[0]


# -- check_all aggregation --------------------------------------------------


def test_check_all_overall_fresh() -> None:
    def fetcher(url: str, headers: dict[str, str]) -> dict:
        return _ok_fetcher(age_hours=2.0)(url, headers)

    report = check_all(
        repo="o/r",
        workflows=[("a.yml", 24.0, False), ("b.yml", 24.0, False)],
        token="t",
        now=NOW,
        fetcher=fetcher,
    )
    assert report.overall == "fresh"
    assert report.stale_count == 0 and report.missing_count == 0 and report.api_error_count == 0
    assert len(report.workflows) == 2


def test_check_all_overall_stale_when_any_stale() -> None:
    state = {"i": 0}
    fresh = _ok_fetcher(age_hours=2.0)
    stale = _ok_fetcher(age_hours=200.0)

    def fetcher(url: str, headers: dict[str, str]) -> dict:
        idx = state["i"]
        state["i"] += 1
        return (fresh if idx == 0 else stale)(url, headers)

    report = check_all(
        repo="o/r",
        workflows=[("a.yml", 24.0, False), ("b.yml", 24.0, False)],
        token="t",
        now=NOW,
        fetcher=fetcher,
    )
    assert report.overall == "stale"
    assert report.stale_count == 1


def test_check_all_overall_error_when_any_api_error() -> None:
    state = {"i": 0}
    ok = _ok_fetcher(age_hours=2.0)

    def fetcher(url: str, headers: dict[str, str]) -> dict:
        idx = state["i"]
        state["i"] += 1
        if idx == 0:
            return ok(url, headers)
        raise urllib.error.URLError("boom")

    report = check_all(
        repo="o/r",
        workflows=[("a.yml", 24.0, False), ("b.yml", 24.0, False)],
        token="t",
        now=NOW,
        fetcher=fetcher,
    )
    assert report.overall == "error"
    assert report.api_error_count == 1


# -- CLI parsing ------------------------------------------------------------


def test_parse_workflow_spec_ok() -> None:
    assert _parse_workflow_spec("ci.yml=24") == ("ci.yml", 24.0, False)
    assert _parse_workflow_spec("foo.yaml=1.5") == ("foo.yaml", 1.5, False)
    assert _parse_workflow_spec("gate.yml=30:any") == ("gate.yml", 30.0, True)


@pytest.mark.parametrize(
    "raw",
    [
        "no-equals.yml",
        "wrong-ext.txt=24",
        "ci.yml=zero",
        "ci.yml=-1",
        "ci.yml=0",
    ],
)
def test_parse_workflow_spec_rejects(raw: str) -> None:
    import argparse as _ap

    with pytest.raises(_ap.ArgumentTypeError):
        _parse_workflow_spec(raw)


# -- CLI integration --------------------------------------------------------


def _patch_check_all(monkeypatch: pytest.MonkeyPatch, report: FreshnessReport) -> None:
    monkeypatch.setattr(
        "scripts.check_workflow_freshness.check_all",
        lambda **kwargs: report,
    )


def test_cli_returns_zero_on_fresh(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    _patch_check_all(monkeypatch, FreshnessReport(overall="fresh", repo="owner/repo"))
    out = tmp_path / "r.json"
    rc = main(["ci.yml=24", "--output", str(out)])
    assert rc == 0
    parsed = json.loads(out.read_text(encoding="utf-8"))
    assert parsed["overall"] == "fresh"


def test_cli_returns_two_on_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    _patch_check_all(monkeypatch, FreshnessReport(overall="stale", stale_count=1, repo="owner/repo"))
    rc = main(["ci.yml=24"])
    assert rc == 2


def test_cli_returns_one_on_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    _patch_check_all(monkeypatch, FreshnessReport(overall="error", api_error_count=1, repo="owner/repo"))
    rc = main(["ci.yml=24"])
    assert rc == 1


def test_cli_returns_one_without_token(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_PAT", raising=False)
    rc = main(["ci.yml=24"])
    assert rc == 1
    assert "no token" in capsys.readouterr().err


def test_cli_returns_one_without_repo(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    rc = main(["ci.yml=24"])
    assert rc == 1
    assert "owner/name" in capsys.readouterr().err


def test_cli_falls_back_to_gh_pat_when_github_token_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GH_PAT", "pat-fallback")
    _patch_check_all(monkeypatch, FreshnessReport(overall="fresh", repo="owner/repo"))
    rc = main(["ci.yml=24"])
    assert rc == 0
