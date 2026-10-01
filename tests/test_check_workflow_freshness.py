"""Tests for ``scripts/check_workflow_freshness.py``.

Exercises every classification path (``fresh`` / ``stale`` / ``missing``
/ ``api_error``), the CLI arg parser, and the exit-code contract.
All network calls are stubbed via the injected ``fetcher`` callable —
zero real HTTP.
"""

from __future__ import annotations

import json
import urllib.error
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from scripts.check_workflow_freshness import (
    FreshnessReport,
    _parse_product_spec,
    _parse_workflow_spec,
    _weekend_hours_between,
    check_all,
    check_product,
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


def test_expected_stale_inside_declared_window() -> None:
    """A dated declaration turns stale into acknowledged expected_stale."""
    r = check_workflow(
        repo="o/r",
        workflow_file="openprep-pine-panel-publish.yml",
        budget_hours=24.0,
        token="t",
        now=NOW,
        fetcher=_ok_fetcher(age_hours=72.0),
        expected_stale_until=date(2026, 5, 30),
    )
    assert r.status == "expected_stale"
    assert r.expected_stale_until == "2026-05-30"
    assert "expires 2026-05-30" in (r.detail or "")


def test_expected_stale_expires_hard_under_a_shifted_clock() -> None:
    """Both sides of the date comparison, DELIVERED by shifting ``now``.

    The declaration is a tripwire, not a mute: the last declared day still
    gates, the day after fails hard again with an EXPIRED detail.
    """
    kwargs: dict = dict(
        repo="o/r",
        workflow_file="openprep-pine-panel-publish.yml",
        budget_hours=24.0,
        token="t",
        fetcher=_ok_fetcher(age_hours=72.0),
        expected_stale_until=date(2026, 5, 30),
    )
    last_day = check_workflow(now=datetime(2026, 5, 30, 23, 59, tzinfo=UTC), **kwargs)
    assert last_day.status == "expected_stale"

    day_after = check_workflow(now=datetime(2026, 5, 31, 0, 1, tzinfo=UTC), **kwargs)
    assert day_after.status == "stale"
    assert "EXPIRED 2026-05-30" in (day_after.detail or "")


def test_expected_stale_declaration_never_touches_a_fresh_row() -> None:
    r = check_workflow(
        repo="o/r",
        workflow_file="openprep-pine-panel-publish.yml",
        budget_hours=30.0,
        token="t",
        now=NOW,
        fetcher=_ok_fetcher(age_hours=12.0),
        expected_stale_until=date(2026, 5, 30),
    )
    assert r.status == "fresh"
    assert r.detail is None


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


def test_check_all_expected_stale_yields_zero_exit_but_real_stale_still_wins() -> None:
    stale = _ok_fetcher(age_hours=200.0)

    # Only an acknowledged row: overall expected_stale, counted separately.
    report = check_all(
        repo="o/r",
        workflows=[("a.yml", 24.0, False, False, date(2026, 5, 30))],
        token="t",
        now=NOW,
        fetcher=stale,
    )
    assert report.overall == "expected_stale"
    assert report.expected_stale_count == 1
    assert report.stale_count == 0

    # An acknowledged row NEXT TO an unrelated stale row: the unrelated one
    # must still fail the probe — that is the whole point of the gate.
    report = check_all(
        repo="o/r",
        workflows=[
            ("a.yml", 24.0, False, False, date(2026, 5, 30)),
            ("b.yml", 24.0, False),
        ],
        token="t",
        now=NOW,
        fetcher=stale,
    )
    assert report.overall == "stale"
    assert report.stale_count == 1
    assert report.expected_stale_count == 1


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
    assert _parse_workflow_spec("ci.yml=24") == ("ci.yml", 24.0, False, False, None)
    assert _parse_workflow_spec("foo.yaml=1.5") == ("foo.yaml", 1.5, False, False, None)
    assert _parse_workflow_spec("gate.yml=30:any") == ("gate.yml", 30.0, True, False, None)
    assert _parse_workflow_spec("gate.yml=30:weekday") == ("gate.yml", 30.0, False, True, None)
    assert _parse_workflow_spec("gate.yml=30:any:weekday") == ("gate.yml", 30.0, True, True, None)
    assert _parse_workflow_spec("gate.yml=30:weekday:any") == ("gate.yml", 30.0, True, True, None)
    assert _parse_workflow_spec(
        "gate.yml=30:weekday:expected-stale-until=2026-09-04"
    ) == ("gate.yml", 30.0, False, True, date(2026, 9, 4))
    # `:success` is the explicit alias for the default success-only mode
    # (meta-watchdog DAG probe pins `:success:weekday`).
    assert _parse_workflow_spec("pipe.yml=14:success:weekday") == (
        "pipe.yml", 14.0, False, True, None,
    )


@pytest.mark.parametrize(
    "raw",
    [
        "no-equals.yml",
        "wrong-ext.txt=24",
        "ci.yml=zero",
        "ci.yml=-1",
        "ci.yml=0",
        # A typo'd suffix that parsed silently would neuter the very
        # guarantee it claims to configure.
        "ci.yml=24:weekdya",
        "ci.yml=24:expected-stale-until=tomorrow",
        "ci.yml=24:expected-stale-until=",
        "ci.yml=24:any:success",
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


def test_cli_returns_zero_on_expected_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    """An acknowledged incident must not fail the probe (and files no issue)."""
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    _patch_check_all(
        monkeypatch,
        FreshnessReport(overall="expected_stale", expected_stale_count=1, repo="owner/repo"),
    )
    rc = main(["ci.yml=24:expected-stale-until=2026-09-04"])
    assert rc == 0


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


# -- Weekend-aware check tests ----------------------------------------------


def test_weekend_hours_between_calculation() -> None:
    # Friday 12:00 UTC to Monday 12:00 UTC = 72 hours total, should have 48 hours of weekend (Saturday/Sunday)
    start = datetime(2026, 5, 29, 12, 0, 0, tzinfo=UTC)  # Friday
    end = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)    # Monday
    assert _weekend_hours_between(start, end) == 48.0

    # Thursday 12:00 UTC to Friday 12:00 UTC = 24 hours total, 0 weekend hours
    start_midweek = datetime(2026, 5, 28, 12, 0, 0, tzinfo=UTC)
    end_midweek = datetime(2026, 5, 29, 12, 0, 0, tzinfo=UTC)
    assert _weekend_hours_between(start_midweek, end_midweek) == 0.0

    # Saturday 00:00 to Sunday 24:00 = 48 hours
    start_weekend = datetime(2026, 5, 30, 0, 0, 0, tzinfo=UTC)
    end_weekend = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
    assert _weekend_hours_between(start_weekend, end_weekend) == 48.0

    # Sub-hour accuracy: Friday 23:30 to Saturday 00:30 = 1 hour total, 0.5 hours weekend (Saturday)
    start_frac = datetime(2026, 5, 29, 23, 30, 0, tzinfo=UTC)
    end_frac = datetime(2026, 5, 30, 0, 30, 0, tzinfo=UTC)
    assert _weekend_hours_between(start_frac, end_frac) == 0.5

    # Reverse or equal times
    assert _weekend_hours_between(end, start) == 0.0
    assert _weekend_hours_between(start, start) == 0.0

    # Extremely long gaps clamped to 1000 hours
    start_long = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    end_long = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
    # 1000 hour range has some number of weekend hours, but it should be calculated safely and fast without hanging
    wk_h = _weekend_hours_between(start_long, end_long)
    assert wk_h > 0.0


def test_weekday_only_workflow_freshness() -> None:
    # A weekend-only gap where 60 hours have elapsed since the Friday run.
    # Check is done on Monday.
    # Friday 18:00 UTC
    last_run = datetime(2026, 5, 29, 18, 0, 0, tzinfo=UTC)
    # Monday 06:00 UTC
    now = datetime(2026, 6, 1, 6, 0, 0, tzinfo=UTC)

    # Standard check: elapsed age is 60 hours, which is > 30 hours, so "stale"
    def fetcher(url: str, headers: dict[str, str]) -> dict:
        return {
            "workflow_runs": [
                {
                    "id": 1111,
                    "html_url": "x",
                    "updated_at": last_run.isoformat().replace("+00:00", "Z"),
                }
            ]
        }

    r_standard = check_workflow(
        repo="o/r",
        workflow_file="daily.yml",
        budget_hours=30.0,
        token="t",
        now=now,
        fetcher=fetcher,
        weekday_only=False,
    )
    assert r_standard.status == "stale"
    assert r_standard.age_hours == 60.0

    # Weekday-only check: subtracts 48 hours, adjusted age is 12 hours <= 30, so "fresh"
    r_weekday = check_workflow(
        repo="o/r",
        workflow_file="daily.yml",
        budget_hours=30.0,
        token="t",
        now=now,
        fetcher=fetcher,
        weekday_only=True,
    )
    assert r_weekday.status == "fresh"
    assert r_weekday.age_hours == 12.0


# ---------------------------------------------------------------------------
# Product rows (2026-10-01): the age of what the chain is FOR.
#
# A run-based row cannot tell a green run from a green-but-idle one. Measured
# 2026-10-01: promotion-gate-daily ended `success` on 17 of 18 runs since
# 2026-08-31 while skipping its body; its row stayed fresh, the newest gate
# report on main was dated 2026-08-27.
# ---------------------------------------------------------------------------

_GATE_GLOB = "docs/calibration/gates/track_record_gate_*.json"


def _gate_files(root: Path, *days: str) -> None:
    gates = root / "docs" / "calibration" / "gates"
    gates.mkdir(parents=True, exist_ok=True)
    for day in days:
        (gates / f"track_record_gate_{day}.json").write_text("{}", encoding="utf-8")


def _product(root: Path, now: datetime, **kwargs):
    return check_product(
        pattern=_GATE_GLOB, budget_hours=72, now=now, root=str(root), **kwargs
    )


@pytest.mark.parametrize(
    ("label", "newest", "now", "expect"),
    [
        # Probe runs 06:30 UTC; a report dated D counts from D 00:00 UTC.
        ("yesterday's report, normal morning", "2026-09-22", "2026-09-23T06:30", "fresh"),
        ("one business day missing", "2026-09-21", "2026-09-23T06:30", "fresh"),
        ("two business days missing", "2026-09-21", "2026-09-24T06:30", "stale"),
        ("Friday's report on Monday", "2026-09-25", "2026-09-28T06:30", "fresh"),
        ("Friday's report on Tuesday", "2026-09-25", "2026-09-29T06:30", "fresh"),
        ("Friday's report on Wednesday", "2026-09-25", "2026-09-30T06:30", "stale"),
    ],
)
def test_product_budget_trips_after_two_missing_business_days(
    tmp_path: Path, label: str, newest: str, now: str, expect: str
) -> None:
    _gate_files(tmp_path, "2026-09-01", newest)
    row = _product(
        tmp_path, datetime.fromisoformat(now).replace(tzinfo=UTC), weekday_only=True
    )
    assert row.status == expect, f"{label}: age {row.age_hours}h"
    assert row.workflow == f"product:{_GATE_GLOB}"
    assert row.timestamp_source == "filename_date"
    assert row.last_success_at.startswith(newest)


def test_product_the_measured_situation_is_stale_while_the_run_row_is_fresh(
    tmp_path: Path,
) -> None:
    """2026-10-01 as it was: gate run green yesterday, newest report 2026-08-27."""
    now = datetime(2026, 10, 1, 6, 30, tzinfo=UTC)
    _gate_files(tmp_path, "2026-08-25", "2026-08-26", "2026-08-27")

    def green_yesterday(url: str, headers: dict[str, str]) -> dict:
        return {"workflow_runs": [{"id": 1, "updated_at": "2026-09-30T14:05:00Z"}]}

    report = check_all(
        repo="o/r",
        workflows=[("promotion-gate-daily.yml", 72.0, False, True)],
        token="t",
        now=now,
        fetcher=green_yesterday,
        products=[(_GATE_GLOB, 72.0, True, None)],
        root=str(tmp_path),
    )
    by_name = {row["workflow"]: row for row in report.workflows}
    assert by_name["promotion-gate-daily.yml"]["status"] == "fresh"
    assert by_name[f"product:{_GATE_GLOB}"]["status"] == "stale"
    assert report.overall == "stale"
    assert report.stale_count == 1


def test_product_weekday_flag_is_what_keeps_monday_green(tmp_path: Path) -> None:
    _gate_files(tmp_path, "2026-09-25")  # a Friday
    monday = datetime(2026, 9, 28, 6, 30, tzinfo=UTC)
    assert _product(tmp_path, monday, weekday_only=True).status == "fresh"
    assert _product(tmp_path, monday, weekday_only=False).status == "stale"


def test_product_missing_when_nothing_dated_matches(tmp_path: Path) -> None:
    now = datetime(2026, 9, 23, 6, 30, tzinfo=UTC)
    assert _product(tmp_path, now).status == "missing"  # directory absent
    gates = tmp_path / "docs" / "calibration" / "gates"
    gates.mkdir(parents=True)
    (gates / "track_record_gate_latest.json").write_text("{}", encoding="utf-8")
    (gates / "track_record_gate_2026-13-45.json").write_text("{}", encoding="utf-8")
    row = _product(tmp_path, now)
    assert row.status == "missing"
    assert "no dated file" in (row.detail or "")


def test_product_ignores_sibling_families_and_subdirectories(tmp_path: Path) -> None:
    """Only the pattern's own files count — not a newer file of another family."""
    now = datetime(2026, 9, 24, 6, 30, tzinfo=UTC)
    _gate_files(tmp_path, "2026-09-21")
    gates = tmp_path / "docs" / "calibration" / "gates"
    (gates / "returns_series_2026-09-23.json").write_text("{}", encoding="utf-8")
    (gates / "15m").mkdir()
    (gates / "15m" / "track_record_gate_2026-09-23.json").write_text("{}", encoding="utf-8")
    row = _product(tmp_path, now, weekday_only=True)
    assert row.status == "stale"
    assert row.last_success_at.startswith("2026-09-21")


def test_product_expected_stale_is_a_tripwire_not_a_mute(tmp_path: Path) -> None:
    _gate_files(tmp_path, "2026-08-27")
    until = date(2026, 10, 8)
    inside = _product(
        tmp_path, datetime(2026, 10, 8, 6, 30, tzinfo=UTC),
        weekday_only=True, expected_stale_until=until,
    )
    assert inside.status == "expected_stale"
    after = _product(
        tmp_path, datetime(2026, 10, 9, 6, 30, tzinfo=UTC),
        weekday_only=True, expected_stale_until=until,
    )
    assert after.status == "stale"
    assert "EXPIRED 2026-10-08" in (after.detail or "")
    # A fresh product is fresh regardless of a still-open declaration.
    _gate_files(tmp_path, "2026-10-07")
    healed = _product(
        tmp_path, datetime(2026, 10, 8, 6, 30, tzinfo=UTC),
        weekday_only=True, expected_stale_until=until,
    )
    assert healed.status == "fresh"


def test_parse_product_spec() -> None:
    assert _parse_product_spec(f"{_GATE_GLOB}=72:weekday") == (_GATE_GLOB, 72.0, True, None)
    assert _parse_product_spec(
        f"{_GATE_GLOB}=72:weekday:expected-stale-until=2026-10-08"
    ) == (_GATE_GLOB, 72.0, True, date(2026, 10, 8))
    assert _parse_product_spec("a/b_*.json=30") == ("a/b_*.json", 30.0, False, None)


@pytest.mark.parametrize(
    "raw",
    [
        "docs/x_*.json",  # no budget
        "=72",  # no pattern
        "docs/x_2026-01-01.json=72",  # not a glob
        "docs/x_*.json=abc",  # non-numeric budget
        "docs/x_*.json=0",  # non-positive budget
        "docs/x_*.json=72:any",  # a product has no conclusion
        "docs/x_*.json=72:success",
        "docs/x_*.json=72:wekday",  # typo must not parse silently
        "docs/x_*.json=72:expected-stale-until=soon",
    ],
)
def test_parse_product_spec_rejects(raw: str) -> None:
    import argparse

    with pytest.raises(argparse.ArgumentTypeError):
        _parse_product_spec(raw)


def test_main_exit_code_follows_a_stale_product(tmp_path: Path, monkeypatch, capsys) -> None:
    """End to end through the CLI: a stale product alone turns the probe red."""
    import scripts.check_workflow_freshness as cwf

    _gate_files(tmp_path, "2020-01-02")  # stale against any real clock
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setattr(
        cwf,
        "_default_fetcher",
        lambda url, headers: {
            "workflow_runs": [
                {"id": 1, "updated_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")}
            ]
        },
    )
    rc = main(["wf.yml=72", "--repo", "o/r", "--product", f"{_GATE_GLOB}=72:weekday"])
    report = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert report["overall"] == "stale"
    assert [row["status"] for row in report["workflows"]] == ["fresh", "stale"]
