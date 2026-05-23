"""Phase-B simulation: per-category breakdown (Option 2) + content-addressed
re-key (Option 1) for issue #2334.

Reads the existing baseline/run1 + baseline/run2 cache-probe JSONL artifacts
and answers:

  - Where are the hits in the existing 12.40% baseline? (per category)
  - What would the cross-day hit-rate be if `build_cache_path` dropped the
    universe-scope token from `parts`? (per category, lookup-weighted + set-overlap)

Pure offline analysis. No production code touched, no Databento quota used.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

# CACHE_VERSION_BY_CATEGORY mirror -- needed to recompute the trailing
# digest after we strip the universe-scope token. Must be kept in sync with
# databento_utils.py until/unless this becomes a real test fixture.
CACHE_VERSION_BY_CATEGORY = {
    "daily_bars": "v2",
    "symbol_support": "v2",
    "full_universe_open_second_detail": "v2",
    "full_universe_close_trade_detail": "v1",
    "full_universe_close_outcome_minute_detail": "v1",
    "intraday_summary": "v2",
    "symbol_detail_second": "v2",
    "symbol_detail_minute": "v2",
}
DEFAULT_CACHE_VERSION = "v1"

# `_symbol_scope_token` mints "<count>_<sha1-12hex>" -- this regex matches.
SCOPE_TOKEN_RE = re.compile(r"^\d+_[0-9a-f]{12}$")

# Trailing digest in every filename is sha1[:12] of (version|category|dataset|parts...).
# build_cache_path joins parts with "__" then appends "__<digest>", so the
# separator between the last part and the digest is "__" (two underscores).
# Using a single underscore here would leave a stray "_" tail on the last
# part and break the scope-token regex below.
TRAILING_DIGEST_RE = re.compile(r"__[0-9a-f]{12}$")


def _digest(parts: list[str], *, version: str, category: str, dataset: str) -> str:
    return hashlib.sha1(
        "|".join([version, category, dataset, *parts]).encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()[:12]


def _parse_event(event: dict) -> tuple[str, str, list[str]] | None:
    """Return (category, dataset, parts_excluding_trailing_digest) or None.

    The probe path looks like
        .../databento_volatility_cache/<category>/<dataset>/<parts>__<digest>.<suffix>
    """
    path = Path(event["path"])
    try:
        cache_idx = path.parts.index("databento_volatility_cache")
    except ValueError:
        return None
    tail = path.parts[cache_idx + 1 :]
    if len(tail) < 3:
        return None
    category, dataset, filename = tail[0], tail[1], tail[-1]
    stem = Path(filename).stem
    if not TRAILING_DIGEST_RE.search(stem):
        return None
    # Drop the trailing __<12hex>
    parts_str = TRAILING_DIGEST_RE.sub("", stem)
    parts = parts_str.split("__") if parts_str else []
    return category, dataset, parts


def _strip_scope_token(parts: list[str]) -> tuple[list[str], bool]:
    stripped = [p for p in parts if not SCOPE_TOKEN_RE.match(p)]
    return stripped, len(stripped) != len(parts)


def _canonical_key(category: str, dataset: str, parts: list[str]) -> str:
    """Re-build a content-addressed filename (universe-scope stripped).

    Note: ``dataset`` here is the *sanitized* directory segment recovered
    from the cache path (dots/slashes replaced with underscores), not the
    raw dataset string that production ``build_cache_path`` hashes. This
    is intentional for the simulation: both Run 1 and Run 2 sanitize the
    same way, so cross-run set-overlap comparisons remain valid. The
    simulated digest does not need to match production byte-for-byte, only
    to be consistent across the two runs being compared.
    """
    version = CACHE_VERSION_BY_CATEGORY.get(category, DEFAULT_CACHE_VERSION)
    digest = _digest(parts, version=version, category=category, dataset=dataset)
    base = "__".join([*parts, digest]) if parts else digest
    return f"{category}/{dataset}/{base}"


def load_events(root: Path) -> list[dict]:
    events: list[dict] = []
    for f in sorted(root.rglob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    run1 = load_events(repo / "baseline" / "run1")
    run2 = load_events(repo / "baseline" / "run2")

    print("=" * 78)
    print("PROBE-LOG SIMULATION  (issue #2334, offline -- zero workflow cost)")
    print("=" * 78)
    print(f"Run 1 events: {len(run1)}   Run 2 events: {len(run2)}")
    print()

    # ── Option 2: per-category breakdown (where do the existing 12.40% come from?)
    print("-" * 78)
    print("Option 2 -- per-category breakdown of the existing baseline")
    print("-" * 78)
    print(f"{'category':<45}{'r1 ev':>8}{'r1 hit':>8}{'r2 ev':>8}{'r2 hit':>8}")
    by_cat: dict[str, dict] = defaultdict(lambda: {"r1_ev": 0, "r1_hit": 0, "r2_ev": 0, "r2_hit": 0})
    for ev in run1:
        parsed = _parse_event(ev)
        if not parsed:
            continue
        cat = parsed[0]
        by_cat[cat]["r1_ev"] += 1
        if ev["hit"]:
            by_cat[cat]["r1_hit"] += 1
    for ev in run2:
        parsed = _parse_event(ev)
        if not parsed:
            continue
        cat = parsed[0]
        by_cat[cat]["r2_ev"] += 1
        if ev["hit"]:
            by_cat[cat]["r2_hit"] += 1
    for cat in sorted(by_cat):
        c = by_cat[cat]
        print(
            f"{cat:<45}{c['r1_ev']:>8}{c['r1_hit']:>8}{c['r2_ev']:>8}{c['r2_hit']:>8}"
        )
    print()

    # ── Option 1: content-addressed re-key simulation
    print("-" * 78)
    print("Option 1 -- simulated hit-rate AFTER stripping universe-scope token")
    print("-" * 78)
    print(
        f"{'category':<45}{'r2 ev':>7}{'today':>9}{'sim hit':>9}{'sim %':>8}"
    )

    # Build run1 keyset under content-addressing
    r1_keys_by_cat: dict[str, set[str]] = defaultdict(set)
    r1_scope_seen: dict[str, int] = defaultdict(int)
    for ev in run1:
        parsed = _parse_event(ev)
        if not parsed:
            continue
        cat, dataset, parts = parsed
        stripped, had_scope = _strip_scope_token(parts)
        if had_scope:
            r1_scope_seen[cat] += 1
        key = _canonical_key(cat, dataset, stripped)
        r1_keys_by_cat[cat].add(key)

    sim_totals = {"events": 0, "today_hit": 0, "sim_hit": 0}
    cat_sim: dict[str, dict[str, int]] = defaultdict(
        lambda: {"events": 0, "today_hit": 0, "sim_hit": 0}
    )
    for ev in run2:
        parsed = _parse_event(ev)
        if not parsed:
            continue
        cat, dataset, parts = parsed
        stripped, _ = _strip_scope_token(parts)
        key = _canonical_key(cat, dataset, stripped)
        sim_hit = key in r1_keys_by_cat[cat]
        cat_sim[cat]["events"] += 1
        cat_sim[cat]["today_hit"] += int(ev["hit"])
        cat_sim[cat]["sim_hit"] += int(sim_hit)
        sim_totals["events"] += 1
        sim_totals["today_hit"] += int(ev["hit"])
        sim_totals["sim_hit"] += int(sim_hit)

    for cat in sorted(cat_sim):
        c = cat_sim[cat]
        pct = (c["sim_hit"] / c["events"] * 100) if c["events"] else 0.0
        print(
            f"{cat:<45}{c['events']:>7}{c['today_hit']:>9}{c['sim_hit']:>9}{pct:>7.1f}%"
        )
    print(
        f"{'TOTAL':<45}{sim_totals['events']:>7}{sim_totals['today_hit']:>9}"
        f"{sim_totals['sim_hit']:>9}"
        f"{(sim_totals['sim_hit']/sim_totals['events']*100):>7.1f}%"
    )
    print()

    # ── Set-overlap (Phase-B's conservative metric) under content-addressing
    print("-" * 78)
    print("Set-overlap (conservative) -- unique canonical keys per run")
    print("-" * 78)
    r2_keys_by_cat: dict[str, set[str]] = defaultdict(set)
    for ev in run2:
        parsed = _parse_event(ev)
        if not parsed:
            continue
        cat, dataset, parts = parsed
        stripped, _ = _strip_scope_token(parts)
        r2_keys_by_cat[cat].add(_canonical_key(cat, dataset, stripped))

    all_cats = sorted(set(r1_keys_by_cat) | set(r2_keys_by_cat))
    print(f"{'category':<45}{'r1 uniq':>9}{'r2 uniq':>9}{'∩':>6}{'∩ %':>7}")
    r1_total = r2_total = inter_total = 0
    for cat in all_cats:
        a = r1_keys_by_cat[cat]
        b = r2_keys_by_cat[cat]
        inter = a & b
        r1_total += len(a)
        r2_total += len(b)
        inter_total += len(inter)
        union = len(a | b)
        pct = (len(inter) / union * 100) if union else 0.0
        print(f"{cat:<45}{len(a):>9}{len(b):>9}{len(inter):>6}{pct:>6.1f}%")
    union_total = r1_total + r2_total - inter_total
    print(
        f"{'TOTAL':<45}{r1_total:>9}{r2_total:>9}{inter_total:>6}"
        f"{(inter_total/union_total*100 if union_total else 0):>6.1f}%"
    )
    print()

    # ── Scope-token incidence (sanity: how many events were even affected?)
    print("-" * 78)
    print("Scope-token incidence in Run 1 (events with a universe-scope segment)")
    print("-" * 78)
    print(f"{'category':<45}{'scope events':>15}")
    for cat in sorted(r1_scope_seen):
        print(f"{cat:<45}{r1_scope_seen[cat]:>15}")
    print()

    # ── Gate verdict
    print("=" * 78)
    print("GATE -- Phase-C re-validation requires >=60% sim hit-rate (lookup-weighted)")
    print("=" * 78)
    pct = sim_totals["sim_hit"] / sim_totals["events"] * 100
    overall = "PASS" if pct >= 60 else "FAIL"
    print(f"Overall simulated lookup-weighted hit-rate: {pct:.1f}%  -> {overall}")
    print()
    print("Per-category gate (would this category alone clear 60%?):")
    for cat in sorted(cat_sim):
        c = cat_sim[cat]
        if c["events"] < 5:
            continue  # too few events to be meaningful
        p = c["sim_hit"] / c["events"] * 100
        v = "PASS" if p >= 60 else "FAIL"
        print(f"  {cat:<45}{p:>6.1f}%  {v}")


if __name__ == "__main__":
    main()
