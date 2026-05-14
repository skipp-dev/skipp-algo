#!/usr/bin/env python3
"""C10c Step 3 — Joint vs. Product G-Test pro Familien-Paar.

For each family pair {A, B} with ≥ 10 co-firing bars: build the 2×2
contingency table of (outcome_A, outcome_B) on the bars where both
families fired. Compute the G-test (likelihood-ratio chi²) of the joint
distribution against the product of the marginals.

  H0: outcome_A and outcome_B are independent on co-firing bars
  H1: outcome_A and outcome_B have an interaction term

Threshold per sprint anchor: p < 0.01 → reject independence → joint
modelling is worth pursuing in Schritt 4.

Output: ``docs/research/co_firing/joint_vs_product.json``

Caveat reporting:
  - cells with expected frequency E_ij < 5 are flagged as
    underpowered. A pair with any underpowered cell is still
    reported but marked "underpowered=true" and excluded from the
    overall reject-count.
"""
import json
import math
from collections import defaultdict
from itertools import combinations
from pathlib import Path

IN = Path("docs/research/co_firing/per_bar_predictions.jsonl")
OUT = Path("docs/research/co_firing/joint_vs_product.json")
OUT.parent.mkdir(parents=True, exist_ok=True)

ALPHA_REJECT = 0.01
MIN_COFIRING_BARS = 10
MIN_EXPECTED_CELL = 5


def chi2_sf_df1(x: float) -> float:
    """Survival function (1 - CDF) of chi² with df=1.

    For df=1, P(X >= x) = erfc(sqrt(x/2)).
    """
    if x <= 0:
        return 1.0
    return math.erfc(math.sqrt(x / 2.0))


def g_test_2x2(table: list[list[int]]) -> tuple[float, float, list[list[float]], bool]:
    """G-test on a 2x2 contingency table.

    Returns (G_stat, p_value, expected_table, underpowered_flag).
    underpowered_flag is True iff any expected cell < MIN_EXPECTED_CELL.
    """
    row_sums = [sum(row) for row in table]
    col_sums = [sum(table[r][c] for r in range(2)) for c in range(2)]
    n = sum(row_sums)
    if n == 0:
        return float("nan"), float("nan"), [[0.0, 0.0], [0.0, 0.0]], True

    expected = [
        [row_sums[r] * col_sums[c] / n for c in range(2)] for r in range(2)
    ]
    underpowered = any(expected[r][c] < MIN_EXPECTED_CELL for r in range(2) for c in range(2))

    G = 0.0
    for r in range(2):
        for c in range(2):
            o = table[r][c]
            e = expected[r][c]
            if o > 0 and e > 0:
                G += 2.0 * o * math.log(o / e)
    p = chi2_sf_df1(G)
    return G, p, expected, underpowered


records = [
    json.loads(line)
    for line in IN.read_text(encoding="utf-8").splitlines()
    if line.strip()
]

# Collect co-firing bars per pair. A bar with families {A, B, C}
# contributes to (A,B), (A,C), and (B,C) — we count the pair iff
# both members fired, regardless of additional co-fires.
pair_bars: dict[tuple[str, str], list[tuple[bool, bool]]] = defaultdict(list)
families_seen: set[str] = set()

for rec in records:
    fams = sorted(rec["families"])
    families_seen.update(fams)
    outcomes = rec["outcomes"]
    if len(fams) < 2:
        continue
    for a, b in combinations(fams, 2):
        pair_bars[(a, b)].append((bool(outcomes[a]), bool(outcomes[b])))

pair_reports = []
for (a, b), pairs in sorted(pair_bars.items()):
    n = len(pairs)
    # table[outcome_a][outcome_b]: 0=False, 1=True
    table = [[0, 0], [0, 0]]
    for oa, ob in pairs:
        table[int(oa)][int(ob)] += 1
    if n < MIN_COFIRING_BARS:
        pair_reports.append(
            {
                "pair": [a, b],
                "n_cofiring_bars": n,
                "skipped_reason": f"n<{MIN_COFIRING_BARS}",
                "table_observed": table,
            }
        )
        continue
    G, p, expected, underpowered = g_test_2x2(table)
    pair_reports.append(
        {
            "pair": [a, b],
            "n_cofiring_bars": n,
            "table_observed": table,
            "table_expected_under_independence": expected,
            "marginal_hit_rate_a": (
                (table[1][0] + table[1][1]) / n if n else float("nan")
            ),
            "marginal_hit_rate_b": (
                (table[0][1] + table[1][1]) / n if n else float("nan")
            ),
            "G_stat": G,
            "p_value": p,
            "underpowered": underpowered,
            "min_expected_cell": MIN_EXPECTED_CELL,
            "reject_independence_at_alpha":
                (not underpowered)
                and not math.isnan(p)
                and p < ALPHA_REJECT,
            "alpha_reject": ALPHA_REJECT,
        }
    )

n_tested = sum(
    1
    for r in pair_reports
    if r.get("skipped_reason") is None and not r["underpowered"]
)
n_underpowered = sum(
    1 for r in pair_reports if r.get("underpowered", False)
)
n_skipped = sum(1 for r in pair_reports if r.get("skipped_reason") is not None)
n_reject = sum(
    1 for r in pair_reports if r.get("reject_independence_at_alpha", False)
)

payload = {
    "alpha_reject": ALPHA_REJECT,
    "min_cofiring_bars": MIN_COFIRING_BARS,
    "min_expected_cell": MIN_EXPECTED_CELL,
    "n_pairs_total": len(pair_reports),
    "n_pairs_tested": n_tested,
    "n_pairs_underpowered": n_underpowered,
    "n_pairs_skipped_below_min_n": n_skipped,
    "n_pairs_reject_independence": n_reject,
    "pair_reports": pair_reports,
    "verdict": (
        f"interaction detected on {n_reject}/{n_tested} testable pair(s)"
        if n_reject >= 1
        else (
            "no interaction detected — outcomes look factorisable across "
            "co-firing pairs on the 1D corpus"
        )
    ),
}

# ATOMIC-WRITE-EXEMPT: c10c research/analysis script — local one-shot write
# to docs/research/co_firing/ (not production hot path). Same rationale as
# scripts/c10b_compute_cofiring.py.
OUT.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

print(json.dumps(payload, indent=2, default=str))
