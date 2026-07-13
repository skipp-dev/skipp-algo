"""Fail closed unless primary per-timeframe structure artifacts are consumable.

Availability (ADR-0027 §5): manifest present, ≥1 artifact, no producer errors,
every referenced artifact readable/normalizable with matching identity.

Completeness / evidence extensions:
- manifest ``counts`` must prove complete production (artifacts_written ==
  symbols_requested, zero counted errors, no duplicate symbols);
- ``--expect-symbols`` / ``--expect-release-reference-symbols`` require the
  manifest to cover an expected symbol set;
- ``--max-age-seconds`` bounds manifest freshness (guards persistent runners
  serving yesterday's materialization);
- read-side provenance guard: an artifact whose ``generated_at`` predates its
  own observed-data timestamps (``asof_ts``/``anchor_ts``) is impossible and
  fails closed — the consumption mirror of ``validate_artifact_provenance``;
- generator provenance: the manifest must carry a ``provenance`` block with a
  ``generator_path`` (source_commit / input_fingerprint are recorded in the
  report details; they may be null where genuinely unresolvable);
- ``--output`` persists the JSON report (e.g. under ``artifacts/ci/``) so a
  blocked release shows exactly which timeframe or artifact was missing.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

from scripts.smc_atomic_write import atomic_write_text
from smc_integration.release_policy import RELEASE_REFERENCE_SYMBOLS
from smc_integration.structure_contract import normalize_structure_contract

# Keys whose values are, by construction, timestamps of already-observed data.
# Deliberately NOT every ``*_ts`` key: projected/forward-looking event fields
# would false-red against ``generated_at``.
_OBSERVED_DATA_TS_KEYS = frozenset({"asof_ts", "anchor_ts"})


def _max_observed_data_ts(node: Any) -> float | None:
    """Return the newest finite observed-data timestamp in ``node``, if any."""
    newest: float | None = None
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            for key, value in current.items():
                if (
                    key in _OBSERVED_DATA_TS_KEYS
                    and isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and math.isfinite(float(value))
                ):
                    ts = float(value)
                    newest = ts if newest is None else max(newest, ts)
                else:
                    stack.append(value)
        elif isinstance(current, list):
            stack.extend(current)
    return newest


def _check_manifest_counts(timeframe: str, manifest: dict[str, Any], failures: list[str]) -> None:
    counts = manifest.get("counts")
    if not isinstance(counts, dict):
        failures.append(f"{timeframe}: manifest missing counts block (cannot prove completeness)")
        return
    try:
        written = int(counts.get("artifacts_written", -1))
        requested = int(counts.get("symbols_requested", -1))
        errors = int(counts.get("errors", -1))
    except (TypeError, ValueError):
        failures.append(f"{timeframe}: manifest counts are not integers")
        return
    if written < 0 or requested < 0 or errors < 0:
        failures.append(f"{timeframe}: manifest counts are missing or negative")
        return
    if errors:
        failures.append(f"{timeframe}: manifest counts report {errors} producer error(s)")
    if written != requested:
        failures.append(
            f"{timeframe}: incomplete production (artifacts_written={written} != symbols_requested={requested})"
        )


def verify_structure_artifact_availability(
    root: Path,
    timeframes: list[str],
    *,
    expect_symbols: list[str] | None = None,
    max_age_seconds: float | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    artifact_dir = root / "reports" / "smc_structure_artifacts"
    expected = sorted({s.strip().upper() for s in expect_symbols or [] if s.strip()})
    now_ts = float(now) if now is not None else time.time()
    failures: list[str] = []
    verified: dict[str, int] = {}
    details: dict[str, dict[str, Any]] = {}
    for timeframe in timeframes:
        manifest_path = artifact_dir / f"manifest_{timeframe}.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            failures.append(f"{timeframe}: manifest unavailable or invalid ({type(exc).__name__})")
            continue
        rows = manifest.get("artifacts")
        if not isinstance(rows, list) or not rows:
            failures.append(f"{timeframe}: manifest has no artifacts")
            continue
        if manifest.get("errors"):
            failures.append(f"{timeframe}: manifest reports producer errors")
            continue
        _check_manifest_counts(timeframe, manifest, failures)
        provenance = manifest.get("provenance")
        if not isinstance(provenance, dict) or not str(provenance.get("generator_path", "")).strip():
            failures.append(f"{timeframe}: manifest missing generator provenance")
            provenance = None
        manifest_generated_at: float | None = None
        raw_generated_at = manifest.get("generated_at")
        if (
            isinstance(raw_generated_at, (int, float))
            and not isinstance(raw_generated_at, bool)
            and math.isfinite(float(raw_generated_at))
        ):
            manifest_generated_at = float(raw_generated_at)
        age_seconds = None if manifest_generated_at is None else now_ts - manifest_generated_at
        if max_age_seconds is not None:
            if age_seconds is None:
                failures.append(f"{timeframe}: manifest generated_at missing/non-finite (freshness unprovable)")
            elif age_seconds > float(max_age_seconds):
                failures.append(
                    f"{timeframe}: manifest is stale (age {age_seconds:.0f}s > max {float(max_age_seconds):.0f}s)"
                )
        loaded = 0
        loaded_symbols: list[str] = []
        for row in rows:
            if not isinstance(row, dict) or not str(row.get("artifact_path", "")).strip():
                failures.append(f"{timeframe}: malformed manifest artifact row")
                continue
            artifact_path = (root / str(row["artifact_path"])).resolve()
            try:
                payload = json.loads(artifact_path.read_text(encoding="utf-8"))
                contract = normalize_structure_contract(payload)
            except (OSError, ValueError, TypeError) as exc:
                failures.append(
                    f"{timeframe}: artifact {artifact_path.name} unavailable or invalid ({type(exc).__name__})"
                )
                continue
            if contract.symbol != str(row.get("symbol", "")).strip().upper() or contract.timeframe != timeframe:
                failures.append(f"{timeframe}: artifact identity does not match manifest row")
                continue
            artifact_generated_at = payload.get("generated_at")
            newest_data_ts = _max_observed_data_ts(payload.get("structure"))
            if (
                isinstance(artifact_generated_at, (int, float))
                and not isinstance(artifact_generated_at, bool)
                and math.isfinite(float(artifact_generated_at))
                and newest_data_ts is not None
                and float(artifact_generated_at) < newest_data_ts
            ):
                failures.append(
                    f"{timeframe}: artifact {artifact_path.name} has impossible provenance "
                    f"(generated_at {float(artifact_generated_at):.0f} < newest data ts {newest_data_ts:.0f})"
                )
                continue
            if contract.symbol in loaded_symbols:
                failures.append(f"{timeframe}: duplicate manifest symbol {contract.symbol}")
                continue
            loaded += 1
            loaded_symbols.append(contract.symbol)
        missing_symbols = sorted(set(expected) - set(loaded_symbols))
        if missing_symbols:
            failures.append(f"{timeframe}: expected symbols missing from manifest: {','.join(missing_symbols)}")
        details[timeframe] = {
            "loaded": loaded,
            "symbols": sorted(loaded_symbols),
            "generated_at": manifest_generated_at,
            "age_seconds": age_seconds,
            "missing_symbols": missing_symbols,
            "unexpected_symbols": sorted(set(loaded_symbols) - set(expected)) if expected else [],
            "provenance": provenance,
        }
        if loaded:
            verified[timeframe] = loaded
    return {
        "ok": not failures and set(verified) == set(timeframes),
        "verified": verified,
        "failures": failures,
        "details": details,
        "checked": {
            "timeframes": list(timeframes),
            "expect_symbols": expected or None,
            "max_age_seconds": max_age_seconds,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeframes", required=True, help="Comma-separated required timeframes")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--expect-symbols",
        default="",
        help="Comma-separated symbols that every timeframe manifest must cover",
    )
    parser.add_argument(
        "--expect-release-reference-symbols",
        action="store_true",
        help="Require the release-policy reference symbol set (SSOT) per timeframe",
    )
    parser.add_argument(
        "--max-age-seconds",
        type=float,
        default=None,
        help="Fail when a manifest's generated_at is older than this many seconds",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Also persist the JSON report to this path (evidence for blocked releases)",
    )
    args = parser.parse_args()
    timeframes = [value.strip() for value in args.timeframes.split(",") if value.strip()]
    if not timeframes:
        parser.error("--timeframes must contain at least one timeframe")
    expect_symbols = [value.strip() for value in args.expect_symbols.split(",") if value.strip()]
    if args.expect_release_reference_symbols:
        expect_symbols.extend(RELEASE_REFERENCE_SYMBOLS)
    report = verify_structure_artifact_availability(
        args.root.resolve(),
        timeframes,
        expect_symbols=expect_symbols or None,
        max_age_seconds=args.max_age_seconds,
    )
    rendered = json.dumps(report, sort_keys=True)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(rendered + "\n", args.output)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
