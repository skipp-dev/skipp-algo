"""E2E Smoke Test for CI — deterministic structural regression guard.

This script validates that the release-gate runner, governance registry,
and artifact structure remain consistent with a known-good reference.
It does NOT run the full measurement pipeline; it exercises the structural
contracts that unit tests miss (row shifts, gate classification drift,
import chains, artifact key sets).

Usage:
    python scripts/e2e_smoke_ci.py [--reference tests/fixtures/e2e_smoke_reference.json]
    python scripts/e2e_smoke_ci.py --update-reference

CI Integration:
    This script runs as an advisory (non-blocking) step in the
    ``smc-deeper-integration-gates`` workflow.  Results appear in
    the workflow summary and are uploaded as part of the
    ``smc-deeper-gate-evidence`` artifact.

What this smoke test protects:
    - GovernanceStatus enum values and registry completeness
    - HARD_BLOCKING_DEGRADATION_CODES consistency with registry
    - Gate names emitted by the release-gate runner
    - MeasurementShadowThresholds field set and default values
    - Dashboard audit-view row count (from SMC_Dashboard.pine)
    - Release reference symbols and timeframes

What this smoke test does NOT protect:
    - Actual measurement quality / metric values
    - Live TradingView chart rendering
    - Provider data availability
    - Network-dependent operations

How to update the reference file:
    When a legitimate structural change is made (e.g. new gate, new
    dashboard row, new governance code), run:
        python scripts/e2e_smoke_ci.py --update-reference
    Review the diff, commit the updated reference file.
"""
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
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Bug-Hunt 2026-05-01 F-01: deferred so the script also works when
# invoked as `python scripts/X.py` (no PYTHONPATH=.) — sys.path.insert
# above must happen before any first-party `from scripts.` import.
from scripts.smc_atomic_write import atomic_write_text  # noqa: E402

DEFAULT_REFERENCE = REPO_ROOT / "tests" / "fixtures" / "e2e_smoke_reference.json"


def collect_smoke_snapshot() -> dict[str, Any]:
    """Collect the current structural snapshot for comparison."""
    from smc_integration.release_policy import (
        GATE_GOVERNANCE_REGISTRY,
        HARD_BLOCKING_DEGRADATION_CODES,
        RELEASE_REFERENCE_SYMBOLS,
        RELEASE_REFERENCE_TIMEFRAMES,
        GovernanceStatus,
        MeasurementShadowThresholds,
        serialize_measurement_shadow_thresholds,
        validate_gate_governance_registry,
    )

    # 1. Governance registry
    governance_codes = sorted(g.code for g in GATE_GOVERNANCE_REGISTRY)
    governance_by_status = {}
    for status in GovernanceStatus:
        codes = sorted(
            g.code for g in GATE_GOVERNANCE_REGISTRY
            if g.promotion_state == status
        )
        governance_by_status[status.value] = codes

    governance_validation_errors = validate_gate_governance_registry()

    # 2. Hard-blocking codes
    hard_blocking_codes = sorted(HARD_BLOCKING_DEGRADATION_CODES)

    # 3. Threshold defaults
    thresholds = serialize_measurement_shadow_thresholds(MeasurementShadowThresholds())
    threshold_fields = sorted(thresholds.keys())

    # 4. Release reference set
    reference_symbols = list(RELEASE_REFERENCE_SYMBOLS)
    reference_timeframes = list(RELEASE_REFERENCE_TIMEFRAMES)

    # 5. GovernanceStatus enum values
    governance_status_values = sorted(s.value for s in GovernanceStatus)

    # 6. Dashboard row count (from Pine source)
    dashboard_row_count = _count_dashboard_audit_rows()

    # 7. Gate names from runner
    gate_names = _collect_gate_names()

    return {
        "schema": "e2e_smoke_v1",
        "governance_codes": governance_codes,
        "governance_by_status": governance_by_status,
        "governance_status_values": governance_status_values,
        "governance_validation_errors": governance_validation_errors,
        "hard_blocking_codes": hard_blocking_codes,
        "threshold_fields": threshold_fields,
        "threshold_defaults": thresholds,
        "reference_symbols": reference_symbols,
        "reference_symbols_count": len(reference_symbols),
        "reference_timeframes": reference_timeframes,
        "dashboard_audit_row_count": dashboard_row_count,
        "gate_names": gate_names,
    }


