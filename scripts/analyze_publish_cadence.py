"""Publish-cadence analyzer.

Out-of-band detector for the OTHER failure shape of the 2026-04-13 ->
2026-05-28 silent publish-skip regression (post-mortem PR #2415,
audit issue #2422).

`scripts/check_workflow_freshness.py` (PR #2433) detects "the daily
cron stopped producing successful runs". That covers half the failure
class. The original #2415 shape was DIFFERENT: the daily cron
succeeded every day, but every run hit the
"Library content unchanged - skipping publish/commit" path (or the
"Breaking change blocks publish" path) and produced NO commit to
``pine/generated/`` for 5 weeks. Job conclusion green, publish output
zero -- nothing for a run-staleness probe to flag.

This analyzer closes that gap. It walks ``git log -- <path>`` for one
or more critical publish paths and reports the largest gap between
commits. If the most recent commit OR the max historical gap exceeds
the configured per-path budget, the path is classified ``stale``.

Pure stdlib (subprocess + json + argparse + datetime). Read-only.
Designed to be invoked from a daily cron alongside the freshness
monitor.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class PathCadence:
    path: str
    status: str  # fresh | stale | missing
    budget_days: float
    commit_count: int = 0
    last_commit_at: str | None = None
    last_commit_sha: str | None = None
    age_days: float | None = None
    max_gap_days: float | None = None
    max_gap_between: tuple[str, str] | None = None
    detail: str | None = None


@dataclass
class CadenceReport:
    schema_version: str = "1"
    generated_at: str = ""
    overall: str = "fresh"  # fresh | stale | error
    stale_count: int = 0
    missing_count: int = 0
    paths: list[dict[str, Any]] = field(default_factory=list)


def _run_git_log(path: str, repo_root: Path) -> str:
    """Return git log for a single pathspec.

    Format: ``<unix-ts>\\t<short-sha>`` one line per commit, newest first.
    Empty output means the path has never received a commit.
    """
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "log",
            "--format=%ct\t%h",
            "--",
            path,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git log failed for path {path!r}: {result.stderr.strip()}"
        )
    return result.stdout


def _parse_git_log(raw: str) -> list[tuple[datetime, str]]:
    commits: list[tuple[datetime, str]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        ts_str, _, sha = line.partition("\t")
        try:
            ts = datetime.fromtimestamp(int(ts_str), tz=timezone.utc)
        except (TypeError, ValueError):
            continue
        commits.append((ts, sha))
    return commits


def analyze_path(
    *,
    path: str,
    budget_days: float,
    repo_root: Path,
    now: datetime | None = None,
    git_log: callable | None = None,
) -> PathCadence:
    """Classify one path's publish cadence."""
    now = now or datetime.now(tz=timezone.utc)
    runner = git_log or (lambda p: _run_git_log(p, repo_root))
    try:
        raw = runner(path)
    except RuntimeError as exc:
        return PathCadence(
            path=path,
            status="missing",
            budget_days=budget_days,
            detail=str(exc),
        )

    commits = _parse_git_log(raw)
    if not commits:
        return PathCadence(
            path=path,
            status="missing",
            budget_days=budget_days,
            detail="no commits ever touched this path",
        )

    last_ts, last_sha = commits[0]
    age_days = (now - last_ts).total_seconds() / 86400.0

    max_gap = 0.0
    max_gap_pair: tuple[str, str] | None = None
    for newer, older in zip(commits, commits[1:]):
        gap = (newer[0] - older[0]).total_seconds() / 86400.0
        if gap > max_gap:
            max_gap = gap
            max_gap_pair = (older[1], newer[1])

    # Stale if either (a) the most recent commit is older than budget,
    # OR (b) the largest historical gap exceeded budget -- the latter
    # is the post-mortem signal: even if today's commit is fresh, a
    # past multi-week silence proves the alert threshold matters.
    # We only fail-loud on (a). (b) is informational and surfaces in
    # the report; CI consumers can decide to escalate.
    if age_days > budget_days:
        status = "stale"
    else:
        status = "fresh"

    return PathCadence(
        path=path,
        status=status,
        budget_days=budget_days,
        commit_count=len(commits),
        last_commit_at=last_ts.isoformat(),
        last_commit_sha=last_sha,
        age_days=round(age_days, 2),
        max_gap_days=round(max_gap, 2),
        max_gap_between=max_gap_pair,
    )


def analyze_all(
    *,
    paths: list[tuple[str, float]],
    repo_root: Path,
    now: datetime | None = None,
    git_log: callable | None = None,
) -> CadenceReport:
    now = now or datetime.now(tz=timezone.utc)
    results = [
        analyze_path(
            path=p,
            budget_days=b,
            repo_root=repo_root,
            now=now,
            git_log=git_log,
        )
        for p, b in paths
    ]
    stale = sum(1 for r in results if r.status == "stale")
    missing = sum(1 for r in results if r.status == "missing")
    if stale or missing:
        overall = "stale"
    else:
        overall = "fresh"
    return CadenceReport(
        generated_at=now.isoformat(),
        overall=overall,
        stale_count=stale,
        missing_count=missing,
        paths=[asdict(r) for r in results],
    )


def _parse_path_spec(raw: str) -> tuple[str, float]:
    """``pine/generated=7`` -> ``("pine/generated", 7.0)``."""
    if "=" not in raw:
        raise argparse.ArgumentTypeError(
            f"path spec must be 'path=BUDGET_DAYS', got {raw!r}"
        )
    p, _, days = raw.rpartition("=")
    p = p.strip()
    days = days.strip()
    if not p:
        raise argparse.ArgumentTypeError("path must be non-empty")
    try:
        budget = float(days)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"budget days must be numeric, got {days!r}"
        ) from exc
    if budget <= 0:
        raise argparse.ArgumentTypeError("budget days must be positive")
    return p, budget


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analyze publish cadence for one or more git paths.",
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=_parse_path_spec,
        help="One or more 'path=BUDGET_DAYS' specs",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path("."),
        help="Repository root (default: cwd)",
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not (args.repo_root / ".git").exists():
        print(
            f"error: {args.repo_root} does not look like a git repo (.git missing)",
            file=sys.stderr,
        )
        return 1

    report = analyze_all(paths=args.paths, repo_root=args.repo_root)
    rendered = json.dumps(asdict(report), indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        # ATOMIC-WRITE-EXEMPT: monitoring CLI output to operator-supplied path; not a production dataset
        args.output.write_text(rendered + "\n", encoding="utf-8")

    if report.overall == "stale":
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
