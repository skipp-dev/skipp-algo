from __future__ import annotations

# F-V5-A1-2 / F-CI-O1 (2026-05-01) + F-V?-? (2026-05-03): bootstrap repo
# root onto sys.path BEFORE the first-party `from scripts._logging_init`
# import so this file works under both `python -m scripts.X` and
# `python scripts/X.py`. The unconditional `sys.path.insert` (literal
# `sys` name, NOT an alias) also satisfies
# tests/test_workflow_invoked_scripts_import_order.py which detects
# the mutation via AST chain `sys.path.insert` — aliased forms
# (`_v5a12_sys.path.insert`) are not detected and were considered
# late-bootstrap, flagging the early bootstrap import as out-of-order.
import os as _bootstrap_os
import sys as _bootstrap_sys_mod
sys = _bootstrap_sys_mod  # noqa: E402  - bind name `sys` so the AST chain `sys.path.insert` below is detected by the import-order linter

_BOOTSTRAP_ROOT = _bootstrap_os.path.dirname(_bootstrap_os.path.dirname(_bootstrap_os.path.abspath(__file__)))
if _BOOTSTRAP_ROOT not in sys.path:
    sys.path.insert(0, _BOOTSTRAP_ROOT)

from scripts._logging_init import init_cli_logging  # noqa: E402


import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.smc_atomic_write import atomic_write_text  # noqa: E402
from scripts.load_databento_export_bundle import load_export_bundle  # noqa: E402
from smc_integration.artifact_resolution import resolve_structure_artifact_inputs
from smc_integration.release_policy import (
    RELEASE_REFERENCE_SYMBOLS,
    RELEASE_REFERENCE_TIMEFRAMES,
    csv_from_values,
    parse_csv,
    runtime_metadata,
)
from smc_integration.structure_batch import write_structure_artifacts_from_workbook


def _iso_utc(ts: float) -> str:
    return datetime.fromtimestamp(float(ts), tz=UTC).isoformat()


def _render(report: dict[str, Any], output: str) -> None:
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if output == "-":
        print(rendered)
        return
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(rendered + "\n", path)


def _artifact_has_structure_signal(artifact: Any) -> bool:
    if not isinstance(artifact, dict):
        return False

    coverage_mode = str(artifact.get("coverage_mode", "")).strip().lower()
    if coverage_mode and coverage_mode != "none":
        return True

    for key in ("has_bos", "has_orderblocks", "has_fvg", "has_liquidity_sweeps"):
        if bool(artifact.get(key)):
            return True

    for key in ("bos_count", "orderblocks_count", "fvg_count", "liquidity_sweeps_count"):
        value = artifact.get(key, 0)
        try:
            if int(value) > 0:
                return True
        except (TypeError, ValueError):
            continue

    return False


def _collect_structurally_empty_failure(
    manifest: dict[str, Any], *, timeframe: str
) -> dict[str, Any] | None:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        return None

    if any(_artifact_has_structure_signal(artifact) for artifact in artifacts):
        return None

    coverage_modes = sorted({str(artifact.get("coverage_mode", "none")) for artifact in artifacts if isinstance(artifact, dict)})
    # F-V?-? (2026-05-03): attach a snapshot of the manifest's `errors` list
    # as `details` so the soft-skip predicate can apply the same inner-code
    # structural check it already applies to REFRESH_MANIFEST_ERRORS.
    # An empty manifest with no inner errors most likely indicates a
    # producer-side regression (writer ran cleanly but emitted nothing),
    # which must surface as rc=1; only when every inner error is itself a
    # known missing-input class do we treat structural emptiness as a
    # genuine missing-input scenario warranting rc=78.
    manifest_errors = manifest.get("errors")
    details = list(manifest_errors) if isinstance(manifest_errors, list) else []
    return {
        "code": "REFRESH_EMPTY_REFERENCE_ARTIFACTS",
        "timeframe": timeframe,
        "artifacts_evaluated": len(artifacts),
        "coverage_modes": coverage_modes,
        "details": details,
    }


