#!/usr/bin/env python3
"""Durable aggregate counter for CI runner-selection outcomes.

Background
----------
The hybrid runner control-plane (``scripts/resolve_workflow_runner.py``)
decides, on every routed workflow run, whether a matching self-hosted Windows
runner is online and idle. Until now that decision was only emitted as a
``::notice::`` annotation into a single run's log, so there was **no aggregate
counter** answering operational questions such as:

* How often does the self-hosted runner actually get used?
* How often do we fall back to the GitHub-hosted runner?
* Is the self-hosted box silently offline for long stretches?

This module persists one structured event per selection to an append-only
JSON-Lines ledger and renders a human-readable rollup. The ledger lives on a
dedicated metrics branch (see ``automation/metrics/push_runner_selection_metric.sh``)
so it never pollutes the default branch's history.

The pure functions here are deliberately free of any git / network side
effects so they can be unit-tested in isolation.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Reason emitted by the resolver when a self-hosted runner was matched.
MATCHED_SELF_HOSTED_REASON = "matched_idle_self_hosted_runner"
# Runner environment label for the GitHub-hosted fallback.
GITHUB_HOSTED_ENVIRONMENT = "github-hosted"
SELF_HOSTED_ENVIRONMENT = "self-hosted"


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with a ``Z`` suffix."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_event(
    *,
    reason: str,
    runner_environment: str,
    matched_runner_name: str | None = None,
    workflow: str | None = None,
    event_name: str | None = None,
    run_id: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Build a single normalised runner-selection event record.

    Empty strings are normalised to ``None`` so downstream aggregation does not
    have to special-case the difference between "absent" and "blank".
    """

    def _clean(value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    return {
        "ts": _clean(timestamp) or utc_now_iso(),
        "reason": _clean(reason) or "unknown",
        "runner_environment": _clean(runner_environment) or "unknown",
        "matched_runner_name": _clean(matched_runner_name),
        "workflow": _clean(workflow),
        "event_name": _clean(event_name),
        "run_id": _clean(run_id),
    }


def append_event(metrics_file: str | Path, event: dict[str, Any]) -> None:
    """Append ``event`` as one JSON line to ``metrics_file`` (created if absent)."""
    path = Path(metrics_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event, sort_keys=True, separators=(",", ":"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def load_events(metrics_file: str | Path) -> list[dict[str, Any]]:
    """Load all events from a JSON-Lines ledger, skipping blank/corrupt lines."""
    path = Path(metrics_file)
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            # A single corrupt line must not nuke the whole aggregate.
            continue
        if isinstance(parsed, dict):
            events.append(parsed)
    return events


def summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate runner-selection events into counts and fallback rates."""
    total = len(events)
    by_reason: Counter[str] = Counter()
    by_environment: Counter[str] = Counter()
    timestamps: list[str] = []
    for event in events:
        by_reason[str(event.get("reason") or "unknown")] += 1
        by_environment[str(event.get("runner_environment") or "unknown")] += 1
        ts = event.get("ts")
        if isinstance(ts, str) and ts:
            timestamps.append(ts)

    matched_self_hosted = by_reason.get(MATCHED_SELF_HOSTED_REASON, 0)
    hosted_fallback = by_environment.get(GITHUB_HOSTED_ENVIRONMENT, 0)

    def _rate(numerator: int) -> float:
        return round(numerator / total, 4) if total else 0.0

    return {
        "total": total,
        "by_reason": dict(sorted(by_reason.items())),
        "by_runner_environment": dict(sorted(by_environment.items())),
        "matched_self_hosted": matched_self_hosted,
        "hosted_fallback": hosted_fallback,
        "self_hosted_match_rate": _rate(matched_self_hosted),
        "hosted_fallback_rate": _rate(hosted_fallback),
        "first_event_ts": min(timestamps) if timestamps else None,
        "last_event_ts": max(timestamps) if timestamps else None,
    }


def render_summary_md(summary: dict[str, Any]) -> str:
    """Render a Markdown rollup suitable for a job summary or committed file."""
    lines = [
        "# Runner Selection Metrics",
        "",
        f"- **Total selections:** {summary['total']}",
        f"- **Self-hosted matched:** {summary['matched_self_hosted']} "
        f"({summary['self_hosted_match_rate'] * 100:.1f}%)",
        f"- **GitHub-hosted fallback:** {summary['hosted_fallback']} "
        f"({summary['hosted_fallback_rate'] * 100:.1f}%)",
        f"- **Window:** {summary['first_event_ts'] or 'n/a'} → "
        f"{summary['last_event_ts'] or 'n/a'}",
        "",
        "## By resolution reason",
        "",
        "| Reason | Count |",
        "| --- | ---: |",
    ]
    for reason, count in summary["by_reason"].items():
        lines.append(f"| `{reason}` | {count} |")
    lines += [
        "",
        "## By runner environment",
        "",
        "| Environment | Count |",
        "| --- | ---: |",
    ]
    for env, count in summary["by_runner_environment"].items():
        lines.append(f"| `{env}` | {count} |")
    lines.append("")
    return "\n".join(lines)


def _cmd_append(args: argparse.Namespace) -> int:
    event = build_event(
        reason=args.reason,
        runner_environment=args.runner_environment,
        matched_runner_name=args.matched_runner_name,
        workflow=args.workflow,
        event_name=args.event_name,
        run_id=args.run_id,
        timestamp=args.timestamp,
    )
    append_event(args.metrics_file, event)
    if args.summary_md:
        summary = summarize(load_events(args.metrics_file))
        Path(args.summary_md).write_text(render_summary_md(summary), encoding="utf-8")
    print(json.dumps(event, sort_keys=True))
    return 0


def _cmd_summary(args: argparse.Namespace) -> int:
    summary = summarize(load_events(args.metrics_file))
    if args.format == "md":
        output = render_summary_md(summary)
    else:
        output = json.dumps(summary, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    print(output)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    append = sub.add_parser("append", help="Append one runner-selection event.")
    append.add_argument("--metrics-file", required=True)
    append.add_argument("--reason", required=True)
    append.add_argument("--runner-environment", required=True)
    append.add_argument("--matched-runner-name", default=None)
    append.add_argument("--workflow", default=None)
    append.add_argument("--event-name", default=None)
    append.add_argument("--run-id", default=None)
    append.add_argument("--timestamp", default=None)
    append.add_argument(
        "--summary-md",
        default=None,
        help="Optional path to (re)write a Markdown rollup after appending.",
    )
    append.set_defaults(func=_cmd_append)

    summary = sub.add_parser("summary", help="Print the aggregate summary.")
    summary.add_argument("--metrics-file", required=True)
    summary.add_argument("--format", choices=("json", "md"), default="json")
    summary.add_argument("--output", default=None)
    summary.set_defaults(func=_cmd_summary)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
