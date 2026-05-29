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
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


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


def check_workflow(
    *,
    repo: str,
    workflow_file: str,
    budget_hours: float,
    token: str,
    now: datetime | None = None,
    fetcher: Fetcher | None = None,
) -> WorkflowFreshness:
    """Look up the most recent successful run of one workflow."""
    now = now or datetime.now(tz=timezone.utc)
    fetcher = fetcher or _default_fetcher
    url = (
        f"https://api.github.com/repos/{repo}/actions/workflows/"
        f"{workflow_file}/runs?status=success&per_page=1"
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
    finished_raw = run.get("updated_at") or run.get("run_started_at") or run.get("created_at")
    if not isinstance(finished_raw, str):
        return WorkflowFreshness(
            workflow=workflow_file,
            status="api_error",
            budget_hours=budget_hours,
            detail="run payload missing updated_at / created_at",
        )

    age = (now - _parse_iso(finished_raw)).total_seconds() / 3600.0
    status = "fresh" if age <= budget_hours else "stale"
    return WorkflowFreshness(
        workflow=workflow_file,
        status=status,
        last_success_at=finished_raw,
        age_hours=round(age, 2),
        budget_hours=budget_hours,
        run_id=run.get("id"),
        run_url=run.get("html_url"),
    )


def check_all(
    *,
    repo: str,
    workflows: list[tuple[str, float]],
    token: str,
    now: datetime | None = None,
    fetcher: Fetcher | None = None,
) -> FreshnessReport:
    """Check a list of ``(workflow_file, budget_hours)`` pairs."""
    now = now or datetime.now(tz=timezone.utc)
    results = [
        check_workflow(
            repo=repo,
            workflow_file=wf,
            budget_hours=budget,
            token=token,
            now=now,
            fetcher=fetcher,
        )
        for wf, budget in workflows
    ]
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


def _parse_workflow_spec(raw: str) -> tuple[str, float]:
    """``smc-library-refresh.yml=30`` -> ``("smc-library-refresh.yml", 30.0)``."""
    if "=" not in raw:
        raise argparse.ArgumentTypeError(
            f"workflow spec must be 'file.yml=HOURS', got {raw!r}"
        )
    name, _, hours = raw.partition("=")
    name = name.strip()
    hours = hours.strip()
    if not name.endswith((".yml", ".yaml")):
        raise argparse.ArgumentTypeError(
            f"workflow file must end with .yml/.yaml, got {name!r}"
        )
    try:
        budget = float(hours)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"budget hours must be numeric, got {hours!r}"
        ) from exc
    if budget <= 0:
        raise argparse.ArgumentTypeError("budget hours must be positive")
    return name, budget


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
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")

    if report.overall == "error":
        return 1
    if report.overall == "stale":
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