def _discover_available_reference_symbols(
    *,
    workbook_path: Path | None,
    export_bundle_root: Path | None,
    timeframe: str,
) -> list[str] | None:
    discovered = False
    available: list[str] = []
    seen: set[str] = set()

    def _ingest(frame: pd.DataFrame | None) -> None:
        nonlocal discovered
        if not isinstance(frame, pd.DataFrame) or frame.empty or "symbol" not in frame.columns:
            return
        discovered = True
        for raw_symbol in frame["symbol"].dropna().tolist():
            symbol = str(raw_symbol).strip().upper()
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            available.append(symbol)

    required_frames = ("daily_bars",) if str(timeframe).strip().upper() == "1D" else ("full_universe_second_detail_open",)
    if export_bundle_root is not None:
        try:
            bundle = load_export_bundle(
                export_bundle_root,
                required_frames=required_frames,
                manifest_prefix="databento_volatility_production_",
            )
        except Exception:
            bundle = None
        if isinstance(bundle, dict):
            frames = bundle.get("frames", {}) if isinstance(bundle.get("frames"), dict) else {}
            _ingest(frames.get(required_frames[0]))

    if workbook_path is not None and workbook_path.exists():
        try:
            daily_bars = pd.read_excel(workbook_path, sheet_name="daily_bars")
        except Exception:
            daily_bars = pd.DataFrame()
        _ingest(daily_bars)

    if not discovered:
        return None
    return available


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Refresh release-reference structure artifacts before strict release gates.")
    parser.add_argument("--symbols", default=csv_from_values(RELEASE_REFERENCE_SYMBOLS), help="Comma-separated reference symbols.")
    parser.add_argument("--timeframes", default=csv_from_values(RELEASE_REFERENCE_TIMEFRAMES), help="Comma-separated reference timeframes.")
    parser.add_argument(
        "--structure-artifacts-dir",
        default="reports/smc_structure_artifacts",
        help="Directory where structure artifacts/manifest files are written.",
    )
    parser.add_argument("--workbook-path", default="", help="Optional explicit workbook path.")
    parser.add_argument("--export-bundle-root", default="", help="Optional explicit export bundle root path.")
    parser.add_argument("--structure-profile", default="hybrid_default", help="Structure profile used for refresh.")
    parser.add_argument(
        "--allow-missing-inputs",
        action="store_true",
        help="Allow missing workbook/export bundle and keep going with preexisting artifacts.",
    )
    parser.add_argument(
        "--warn-on-empty-artifacts",
        action="store_true",
        help="Downgrade structurally empty refreshed reference artifacts from fail to warn.",
    )
    parser.add_argument(
        "--soft-skip-on-missing-inputs",
        action="store_true",
        help=(
            "Exit with rc=78 (soft-skip) instead of rc=1 when every failure "
            "is REFRESH_EXECUTION_FAILED caused by a missing canonical export "
            "manifest (typical on ephemeral CI runners that do not carry the "
            "upstream Databento export bundle). Bug-Hunt 2026-05-01 F-03."
        ),
    )
    parser.add_argument("--output", default="-", help="Output JSON path, or '-' for stdout.")
    return parser


