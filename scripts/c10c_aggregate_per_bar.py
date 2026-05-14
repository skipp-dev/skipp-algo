#!/usr/bin/env python3
"""C10c Step 1 — per-bar aggregation of family firings on the 1D corpus.

For each (symbol, timestamp) bar, collect *all* families that fired
together with their predicted_prob and outcome. Emits one JSONL record
per bar to ``docs/research/co_firing/per_bar_predictions.jsonl``.

Output schema (one line = one bar):

    {
      "symbol": "AAPL",
      "timestamp": 1769558400.0,
      "n_families": 2,
      "families": ["FVG", "SWEEP"],
      "predictions": {"FVG": 0.53, "SWEEP": 0.78},
      "outcomes":    {"FVG": true,  "SWEEP": false},
      "context":     {"session": "NONE", "htf_bias": "BEARISH", "vol_regime": "NORMAL"}
    }

If two events of the same family hit the same bar (rare, defensive guard),
the latest one wins (events are read in JSONL order).
"""
from __future__ import annotations

import contextlib
import glob
import json
import os
import tempfile
from collections import defaultdict
from pathlib import Path

CORPUS_ROOT = Path("/tmp/c10b_local_run/measurement_benchmark")
OUT = Path("docs/research/co_firing/per_bar_predictions.jsonl")
OUT.parent.mkdir(parents=True, exist_ok=True)


def _atomic_write_jsonl(path: Path, lines: list[str]) -> None:
    """Atomically write ``lines`` (each already including a trailing newline)
    to ``path`` via the mkstemp + fsync + os.replace pattern.

    Mirrors the pattern used in ``scripts/build_backtest_slippage_samples.py``
    (smc_atomic_write is parquet/csv specific; this is the JSONL equivalent).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            # ATOMIC-WRITE-EXEMPT: hand-rolled mkstemp+fsync+os.replace.
            for line in lines:
                fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise

# bar_key -> dict of family -> event
per_bar: dict[tuple[str, float], dict[str, dict]] = defaultdict(dict)

n_events = 0
for fp in sorted(CORPUS_ROOT.glob("*/1D/events_*_1D.jsonl")):
    for line in fp.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        ev = json.loads(line)
        bar_key = (ev["symbol"], float(ev["timestamp"]))
        per_bar[bar_key][ev["family"]] = ev
        n_events += 1

records = []
for (symbol, ts), fams in per_bar.items():
    # Sort family list for deterministic output (alphabetical).
    family_names = sorted(fams.keys())
    # Pick a context: families on the same bar share context by
    # construction (same symbol+timestamp). Take the first family's
    # context but assert consistency for diagnostic confidence.
    contexts = {tuple(sorted(fams[f].get("context", {}).items())) for f in family_names}
    context = dict(next(iter(contexts))) if contexts else {}
    records.append(
        {
            "symbol": symbol,
            "timestamp": ts,
            "n_families": len(family_names),
            "families": family_names,
            "predictions": {f: fams[f]["predicted_prob"] for f in family_names},
            "outcomes": {f: bool(fams[f]["outcome"]) for f in family_names},
            "context": context,
            "context_consistent": len(contexts) <= 1,
        }
    )

# Sort by (symbol, timestamp) for diff-stability.
records.sort(key=lambda r: (r["symbol"], r["timestamp"]))

# Atomic JSONL write via mkstemp + fsync + os.replace (smc_atomic_write is
# parquet/csv specific; the JSONL equivalent lives in _atomic_write_jsonl
# above and mirrors scripts/build_backtest_slippage_samples.py).
_atomic_write_jsonl(
    OUT,
    [json.dumps(rec, sort_keys=True) + "\n" for rec in records],
)

print(f"Loaded {n_events} events into {len(per_bar)} unique bars")
print(f"Wrote {OUT}")

# Quick distribution summary for sanity-check output.
n_by_size = defaultdict(int)
for rec in records:
    n_by_size[rec["n_families"]] += 1
print("Bar count by n_families:")
for size in sorted(n_by_size):
    print(f"  n_families={size}: {n_by_size[size]} bars")

multi_firing = sum(1 for r in records if r["n_families"] >= 2)
single_firing = sum(1 for r in records if r["n_families"] == 1)
total = len(records)
print(
    f"Co-firing (>=2 families): {multi_firing}/{total} = "
    f"{100.0 * multi_firing / total:.2f}%"
)
print(
    f"Single-firing:            {single_firing}/{total} = "
    f"{100.0 * single_firing / total:.2f}%"
)
