#!/usr/bin/env python3
"""Compute Co-Firing matrix + pairwise Cramér's V on 1D corpus."""
import json, math, glob, sys
from collections import defaultdict, Counter
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.smc_atomic_write import atomic_write_json  # noqa: E402

CORPUS_ROOT = Path("/tmp/c10b_local_run/measurement_benchmark")
OUT_DIR = Path("/tmp/provider_audit/skipp-algo/docs/research/c10b")
OUT_DIR.mkdir(parents=True, exist_ok=True)

FAMILIES = ["BOS", "OB", "FVG", "SWEEP"]

# ---- Load all events ----
records = []
for fp in sorted(CORPUS_ROOT.glob("*/1D/events_*_1D.jsonl")):
    for line in fp.read_text().splitlines():
        if line.strip():
            records.append(json.loads(line))

print(f"Loaded {len(records)} events from {CORPUS_ROOT}")

# ---- Group by (symbol, timestamp) bar ----
bars = defaultdict(list)  # (sym, ts) -> [records]
for r in records:
    bars[(r["symbol"], r["timestamp"])].append(r)

# ---- Co-Firing distribution ----
fam_count_dist = Counter()
multi_firing_bars = []
for key, recs in bars.items():
    fams_on_bar = set(r["family"] for r in recs)
    fam_count_dist[len(fams_on_bar)] += 1
    if len(fams_on_bar) >= 2:
        multi_firing_bars.append((key, recs, fams_on_bar))

total_bars = len(bars)
multi_bar_count = sum(c for k, c in fam_count_dist.items() if k >= 2)
multi_pct = 100.0 * multi_bar_count / total_bars if total_bars else 0.0

# Threshold verdict per sprint doc
if multi_pct < 5:
    cofiring_verdict = "BEIBEHALT_TENDENCY (multi-firing <5%)"
elif multi_pct > 20:
    cofiring_verdict = "POOLING_TENDENCY (multi-firing >20%)"
else:
    cofiring_verdict = "INCONCLUSIVE_ZONE (5%..20%)"

# ---- Pairwise co-occurrence on bars ----
pair_cooccurrence = defaultdict(int)
for key, recs, fams_on_bar in multi_firing_bars:
    for a, b in combinations(sorted(fams_on_bar), 2):
        pair_cooccurrence[(a, b)] += 1

# ---- Cramér's V on (family-A outcome × family-B outcome) on co-firing bars ----
# Build per-bar best outcome per family (True if any event of that family on the bar succeeded).
bar_outcomes = {}  # (sym,ts) -> {family: bool}
for key, recs in bars.items():
    fam_map = {}
    for r in recs:
        fam = r["family"]
        # If multiple same-family events on one bar, take ANY-TRUE
        fam_map[fam] = fam_map.get(fam, False) or bool(r["outcome"])
    bar_outcomes[key] = fam_map

def cramers_v_2x2(a11, a10, a01, a00):
    """Cramér's V for 2x2 contingency."""
    n = a11 + a10 + a01 + a00
    if n == 0:
        return None, None, None
    row1 = a11 + a10; row0 = a01 + a00
    col1 = a11 + a01; col0 = a10 + a00
    if row1 == 0 or row0 == 0 or col1 == 0 or col0 == 0:
        return 0.0, 0.0, n
    chi2 = 0.0
    for obs, r, c in [(a11, row1, col1), (a10, row1, col0), (a01, row0, col1), (a00, row0, col0)]:
        exp = r * c / n
        chi2 += (obs - exp) ** 2 / exp
    v = math.sqrt(chi2 / n)  # for 2x2 min(r-1,c-1)=1
    return v, chi2, n

pairwise_v = {}
for a, b in combinations(FAMILIES, 2):
    a11 = a10 = a01 = a00 = 0
    for key, fam_map in bar_outcomes.items():
        if a in fam_map and b in fam_map:
            oa = fam_map[a]; ob = fam_map[b]
            if oa and ob: a11 += 1
            elif oa and not ob: a10 += 1
            elif not oa and ob: a01 += 1
            else: a00 += 1
    v, chi2, n = cramers_v_2x2(a11, a10, a01, a00)
    pairwise_v[f"{a}__{b}"] = {
        "contingency": {"a_true_b_true": a11, "a_true_b_false": a10, "a_false_b_true": a01, "a_false_b_false": a00},
        "n_bars_with_both": n,
        "cramers_v": v,
        "chi2": chi2,
    }

# Verdict on Cramér's V
v_values = [d["cramers_v"] for d in pairwise_v.values() if d["cramers_v"] is not None and d["n_bars_with_both"] and d["n_bars_with_both"] > 0]
v_max = max(v_values) if v_values else None
all_below_02 = all(v < 0.2 for v in v_values) if v_values else False
any_above_05 = any(v > 0.5 for v in v_values) if v_values else False
if all_below_02:
    v_verdict = "BEIBEHALT (all V<0.2 — outcomes independent)"
elif any_above_05:
    v_verdict = "POOLING (some V>0.5 — outcomes redundant)"
else:
    v_verdict = "INCONCLUSIVE_ZONE (0.2 .. 0.5)"

# ---- Persist artifacts ----
cofiring_payload = {
    "schema_version": "1.0",
    "corpus": {
        "source": str(CORPUS_ROOT),
        "timeframe": "1D",
        "n_events": len(records),
        "n_distinct_bars": total_bars,
        "n_symbols": len(set(r["symbol"] for r in records)),
        "date_range_unix": {
            "min": min(r["timestamp"] for r in records),
            "max": max(r["timestamp"] for r in records),
        },
        "family_counts": dict(Counter(r["family"] for r in records)),
    },
    "family_count_distribution": {
        "bars_with_1_family": fam_count_dist.get(1, 0),
        "bars_with_2_families": fam_count_dist.get(2, 0),
        "bars_with_3_families": fam_count_dist.get(3, 0),
        "bars_with_4_families": fam_count_dist.get(4, 0),
    },
    "co_firing": {
        "n_multi_firing_bars": multi_bar_count,
        "n_total_bars": total_bars,
        "multi_firing_pct": multi_pct,
        "threshold_low_pct": 5.0,
        "threshold_high_pct": 20.0,
        "verdict": cofiring_verdict,
    },
    "pairwise_cooccurrence_counts": {f"{a}__{b}": c for (a, b), c in sorted(pair_cooccurrence.items())},
}

cramers_payload = {
    "schema_version": "1.0",
    "corpus": cofiring_payload["corpus"],
    "method": "Pairwise Cramér's V on 2x2 contingency tables of binary outcomes (TP-Hit-before-SL) per family, restricted to bars where both families fired.",
    "pairwise": pairwise_v,
    "verdict": {
        "max_cramers_v": v_max,
        "all_below_0.2": all_below_02,
        "any_above_0.5": any_above_05,
        "decision": v_verdict,
    },
}

atomic_write_json(cofiring_payload, OUT_DIR / "co_firing_matrix.json", default=str)
atomic_write_json(cramers_payload, OUT_DIR / "cramers_v_pairwise.json", default=str)

print("\n=== Co-Firing summary ===")
print(json.dumps(cofiring_payload["family_count_distribution"], indent=2))
print(json.dumps(cofiring_payload["co_firing"], indent=2))
print("Pairwise co-occurrence:", dict(pair_cooccurrence))
print("\n=== Cramér's V summary ===")
for k, v in pairwise_v.items():
    print(f"  {k}: V={v['cramers_v']}, n={v['n_bars_with_both']}, χ²={v['chi2']}")
print("Verdict:", v_verdict)
