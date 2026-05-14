#!/usr/bin/env python3
"""C10c Step 2 — Co-firing vs. single-firing hit-rate comparison per family.

For each family F:
  - hits_single = # bars where ONLY F fired and outcome[F] is True
  - n_single    = # bars where ONLY F fired
  - hits_co     = # bars where F fired AND at least one other family
                  also fired AND outcome[F] is True
  - n_co        = # bars where F fired AND at least one other family fired

Two-sided z-test for proportion difference (pooled variance, Newcombe-style
diff). Bonferroni-corrected over 4 families (alpha_fwer = 0.05 → alpha_each
= 0.0125).

Output: ``docs/research/co_firing/cofiring_vs_single_hitrate.json``
"""
import json
import math
from collections import defaultdict
from pathlib import Path

IN = Path("docs/research/co_firing/per_bar_predictions.jsonl")
OUT = Path("docs/research/co_firing/cofiring_vs_single_hitrate.json")
OUT.parent.mkdir(parents=True, exist_ok=True)

FAMILIES = ("BOS", "FVG", "OB", "SWEEP")
ALPHA_FWER = 0.05
N_FAMILIES = len(FAMILIES)
ALPHA_PER_TEST = ALPHA_FWER / N_FAMILIES  # Bonferroni


def two_sided_p_from_z(z: float) -> float:
    """Two-sided p-value from a z-statistic via the normal CDF."""
    return 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(z) / math.sqrt(2.0))))


def two_proportion_z_test(
    hits1: int, n1: int, hits2: int, n2: int
) -> tuple[float, float]:
    """Pooled two-proportion z-test (single vs. co-firing).

    Returns (z, two_sided_p). NaN if either group is empty or pooled
    variance is zero.
    """
    if n1 == 0 or n2 == 0:
        return float("nan"), float("nan")
    p1 = hits1 / n1
    p2 = hits2 / n2
    p_pool = (hits1 + hits2) / (n1 + n2)
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    if se == 0:
        return float("nan"), float("nan")
    z = (p1 - p2) / se
    return z, two_sided_p_from_z(z)


records = [
    json.loads(line)
    for line in IN.read_text(encoding="utf-8").splitlines()
    if line.strip()
]

# Build single / co-fire counters per family.
single_n: dict[str, int] = defaultdict(int)
single_hits: dict[str, int] = defaultdict(int)
co_n: dict[str, int] = defaultdict(int)
co_hits: dict[str, int] = defaultdict(int)

for rec in records:
    fams = rec["families"]
    outcomes = rec["outcomes"]
    if len(fams) == 1:
        f = fams[0]
        single_n[f] += 1
        if outcomes[f]:
            single_hits[f] += 1
    else:
        for f in fams:
            co_n[f] += 1
            if outcomes[f]:
                co_hits[f] += 1

per_family = []
for f in FAMILIES:
    hits_s, n_s = single_hits[f], single_n[f]
    hits_c, n_c = co_hits[f], co_n[f]
    p_s = hits_s / n_s if n_s else float("nan")
    p_c = hits_c / n_c if n_c else float("nan")
    z, p = two_proportion_z_test(hits_s, n_s, hits_c, n_c)
    diff_pp = (p_c - p_s) * 100.0 if not (math.isnan(p_s) or math.isnan(p_c)) else float("nan")
    per_family.append(
        {
            "family": f,
            "single_firing": {"hits": hits_s, "n": n_s, "hit_rate": p_s},
            "co_firing": {"hits": hits_c, "n": n_c, "hit_rate": p_c},
            "diff_pp_co_minus_single": diff_pp,
            "z_stat": z,
            "p_value_two_sided": p,
            "reject_pool_at_alpha_per_test": (not math.isnan(p)) and p < ALPHA_PER_TEST,
            "alpha_per_test_bonferroni": ALPHA_PER_TEST,
        }
    )

n_significant = sum(1 for r in per_family if r["reject_pool_at_alpha_per_test"])

payload = {
    "n_total_bars": len(records),
    "alpha_fwer": ALPHA_FWER,
    "alpha_per_test_bonferroni": ALPHA_PER_TEST,
    "n_families": N_FAMILIES,
    "n_significant": n_significant,
    "per_family": per_family,
    "verdict": (
        "co-firing lifts hit-rate significantly for ≥1 family"
        if n_significant >= 1
        else "no per-family hit-rate lift from co-firing detected"
    ),
}

# ATOMIC-WRITE-EXEMPT: c10c research/analysis script — local one-shot write
# to docs/research/co_firing/ (not production hot path). Same rationale as
# scripts/c10b_compute_cofiring.py.
OUT.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

print(json.dumps(payload, indent=2, default=str))
