"""Best-effort failure trend tracker for ``smc-library-refresh`` (W3, R4b audit).

The ``smc-library-refresh`` workflow runs several ``continue-on-error: true``
("best-effort") steps — evidence-gate probe, release-reference refresh,
TradingView post-release validation, signal alerts, breaking-change notify,
end-of-run heartbeat. Each only emits a ``::warning::`` on failure, so an
operator has to read the raw logs of every run to notice a degradation. There
was no cumulative view and no cross-run trend.

This module provides that view with two subcommands:

``record``
    Append one JSON line describing the current run's best-effort step
    outcomes to a rolling history JSONL, and write a single-run snapshot JSON.

``digest``
    Read the history JSONL and render a Markdown trend summary (per-step
    failure counts and rates over the last N runs) to stdout, suitable for
    appending to ``$GITHUB_STEP_SUMMARY``.

The history JSONL is persisted across runs as a GitHub Actions artifact
(downloaded at job start, re-uploaded at job end). Both read paths tolerate
corrupt/truncated lines so a partial write from a crashed run never breaks the
digest — the affected line is skipped, mirroring ``_existing_keys`` in
``collect_drift_calibration_corpus``.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import tempfile
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default number of most-recent runs to summarise in the trend digest.
_DEFAULT_WINDOW = 30


def _parse_outcomes(items: Sequence[str]) -> dict[str, str]:
    """Parse repeated ``name=value`` ``--outcome`` arguments into a dict."""
    outcomes: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"--outcome must be name=value, got: {item!r}")
        name, _, value = item.partition("=")
        name = name.strip()
        value = value.strip() or "unknown"
        if name:
            outcomes[name] = value
    return outcomes


def _failed_steps(outcomes: dict[str, str]) -> list[str]:
    """Return the names of steps whose GHA outcome is ``failure``."""
    return sorted(name for name, outcome in outcomes.items() if outcome == "failure")


def _load_history(history_path: Path) -> list[dict[str, Any]]:
    """Load history records, tolerating corrupt/truncated JSONL lines."""
    records: list[dict[str, Any]] = []
    if not history_path.exists():
        return records
    for line in history_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            # A truncated final line from a crashed run is expected and benign.
            continue
        if isinstance(obj, dict):
            records.append(obj)
    return records


def record(
    *,
    history_path: Path,
    snapshot_path: Path,
    outcomes: dict[str, str],
    run_id: str,
    run_url: str,
    ref: str,
) -> int:
    """Append the current run's record to *history_path* and write a snapshot.

    Returns the number of best-effort steps that failed in this run.
    """
    failed = _failed_steps(outcomes)
    rec: dict[str, Any] = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "run_url": run_url,
        "ref": ref,
        "outcomes": dict(sorted(outcomes.items())),
        "failed": failed,
        "failed_count": len(failed),
    }

    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())

    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_str = tempfile.mkstemp(
        dir=str(snapshot_path.parent),
        prefix=snapshot_path.name + ".",
        suffix=".tmp",
    )
    tmp_path = Path(tmp_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            # ATOMIC-WRITE-EXEMPT: hand-rolled mkstemp+fsync+os.replace pattern
            json.dump(rec, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, snapshot_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise

    if failed:
        logger.warning(
            "best-effort: %d step(s) failed this run: %s",
            len(failed),
            ", ".join(failed),
        )
    else:
        logger.info("best-effort: all steps succeeded or were skipped")
    return len(failed)


def _format_digest(records: list[dict[str, Any]], window: int) -> str:
    """Render a Markdown trend digest for the last *window* records."""
    lines: list[str] = ["## Best-effort failure trend", ""]
    if not records:
        lines.append("No best-effort history yet (cold start).")
        return "\n".join(lines) + "\n"

    recent = records[-window:]
    total = len(recent)

    # Per-step failure counts and how many runs observed each step at all.
    fail_counter: Counter[str] = Counter()
    seen_counter: Counter[str] = Counter()
    for rec in recent:
        outcomes = rec.get("outcomes", {})
        if not isinstance(outcomes, dict):
            continue
        for name, outcome in outcomes.items():
            seen_counter[name] += 1
            if outcome == "failure":
                fail_counter[name] += 1

    lines.append(f"Runs analysed: **{total}** (of {len(records)} recorded)")
    lines.append("")

    if fail_counter:
        lines.append("| Step | Failures | Runs observed | Failure rate |")
        lines.append("|------|----------|---------------|--------------|")
        for name in sorted(fail_counter, key=lambda n: (-fail_counter[n], n)):
            fails = fail_counter[name]
            seen = seen_counter[name] or 1
            rate = 100.0 * fails / seen
            lines.append(f"| `{name}` | {fails} | {seen} | {rate:.1f}% |")
    else:
        lines.append("✅ No best-effort failures in the analysed window.")
    lines.append("")

    # Most-recent run detail.
    last = recent[-1]
    last_failed = last.get("failed") or []
    run_id = last.get("run_id", "?")
    ref = last.get("ref", "?")
    if last_failed:
        joined = ", ".join(f"`{name}`" for name in last_failed)
        lines.append(f"Most recent run (`{run_id}`, `{ref}`): ❌ failed: {joined}")
    else:
        lines.append(f"Most recent run (`{run_id}`, `{ref}`): ✅ all clear")

    return "\n".join(lines) + "\n"


def digest(*, history_path: Path, window: int) -> str:
    """Return the Markdown trend digest for *history_path*."""
    records = _load_history(history_path)
    return _format_digest(records, window)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Track and summarise best-effort workflow step failures."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_record = sub.add_parser("record", help="append current run to history")
    p_record.add_argument("--history", required=True, type=Path)
    p_record.add_argument("--snapshot", required=True, type=Path)
    p_record.add_argument("--run-id", default="")
    p_record.add_argument("--run-url", default="")
    p_record.add_argument("--ref", default="")
    p_record.add_argument(
        "--outcome",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="step outcome, e.g. --outcome tv_post_release_raw=failure",
    )

    p_digest = sub.add_parser("digest", help="render Markdown trend digest")
    p_digest.add_argument("--history", required=True, type=Path)
    p_digest.add_argument("--window", type=int, default=_DEFAULT_WINDOW)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "record":
        outcomes = _parse_outcomes(args.outcome)
        record(
            history_path=args.history,
            snapshot_path=args.snapshot,
            outcomes=outcomes,
            run_id=args.run_id,
            run_url=args.run_url,
            ref=args.ref,
        )
        return 0

    if args.command == "digest":
        window = args.window if args.window > 0 else _DEFAULT_WINDOW
        print(digest(history_path=args.history, window=window), end="")
        return 0

    return 2  # pragma: no cover - argparse enforces a valid subcommand


if __name__ == "__main__":  # pragma: no cover
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        logger.warning("Interrupted by user (SIGINT/KeyboardInterrupt).")
        raise SystemExit(130) from None
    except SystemExit:
        raise
    except Exception:
        logger.critical("Fatal error in %s", __name__, exc_info=True)
        raise SystemExit(1) from None
