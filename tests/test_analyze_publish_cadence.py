"""Tests for ``scripts/analyze_publish_cadence.py``.

Stubs the ``git_log`` runner so no real git invocation is needed -- the
tests run entirely off synthetic commit timelines.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts.analyze_publish_cadence import (
    CadenceReport,
    _parse_path_spec,
    analyze_all,
    analyze_path,
    main,
)

NOW = datetime(2026, 5, 29, 12, 0, 0, tzinfo=UTC)


def _fake_log(commits_age_days: list[float]):
    """Return a runner producing one line per (age_days_from_NOW) entry,
    newest-first as `git log` does."""

    def runner(path: str) -> str:
        lines = []
        for i, age in enumerate(commits_age_days):
            ts = int((NOW - timedelta(days=age)).timestamp())
            lines.append(f"{ts}\t{i:07x}abc")
        return "\n".join(lines) + ("\n" if lines else "")

    return runner


# -- analyze_path -----------------------------------------------------------


def test_fresh_when_last_commit_within_budget(tmp_path: Path) -> None:
    r = analyze_path(
        path="pine/generated",
        budget_days=7.0,
        repo_root=tmp_path,
        now=NOW,
        git_log=_fake_log([1.0, 5.0, 12.0]),
    )
    assert r.status == "fresh"
    assert r.age_days == 1.0
    assert r.commit_count == 3
    assert r.last_commit_sha is not None
    assert r.max_gap_days == 7.0  # gap between 5d and 12d


def test_stale_when_last_commit_older_than_budget(tmp_path: Path) -> None:
    r = analyze_path(
        path="pine/generated",
        budget_days=7.0,
        repo_root=tmp_path,
        now=NOW,
        git_log=_fake_log([45.0, 50.0]),  # 5-week silence -- the #2415 shape
    )
    assert r.status == "stale"
    assert r.age_days == 45.0


def test_max_gap_reported_even_when_fresh(tmp_path: Path) -> None:
    """The historical max-gap is informational; report it regardless."""
    r = analyze_path(
        path="pine/generated",
        budget_days=7.0,
        repo_root=tmp_path,
        now=NOW,
        git_log=_fake_log([1.0, 36.0, 100.0]),  # huge old gap, fresh today
    )
    assert r.status == "fresh"
    assert r.max_gap_days == 64.0
    # The pair tuple identifies which commits bracket the gap.
    assert r.max_gap_between is not None
    older_sha, newer_sha = r.max_gap_between
    assert older_sha != newer_sha


def test_missing_when_no_commits_touched_path(tmp_path: Path) -> None:
    r = analyze_path(
        path="never/published",
        budget_days=7.0,
        repo_root=tmp_path,
        now=NOW,
        git_log=lambda p: "",
    )
    assert r.status == "missing"
    assert r.commit_count == 0
    assert r.detail is not None
    assert r.age_days is None


def test_missing_when_git_log_raises(tmp_path: Path) -> None:
    def broken(p: str) -> str:
        raise RuntimeError("git log failed for path 'x': fatal")

    r = analyze_path(
        path="x",
        budget_days=7.0,
        repo_root=tmp_path,
        now=NOW,
        git_log=broken,
    )
    assert r.status == "missing"
    assert "fatal" in (r.detail or "")


def test_single_commit_has_zero_max_gap(tmp_path: Path) -> None:
    r = analyze_path(
        path="x",
        budget_days=30.0,
        repo_root=tmp_path,
        now=NOW,
        git_log=_fake_log([3.0]),
    )
    assert r.status == "fresh"
    assert r.commit_count == 1
    assert r.max_gap_days == 0.0
    assert r.max_gap_between is None


def test_garbage_lines_skipped_silently(tmp_path: Path) -> None:
    def runner(p: str) -> str:
        # First line is garbage; second is valid.
        ts = int((NOW - timedelta(days=2)).timestamp())
        return f"not-a-number\tdeadbee\n{ts}\tabc1234\n"

    r = analyze_path(
        path="x",
        budget_days=7.0,
        repo_root=tmp_path,
        now=NOW,
        git_log=runner,
    )
    assert r.status == "fresh"
    assert r.commit_count == 1
    assert r.last_commit_sha == "abc1234"


# -- analyze_all aggregation ------------------------------------------------


def test_overall_fresh_when_all_paths_fresh(tmp_path: Path) -> None:
    report = analyze_all(
        paths=[("a", 7.0), ("b", 7.0)],
        repo_root=tmp_path,
        now=NOW,
        git_log=_fake_log([1.0, 4.0]),
    )
    assert report.overall == "fresh"
    assert report.stale_count == 0 and report.missing_count == 0


def test_overall_stale_when_any_stale_or_missing(tmp_path: Path) -> None:
    state = {"i": 0}
    fresh = _fake_log([1.0])
    stale = _fake_log([60.0])

    def runner(p: str) -> str:
        idx = state["i"]
        state["i"] += 1
        return (fresh if idx == 0 else stale)(p)

    report = analyze_all(
        paths=[("a", 7.0), ("b", 7.0)],
        repo_root=tmp_path,
        now=NOW,
        git_log=runner,
    )
    assert report.overall == "stale"
    assert report.stale_count == 1


def test_overall_stale_when_path_missing(tmp_path: Path) -> None:
    report = analyze_all(
        paths=[("a", 7.0)],
        repo_root=tmp_path,
        now=NOW,
        git_log=lambda p: "",
    )
    assert report.overall == "stale"
    assert report.missing_count == 1


# -- spec parser ------------------------------------------------------------


def test_parse_path_spec_ok() -> None:
    assert _parse_path_spec("pine/generated=7") == ("pine/generated", 7.0)
    assert _parse_path_spec("a/b/c.txt=1.5") == ("a/b/c.txt", 1.5)


def test_parse_path_spec_accepts_equals_in_filename() -> None:
    # rpartition means the last `=` is the separator; rare paths with
    # an `=` in them still parse.
    assert _parse_path_spec("weird=name=7") == ("weird=name", 7.0)


@pytest.mark.parametrize(
    "raw",
    ["no-equals", "path=zero", "path=-1", "path=0", "=7"],
)
def test_parse_path_spec_rejects(raw: str) -> None:
    import argparse as _ap

    with pytest.raises(_ap.ArgumentTypeError):
        _parse_path_spec(raw)


# -- CLI integration --------------------------------------------------------


def _patch(monkeypatch: pytest.MonkeyPatch, report: CadenceReport) -> None:
    monkeypatch.setattr(
        "scripts.analyze_publish_cadence.analyze_all",
        lambda **kwargs: report,
    )


def test_cli_returns_zero_on_fresh(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    _patch(monkeypatch, CadenceReport(overall="fresh"))
    out = tmp_path / "r.json"
    rc = main(["pine/generated=7", "--repo-root", str(tmp_path), "--output", str(out)])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["overall"] == "fresh"


def test_cli_returns_two_on_stale(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    _patch(monkeypatch, CadenceReport(overall="stale", stale_count=1))
    rc = main(["pine/generated=7", "--repo-root", str(tmp_path)])
    assert rc == 2


def test_cli_rejects_non_git_root(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["pine/generated=7", "--repo-root", str(tmp_path)])
    assert rc == 1
    assert "not look like a git repo" in capsys.readouterr().err


# -- integration against a real ephemeral git repo --------------------------


def test_end_to_end_against_real_git_repo(tmp_path: Path) -> None:
    """Smoke test: build a tiny git repo with one commit touching a
    path and one that doesn't. Verify _run_git_log returns the right
    shape without stubbing."""
    import subprocess

    def run(*args: str) -> None:
        subprocess.run(args, cwd=tmp_path, check=True, capture_output=True)

    run("git", "init", "-q")
    run("git", "config", "user.email", "t@t.t")
    run("git", "config", "user.name", "t")
    (tmp_path / "pine").mkdir()
    (tmp_path / "pine" / "x.txt").write_text("v1", encoding="utf-8")
    run("git", "add", "pine/x.txt")
    run(
        "git",
        "-c", "commit.gpgsign=false",
        "commit", "-q", "-m", "first",
    )
    (tmp_path / "other.txt").write_text("o", encoding="utf-8")
    run("git", "add", "other.txt")
    run("git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "unrelated")

    r = analyze_path(
        path="pine",
        budget_days=365.0,
        repo_root=tmp_path,
        now=NOW,
    )
    assert r.status == "fresh"
    assert r.commit_count == 1

    r2 = analyze_path(
        path="never-existed",
        budget_days=365.0,
        repo_root=tmp_path,
        now=NOW,
    )
    assert r2.status == "missing"
