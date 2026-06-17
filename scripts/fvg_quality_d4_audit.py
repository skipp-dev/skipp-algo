"""Q3 Phase D4 — FVG Quality Signal conditional hit-rate audit.

Reads ``events_*.jsonl`` files from a benchmark snapshot and reports
conditional hit rates (strict ≥50% partial-fill label) split by the
A1.B FVG quality features:

- ``htf_aligned`` (bool)
- ``is_full_body`` (bool)
- ``gap_size_atr`` (quartiles)
- ``distance_to_price_atr`` (quartiles)

Plus combined "top-quality" and "bottom-quality" buckets to estimate the
maximum lift a FVG quality filter could provide for the scoring pipeline.

Usage:
    python scripts/fvg_quality_d4_audit.py \
        --root artifacts/ci/measurement_benchmark_2026-04-22_partial50_v3
"""

from __future__ import annotations

import argparse
import glob
import json
import statistics
from collections.abc import Iterable
from pathlib import Path


def _load_fvg_events(root: Path) -> list[dict]:
    files = sorted(glob.glob(str(root / "*" / "*" / "events_*.jsonl")))
    out: list[dict] = []
    for fp in files:
        with open(fp, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                e = json.loads(line)
                if e.get("family") == "FVG":
                    out.append(e)
    return out


def _hit(event: dict, label: str) -> bool:
    if label == "strict":
        return bool((event.get("features") or {}).get("label_partial_50"))
    return bool(event.get("outcome"))


def _rollup(items: Iterable[dict], label: str) -> tuple[float | None, int]:
    items = list(items)
    n = len(items)
    if n == 0:
        return None, 0
    hits = sum(1 for e in items if _hit(e, label))
    return hits / n, n


def _print_bucket(name: str, items: list[dict]) -> None:
    hr_s, n = _rollup(items, "strict")
    hr_l, _ = _rollup(items, "lenient")
    if n == 0:
        print(f"  {name:32s}: n=    0  (skipped)")
        return
    print(
        f"  {name:32s}: n={n:5d}  strict={hr_s:.4f}  lenient={hr_l:.4f}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        required=True,
        type=Path,
        help="Benchmark snapshot directory (must contain SYMBOL/TF/events_*.jsonl).",
    )
    args = parser.parse_args()

    ev = _load_fvg_events(args.root)
    print("== D4 FVG quality conditional hit rates ==")
    print(f"   root: {args.root}")
    print(f"   total FVG events: {len(ev)}")
    print()

    # 1. htf_aligned
    print("--- htf_aligned (bool) ---")
    aligned = [e for e in ev if (e.get("features") or {}).get("htf_aligned") is True]
    unaligned = [e for e in ev if (e.get("features") or {}).get("htf_aligned") is False]
    _print_bucket("htf_aligned=True", aligned)
    _print_bucket("htf_aligned=False", unaligned)
    a, _ = _rollup(aligned, "strict")
    u, _ = _rollup(unaligned, "strict")
    if a is not None and u is not None:
        print(f"  ⇒ Δ aligned vs unaligned (strict) = {a - u:+.3f}")

    # 2. is_full_body
    print("\n--- is_full_body (bool) ---")
    fb_t = [e for e in ev if (e.get("features") or {}).get("is_full_body") is True]
    fb_f = [e for e in ev if (e.get("features") or {}).get("is_full_body") is False]
    _print_bucket("is_full_body=True", fb_t)
    _print_bucket("is_full_body=False", fb_f)
    a, _ = _rollup(fb_t, "strict")
    u, _ = _rollup(fb_f, "strict")
    if a is not None and u is not None:
        print(f"  ⇒ Δ full_body vs not (strict) = {a - u:+.3f}")

    # 3. gap_size_atr quartiles
    print("\n--- gap_size_atr (quartiles) ---")
    gs = [
        (e, (e.get("features") or {}).get("gap_size_atr"))
        for e in ev
    ]
    gs = [(e, x) for e, x in gs if x is not None]
    gs.sort(key=lambda t: t[1])
    print(f"  n_with_gap_size_atr = {len(gs)}")
    gap_q = None
    if len(gs) >= 4:
        gap_q = statistics.quantiles([x for _, x in gs], n=4)
        print(f"  Q1={gap_q[0]:.3f} Q2={gap_q[1]:.3f} Q3={gap_q[2]:.3f}")
        for name, lo, hi in (
            ("Q1 (smallest)", float("-inf"), gap_q[0]),
            ("Q2", gap_q[0], gap_q[1]),
            ("Q3", gap_q[1], gap_q[2]),
            ("Q4 (largest)", gap_q[2], float("inf")),
        ):
            sel = [e for e, x in gs if lo < x <= hi]
            _print_bucket(name, sel)

    # 4. distance_to_price_atr quartiles
    print("\n--- distance_to_price_atr (quartiles) ---")
    ds = [
        (e, (e.get("features") or {}).get("distance_to_price_atr"))
        for e in ev
    ]
    ds = [(e, x) for e, x in ds if x is not None]
    ds.sort(key=lambda t: t[1])
    print(f"  n_with_distance_to_price_atr = {len(ds)}")
    dist_q = None
    if len(ds) >= 4:
        dist_q = statistics.quantiles([x for _, x in ds], n=4)
        print(f"  Q1={dist_q[0]:.3f} Q2={dist_q[1]:.3f} Q3={dist_q[2]:.3f}")
        for name, lo, hi in (
            ("Q1 (closest)", float("-inf"), dist_q[0]),
            ("Q2", dist_q[0], dist_q[1]),
            ("Q3", dist_q[1], dist_q[2]),
            ("Q4 (farthest)", dist_q[2], float("inf")),
        ):
            sel = [e for e, x in ds if lo < x <= hi]
            _print_bucket(name, sel)

    # 5. htf_aligned × is_full_body
    print("\n--- htf_aligned × is_full_body ---")
    for ha in (True, False):
        for fb in (True, False):
            sel = [
                e for e in ev
                if (e.get("features") or {}).get("htf_aligned") is ha
                and (e.get("features") or {}).get("is_full_body") is fb
            ]
            _print_bucket(f"aligned={ha!s} full_body={fb!s}", sel)

    # 6. hurst_50 quartiles (D4.5 — coverage 62.6% in v3 snapshot)
    print("\n--- hurst_50 (quartiles) ---")
    hs = [(e, (e.get("features") or {}).get("hurst_50")) for e in ev]
    hs = [(e, x) for e, x in hs if x is not None]
    hs.sort(key=lambda t: t[1])
    print(
        f"  n_with_hurst_50 = {len(hs)} "
        f"({100 * len(hs) / max(len(ev), 1):.1f}% coverage)"
    )
    if len(hs) >= 4:
        hurst_q = statistics.quantiles([x for _, x in hs], n=4)
        print(f"  Q1={hurst_q[0]:.3f} Q2={hurst_q[1]:.3f} Q3={hurst_q[2]:.3f}")
        for name, lo, hi in (
            ("Q1 (most mean-rev)", float("-inf"), hurst_q[0]),
            ("Q2", hurst_q[0], hurst_q[1]),
            ("Q3", hurst_q[1], hurst_q[2]),
            ("Q4 (most trending)", hurst_q[2], float("inf")),
        ):
            sel = [e for e, x in hs if lo < x <= hi]
            _print_bucket(name, sel)

    # 7. Per-TF breakdown of the dominant signal: distance_to_price_atr
    if dist_q is not None:
        print(
            "\n--- distance_to_price_atr × timeframe (Q1 closest vs Q4 farthest) ---"
        )
        tfs = sorted({e.get("timeframe") for e in ev if e.get("timeframe")})
        for tf in tfs:
            tf_ev = [e for e in ev if e.get("timeframe") == tf]
            close_b = [
                e for e in tf_ev
                if (e.get("features") or {}).get("distance_to_price_atr") is not None
                and (e.get("features") or {})["distance_to_price_atr"] <= dist_q[0]
            ]
            far_b = [
                e for e in tf_ev
                if (e.get("features") or {}).get("distance_to_price_atr") is not None
                and (e.get("features") or {})["distance_to_price_atr"] > dist_q[2]
            ]
            close_hr, close_n = _rollup(close_b, "strict")
            far_hr, far_n = _rollup(far_b, "strict")
            close_str = f"{close_hr:.4f}" if close_hr is not None else "—"
            far_str = f"{far_hr:.4f}" if far_hr is not None else "—"
            print(
                f"  TF {tf:4s}: Q1 (n={close_n:4d}) strict={close_str}  "
                f"Q4 (n={far_n:4d}) strict={far_str}"
            )

    # 7b. Per-symbol robustness check (D4.7) — count how many symbols
    # confirm the Q1>Q4 inversion. Used as a sanity gate before D3
    # promotion PR.
    if dist_q is not None:
        print("\n--- distance_to_price_atr × symbol (robustness check) ---")
        syms = sorted({e.get("symbol") for e in ev if e.get("symbol")})
        confirms = 0
        deltas: list[float] = []
        for sym in syms:
            sym_ev = [e for e in ev if e.get("symbol") == sym]
            close_b = [
                e for e in sym_ev
                if (e.get("features") or {}).get("distance_to_price_atr") is not None
                and (e.get("features") or {})["distance_to_price_atr"] <= dist_q[0]
            ]
            far_b = [
                e for e in sym_ev
                if (e.get("features") or {}).get("distance_to_price_atr") is not None
                and (e.get("features") or {})["distance_to_price_atr"] > dist_q[2]
            ]
            c_hr, c_n = _rollup(close_b, "strict")
            f_hr, f_n = _rollup(far_b, "strict")
            if c_hr is None or f_hr is None or c_n == 0 or f_n == 0:
                continue
            d = c_hr - f_hr
            deltas.append(d)
            if d > 0:
                confirms += 1
            flag = "✓" if d > 0 else "✗"
            print(
                f"  {sym:6s} Q1(n={c_n:4d})={c_hr:.4f}  "
                f"Q4(n={f_n:4d})={f_hr:.4f}  Δ={d:+.3f} {flag}"
            )
        if deltas:
            print(
                f"  ⇒ {confirms}/{len(deltas)} symbols confirm Q1>Q4 inversion. "
                f"Median Δ={statistics.median(deltas):+.3f}, "
                f"Mean Δ={statistics.fmean(deltas):+.3f}"
            )

    # 8. Top / Bottom quality combos (need both quantile sets)
    if gap_q is not None and dist_q is not None:
        print("\n--- Top-quality combo (aligned & full_body & gap≥Q3 & dist≤Q1) ---")
        top = [
            e for e in ev
            if (e.get("features") or {}).get("htf_aligned") is True
            and (e.get("features") or {}).get("is_full_body") is True
            and ((e.get("features") or {}).get("gap_size_atr") or 0.0) >= gap_q[2]
            and ((e.get("features") or {}).get("distance_to_price_atr") or float("inf")) <= dist_q[0]
        ]
        _print_bucket("TOP", top)

        print("\n--- Bottom-quality combo (unaligned & not full_body & gap≤Q1) ---")
        bot = [
            e for e in ev
            if (e.get("features") or {}).get("htf_aligned") is False
            and (e.get("features") or {}).get("is_full_body") is False
            and ((e.get("features") or {}).get("gap_size_atr") or float("inf")) <= gap_q[0]
        ]
        _print_bucket("BOT", bot)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
