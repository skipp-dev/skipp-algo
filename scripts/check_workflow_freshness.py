"""Workflow freshness monitor.

Detects the failure mode that hid the 2026-04 / 2026-05 publish
regression for 5 weeks: a daily cron silently stopped producing
successful runs and nobody noticed because the job conclusion stayed
green (see PR #2415 / #2418 / #2421 post-mortem in issue #2422).

For each requested workflow this tool calls the GitHub Actions API,
finds the most recent run with ``conclusion == "success"`` and
classifies its age against a per-workflow staleness budget:

* ``fresh``    — last success within the budget
* ``stale``    — last success older than the budget
* ``missing``  — no successful run in the API response window
* ``api_error`` — request to the GitHub API failed

The intended deploy shape is a daily cron whose own job fails (exit
code 2) when any monitored workflow is stale — i.e. the monitor itself
cannot suffer the same silent-skip failure mode.

Auth: reads ``GITHUB_TOKEN`` (or ``GH_PAT``) from the environment.
Repo:  reads ``GITHUB_REPOSITORY`` ("owner/name") or accepts ``--repo``.
No third-party deps; ``urllib.request`` only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any


@dataclass
class WorkflowFreshness:
    workflow: str
    status: str  # fresh | stale | missing | api_error
    last_success_at: str | None = None
    age_hours: float | None = None
    budget_hours: float | None = None
    run_id: int | None = None
    run_url: str | None = None
    detail: str | None = None
    timestamp_source: str | None = None  # updated_at | run_started_at | created_at


@dataclass
class FreshnessReport:
    schema_version: str = "1"
    generated_at: str = ""
    repo: str = ""
    overall: str = "fresh"  # fresh | stale | error
    stale_count: int = 0
    missing_count: int = 0
    api_error_count: int = 0
    workflows: list[dict[str, Any]] = field(default_factory=list)


# Type alias for the injected fetcher so tests can stub the network.
Fetcher = Callable[[str, dict[str, str]], dict[str, Any]]


def _default_fetcher(url: str, headers: dict[str, str]) -> dict[str, Any]:
    """Real HTTP GET against the GitHub API. Returns parsed JSON dict."""
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=15) as resp:  # nosec B310 - https URL only
        body = resp.read().decode("utf-8")
    return json.loads(body)


def _parse_iso(s: str) -> datetime:
    # GitHub returns ``...Z`` (UTC). datetime.fromisoformat handles ``+00:00``.
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _weekend_hours_between(start: datetime, end: datetime) -> float:
    """Return the number of Saturday and Sunday hours (UTC) between start and end.

    If start >= end, returns 0.0. Clamped to a max of 1000 hours to avert loops.
    """
    if start >= end:
        return 0.0
    start_utc = start.astimezone(UTC)
    end_utc = end.astimezone(UTC)

    total_hours = (end_utc - start_utc).total_seconds() / 3600.0
    if total_hours > 1000:
        # Clamp to 1000 to keep execution rapid even for extremely long gaps.
        # Any gap > 1000h is already far beyond any standard budget budget_hours anyway.
        # This protects against infinite/slow loops if someone runs checks with massive gaps.
        end_utc = start_utc + timedelta(hours=1000)

    curr = start_utc
    weekend_hours = 0.0
    while curr < end_utc:
        # Ensure we don't cross a midnight boundary or an hour boundary in a single step
        nxt_hour = (curr + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        if nxt_hour <= curr:
            nxt_hour = curr + timedelta(hours=1)
        nxt_midnight = (curr + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

        nxt = min(nxt_hour, nxt_midnight, end_utc)
        duration_hours = (nxt - curr).total_seconds() / 3600.0
        if curr.weekday() in (5, 6):
            weekend_hours += duration_hours
        curr = nxt
    return weekend_hours


def check_workflow(
    *,
    repo: str,
    workflow_file: str,
    budget_hours: float,
    token: str,
    now: datetime | None = None,
    fetcher: Fetcher | None = None,
    any_conclusion: bool = False,
    weekday_only: bool = False,
) -> WorkflowFreshness:
    """Look up the most recent successful (or any completed) run of one workflow.

    When *any_conclusion* is True the query uses ``status=completed``
    instead of ``status=success``.  This is useful for workflows whose
    non-zero exit code is an expected operational outcome (e.g. a
    promotion gate emitting ``rollback``) rather than an infrastructure
    failure.  The freshness contract then means "the workflow *ran*
    recently" rather than "the workflow *succeeded* recently".
    """
    now = now or datetime.now(tz=UTC)
    fetcher = fetcher or _default_fetcher
    qs = "status=completed" if any_conclusion else "status=success"
    url = (
        f"https://api.github.com/repos/{repo}/actions/workflows/"
        f"{workflow_file}/runs?{qs}&per_page=1"
    )
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "skipp-algo-workflow-freshness/1",
    }
    try:
        payload = fetcher(url, headers)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        return WorkflowFreshness(
            workflow=workflow_file,
            status="api_error",
            budget_hours=budget_hours,
            detail=f"{type(exc).__name__}: {exc}",
        )

    runs = payload.get("workflow_runs") or []
    if not runs:
        return WorkflowFreshness(
            workflow=workflow_file,
            status="missing",
            budget_hours=budget_hours,
            detail="no successful runs returned by the API",
        )

    run = runs[0]
    _ts_field = (
        "updated_at" if run.get("updated_at")
        else "run_started_at" if run.get("run_started_at")
        else "created_at"
    )
    finished_raw = run.get(_ts_field)
    if not isinstance(finished_raw, str):
        return WorkflowFreshness(
            workflow=workflow_file,
            status="api_error",
            budget_hours=budget_hours,
            detail="run payload missing updated_at / created_at",
        )

    age = (now - _parse_iso(finished_raw)).total_seconds() / 3600.0
    if weekday_only:
        weekend_h = _weekend_hours_between(_parse_iso(finished_raw), now)
        age = max(0.0, age - weekend_h)

    status = "fresh" if age <= budget_hours else "stale"
    return WorkflowFreshness(
        workflow=workflow_file,
        status=status,
        last_success_at=finished_raw,
        age_hours=round(age, 2),
        budget_hours=budget_hours,
        run_id=run.get("id"),
        run_url=run.get("html_url"),
        timestamp_source=_ts_field,
    )


def check_all(
    *,
    repo: str,
    workflows: list[tuple[str, float, bool] | tuple[str, float, bool, bool]],
    token: str,
    now: datetime | None = None,
    fetcher: Fetcher | None = None,
) -> FreshnessReport:
    """Check a list of ``(workflow_file, budget_hours, any_conclusion, [weekday_only])`` elements."""
    now = now or datetime.now(tz=UTC)
    results = []
    for item in workflows:
        wf = item[0]
        budget = item[1]
        any_conc = item[2]
        wkday = item[3] if len(item) > 3 else False
        results.append(
            check_workflow(
                repo=repo,
                workflow_file=wf,
                budget_hours=budget,
                token=token,
                now=now,
                fetcher=fetcher,
                any_conclusion=any_conc,
                weekday_only=wkday,
            )
        )
    stale = sum(1 for r in results if r.status == "stale")
    missing = sum(1 for r in results if r.status == "missing")
    api_err = sum(1 for r in results if r.status == "api_error")

    if api_err:
        overall = "error"
    elif stale or missing:
        overall = "stale"
    else:
        overall = "fresh"

    return FreshnessReport(
        generated_at=now.isoformat(),
        repo=repo,
        overall=overall,
        stale_count=stale,
        missing_count=missing,
        api_error_count=api_err,
        workflows=[asdict(r) for r in results],
    )


def _parse_workflow_spec(raw: str) -> tuple[str, float, bool, bool]:
    """Parse ``file.yml=HOURS`` or suffixes such as ``:any`` or ``:weekday``.

    The optional ``:any`` suffix enables *any_conclusion* mode — the
    freshness check queries ``status=completed`` instead of
    ``status=success``.  This is intended for promotion-gate workflows
    whose non-zero exit code is an expected operational outcome.

    The optional ``:weekday`` suffix excludes Saturday and Sunday UTC hours.

    Returns ``(workflow_file, budget_hours, any_conclusion, weekday_only)``.
    """
    if "=" not in raw:
        raise argparse.ArgumentTypeError(
            f"workflow spec must be 'file.yml=HOURS', got {raw!r}"
        )
    name, _, rest = raw.partition("=")
    name = name.strip()
    rest = rest.strip()
    if not name.endswith((".yml", ".yaml")):
        raise argparse.ArgumentTypeError(
            f"workflow file must end with .yml/.yaml, got {name!r}"
        )

    parts = rest.split(":")
    budget_s = parts[0].strip()
    tags = {p.strip().lower() for p in parts[1:]} if len(parts) > 1 else set()

    any_conclusion = "any" in tags
    weekday_only = "weekday" in tags

    try:
        budget = float(budget_s)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"budget hours must be numeric, got {budget_s!r}"
        ) from exc
    if budget <= 0:
        raise argparse.ArgumentTypeError("budget hours must be positive")
    return name, budget, any_conclusion, weekday_only


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check freshness of recent successful workflow runs.")
    parser.add_argument(
        "workflows",
        nargs="+",
        type=_parse_workflow_spec,
        help="One or more 'workflow-file.yml=BUDGET_HOURS' specs",
    )
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY", ""),
        help="owner/name (defaults to $GITHUB_REPOSITORY)",
    )
    parser.add_argument(
        "--token-env",
        default="GITHUB_TOKEN",
        help="Env var holding the GitHub token (default GITHUB_TOKEN; falls back to GH_PAT)",
    )
    parser.add_argument("--output", type=str, default=None, help="Also write the JSON report to this file")
    args = parser.parse_args(argv)

    if not args.repo or "/" not in args.repo:
        print(
            "error: --repo or $GITHUB_REPOSITORY must be set to 'owner/name'",
            file=sys.stderr,
        )
        return 1

    token = os.environ.get(args.token_env) or os.environ.get("GH_PAT") or ""
    if not token:
        print(
            f"error: no token found in ${args.token_env} or $GH_PAT",
            file=sys.stderr,
        )
        return 1

    report = check_all(repo=args.repo, workflows=args.workflows, token=token)
    rendered = json.dumps(asdict(report), indent=2)
    print(rendered)
    if args.output:
        from pathlib import Path

        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        # ATOMIC-WRITE-EXEMPT: monitoring CLI output to operator-supplied path; not a production dataset
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")

    if report.overall == "error":
        return 1
    if report.overall == "stale":
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
