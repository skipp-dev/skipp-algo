#!/usr/bin/env python3
"""Sweep-trap shadow evaluator (WS4a-ops → WS4b evidence).

Reads the measurement event ledgers (``events_*.jsonl``), pulls the SWEEP-family
events that carry the observe-only ``sweep_trap_quality_score`` feature (logged
when ``ENABLE_SWEEP_TRAP=1``), and measures whether that score has skill at
predicting the DISJOINT late-window label ``sweep_trap_outcome_late`` (the
follow-through on bars N+1..lookahead; the quality is confirmed on bars 1..N, so
the two windows never overlap — no target leakage):

* ``brier_signal``   — Brier of ``sweep_trap_quality_score`` vs the late outcome
* ``brier_baseline`` — Brier of the pooled base-rate vs the late outcome
* ``brier_delta``    — ``baseline - signal`` (>0 ⇒ the RAW score's Brier beats the
  pooled base-rate on this shadow corpus — a candidate signal, NOT a calibrated
  skill proof: the score is uncalibrated and no confidence interval is computed)
* ``lift``           — top-tercile minus bottom-tercile reversal hit-rate

It appends one row per run to a committed shadow ledger
(``artifacts/governance/sweep_trap_shadow.jsonl``) that accumulates across daily
runs, and writes a compact monitoring snapshot
(``artifacts/monitoring/sweep_trap_shadow.json``) for the live-overlay daemon to
re-expose as Prometheus gauges (Grafana). This is the DAILY shadow layer; the
promotion decision (weeks of data, k-of-n) is deliberately downstream.

Sample-count semantics. ``MIN_SHADOW_SAMPLES`` is a floor on the number of pooled
shadow records, NOT a walk-forward out-of-sample guarantee: this path has no
time-split, no holdout and no OOS fold-IDs, so ``PROMOTABLE`` means "interesting
shadow candidate", not a validated promotion. Numerically it equals the calibration
layer's ``MIN_OOS_SAMPLES`` (40) but the two are kept distinct so a future real-OOS
gate (block-bootstrap CI on the Brier + time-separated folds) can raise this floor
without silently borrowing OOS semantics it does not yet have.

Fail-soft, mirroring ``run_magnitude_shadow_ledger``: an empty/absent corpus is
``no_data`` (exit 3, green in CI), a re-served identical feed is a stale row
(exit 5, appends nothing), and the ledger read fails CLOSED on corruption.

Exit codes: 0 promotable-or-measured · 2 measured but not promotable · 3 thin /
no data · 5 stale feed · 1 usage/config error.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_json, atomic_write_text
from smc_core.event_ledger import ledger_label

# Floor on the pooled shadow-record count before a verdict may leave INCONCLUSIVE.
# This is a SAMPLE-COUNT floor for a collected (non-time-split) shadow corpus, NOT
# a walk-forward OOS guarantee — see the module docstring. It equals the calibration
# layer's MIN_OOS_SAMPLES (40) numerically but is kept as its own constant so this
# path never imports OOS semantics it does not deliver.
MIN_SHADOW_SAMPLES = 40

DEFAULT_LEDGER = "artifacts/governance/sweep_trap_shadow.jsonl"
DEFAULT_SNAPSHOT = "artifacts/monitoring/sweep_trap_shadow.json"
QUALITY_KEY = "sweep_trap_quality_score"
OUTCOME_KEY = "sweep_trap_outcome_late"  # disjoint late-window label (leakage-free)
# SCOPE: the ledger classifies the trap on the 3-bar confirm window (#3509), where
# trap_type="delayed" (bars 4-12) is unreachable — this shadow validates ONLY the
# immediate-vs-failed dichotomy; a WS4b promotion would carry the delayed
# type_weight untested (the up-to-13-bar liquidity-enrichment fields are a
# different window under near-identical names; never join them by name).

VERDICT_CODE = {"INCONCLUSIVE": 0, "SHADOW": 1, "PROMOTABLE": 2}


# ── sample extraction ────────────────────────────────────────────────────────
def collect_samples(events: list[dict[str, Any]]) -> list[tuple[float, int]]:
    """Return ``(quality, outcome)`` pairs for SWEEP events carrying the score.

    Leakage-free contract: the label is ``sweep_trap_outcome_late`` (the
    follow-through on the DISJOINT later window), NOT the full-window
    ``ScoredEvent.outcome`` — the trap quality is confirmed on bars 1..N and
    the outcome on bars N+1..lookahead. Records emitted before the leakage fix
    lack ``sweep_trap_outcome_late`` and are excluded so their leaky Brier/lift
    can never count as promotion evidence.
    """
    out: list[tuple[float, int]] = []
    for ev in events:
        if str(ev.get("family", "")).upper() != "SWEEP":
            continue
        feats = ev.get("features") or {}
        # Era-cut: schema v2 (edge-censoring fix) guarantees the late label was
        # observed on the FULL disjoint outcome window; v1 rows may be
        # right-censored at the data edge and must never grade the verdict.
        try:
            if int(feats.get("sweep_trap_schema_version", 0)) < 2:
                continue
        except (TypeError, ValueError):
            continue
        # QUALITY_KEY is a feature; OUTCOME_KEY is a label (schema 1.1 -> outcome_extras,
        # 1.0 -> features). ledger_label reads either generation. Only a genuine JSON
        # boolean grades: plain truthiness would count the string "false" as a hit.
        outcome_late = ledger_label(ev, OUTCOME_KEY, default=None)
        if QUALITY_KEY not in feats or not isinstance(outcome_late, bool):
            continue
        try:
            q = float(feats[QUALITY_KEY])
        except (TypeError, ValueError):
            continue
        if not (0.0 <= q <= 1.0):
            continue
        out.append((q, 1 if outcome_late else 0))
    return out


def _read_events_from_dir(benchmark_dir: Path) -> list[dict[str, Any]]:
    from smc_core.event_ledger import read_event_ledger

    events: list[dict[str, Any]] = []
    # strict=True: an off-schema / malformed line raises EventLedgerSchemaError
    # (a ValueError), caught by main()'s fail-closed handler — the shadow verdict
    # is never graded from a partial or corrupt event corpus.
    for path in sorted(glob.glob(str(benchmark_dir / "*" / "*" / "events_*.jsonl"))):
        events.extend(read_event_ledger(Path(path), strict=True))
    return events


def _read_events_from_json(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{path}: expected a JSON list of events")
    return payload


# ── statistics ───────────────────────────────────────────────────────────────
def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def evaluate(samples: list[tuple[float, int]]) -> dict[str, Any]:
    """Compute the shadow evidence metrics + verdict for the sample set."""
    n = len(samples)
    if n == 0:
        return {
            "n_samples": 0, "base_rate": None, "brier_signal": None,
            "brier_baseline": None, "brier_delta": None,
            "hit_rate_top_tercile": None, "hit_rate_bottom_tercile": None,
            "lift": None, "verdict": "INCONCLUSIVE",
        }

    outcomes = [o for _, o in samples]
    base_rate = _mean([float(o) for o in outcomes])
    brier_signal = _mean([(q - o) ** 2 for q, o in samples])
    brier_baseline = _mean([(base_rate - o) ** 2 for o in outcomes])
    brier_delta = brier_baseline - brier_signal

    hit_top = hit_bot = lift = None
    if n >= 6:  # need a meaningful tercile split
        ordered = sorted(samples, key=lambda s: s[0])
        k = n // 3
        bottom = ordered[:k]
        top = ordered[-k:]
        hit_bot = _mean([float(o) for _, o in bottom])
        hit_top = _mean([float(o) for _, o in top])
        lift = hit_top - hit_bot

    if n < MIN_SHADOW_SAMPLES:
        verdict = "INCONCLUSIVE"
    elif brier_delta > 0.0 and (lift is None or lift > 0.0):
        verdict = "PROMOTABLE"
    else:
        verdict = "SHADOW"

    return {
        "n_samples": n,
        "base_rate": round(base_rate, 6),
        "brier_signal": round(brier_signal, 6),
        "brier_baseline": round(brier_baseline, 6),
        "brier_delta": round(brier_delta, 6),
        "hit_rate_top_tercile": None if hit_top is None else round(hit_top, 6),
        "hit_rate_bottom_tercile": None if hit_bot is None else round(hit_bot, 6),
        "lift": None if lift is None else round(lift, 6),
        "verdict": verdict,
    }


def events_content_hash(samples: list[tuple[float, int]]) -> str:
    canonical = json.dumps(sorted(samples), separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


# ── ledger persistence (fail-closed read, idempotent merge, atomic write) ─────
def load_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{lineno}: corrupt shadow ledger line: {exc}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{lineno}: shadow ledger line is not an object")
        rows.append(row)
    return rows


def merge_row(rows: list[dict[str, Any]], new: dict[str, Any]) -> list[dict[str, Any]]:
    key = (new["date"], new["events_hash"])
    kept = [r for r in rows if (r.get("date"), r.get("events_hash")) != key]
    kept.append(new)
    kept.sort(key=lambda r: str(r.get("date", "")))
    return kept


def _is_stale_feed(rows: list[dict[str, Any]], date: str, events_hash: str) -> bool:
    """True if this exact hash was already graded under a strictly earlier date."""
    return any(
        r.get("events_hash") == events_hash and str(r.get("date", "")) < date for r in rows
    )


def build_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "generated_at": time.time(),
        "date": row["date"],
        "n_samples": row["n_samples"],
        "min_samples": MIN_SHADOW_SAMPLES,
        "brier_delta": row["brier_delta"],
        "lift": row["lift"],
        "verdict": row["verdict"],
        "verdict_code": VERDICT_CODE.get(row["verdict"], 0),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--benchmark-dir", type=Path, help="Dir containing SYMBOL/TF/events_*.jsonl.")
    src.add_argument("--events-json", type=Path, help="A JSON list of event-ledger records (dispatch/testing).")
    ap.add_argument("--date", default=time.strftime("%Y-%m-%d", time.gmtime()))
    ap.add_argument("--ledger", type=Path, default=Path(DEFAULT_LEDGER))
    ap.add_argument("--snapshot", type=Path, default=Path(DEFAULT_SNAPSHOT))
    args = ap.parse_args(argv)

    try:
        if args.events_json:
            events = _read_events_from_json(args.events_json)
        elif args.benchmark_dir:
            events = _read_events_from_dir(args.benchmark_dir)
        else:
            events = []
        ledger_rows = load_ledger(args.ledger)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    samples = collect_samples(events)
    if not samples:
        print(f"::notice::sweep-trap shadow: no SWEEP events with {QUALITY_KEY} (no_data)")
        return 3

    events_hash = events_content_hash(samples)
    if _is_stale_feed(ledger_rows, args.date, events_hash):
        print(f"::notice::sweep-trap shadow: stale feed (hash {events_hash} already graded) — no append")
        return 5

    metrics = evaluate(samples)
    row = {"date": args.date, "events_hash": events_hash, "min_samples": MIN_SHADOW_SAMPLES, **metrics}

    args.ledger.parent.mkdir(parents=True, exist_ok=True)
    merged = merge_row(ledger_rows, row)
    atomic_write_text("\n".join(json.dumps(r, sort_keys=True) for r in merged) + "\n", args.ledger)

    args.snapshot.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(build_snapshot(row), args.snapshot)

    print(
        f"sweep-trap shadow [{args.date}] n={row['n_samples']} "
        f"brier_delta={row['brier_delta']} lift={row['lift']} verdict={row['verdict']}"
    )
    if row["verdict"] == "PROMOTABLE":
        return 0
    if row["verdict"] == "SHADOW":
        return 2
    return 3  # INCONCLUSIVE (measured but below MIN_OOS)


if __name__ == "__main__":
    raise SystemExit(main())
