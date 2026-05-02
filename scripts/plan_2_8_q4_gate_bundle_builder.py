"""Q4-gate input bundle builder for Plan 2.8 Phase 2 (A/B arm reduction).

Reads two ``plan_2_8_tf_family_rollup.json`` manifests — one from the
baseline (3-TF) arm and one from the candidate (4-TF / 2H) arm — and
projects them into the bundle schema consumed by
``scripts/plan_2_8_q4_gate_evaluator.py``.

Bucket keys are formed as ``"<tf>/<family>"``. Operators can either
take the auto-derived bucket set (intersection of TF×family slices
present in *both* rollups) or restrict it via ``--bucket``.

Brier scores are not produced by the rollup tool; they must be
supplied via ``--brier-baseline`` / ``--brier-candidate`` from the
A/B harness output. The builder refuses to fabricate them.

Exit codes
----------
  0 = bundle written
  1 = I/O error or schema mismatch
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

BUNDLE_SCHEMA_VERSION = 1


def _load(path: Path) -> dict[str, Any]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"unreadable rollup {path}: {exc}") from exc


def _per_tf_families(rollup: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """Return ``{(tf, family): {n_events, hit_rate}}`` for one rollup."""
    per_tf = rollup.get("per_tf") or {}
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for tf, slot in per_tf.items():
        families = (slot or {}).get("families") or {}
        for fam, fslot in families.items():
            out[(str(tf), str(fam))] = {
                "n_events": int(fslot.get("n_events") or 0),
                "hit_rate": float(fslot.get("hit_rate") or 0.0),
            }
    return out


def build_bundle(
    *,
    baseline_rollup: dict[str, Any],
    candidate_rollup: dict[str, Any],
    brier_baseline: float,
    brier_candidate: float,
    bucket_filter: list[str] | None = None,
) -> dict[str, Any]:
    """Project two rollups + Brier scores into an evaluator bundle.

    ``bucket_filter`` (if given) is a list of ``"tf/family"`` strings;
    only those buckets are emitted, in the supplied order. When omitted
    the bundle uses the intersection of TF×family slices, sorted by
    ``(tf, family)`` for determinism.

    The ``n_events`` reported per bucket is the *candidate* arm's count
    (the 2H 4-TF treatment), matching addendum §3.2 G3 which gates on
    the treatment arm's exposure.
    """
    base = _per_tf_families(baseline_rollup)
    cand = _per_tf_families(candidate_rollup)
    common = sorted(set(base.keys()) & set(cand.keys()))

    if bucket_filter is not None:
        wanted: list[tuple[str, str]] = []
        for spec in bucket_filter:
            if "/" not in spec:
                raise ValueError(f"bucket spec must be 'tf/family', got {spec!r}")
            tf, fam = spec.split("/", 1)
            key = (tf.strip(), fam.strip())
            if key not in common:
                raise ValueError(
                    f"bucket {spec!r} not present in both rollups; "
                    f"available: {sorted(spec.replace('/', '/') for spec in (f'{tf}/{fam}' for tf, fam in common))}"
                )
            wanted.append(key)
        keys = wanted
    else:
        keys = common

    buckets: list[dict[str, Any]] = []
    for tf, fam in keys:
        b = base[(tf, fam)]
        c = cand[(tf, fam)]
        buckets.append({
            "key": f"{tf}/{fam}",
            "hr_baseline": b["hit_rate"],
            "hr_candidate": c["hit_rate"],
            "n_events": c["n_events"],
        })

    return {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "buckets": buckets,
        "brier_baseline": float(brier_baseline),
        "brier_candidate": float(brier_candidate),
        "sources": {
            "baseline_rollup": baseline_rollup.get("scoring_root", "?"),
            "candidate_rollup": candidate_rollup.get("scoring_root", "?"),
        },
    }

# F-V6-A1.1 (2026-05-02): bootstrap root logging so the logger.info(...)
# progress messages this entry point emits actually surface in CI logs
# (default WARNING-only handler would drop them). Extends F-V5-A1-2 / #2012
# from the priority entry-point set to plan_2_8 aggregators + showcase.
try:
    from scripts._logging_init import init_cli_logging
except ImportError:  # script-style invocation: `python scripts/X.py`
    import sys as _v6a11_sys
    from pathlib import Path as _v6a11_Path

    _v6a11_sys.path.insert(0, str(_v6a11_Path(__file__).resolve().parents[1]))
    from scripts._logging_init import init_cli_logging  # type: ignore[no-redef]




def main(argv: list[str] | None = None) -> int:
    init_cli_logging()  # F-V6-A1.1 (2026-05-02)
    parser = argparse.ArgumentParser(
        description="Build a Q4-gate input bundle from two rollup manifests.",
    )
    parser.add_argument("--baseline-rollup", type=Path, required=True)
    parser.add_argument("--candidate-rollup", type=Path, required=True)
    parser.add_argument("--brier-baseline", type=float, required=True,
                        help="Aggregate Brier of the 3-TF (baseline) arm.")
    parser.add_argument("--brier-candidate", type=float, required=True,
                        help="Aggregate Brier of the 4-TF (candidate) arm.")
    parser.add_argument("--bucket", action="append", default=None,
                        help="Restrict to specific 'tf/family' bucket(s). "
                             "Repeat the flag for multiple buckets.")
    parser.add_argument("--output", type=Path, required=True,
                        help="Path to write the bundle JSON.")
    args = parser.parse_args(argv)

    try:
        base = _load(args.baseline_rollup)
        cand = _load(args.candidate_rollup)
        bundle = build_bundle(
            baseline_rollup=base,
            candidate_rollup=cand,
            brier_baseline=args.brier_baseline,
            brier_candidate=args.brier_candidate,
            bucket_filter=args.bucket,
        )
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(json.dumps(bundle, indent=2) + "\n", args.output)
    print(f"wrote bundle with {len(bundle['buckets'])} bucket(s) to {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
