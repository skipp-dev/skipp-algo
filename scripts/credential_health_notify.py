"""Push a credential-health alert to the operator via Slack (use case #1).

The ``credential-health-check`` workflow already (a) annotates the run, (b)
writes a step summary, and (c) opens/updates a ``cron-failure`` GitHub issue
via ``gh``. What it historically lacked was a *direct-push channel*: the
2026-06 TV-cookie incident sat unnoticed for ~99h because nobody was reading
the run summary or the issue list. This script closes that gap — it turns the
JSON report from ``credential_health_check.py`` into a short Slack ping to the
operator (DM to ``SLACK_ALERT_USER_ID`` or post to ``SLACK_ALERT_CHANNEL``).

It is deliberately **fail-soft and non-authoritative**: it never files issues
(that stays with ``gh`` in the workflow, the source of truth) and always exits
0 so a Slack/Composio hiccup can never turn the health workflow red. Delivery
is attempted only when the report is ``warn`` or ``error`` (or ``--always``).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

try:  # `python scripts/foo.py` puts scripts/ on sys.path[0]
    import composio_ops
except ImportError:  # imported as scripts.credential_health_notify (pytest pythonpath=".")
    from scripts import composio_ops

_SEVERITY_EMOJI = {"error": "🔴", "warn": "🟠", "ok": "🟢"}


def _load_report(path: str | None) -> dict[str, Any]:
    """Load the report from ``path`` or stdin; return {} on any read failure."""
    try:
        if path and path != "-":
            raw = Path(path).read_text(encoding="utf-8")
        else:
            raw = sys.stdin.read()
        parsed = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"credential_health_notify: could not load report ({exc})", file=sys.stderr)
        return {}
    return parsed if isinstance(parsed, dict) else {}


def build_message(report: dict[str, Any]) -> str:
    """Render a compact Slack Markdown alert from the probe report."""
    overall = str(report.get("overall_severity", "unknown"))
    repo = os.getenv("GITHUB_REPOSITORY", "").strip()
    run_id = os.getenv("GITHUB_RUN_ID", "").strip()
    header = f"{_SEVERITY_EMOJI.get(overall, '⚪')} *Credential health: `{overall}`*"

    lines = [header]
    for probe in report.get("probes", []):
        if not isinstance(probe, dict):
            continue
        sev = str(probe.get("severity", "ok"))
        if sev == "ok":
            continue
        emoji = _SEVERITY_EMOJI.get(sev, "⚪")
        lines.append(f"{emoji} *{probe.get('name', '?')}* — {probe.get('message', '')}")

    if len(lines) == 1:
        lines.append("_(no non-ok probes in report)_")

    if repo and run_id:
        lines.append(f"\n<https://github.com/{repo}/actions/runs/{run_id}|View run> · a `cron-failure` issue was opened/updated in `{repo}`.")
    elif repo:
        lines.append(f"\nA `cron-failure` issue was opened/updated in `{repo}`.")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument(
        "--report",
        default="artifacts/ci/credential_health.json",
        help="Path to the credential_health_check.py JSON report, or '-' for stdin.",
    )
    parser.add_argument(
        "--always",
        action="store_true",
        help="Send even when overall_severity is ok (default: only warn/error).",
    )
    args = parser.parse_args(argv)

    report = _load_report(args.report)
    overall = str(report.get("overall_severity", "error" if not report else "unknown"))

    if not args.always and overall not in ("warn", "error"):
        print(f"credential_health_notify: overall={overall!r} — nothing to push (ok).")
        return 0

    result = composio_ops.notify_slack(build_message(report))
    if result.skipped:
        print(f"credential_health_notify: Slack push skipped — {result.detail}")
    elif result.delivered:
        print("credential_health_notify: Slack alert delivered.")
    else:
        # Non-fatal: the gh issue + step summary remain the authoritative alert.
        print(f"credential_health_notify: Slack push FAILED — {result.detail}", file=sys.stderr)

    # Always succeed: a notification failure must never fail the health workflow.
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
