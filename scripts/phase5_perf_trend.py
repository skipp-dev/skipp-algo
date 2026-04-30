#!/usr/bin/env python3
"""Compute Phase-5 larger-runner before/after wallclock medians per workflow.

Cutoff: merge-commit 573863c56e74df38f59a24767138ba41264f154c
        2026-04-30 23:02:01 +0200 == 2026-04-30T21:02:01Z
"""
from __future__ import annotations

import json
import subprocess
import statistics
from datetime import datetime, timezone

CUTOFF = datetime(2026, 4, 30, 21, 2, 1, tzinfo=timezone.utc)
REPO = "skippALGO/skipp-algo"
WORKFLOWS = [
    "c13-daily-cron",
    "phase-b-promotion-readiness",
    "smc-measurement-benchmark-rolling",
    "smc-measurement-benchmark",
    "run-open-prep-daily",
    "open-prep-outcome-backfill",
    "feature-importance-daily",
    "fvg-quality-recal-shadow-daily",
    "f2-promotion-gate-daily",
    "regime-stratification-validation",
    "plan-2-8-q4-gate-dryrun",
    "smc-databento-production-export",
    "smc-deeper-integration-gates",
    "smc-library-refresh",
]


def parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def fetch_runs(wf: str, limit: int = 60) -> list[dict]:
    out = subprocess.check_output([
        "gh", "run", "list",
        "--workflow", f"{wf}.yml",
        "--repo", REPO,
        "--status", "success",
        "--limit", str(limit),
        "--json", "databaseId,createdAt,updatedAt,event,headBranch,conclusion",
    ], text=True)
    return json.loads(out) or []


def split_and_median(runs: list[dict]) -> tuple[int, int, float | None, float | None]:
    before, after = [], []
    for r in runs:
        try:
            c = parse_ts(r["createdAt"])
            u = parse_ts(r["updatedAt"])
            wall = (u - c).total_seconds()
            if wall <= 0:
                continue
            (before if c < CUTOFF else after).append(wall)
        except Exception:
            continue
    mb = statistics.median(before) if before else None
    ma = statistics.median(after) if after else None
    return len(before), len(after), mb, ma


def fmt_secs(x: float | None) -> str:
    if x is None:
        return "—"
    if x < 60:
        return f"{x:.0f}s"
    return f"{x/60:.1f}m"


def fmt_pct(b: float | None, a: float | None) -> str:
    if b is None or a is None or b == 0:
        return "—"
    p = (a - b) / b * 100
    sign = "+" if p >= 0 else ""
    return f"{sign}{p:.1f}%"


def fmt_delta(b: float | None, a: float | None) -> str:
    if b is None or a is None:
        return "—"
    d = a - b
    sign = "+" if d >= 0 else ""
    return f"{sign}{fmt_secs(abs(d)) if d >= 0 else '-' + fmt_secs(abs(d))}".replace("+-", "-")


rows = []
for wf in WORKFLOWS:
    try:
        runs = fetch_runs(wf)
    except subprocess.CalledProcessError as exc:
        print(f"# {wf}: failed to fetch — {exc}")
        continue
    nb, na, mb, ma = split_and_median(runs)
    rows.append((wf, nb, na, mb, ma))
    print(f"{wf:42s} before n={nb:2d} med={fmt_secs(mb):>7s}  after n={na:2d} med={fmt_secs(ma):>7s}  Δ={fmt_pct(mb, ma):>7s}")

# Write artifact
md_lines = [
    "# v3-Phase-5 — Larger-Runner Performance Trend",
    "",
    "**Generated:** 2026-05-01  ",
    f"**Cutoff:** Phase-5 merge commit `573863c5` (2026-04-30 21:02 UTC) — workflows flipped from `ubuntu-latest` to `${{ vars.SMC_GH_HOSTED_RUNNER || 'ubuntu-latest-m' }}`.  ",
    "**Sample window:** last 60 successful runs per workflow (gh run list).  ",
    "**Metric:** wallclock = `updatedAt − createdAt` (includes queue + job time).  ",
    "",
    "## Summary table",
    "",
    "| Workflow | n before | n after | median before | median after | Δ | % change |",
    "|---|---:|---:|---:|---:|---:|---:|",
]
for wf, nb, na, mb, ma in rows:
    md_lines.append(
        f"| `{wf}.yml` | {nb} | {na} | {fmt_secs(mb)} | {fmt_secs(ma)} | "
        f"{fmt_delta(mb, ma)} | {fmt_pct(mb, ma)} |"
    )

# Aggregates — only for rows with both sides ≥ 5 samples
qualified = [(wf, mb, ma) for wf, nb, na, mb, ma in rows if nb >= 5 and na >= 5 and mb and ma]
md_lines += [
    "",
    "## Aggregate (workflows with ≥5 runs both sides)",
    "",
]
if qualified:
    pcts = [(ma - mb) / mb * 100 for _, mb, ma in qualified]
    md_lines += [
        f"- **Workflows qualifying:** {len(qualified)} of {len(rows)}",
        f"- **Median % change in wallclock:** {statistics.median(pcts):+.1f}%",
        f"- **Mean % change in wallclock:** {statistics.mean(pcts):+.1f}%",
        f"- **Best (largest speedup):** {min(qualified, key=lambda x: (x[2]-x[1])/x[1])[0]}",
        f"- **Worst (largest regression or smallest speedup):** {max(qualified, key=lambda x: (x[2]-x[1])/x[1])[0]}",
    ]
else:
    md_lines.append("- _Insufficient post-cutoff samples (≥5) yet; revisit after more cron cycles._")

md_lines += [
    "",
    "## Notes",
    "",
    "- Negative % change = faster on `ubuntu-latest-m`.",
    "- Wallclock includes queue time, so a regression here can also reflect larger-runner pool starvation rather than the job itself.",
    "- Workflows with `n after < 5` should be re-sampled in the next monthly Phase-5 review.",
    "- Pre-cutoff runs that already used the canonical line (the original 3 workflows: `smc-databento-production-export`, `smc-deeper-integration-gates`, `smc-library-refresh`) compare two `ubuntu-latest-m` regimes against each other — expect ≈0% change for those.",
    "",
    "## Reproduce",
    "",
    "```bash",
    ".venv/bin/python scripts/phase5_perf_trend.py",
    "```",
    "",
]

import pathlib
out_path = pathlib.Path("artifacts/review-v3/perf_trend.md")
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text("\n".join(md_lines) + "\n")
print(f"\nWrote {out_path}")