def main() -> int:
    init_cli_logging()  # F-V5-A1-2 (2026-05-01)
    args = build_parser().parse_args()

    symbols = parse_csv(str(args.symbols), normalize_upper=True)
    timeframes = parse_csv(str(args.timeframes), normalize_upper=False)
    if not symbols:
        raise ValueError("release pre-refresh requires at least one reference symbol")
    if not timeframes:
        raise ValueError("release pre-refresh requires at least one reference timeframe")

    resolved_inputs = resolve_structure_artifact_inputs(
        explicit_workbook_path=str(args.workbook_path).strip() or None,
        explicit_export_bundle_root=str(args.export_bundle_root).strip() or None,
        explicit_structure_artifacts_dir=str(args.structure_artifacts_dir).strip() or None,
    )
    artifacts_dir = resolved_inputs.get("structure_artifacts_dir")
    if artifacts_dir is None:
        artifacts_dir = Path(str(args.structure_artifacts_dir)).expanduser()
    elif not isinstance(artifacts_dir, Path):
        artifacts_dir = Path(str(artifacts_dir)).expanduser()

    refresh_reports: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = list(resolved_inputs.get("warnings", []))

    generated_at = float(time.time())
    for timeframe in timeframes:
        effective_symbols = list(symbols)
        available_reference_symbols = _discover_available_reference_symbols(
            workbook_path=resolved_inputs.get("workbook_path"),
            export_bundle_root=resolved_inputs.get("export_bundle_root"),
            timeframe=timeframe,
        )
        if available_reference_symbols is not None:
            available_symbol_set = set(available_reference_symbols)
            missing_symbols = [symbol for symbol in symbols if symbol not in available_symbol_set]
            if missing_symbols:
                warnings.append(
                    {
                        "code": "REFERENCE_SYMBOLS_UNAVAILABLE_IN_SOURCE",
                        "timeframe": timeframe,
                        "symbols_missing": missing_symbols,
                        "symbols_available": [symbol for symbol in symbols if symbol in available_symbol_set],
                        "message": "Resolved refresh inputs do not cover every requested reference symbol; continuing with the available subset.",
                    }
                )
            effective_symbols = [symbol for symbol in symbols if symbol in available_symbol_set]
            if not effective_symbols:
                failures.append(
                    {
                        "code": "REFRESH_REFERENCE_SYMBOLS_UNAVAILABLE",
                        "timeframe": timeframe,
                        "symbols_requested": symbols,
                        "message": "None of the requested reference symbols were available in the resolved refresh inputs.",
                    }
                )
                continue

        try:
            manifest = write_structure_artifacts_from_workbook(
                workbook=resolved_inputs.get("workbook_path"),
                timeframe=timeframe,
                symbols=effective_symbols,
                output_dir=artifacts_dir,
                export_bundle_root=resolved_inputs.get("export_bundle_root"),
                generated_at=generated_at,
                allow_missing_inputs=bool(args.allow_missing_inputs),
                structure_profile=str(args.structure_profile),
            )
            refresh_reports.append(manifest)
        except Exception as exc:
            failures.append(
                {
                    "code": "REFRESH_EXECUTION_FAILED",
                    "timeframe": timeframe,
                    "message": str(exc),
                }
            )
            continue

        manifest_errors = list(manifest.get("errors", []))
        if manifest_errors:
            failures.append(
                {
                    "code": "REFRESH_MANIFEST_ERRORS",
                    "timeframe": timeframe,
                    "details": manifest_errors,
                }
            )

        counts = manifest.get("counts", {}) if isinstance(manifest.get("counts"), dict) else {}
        symbols_requested = int(counts.get("symbols_requested", 0))
        artifacts_written = int(counts.get("artifacts_written", 0))
        if artifacts_written < symbols_requested:
            # F-V?-? (2026-05-03): attach `details: manifest_errors` so the
            # soft-skip predicate can apply the same inner-code structural
            # check it already applies to REFRESH_MANIFEST_ERRORS. An
            # incomplete reference set with NO inner errors usually means
            # the writer succeeded for some symbols and silently dropped
            # others — a producer regression that must surface as rc=1, not
            # rc=78.
            failures.append(
                {
                    "code": "REFRESH_INCOMPLETE_REFERENCE_SET",
                    "timeframe": timeframe,
                    "symbols_requested": symbols_requested,
                    "artifacts_written": artifacts_written,
                    "details": list(manifest_errors),
                }
            )

        empty_failure = _collect_structurally_empty_failure(manifest, timeframe=timeframe)
        if empty_failure is not None:
            if bool(args.warn_on_empty_artifacts):
                warnings.append(
                    {
                        **empty_failure,
                        "message": "Refreshed reference artifacts are structurally empty for this timeframe.",
                        "promoted_to_warning_by": "warn_on_empty_artifacts",
                    }
                )
            else:
                failures.append(empty_failure)

    checked_at = float(time.time())

    # F-V8-followup (2026-05-02): on a smc-deeper-integration-gates runner
    # without the canonical Databento export bundle the per-timeframe refresh
    # never reaches the `REFRESH_EXECUTION_FAILED` exception path; instead
    # `write_structure_artifacts_from_workbook` returns a manifest containing
    # `errors=[…]` and `counts.artifacts_written < counts.symbols_requested`,
    # which produces `REFRESH_MANIFEST_ERRORS` + `REFRESH_INCOMPLETE_REFERENCE_SET`
    # failures. The previous narrow predicate only soft-skipped on the older
    # `REFRESH_EXECUTION_FAILED` + "manifest" message and therefore exited 1
    # — defeating the workflow's `if rc==78: warn+exit 0` wrapper. Verified
    # against artifact smc_deeper_refresh_report.json from run 25248713567.
    _MISSING_INPUT_FAILURE_CODES = frozenset(
        {
            "REFRESH_REFERENCE_SYMBOLS_UNAVAILABLE",
        }
    )
    # 2026-05-03 (#2034 + follow-up): wrapper failure codes whose severity
    # depends on the *inner* error codes carried in `details`. We only
    # treat them as missing-input when every inner error is itself a
    # missing-input class. Inner codes outside that set indicate real
    # producer breakage and must surface as rc=1, not rc=78.
    # Initially only REFRESH_MANIFEST_ERRORS used this pattern; extended
    # 2026-05-03 to REFRESH_INCOMPLETE_REFERENCE_SET and
    # REFRESH_EMPTY_REFERENCE_ARTIFACTS (which were previously in the
    # unconditional missing-input set above and could mask producer
    # regressions as soft-skips).
    _MISSING_INPUT_WRAPPER_CODES = frozenset(
        {
            "REFRESH_MANIFEST_ERRORS",
            "REFRESH_INCOMPLETE_REFERENCE_SET",
            "REFRESH_EMPTY_REFERENCE_ARTIFACTS",
        }
    )
    _MISSING_INPUT_INNER_CODES = frozenset(
        {
            "WORKBOOK_NOT_FOUND",
            "MISSING_STRUCTURE_INPUTS",
        }
    )
    # 2026-05-03 (#2040 follow-up to #2036): narrow pattern set for inner
    # failures whose ``code`` alone is too broad to soft-skip safely, but
    # whose ``error`` message uniquely identifies a missing-input scenario.
    # Each entry is ``(inner_code, error_substring_lowercase)``; both
    # must match for the failure to be treated as missing-input.
    #
    # Currently registered:
    # * (``BUILD_SYMBOL_ARTIFACT_FAILED``, "workbook fallback is only
    #   supported for 1d") — deeper-gates schedule run cannot fetch
    #   intraday timeframes (5m/15m/1H/4H) without a Databento export
    #   bundle. The production workbook is daily-only by design; the
    #   producer raises ``BUILD_SYMBOL_ARTIFACT_FAILED`` with a
    #   well-defined error string instructing the operator to provide
    #   ``--export-bundle-root`` or use ``--timeframe 1D``. Verified
    #   against artifact smc_deeper_refresh_report.json from run
    #   25271677690 (12 symbols × 4 intraday TFs = 48 inner failures,
    #   all carrying this exact error prefix).
    _MISSING_INPUT_INNER_PATTERNS: tuple[tuple[str, str], ...] = (
        ("BUILD_SYMBOL_ARTIFACT_FAILED", "workbook fallback is only supported for 1d"),
    )

    def _inner_indicates_missing_input(inner: dict[str, Any]) -> bool:
        inner_code = inner.get("code")
        if inner_code in _MISSING_INPUT_INNER_CODES:
            return True
        if not isinstance(inner_code, str):
            return False
        inner_error = str(inner.get("error", "")).lower()
        for pattern_code, pattern_substring in _MISSING_INPUT_INNER_PATTERNS:
            if inner_code == pattern_code and pattern_substring in inner_error:
                return True
        return False

    def _failure_indicates_missing_input(failure: dict[str, Any]) -> bool:
        code = failure.get("code")
        if code in _MISSING_INPUT_FAILURE_CODES:
            return True
        if code in _MISSING_INPUT_WRAPPER_CODES:
            details = failure.get("details")
            if not isinstance(details, list) or not details:
                return False
            return all(
                isinstance(inner, dict) and _inner_indicates_missing_input(inner)
                for inner in details
            )
        if code == "REFRESH_EXECUTION_FAILED":
            message = str(failure.get("message", "")).lower()
            return "manifest" in message or "export bundle" in message
        return False

    soft_skipped = bool(
        getattr(args, "soft_skip_on_missing_inputs", False)
        and failures
        and all(_failure_indicates_missing_input(failure) for failure in failures)
    )
    if soft_skipped:
        exit_code = 78
    else:
        exit_code = 1 if failures else 0
    if soft_skipped:
        overall_status = "skipped"
    elif failures:
        overall_status = "fail"
    elif warnings:
        overall_status = "warn"
    else:
        overall_status = "ok"
    report = {
        "report_kind": "pre_release_refresh",
        "checked_at": checked_at,
        "checked_at_iso": _iso_utc(checked_at),
        "overall_status": overall_status,
        "reference_symbols": symbols,
        "reference_timeframes": timeframes,
        "resolved_inputs": {
            "workbook_path": str(resolved_inputs.get("workbook_path")) if resolved_inputs.get("workbook_path") is not None else None,
            "export_bundle_root": str(resolved_inputs.get("export_bundle_root")) if resolved_inputs.get("export_bundle_root") is not None else None,
            "structure_artifacts_dir": str(artifacts_dir),
            "resolution_mode": str(resolved_inputs.get("resolution_mode", "unknown")),
        },
        "warnings": warnings,
        "failures": failures,
        "refresh_manifests": refresh_reports,
        "runner": {
            "script": "scripts/run_smc_pre_release_artifact_refresh.py",
            "mode": "pre_release_refresh",
            "warn_on_empty_artifacts": bool(args.warn_on_empty_artifacts),
            "soft_skip_on_missing_inputs": bool(getattr(args, "soft_skip_on_missing_inputs", False)),
            "soft_skipped": bool(soft_skipped),
            "exit_code": int(exit_code),
        },
        "runtime_metadata": runtime_metadata(),
    }

    _render(report, str(args.output))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
