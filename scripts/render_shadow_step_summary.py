"""Render a GitHub Step Summary for the ADR-0023 magnitude-shadow workflow.

Reads the shadow ledger JSONL, computes per-family AUC sparklines and
Stage-2 progress, and writes a Markdown summary to stdout.  The caller
pipes this into ``$GITHUB_STEP_SUMMARY``.

Usage::

    python scripts/render_shadow_step_summary.py \
        [--ledger PATH] [--k 3] [--n 4]

If the ledger is empty or missing, a brief "no data yet" summary is
written — this is the expected path on the first dispatch.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from scripts.eval_magnitude_shadow_weekly import (
    SPARK_HI,
    SPARK_LO,
    sparkline,
)
from scripts.run_magnitude_shadow_ledger import (
    CANDIDATE_FAMILIES,
    DEFAULT_LEDGER,
    load_ledger,
)


def _latest_n_per_family(
    rows: list[dict[str, Any]], n: int
) -> dict[str, list[dict[str, Any]]]:
    """Return the last *n* rows per family, ordered oldest-first."""
    by_family: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        fam = row.get("family", "")
        if fam:
            by_family.setdefault(fam, []).append(row)
    for fam in by_family:
        by_family[fam].sort(key=lambda r: str(r.get("date")))
        by_family[fam] = by_family[fam][-n:]
    return by_family


def _pass_count(rows: list[dict[str, Any]]) -> int:
    return sum(1 for r in rows if r.get("status") == "PASS")


def render_summary(
    rows: list[dict[str, Any]], *, k: int = 3, n: int = 4
) -> str:
    """Return the Markdown summary string."""
    lines: list[str] = []
    lines.append("### Shadow ledger — per-family detail")
    lines.append("")

    if not rows:
        lines.append("_No shadow data yet._ The scheduler has been armed but")
        lines.append("no events have been processed. This is expected on the")
        lines.append("first dispatch or when no events path is supplied.")
        return "\n".join(lines)

    families = _latest_n_per_family(rows, n)

    lines.append(
        "| Family | Role | Window | Pass | AUC spark | Latest AUC | Stage-2 |"
    )
    lines.append(
        "|--------|------|--------|------|-----------|------------|---------|"
    )

    for fam in sorted(families):
        window = families[fam]
        role = "candidate" if fam in CANDIDATE_FAMILIES else "control"
        passes = _pass_count(window)
        aucs = [r.get("magnitude_auc") for r in window]
        spark = sparkline(aucs, lo=SPARK_LO, hi=SPARK_HI)
        latest_auc = aucs[-1] if aucs else None
        auc_s = f"{latest_auc:.3f}" if isinstance(latest_auc, (int, float)) else "n/a"

        if role == "candidate":
            if passes >= k:
                stage2 = f"{k}-of-{n} met"
            else:
                remaining = k - passes
                stage2 = f"{passes}/{k} (need {remaining})"
        else:
            stage2 = "—"

        lines.append(
            f"| {fam} | {role} | {len(window)}/{n} "
            f"| {passes} | {spark} | {auc_s} | {stage2} |"
        )

    lines.append("")
    lines.append(
        f"_Sparkline range: {SPARK_LO:.2f} (coin-flip) → "
        f"{SPARK_HI:.2f} (strong). "
        f"This table previews the last {n} *daily* ledger rows; the "
        f"authoritative Stage-2 judgement is the weekly evaluator's "
        f"{k}-of-{n} over ISO-week evaluations (handover §4.4)._"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ledger",
        default=DEFAULT_LEDGER,
        help=f"JSONL ledger path (default: {DEFAULT_LEDGER})",
    )
    parser.add_argument("--k", type=int, default=3, help="k for k-of-n (default 3)")
    parser.add_argument("--n", type=int, default=4, help="n for k-of-n (default 4)")
    args = parser.parse_args(argv)

    rows = load_ledger(args.ledger)
    print(render_summary(rows, k=args.k, n=args.n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
