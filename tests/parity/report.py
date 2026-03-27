"""Parity report utility — summarizes canonical ↔ bridge ↔ TV drift.

Usage:
    python -m tests.parity.report

Outputs a text summary to stdout suitable for CI logs.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any

from tests.parity.fixtures import PARITY_FIXTURES
from tests.parity.normalization import (
    bridge_bos_to_dicts,
    bridge_fvg_to_dicts,
    bridge_ob_to_dicts,
    bridge_sweep_to_dicts,
    normalize_canonical_bos,
    normalize_canonical_fvg,
    normalize_canonical_ob,
    normalize_canonical_sweeps,
    strip_pine_style,
)

from scripts.explicit_structure_from_bars import build_explicit_structure_from_bars
from smc_adapters.ingest import build_structure_from_raw
from smc_adapters.pine import snapshot_to_pine_payload
from smc_core import apply_layering
from smc_core.types import SmcMeta, TimedVolumeInfo, VolumeInfo


@dataclass
class FamilyResult:
    family: str
    canonical_count: int
    bridge_count: int
    exact_match: bool
    normalized_match: bool
    diff_detail: str = ""


@dataclass
class FixtureResult:
    name: str
    families: list[FamilyResult] = field(default_factory=list)
    pine_families: list[FamilyResult] = field(default_factory=list)
    error: str | None = None


def _default_meta(symbol: str, timeframe: str) -> SmcMeta:
    return SmcMeta(
        symbol=symbol,
        timeframe=timeframe,
        asof_ts=1709253580.0,
        volume=TimedVolumeInfo(
            value=VolumeInfo(regime="NORMAL", thin_fraction=0.1),
            asof_ts=1709253580.0,
            stale=False,
        ),
    )


def _compare_family(
    name: str,
    canonical: list[dict[str, Any]],
    bridge: list[dict[str, Any]],
) -> FamilyResult:
    exact = canonical == bridge
    return FamilyResult(
        family=name,
        canonical_count=len(canonical),
        bridge_count=len(bridge),
        exact_match=exact,
        normalized_match=exact,  # normalization already applied by caller
        diff_detail="" if exact else f"first mismatch in {name}",
    )


def run_parity_report() -> list[FixtureResult]:
    results: list[FixtureResult] = []

    for fixture_name, factory, symbol, timeframe in PARITY_FIXTURES:
        bars = factory(symbol=symbol)
        fr = FixtureResult(name=fixture_name)

        try:
            canonical = build_explicit_structure_from_bars(
                bars, symbol=symbol, timeframe=timeframe, structure_profile="hybrid_default",
            )
        except Exception as exc:
            fr.error = f"canonical build failed: {exc}"
            results.append(fr)
            continue

        # --- canonical → bridge structure ---
        raw_structure = {
            "bos": canonical["bos"],
            "orderblocks": canonical["orderblocks"],
            "fvg": canonical["fvg"],
            "liquidity_sweeps": canonical["liquidity_sweeps"],
        }
        try:
            bridge_structure = build_structure_from_raw(raw_structure)
        except Exception as exc:
            fr.error = f"bridge ingest failed: {exc}"
            results.append(fr)
            continue

        # Normalize and compare each family
        comparisons = [
            ("bos", normalize_canonical_bos(canonical["bos"]), bridge_bos_to_dicts(bridge_structure.bos)),
            ("orderblocks", normalize_canonical_ob(canonical["orderblocks"]), bridge_ob_to_dicts(bridge_structure.orderblocks)),
            ("fvg", normalize_canonical_fvg(canonical["fvg"]), bridge_fvg_to_dicts(bridge_structure.fvg)),
            ("liquidity_sweeps", normalize_canonical_sweeps(canonical["liquidity_sweeps"]), bridge_sweep_to_dicts(bridge_structure.liquidity_sweeps)),
        ]
        for family_name, canon_norm, bridge_norm in comparisons:
            fr.families.append(_compare_family(family_name, canon_norm, bridge_norm))

        # --- bridge → TV pine payload ---
        try:
            meta = _default_meta(symbol, timeframe)
            snapshot = apply_layering(bridge_structure, meta, generated_at=1709254000.0)
            pine = snapshot_to_pine_payload(snapshot)
        except Exception as exc:
            fr.error = f"pine payload build failed: {exc}"
            results.append(fr)
            continue

        pine_comparisons = [
            ("bos", bridge_bos_to_dicts(bridge_structure.bos), strip_pine_style(pine.get("bos", []))),
            ("orderblocks", bridge_ob_to_dicts(bridge_structure.orderblocks), strip_pine_style(pine.get("orderblocks", []))),
            ("fvg", bridge_fvg_to_dicts(bridge_structure.fvg), strip_pine_style(pine.get("fvg", []))),
            ("liquidity_sweeps", bridge_sweep_to_dicts(bridge_structure.liquidity_sweeps), strip_pine_style(pine.get("liquidity_sweeps", []))),
        ]
        for family_name, bridge_norm, pine_norm in pine_comparisons:
            fr.pine_families.append(_compare_family(family_name, bridge_norm, pine_norm))

        results.append(fr)

    return results


def print_parity_report(results: list[FixtureResult]) -> bool:
    """Print summary and return True if all passed."""
    total = len(results)
    errors = [r for r in results if r.error]
    all_ok = True

    print("=" * 60)
    print("SMC PARITY REPORT")
    print("=" * 60)
    print(f"Total fixtures:  {total}")
    print(f"Build errors:    {len(errors)}")
    print()

    for r in results:
        status = "ERROR" if r.error else "OK"
        if not r.error:
            for fam in r.families + r.pine_families:
                if not fam.normalized_match:
                    status = "DRIFT"
                    all_ok = False
                    break
        else:
            all_ok = False

        print(f"  [{status:5s}] {r.name}")

        if r.error:
            print(f"         → {r.error}")
            continue

        for fam in r.families:
            match_label = "exact" if fam.exact_match else "DRIFT"
            print(f"         canonical→bridge  {fam.family:20s}  "
                  f"canon={fam.canonical_count} bridge={fam.bridge_count}  [{match_label}]")

        for fam in r.pine_families:
            match_label = "exact" if fam.exact_match else "DRIFT"
            print(f"         bridge→pine       {fam.family:20s}  "
                  f"bridge={fam.canonical_count} pine={fam.bridge_count}  [{match_label}]")

    print()
    print(f"Result: {'ALL PASS' if all_ok else 'FAILURES DETECTED'}")
    print("=" * 60)
    return all_ok


def main() -> None:
    results = run_parity_report()
    ok = print_parity_report(results)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
