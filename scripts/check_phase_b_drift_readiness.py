"""Phase-B promotion readiness gate for live-drift artifacts.

Deep-Review 2026-04-27 follow-up — closes the gap that
``slippage_ks_reference_type == "synthetic_normal"`` was the
silent default of :mod:`scripts.compute_live_drift` while no
backtest slippage sample existed, and the C8 runbook required
``backtest_samples`` for Phase-B sign-off **but no CI check
verified it**.

This module exposes a small, dependency-free CLI that scans a
glob of drift-artifact JSON files and exits non-zero if **any**
artifact is still using a synthetic null distribution for the
slippage K-S comparison.

Wiring:
- ``.github/workflows/drift-watchdog.yml`` runs this in addition
  to the watchdog itself; failure blocks Phase-B promotion.
- Local pre-promotion check::

      python -m scripts.check_phase_b_drift_readiness \\
          artifacts/drift/drift_report_latest.json
"""
from __future__ import annotations

# F-V5-A1-2 / F-CI-O1 (2026-05-01): bootstrap root logging so the
# logger.info(...) progress messages this entry point emits actually
# surface in CI logs (default WARNING-only handler would drop them).
try:
    from scripts._logging_init import init_cli_logging
except ImportError:  # script-style invocation: `python scripts/X.py`
    import sys as _v5a12_sys
    from pathlib import Path as _v5a12_Path

    _v5a12_sys.path.insert(0, str(_v5a12_Path(__file__).resolve().parents[1]))
    from scripts._logging_init import init_cli_logging  # type: ignore[no-redef]


import argparse
import glob
import json
import sys
from collections.abc import Iterable
from pathlib import Path

# String constants kept in sync with ``scripts/compute_live_drift.py``.
SYNTHETIC_NORMAL = "synthetic_normal"
UNAVAILABLE = "unavailable"
BACKTEST_SAMPLES = "backtest_samples"

# Exit codes designed for `set -e` shell wrappers.
EXIT_OK = 0
EXIT_NOT_READY = 2  # synthetic_normal or unavailable found.
EXIT_USAGE = 64  # bad inputs (no files matched).


def _iter_variants(payload: object) -> Iterable[dict]:
    """Yield variant dicts that may carry the slippage reference field.

    Drift artifacts have evolved through several shapes (top-level
    dict, ``{"variants": [...]}``, ``{"per_variant": {name: {...}}}``).
    We accept all three rather than hard-coding one shape so adding
    a new shape later does not silently bypass the gate.
    """
    if isinstance(payload, dict):
        # Top-level direct emission.
        if "slippage_ks_reference_type" in payload:
            yield payload
        # Nested ``variants`` list.
        for v in payload.get("variants", []) or []:
            if isinstance(v, dict):
                yield v
        # Nested ``per_variant`` mapping.
        per = payload.get("per_variant", {}) or {}
        if isinstance(per, dict):
            for v in per.values():
                if isinstance(v, dict):
                    yield v


def assess_artifact(path: Path) -> tuple[bool, list[str]]:
    """Return ``(ready, reasons)`` for a single drift artifact.

    ``ready`` is False if any variant in the artifact has
    ``slippage_ks_reference_type`` set to ``synthetic_normal`` or
    ``unavailable``.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    reasons: list[str] = []
    saw_any = False
    for variant in _iter_variants(payload):
        ref = variant.get("slippage_ks_reference_type")
        if ref is None:
            continue
        saw_any = True
        if ref == SYNTHETIC_NORMAL:
            name = variant.get("variant", "<unnamed>")
            reasons.append(f"{path.name}::{name}: slippage_ks_reference_type={SYNTHETIC_NORMAL!r}")
        elif ref == UNAVAILABLE:
            name = variant.get("variant", "<unnamed>")
            reasons.append(f"{path.name}::{name}: slippage_ks_reference_type={UNAVAILABLE!r}")
        # ``backtest_samples`` => ready for Phase-B (no reason added).
    if not saw_any:
        # Be conservative: an artifact missing the field entirely is
        # treated as not-ready, otherwise old/legacy artifacts would
        # silently pass the gate.
        reasons.append(f"{path.name}: missing slippage_ks_reference_type on all variants")
    return (len(reasons) == 0), reasons


def main(argv: list[str] | None = None) -> int:
    init_cli_logging()  # F-V5-A1-2 (2026-05-01)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="+",
        help="Drift artifact JSON files or globs.",
    )
    args = parser.parse_args(argv)

    files: list[Path] = []
    for raw in args.paths:
        matches = glob.glob(raw)
        # Allow a literal path that exists.
        if not matches and Path(raw).exists():
            matches = [raw]
        for m in matches:
            p = Path(m)
            if p.is_file() and p.suffix == ".json":
                files.append(p)

    if not files:
        print(f"[check_phase_b_drift_readiness] no JSON files matched {args.paths!r}", file=sys.stderr)
        return EXIT_USAGE

    all_reasons: list[str] = []
    for f in sorted(files):
        ready, reasons = assess_artifact(f)
        if not ready:
            all_reasons.extend(reasons)

    if all_reasons:
        print("[check_phase_b_drift_readiness] Phase-B NOT ready:", file=sys.stderr)
        for r in all_reasons:
            print(f"  - {r}", file=sys.stderr)
        return EXIT_NOT_READY

    print(f"[check_phase_b_drift_readiness] OK ({len(files)} artifact(s) ready for Phase-B)")
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
