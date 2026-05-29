"""Post-mortem analyzer for the TradingView preflight retry telemetry.

Consumes the per-attempt artifacts emitted by the retry wrapper in
``.github/workflows/smc-library-refresh.yml`` (Bundle B, PR #2431):

  * ``preflight_retry_log.jsonl`` — one record per attempt with
    attempt / exit_code / timing / preserved-output path.
  * ``tv_preflight_ci.attempt_${attempt}.json`` — the preflight tool's
    full JSON output preserved BEFORE the next attempt overwrote it.

Classifies the run into one of:

  * ``success``                 — every attempt exited 0.
  * ``flake_recovered``         — at least one attempt failed, but a
                                  later attempt succeeded. The wrapper
                                  earned its keep.
  * ``deterministic_failure``   — every attempt failed AND every
                                  failed attempt produced an
                                  identical failure shape. Strong
                                  signal of real DOM / API drift
                                  (the #2425 hypothesis). Retrying
                                  will NOT help.
  * ``flake_with_progression``  — every attempt failed but the failure
                                  shapes differed across attempts.
                                  Suggests partial recovery / racing
                                  rather than a clean regression.
  * ``inconclusive``            — log present but per-attempt
                                  preflight JSON missing (e.g. tool
                                  crashed before writing). Operator
                                  must inspect job logs.

This is the tool a #2425-style post-mortem reaches for first. It does
NOT touch any external service; it only reads files on disk.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


# Fields whose values describe "what failed" structurally — i.e. removing
# noisy time / id fields so two attempts with the same DOM problem
# fingerprint identically.
_NOISE_FIELDS = frozenset(
    {
        "generatedAt",
        "generated_at",
        "started_at",
        "ended_at",
        "duration_ms",
        "duration_seconds",
        "run_id",
        "runId",
        "screenshot",
        "screenshots",
        "trace",
        "browser_version",
        "playwright_version",
        "request_id",
        "requestId",
        # Per-attempt path the wrapper added; not part of the actual
        # preflight payload, but harmless to scrub if it ever leaks in.
        "output_preserved_as",
    }
)


def _scrub(value: Any) -> Any:
    """Recursively drop noise fields so two attempts compare structurally."""
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in sorted(value.items()) if k not in _NOISE_FIELDS}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


@dataclass
class AttemptRecord:
    attempt: int
    exit_code: int
    will_retry: bool
    duration_seconds: int | None
    preserved_path: str | None
    payload_present: bool
    # ``fingerprint_keys`` is a stable, ordered list of (key, value)
    # pairs from the scrubbed payload — used only by the equality
    # comparison, not exposed in the final report.
    fingerprint: str | None


@dataclass
class AnalysisReport:
    schema_version: str = "1"
    verdict: str = "inconclusive"
    attempts: int = 0
    failed_attempts: int = 0
    succeeded_attempts: int = 0
    distinct_failure_fingerprints: int = 0
    summary: str = ""
    per_attempt: list[dict[str, Any]] = field(default_factory=list)
    recommendation: str = ""


def _fingerprint(path: Path | None) -> str | None:
    if path is None or not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return json.dumps(_scrub(payload), sort_keys=True, separators=(",", ":"))


def _load_retry_log(log_path: Path) -> list[dict[str, Any]]:
    if not log_path.exists():
        raise FileNotFoundError(f"retry log not found: {log_path}")
    records: list[dict[str, Any]] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"corrupt retry log line {len(records) + 1}: {exc}") from exc
    return records


def analyze(log_path: Path, base_dir: Path | None = None) -> AnalysisReport:
    """Analyze a preflight retry run.

    ``log_path`` points at ``preflight_retry_log.jsonl``.
    ``base_dir`` is where the ``tv_preflight_ci.attempt_N.json`` files
    live; defaults to the log's directory.
    """
    base_dir = base_dir or log_path.parent
    records = _load_retry_log(log_path)
    if not records:
        return AnalysisReport(
            verdict="inconclusive",
            summary="retry log is empty — wrapper did not record any attempt",
            recommendation="check the workflow run logs for an early crash before the retry loop started",
        )

    attempts: list[AttemptRecord] = []
    for rec in records:
        preserved_raw = rec.get("output_preserved_as")
        preserved = Path(preserved_raw) if preserved_raw else None
        # Allow both absolute paths (CI runner) and paths relative to base_dir.
        if preserved is not None and not preserved.is_absolute() and not preserved.exists():
            candidate = base_dir / preserved.name
            if candidate.exists():
                preserved = candidate
        fp = _fingerprint(preserved)
        attempts.append(
            AttemptRecord(
                attempt=int(rec["attempt"]),
                exit_code=int(rec["exit_code"]),
                will_retry=bool(rec.get("will_retry", False)),
                duration_seconds=rec.get("duration_seconds"),
                preserved_path=preserved_raw,
                payload_present=fp is not None,
                fingerprint=fp,
            )
        )

    attempts.sort(key=lambda a: a.attempt)
    failed = [a for a in attempts if a.exit_code != 0]
    succeeded = [a for a in attempts if a.exit_code == 0]
    failed_fingerprints = {a.fingerprint for a in failed if a.fingerprint is not None}

    # Classify.
    if not failed:
        verdict = "success"
        summary = f"all {len(attempts)} attempt(s) succeeded"
        recommendation = "no action — retry wrapper not exercised"
    elif succeeded:
        # Convention: success only counts if it's the LAST attempt or any
        # attempt after a failure — i.e. the wrapper recovered.
        last = attempts[-1]
        if last.exit_code == 0:
            verdict = "flake_recovered"
            summary = (
                f"recovered after {len(failed)} failed attempt(s); "
                f"final attempt {last.attempt} succeeded"
            )
            recommendation = (
                "no immediate action — retry wrapper earned its keep. If this "
                "pattern repeats daily, investigate the underlying flake source."
            )
        else:
            # Edge: success in the middle then failure at the end. Unusual.
            verdict = "flake_with_progression"
            summary = "mixed result — a non-final attempt succeeded but the final one failed"
            recommendation = "rerun the workflow; if the same pattern repeats, investigate test ordering"
    elif failed and not succeeded:
        # All failed. Distinguish deterministic from progression.
        attempts_with_payload = [a for a in failed if a.payload_present]
        if not attempts_with_payload:
            verdict = "inconclusive"
            summary = (
                f"all {len(attempts)} attempt(s) failed but NO per-attempt "
                "preflight JSON was preserved — cannot fingerprint"
            )
            recommendation = (
                "inspect the workflow run logs directly; the preflight tool "
                "may have crashed before writing its output file"
            )
        elif len(failed_fingerprints) == 1 and len(attempts_with_payload) == len(failed):
            verdict = "deterministic_failure"
            summary = (
                f"all {len(failed)} attempt(s) failed with IDENTICAL failure "
                "fingerprint — retrying will NOT help"
            )
            recommendation = (
                "this is the #2425 DOM-drift signature. Inspect the preserved "
                "attempt_1 payload, locate the failing assertion, and update "
                "the corresponding selector in automation/tradingview/."
            )
        else:
            verdict = "flake_with_progression"
            summary = (
                f"all {len(failed)} attempt(s) failed but with "
                f"{len(failed_fingerprints)} distinct failure shape(s) — "
                "partial racing rather than a clean regression"
            )
            recommendation = (
                "rerun once; if the distinct-fingerprint count drops to 1 on "
                "the next run, treat as deterministic_failure"
            )
    else:  # pragma: no cover — exhaustive fallback
        verdict = "inconclusive"
        summary = "unable to classify"
        recommendation = "inspect run logs"

    return AnalysisReport(
        verdict=verdict,
        attempts=len(attempts),
        failed_attempts=len(failed),
        succeeded_attempts=len(succeeded),
        distinct_failure_fingerprints=len(failed_fingerprints),
        summary=summary,
        per_attempt=[
            {
                "attempt": a.attempt,
                "exit_code": a.exit_code,
                "will_retry": a.will_retry,
                "duration_seconds": a.duration_seconds,
                "preserved_path": a.preserved_path,
                "payload_present": a.payload_present,
                # Only short fingerprint preview — full string is noisy.
                "fingerprint_sha": (
                    None
                    if a.fingerprint is None
                    else __import__("hashlib")
                    .sha256(a.fingerprint.encode("utf-8"))
                    .hexdigest()[:12]
                ),
            }
            for a in attempts
        ],
        recommendation=recommendation,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument(
        "log_path",
        type=Path,
        help="Path to preflight_retry_log.jsonl (usually under artifacts/tradingview/)",
    )
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=None,
        help="Directory holding tv_preflight_ci.attempt_N.json files (defaults to the log's directory)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write JSON report to this path (in addition to stdout)",
    )
    parser.add_argument(
        "--exit-on-deterministic",
        action="store_true",
        help="Exit non-zero (3) when verdict == deterministic_failure (useful in CI to gate on DOM-drift)",
    )
    args = parser.parse_args(argv)

    report = analyze(args.log_path, base_dir=args.base_dir)
    rendered = json.dumps(asdict(report), indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")

    if args.exit_on_deterministic and report.verdict == "deterministic_failure":
        return 3
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