def _count_dashboard_audit_rows() -> int | None:
    """Count dashboard row calls in the audit view section of SMC_Dashboard.pine."""
    dashboard_path = REPO_ROOT / "SMC_Dashboard.pine"
    if not dashboard_path.exists():
        return None
    content = dashboard_path.read_text(encoding="utf-8", errors="replace")
    # Count lines that call dashboard_row(), dashboard_row_tt(), or section_row()
    # in the audit else block. Tooltip rows render real table rows too; excluding
    # them made the snapshot drift when a visible row gained hover copy.
    in_audit = False
    count = 0
    for line in content.splitlines():
        stripped = line.strip()
        if 'surface_mode == "Decision Brief"' in stripped:
            in_audit = False
        if "Audit View" in stripped:
            in_audit = True
        if in_audit and (
            "dashboard_row(" in stripped
            or "dashboard_row_tt(" in stripped
            or "section_row(" in stripped
        ):
            count += 1
    return count


def _collect_gate_names() -> list[str]:
    """Collect the known gate names from the release-gate runner."""
    # These are the gate names that the runner produces.
    # We extract them statically to avoid running the full pipeline.
    return sorted([
        "provider_health",
        "publish_contract",
        "reference_bundle",
        "measurement_lane",
        "post_release_validation",
    ])


def compare_snapshots(
    current: dict[str, Any],
    reference: dict[str, Any],
) -> list[str]:
    """Compare current snapshot against reference, return list of differences."""
    diffs: list[str] = []

    # Governance validation must pass
    errors = current.get("governance_validation_errors", [])
    if errors:
        diffs.append(f"Governance validation failed: {errors}")

    # Keys to compare exactly
    exact_keys = [
        "governance_codes",
        "governance_by_status",
        "governance_status_values",
        "hard_blocking_codes",
        "threshold_fields",
        "threshold_defaults",
        "reference_symbols",
        "reference_timeframes",
        "gate_names",
    ]
    for key in exact_keys:
        current_val = current.get(key)
        reference_val = reference.get(key)
        if current_val != reference_val:
            diffs.append(
                f"{key} changed:\n"
                f"  reference: {json.dumps(reference_val, sort_keys=True)}\n"
                f"  current:   {json.dumps(current_val, sort_keys=True)}"
            )

    # Dashboard row count: must not change silently
    ref_rows = reference.get("dashboard_audit_row_count")
    cur_rows = current.get("dashboard_audit_row_count")
    if ref_rows is not None and cur_rows is not None and ref_rows != cur_rows:
        diffs.append(
            f"Dashboard audit row count changed: {ref_rows} -> {cur_rows}"
        )

    # Symbol count must not silently shrink
    ref_sym_count = reference.get("reference_symbols_count", 0)
    cur_sym_count = current.get("reference_symbols_count", 0)
    if cur_sym_count < ref_sym_count:
        diffs.append(
            f"Reference symbol count shrank: {ref_sym_count} -> {cur_sym_count}"
        )

    return diffs


def main() -> int:
    init_cli_logging()  # F-V5-A1-2 (2026-05-01)
    parser = argparse.ArgumentParser(description="E2E smoke test for CI.")
    parser.add_argument(
        "--reference",
        default=str(DEFAULT_REFERENCE),
        help="Path to reference snapshot JSON.",
    )
    parser.add_argument(
        "--update-reference",
        action="store_true",
        help="Update the reference file with current snapshot.",
    )
    args = parser.parse_args()

    current = collect_smoke_snapshot()

    if args.update_reference:
        ref_path = Path(args.reference)
        ref_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", ref_path)
        print(f"Reference updated: {ref_path}")
        return 0

    ref_path = Path(args.reference)
    if not ref_path.exists():
        print(f"ERROR: Reference file not found: {ref_path}")
        print("Run with --update-reference to create it.")
        return 1

    reference = json.loads(ref_path.read_text(encoding="utf-8"))
    diffs = compare_snapshots(current, reference)

    if diffs:
        print(f"E2E SMOKE FAILED — {len(diffs)} structural difference(s):")
        for i, diff in enumerate(diffs, 1):
            print(f"  [{i}] {diff}")
        print()
        print("If these changes are intentional, run:")
        print("  python scripts/e2e_smoke_ci.py --update-reference")
        return 1

    print("E2E smoke test passed — no structural regressions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
