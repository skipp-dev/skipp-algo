#!/usr/bin/env python3
"""Replicate Step 2d (variance decomposition + family/context analysis) on 1D corpus.

Mirrors family_partition_analysis_v4_corpus.json structure for direct comparison.
"""
import json
import math
from itertools import combinations
from pathlib import Path
from statistics import mean

CORPUS_ROOT = Path("/tmp/c10b_local_run/measurement_benchmark")
OUT = Path("/tmp/provider_audit/skipp-algo/docs/research/c10b/family_partition_analysis_1d_corpus.json")

FAMILIES = ["BOS", "OB", "FVG", "SWEEP"]
CONTEXTS = [
    ("htf_bias", ["BEARISH", "BULLISH"]),
    ("session", ["ASIA", "LONDON", "NY_AM"]),
    ("vol_regime", ["HIGH_VOL", "LOW_VOL", "NORMAL"]),
]

records = []
for fp in sorted(CORPUS_ROOT.glob("*/1D/events_*_1D.jsonl")):
    for line in fp.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))

print(f"Loaded {len(records)} events")

# ---- Family hit rates with Wilson CI95 ----
def wilson_ci(p, n, z=1.96):
    if n == 0: return [None, None]
    denom = 1 + z*z/n
    centre = (p + z*z/(2*n)) / denom
    half = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / denom
    return [round(centre - half, 4), round(centre + half, 4)]

baseline = {}
for fam in FAMILIES:
    fam_recs = [r for r in records if r["family"] == fam]
    n = len(fam_recs)
    hits = sum(1 for r in fam_recs if r["outcome"])
    hr = hits / n if n else 0.0
    baseline[fam] = {
        "n": n,
        "hits": hits,
        "hit_rate": round(hr, 4),
        "ci95": wilson_ci(hr, n),
        "weight": round(hr, 4),  # same convention as v4
    }

# ---- Pairwise z-tests (proportion difference) ----
def z_two_prop(x1, n1, x2, n2):
    if n1 == 0 or n2 == 0:
        return 0.0, 1.0
    p1, p2 = x1/n1, x2/n2
    p = (x1+x2)/(n1+n2)
    se = math.sqrt(p*(1-p)*(1/n1+1/n2))
    if se == 0:
        return 0.0, 1.0
    z = (p1-p2)/se
    # two-sided p
    from math import erf, sqrt
    p_val = 2 * (1 - 0.5*(1+erf(abs(z)/sqrt(2))))
    return z, p_val

bonf_alpha = 0.05 / 6
pairwise = []
for a, b in combinations(FAMILIES, 2):
    ba, bb = baseline[a], baseline[b]
    z, pv = z_two_prop(ba["hits"], ba["n"], bb["hits"], bb["n"])
    pairwise.append({
        "pair": f"{a} vs {b}",
        "delta_hit_rate": round(ba["hit_rate"] - bb["hit_rate"], 4),
        "z": round(z, 3),
        "p_value": round(pv, 6),
        "reject_pool_at_bonf_0.05": pv < bonf_alpha,
    })

# ---- Within-family context dispersion ----
def bucket_label(ctx_key, val):
    return f"{ctx_key}:{val}"

context_buckets = []
for ck, vals in CONTEXTS:
    for v in vals:
        context_buckets.append((ck, v, bucket_label(ck, v)))

within = {}
contextual_weights_per_family = {}  # fam -> {bucket: hit_rate} for variance decomp
for fam in FAMILIES:
    fam_recs = [r for r in records if r["family"] == fam]
    per_bucket = []
    bucket_weights = {}
    for ck, val, label in context_buckets:
        sub = [r for r in fam_recs if r["context"].get(ck) == val]
        if not sub:
            continue
        hr = sum(1 for r in sub if r["outcome"]) / len(sub)
        per_bucket.append([label, round(hr, 4)])
        bucket_weights[label] = hr
    contextual_weights_per_family[fam] = bucket_weights
    if per_bucket:
        weights = [w for _, w in per_bucket]
        rng = max(weights) - min(weights)
        m = mean(weights)
        if len(weights) > 1:
            std = math.sqrt(sum((w - m)**2 for w in weights) / (len(weights) - 1))
        else:
            std = 0.0
    else:
        rng = std = m = 0.0
    within[fam] = {
        "global_weight": baseline[fam]["weight"],
        "context_range": round(rng, 4),
        "context_std": round(std, 4),
        "context_mean": round(m, 4),
        "per_bucket": per_bucket,
    }

# ---- Rank inversion by context ----
global_rank = sorted(FAMILIES, key=lambda f: -baseline[f]["weight"])
inversions = {}
for _, _, label in context_buckets:
    weights_here = {}
    for fam in FAMILIES:
        w = contextual_weights_per_family[fam].get(label)
        if w is not None:
            weights_here[fam] = w
    if len(weights_here) >= 2:
        ctx_rank_all = sorted(FAMILIES, key=lambda f: -weights_here.get(f, -1) if f in weights_here else 1)
        # Only meaningful if all 4 represented
        if all(f in weights_here for f in FAMILIES):
            ctx_rank = sorted(FAMILIES, key=lambda f: -weights_here[f])
            if ctx_rank != global_rank:
                inversions[label] = {
                    "global_rank": global_rank,
                    "context_rank": ctx_rank,
                    "weights": {f: round(weights_here[f], 4) for f in FAMILIES},
                }

