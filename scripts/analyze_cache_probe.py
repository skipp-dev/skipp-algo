"""Aggregate cache-probe shard JSONL into per-run / per-family hit-rates.

Used for Phase-C re-validation of the universe-key cache redesign (#2334)
against the 60% pre-redesign baseline and the 86.8% simulated target.
"""
from __future__ import annotations

import collections
import json
import pathlib
import re
import sys

# Normalize separators so the same regex works on Linux/macOS (`/`) probe
# logs and any future Windows runs (`\\`). The leading `(?:^|/)` lets the
# pattern match probe paths that are either absolute, relative, or stored
# without a leading slash.
FAMILY_RE = re.compile(r"(?:^|/)databento_volatility_cache/([^/]+)/")


def fam(p: str) -> str:
    normalized = p.replace("\\", "/")
    m = FAMILY_RE.search(normalized)
    return m.group(1) if m else "unknown"


def analyze(root: pathlib.Path) -> None:
    for run in sorted(root.iterdir()):
        if not run.is_dir():
            continue
        overall = collections.Counter()
        by_fam: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
        n = 0
        for shard in sorted(run.glob("cache-probe-shard-*/*.jsonl")):
            for line in shard.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                rec = json.loads(line)
                n += 1
                key = "hit" if rec["hit"] else "miss"
                overall[key] += 1
                by_fam[fam(rec["path"])][key] += 1
        total = overall["hit"] + overall["miss"]
        rate = (overall["hit"] / total * 100) if total else 0.0
        print(f"== {run.name} ==  records={n}  hit={overall['hit']}  miss={overall['miss']}  rate={rate:.2f}%")
        for f, c in sorted(by_fam.items()):
            t = c["hit"] + c["miss"]
            r = (c["hit"] / t * 100) if t else 0.0
            print(f"   {f:32s}  hit={c['hit']:5d}  miss={c['miss']:5d}  rate={r:6.2f}%")


if __name__ == "__main__":
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "baseline")
    analyze(root)