"""Q3/Q4 plan §3.3 — FX-Major Probe (W18–W22) scaffold.

This module is the *symbol/universe + inverse-pair* contract for the
plan's Q4 multi-asset probe. It does NOT execute Databento queries
itself (that's owned by `databento_provider.py` and the existing
benchmark pipeline); it only:

1. Declares the canonical FX-Major symbol mapping
   (CME continuous-front-month → spot-pair semantics).
2. Encodes the **inverse-pair convention** for ``USDJPY`` (the CME
   ``6J`` future quotes JPY/USD, not USD/JPY — every consumer must
   invert ``1 / price`` to align with spot semantics).
3. Provides a probe runner CLI that calls a *user-supplied* fetch
   callback, applies the inverse where required, and writes a
   structured result JSON for downstream benchmark code.

Plan reference (lines 547-565):
    "4 Symbole: EURUSD, GBPUSD, USDJPY, AUDUSD. 2 Timeframes: 15m, 1H.
     Session-Kalibrierung: Tokyo/London/NY Sessions. Ziel: Feststellen,
     ob Family-Rangfolge (BOS > OB > SWEEP > FVG) Asset-übergreifend
     stabil ist."

Scope discipline
----------------
Per the plan: this is a **probe** (not a production benchmark). The
output of this scaffold feeds `docs/MULTI_ASSET_PROBE_Q4.md` (plan
line 561). The scaffold deliberately does **not** integrate with
`databento_provider.py` directly — that wiring is the next step
once the probe receives a green light. Keeping the surface narrow
matches the plan's "Scope" bullet (1 additional asset class only).

Repo memory cross-reference
---------------------------
The CME GLBX.MDP3 entitlement was verified live on 2026-04-21 (see
``/memories/repo/fx-probe-databento-glbx-mdp3.md``). The symbol map
below mirrors that note exactly so any drift will surface in tests.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterable

# ── canonical universe ────────────────────────────────────────────────────


@dataclass(frozen=True)
class FxPair:
    spot_symbol: str       # e.g. "EURUSD"  (consumer-facing)
    cme_symbol: str        # e.g. "6E.c.0"  (Databento continuous front-month)
    invert: bool           # True iff price must be 1 / px to match spot semantics
    description: str       # human-readable note

    def to_spot_price(self, raw: float) -> float:
        """Translate a CME-future price to spot-pair semantics.

        Raises ``ValueError`` for non-positive inputs since both
        directions need a strictly positive price (an inverse of zero
        is undefined and a negative future price would already be
        invalid for FX).
        """
        if raw is None or not isinstance(raw, (int, float)):
            raise ValueError(f"raw price must be numeric; got {raw!r}")
        if raw <= 0:
            raise ValueError(f"raw price must be > 0; got {raw}")
        return (1.0 / float(raw)) if self.invert else float(raw)


# Per ``/memories/repo/fx-probe-databento-glbx-mdp3.md``:
#   EURUSD -> 6E.c.0  (direct)
#   GBPUSD -> 6B.c.0  (direct)
#   AUDUSD -> 6A.c.0  (direct)
#   USDJPY -> 6J.c.0  *inverse* (6J quotes JPY/USD)
FX_MAJORS: tuple[FxPair, ...] = (
    FxPair("EURUSD", "6E.c.0", invert=False,
           description="Euro FX future (CME 6E), direct."),
    FxPair("GBPUSD", "6B.c.0", invert=False,
           description="British Pound future (CME 6B), direct."),
    FxPair("AUDUSD", "6A.c.0", invert=False,
           description="Australian Dollar future (CME 6A), direct."),
    FxPair("USDJPY", "6J.c.0", invert=True,
           description="Japanese Yen future (CME 6J quotes JPY/USD); inverted."),
)

# Plan §3.3 timeframes (line 553).
FX_TIMEFRAMES: tuple[str, ...] = ("15m", "1H")

# Plan §3.3 sessions (line 554) — single source of truth so the
# benchmark consumer doesn't have to re-derive the FX session map.
# Hours are UTC; consumer-side calibration code aligns to these.
FX_SESSIONS: dict[str, tuple[int, int]] = {
    # Tokyo session 00:00–09:00 UTC (~JST 09:00–18:00).
    "TOKYO": (0, 9),
    # London session 07:00–16:00 UTC.
    "LONDON": (7, 16),
    # NY session 13:00–22:00 UTC.
    "NY": (13, 22),
}


# ── lookups ───────────────────────────────────────────────────────────────


def get_pair_by_spot(symbol: str) -> FxPair:
    """Return the FxPair whose ``spot_symbol`` matches *symbol* (case-insensitive)."""
    needle = symbol.upper().strip()
    for pair in FX_MAJORS:
        if pair.spot_symbol == needle:
            return pair
    raise KeyError(f"Unknown FX major spot symbol: {symbol!r}")


def get_pair_by_cme(symbol: str) -> FxPair:
    """Return the FxPair whose ``cme_symbol`` matches *symbol*."""
    needle = symbol.strip()
    for pair in FX_MAJORS:
        if pair.cme_symbol == needle:
            return pair
    raise KeyError(f"Unknown CME continuous symbol: {symbol!r}")


def databento_symbols() -> list[str]:
    """All CME continuous symbols, in canonical order (consumed by Databento client)."""
    return [pair.cme_symbol for pair in FX_MAJORS]


# ── probe runner ──────────────────────────────────────────────────────────


@dataclass
class ProbeResult:
    spot_symbol: str
    cme_symbol: str
    timeframe: str
    n_bars: int
    last_raw_price: float | None
    last_spot_price: float | None
    error: str | None = None


@dataclass
class ProbeReport:
    generated_at: str
    pairs: list[ProbeResult] = field(default_factory=list)
    timeframes: list[str] = field(default_factory=list)
    source: dict[str, Any] = field(default_factory=dict)
    status: str = "AWAITING_DATA"  # AWAITING_DATA | OK | PARTIAL | FAIL

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


# Fetch callback contract:
#   (cme_symbol: str, timeframe: str) -> list[dict]
# where each dict has at least a ``"close"`` key (floats). Empty list
# means the dataset has no data in the requested window.
FetchCallback = Callable[[str, str], list[dict[str, Any]]]


def _safe_fetch(callback: FetchCallback, cme_symbol: str, timeframe: str,
                ) -> tuple[list[dict[str, Any]], str | None]:
    """Wrap the user fetch in a fail-soft envelope; never raises."""
    try:
        bars = callback(cme_symbol, timeframe)
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"
    if not isinstance(bars, list):
        return [], f"fetch returned {type(bars).__name__}, expected list"
    return bars, None


def run_probe(
    callback: FetchCallback,
    *,
    pairs: Iterable[FxPair] = FX_MAJORS,
    timeframes: Iterable[str] = FX_TIMEFRAMES,
    generated_at: str | None = None,
    source: dict[str, Any] | None = None,
) -> ProbeReport:
    """Execute the probe across the (pair × timeframe) grid.

    Each cell calls *callback(cme_symbol, timeframe)* and records the
    last close price (raw + spot-converted via :meth:`FxPair.to_spot_price`).
    Failures are captured per-cell so a single bad symbol doesn't
    sink the whole probe (matches plan's "ehrlicher Bericht (auch
    bei negativem Ergebnis)" — line 562).
    """
    pairs_list = list(pairs)
    tfs_list = list(timeframes)
    report = ProbeReport(
        generated_at=generated_at or datetime.now(UTC).isoformat(),
        timeframes=tfs_list,
        source=source or {},
    )
    n_ok = 0
    n_total = 0
    for pair in pairs_list:
        for tf in tfs_list:
            n_total += 1
            bars, err = _safe_fetch(callback, pair.cme_symbol, tf)
            if err is not None:
                report.pairs.append(ProbeResult(
                    spot_symbol=pair.spot_symbol,
                    cme_symbol=pair.cme_symbol,
                    timeframe=tf,
                    n_bars=0,
                    last_raw_price=None,
                    last_spot_price=None,
                    error=err,
                ))
                continue
            if not bars:
                report.pairs.append(ProbeResult(
                    spot_symbol=pair.spot_symbol,
                    cme_symbol=pair.cme_symbol,
                    timeframe=tf,
                    n_bars=0,
                    last_raw_price=None,
                    last_spot_price=None,
                    error="empty",
                ))
                continue
            try:
                raw = float(bars[-1].get("close"))
                spot = pair.to_spot_price(raw)
            except (TypeError, ValueError) as exc:
                report.pairs.append(ProbeResult(
                    spot_symbol=pair.spot_symbol,
                    cme_symbol=pair.cme_symbol,
                    timeframe=tf,
                    n_bars=len(bars),
                    last_raw_price=None,
                    last_spot_price=None,
                    error=f"bad close: {exc}",
                ))
                continue
            report.pairs.append(ProbeResult(
                spot_symbol=pair.spot_symbol,
                cme_symbol=pair.cme_symbol,
                timeframe=tf,
                n_bars=len(bars),
                last_raw_price=round(raw, 6),
                last_spot_price=round(spot, 6),
            ))
            n_ok += 1
    if n_total == 0:
        report.status = "AWAITING_DATA"
    elif n_ok == n_total:
        report.status = "OK"
    elif n_ok == 0:
        report.status = "FAIL"
    else:
        report.status = "PARTIAL"
    return report


# ── persistence ───────────────────────────────────────────────────────────


def write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    # ATOMIC-WRITE-EXEMPT: tmp+replace pattern (atomic by construction).
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def render_markdown(report: ProbeReport) -> str:
    lines = [
        "# §3.3 FX-Major Probe — Q4 Multi-Asset Scaffold",
        "",
        f"_Generated: `{report.generated_at}`_",
        f"_Status: **{report.status}**_",
        f"_Source commit: `{(report.source.get('commit_sha') or 'unknown')[:7]}`_",
        "",
        "## Universe (CME GLBX.MDP3 continuous front-month)",
        "",
        "| Spot | CME | Inverse? | Description |",
        "|---|---|---|---|",
    ]
    for pair in FX_MAJORS:
        lines.append(
            f"| `{pair.spot_symbol}` | `{pair.cme_symbol}` | "
            f"{'YES' if pair.invert else 'no'} | {pair.description} |"
        )
    lines.extend([
        "",
        "## Probe results",
        "",
        "| Spot | CME | TF | n_bars | last raw | last spot | error |",
        "|---|---|---|---|---|---|---|",
    ])
    if not report.pairs:
        lines.append("| — | — | — | 0 | — | — | (no probe executed yet) |")
    for r in report.pairs:
        lines.append(
            f"| `{r.spot_symbol}` | `{r.cme_symbol}` | {r.timeframe} | {r.n_bars} | "
            f"{'—' if r.last_raw_price is None else r.last_raw_price} | "
            f"{'—' if r.last_spot_price is None else r.last_spot_price} | "
            f"{r.error or ''} |"
        )
    lines.append("")
    return "\n".join(lines)


# ── CLI ───────────────────────────────────────────────────────────────────


DEFAULT_OUTPUT_JSON = Path("docs/fx_probe/probe_status.json")
DEFAULT_OUTPUT_MD = Path("docs/fx_probe/probe_status.md")


def _empty_callback(_cme: str, _tf: str) -> list[dict[str, Any]]:
    """Default fetch — returns empty so the CLI emits AWAITING_DATA without I/O."""
    return []


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    parser.add_argument(
        "--commit-sha", default=os.environ.get("GITHUB_SHA"),
        help="Source commit SHA (default: $GITHUB_SHA).",
    )
    parser.add_argument(
        "--workflow-run", default=os.environ.get("GITHUB_RUN_ID"),
        help="Source workflow run id (default: $GITHUB_RUN_ID).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None,
         *,
         callback: FetchCallback | None = None) -> int:
    """CLI entrypoint.

    Tests inject ``callback``; the bare CLI uses :func:`_empty_callback`
    so a daily run with no Databento wiring still produces a valid
    AWAITING_DATA surface.
    """
    args = _parse_args(argv)
    cb: FetchCallback = callback if callback is not None else _empty_callback
    report = run_probe(cb, source={
        "commit_sha": args.commit_sha,
        "workflow_run": args.workflow_run,
    })
    # When no real callback is wired, downgrade FAIL to AWAITING_DATA so the
    # seed surface is honest about the probe being un-wired (rather than
    # alarming reviewers with a FAIL on a brand-new emitter).
    if callback is None and report.status == "FAIL":
        report.status = "AWAITING_DATA"
    try:
        write_atomic(args.output_json, json.dumps(report.to_json(), indent=2, sort_keys=True) + "\n")
        write_atomic(args.output_md, render_markdown(report))
    except OSError as exc:
        print(f"ERROR: cannot write outputs: {exc}", file=sys.stderr)
        return 1
    print(f"FX probe: status={report.status} pairs={len(report.pairs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