# ---- Variance decomposition on contextual weights ----
# Build matrix: rows = (family, bucket) with weight value (skip empty buckets)
data_points = []
for fam in FAMILIES:
    for label, w in contextual_weights_per_family[fam].items():
        data_points.append((fam, label, w))

if data_points:
    grand = mean(w for _, _, w in data_points)
    fam_means = {fam: mean(w for f, _, w in data_points if f == fam) for fam in FAMILIES if any(f == fam for f, _, _ in data_points)}
    ctx_means = {}
    for ck, val, label in context_buckets:
        vals = [w for _, l, w in data_points if l == label]
        if vals:
            ctx_means[label] = mean(vals)

    ss_total = sum((w - grand)**2 for _, _, w in data_points)
    ss_family = sum((fam_means[f] - grand)**2 for f, _, _ in data_points)
    ss_context = sum((ctx_means[l] - grand)**2 for _, l, _ in data_points)
    ss_residual = sum((w - fam_means[f] - ctx_means[l] + grand)**2 for f, l, w in data_points)
else:
    ss_total = ss_family = ss_context = ss_residual = 0.0

def safediv(a, b):
    return a / b if b else 0.0

variance_decomp = {
    "ss_total": round(ss_total, 6),
    "ss_between_family": round(ss_family, 6),
    "ss_between_context": round(ss_context, 6),
    "ss_residual": round(ss_residual, 6),
    "eta_squared_family": round(safediv(ss_family, ss_total), 4),
    "eta_squared_context": round(safediv(ss_context, ss_total), 4),
    "eta_squared_residual": round(safediv(ss_residual, ss_total), 4),
}

# ---- PSI-like (within family over contexts) ----
psi_like = {}
for fam in FAMILIES:
    weights = list(contextual_weights_per_family[fam].values())
    if len(weights) < 2:
        psi_like[fam] = None; continue
    base = mean(weights)
    # PSI surrogate: sum (w - base)^2 / base * weighting
    if base <= 0 or base >= 1:
        psi_like[fam] = 0.0; continue
    psi = sum((w - base)**2 for w in weights) / base
    psi_like[fam] = round(psi, 4)

# ---- Calibration per context bucket (smooth ECE) ----
def smooth_ece(events, n_bins=10):
    if not events: return None
    bins = [[] for _ in range(n_bins)]
    for p, y in events:
        idx = min(int(p * n_bins), n_bins - 1)
        bins[idx].append((p, y))
    n = len(events)
    ece = 0.0
    for bucket in bins:
        if not bucket: continue
        avg_p = mean(p for p, _ in bucket)
        avg_y = mean(y for _, y in bucket)
        ece += (len(bucket)/n) * abs(avg_p - avg_y)
    return round(ece, 6)

calibration = {}
for ck, val, label in context_buckets:
    sub = [(r["predicted_prob"], 1 if r["outcome"] else 0) for r in records if r["context"].get(ck) == val]
    if len(sub) < 30:
        calibration[label] = {"n_events": len(sub), "smooth_ece": None, "positive_rate": None, "status": "insufficient_events"}
    else:
        calibration[label] = {
            "n_events": len(sub),
            "smooth_ece": smooth_ece(sub),
            "positive_rate": round(mean(y for _, y in sub), 6),
            "status": "ok",
        }

payload = {
    "corpus": "local_workbook_fallback_1D_2026-05-13 (replication)",
    "corpus_metadata": {
        "source": str(CORPUS_ROOT),
        "timeframe": "1D",
        "n_symbols": len(set(r["symbol"] for r in records)),
        "date_range_unix": {"min": min(r["timestamp"] for r in records), "max": max(r["timestamp"] for r in records)},
        "bars_source_mode": "workbook_fallback",
        "production_workbook": "databento_volatility_production_20260307_114724.xlsx",
    },
    "n_events_total": len(records),
    "baseline_family_hit_rates": baseline,
    "pairwise_between_family_tests_bonf_alpha": bonf_alpha,
    "pairwise_between_family": pairwise,
    "within_family_context_dispersion": within,
    "between_family_rank_inversion_by_context": inversions,
    "variance_decomposition_on_contextual_weights": variance_decomp,
    "psi_like_within_family_over_contexts": psi_like,
    "calibration_per_context_bucket": calibration,
}

# ATOMIC-WRITE-EXEMPT: c10b research/analysis script — local one-shot write to
# docs/research/c10b/ (not production hot path, no concurrent consumers). The
# sys.path-insert + lint-suppression import pattern needed to reach
# smc_atomic_write would trip the sys-path and lint-suppression discipline
# pins; this exempt marker is the explicit alternative.
OUT.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
print(json.dumps({
    "baseline": {f: {"n": baseline[f]["n"], "hit_rate": baseline[f]["hit_rate"]} for f in FAMILIES},
    "pairwise_significant": sum(1 for p in pairwise if p["reject_pool_at_bonf_0.05"]),
    "variance_decomp": variance_decomp,
    "inversions": list(inversions.keys()),
    "psi": psi_like,
}, indent=2))
print(f"\nWrote {OUT}")
