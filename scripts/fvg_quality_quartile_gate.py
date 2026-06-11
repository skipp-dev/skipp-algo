"""Q3/Q4 plan §D4 — FVG Quality Quartile Release-Gate.

Plan reference (lines 320–355): *"Training: Quality-Score-Binning auf
bestehenden 96 FVG-Events. Top-Quartil sollte signifikant höhere HR
haben als Bottom-Quartil. Release-Gate: Wenn Top-Quartil HR ≥ 75% und
Bottom-Quartil HR ≤ 55% → deployen mit Gate auf Top-Quartil-only
(aggressive) oder als Gewichtsmultiplikator (konservativ — Default)."*

This emitter is the Quartile-binning + release-gate decision script
the plan calls for. It:

1. Loads FVG events from a benchmark snapshot (same shape as
   `scripts/fvg_quality_d4_audit.py`) — directory layout
   ``ROOT/SYMBOL/TF/events_*.jsonl`` with `family == "FVG"`.
2. Re-scores every event with the production weights via
   :func:`smc_core.fvg_quality.score_fvg` (no opinion on weights —
   that's owned by `fvg_quality_recalibration.py`).
3. Bins events into score quartiles (Q1 = lowest, Q4 = highest) and
   computes per-quartile hit rate against the strict ≥50% partial-fill
   label (matches plan §D4 success criterion).
4. Emits the **release-gate decision** as JSON + Markdown:

   * ``release_gate = "PASS"`` iff Q4 HR ≥ ``--top-threshold`` (default
     0.75) **and** Q1 HR ≤ ``--bottom-threshold`` (default 0.55) **and**
     each quartile has at least ``--min-events`` (default 20)
     observations so the gate is not driven by 1–2 rare events.
   * ``release_gate = "FAIL"`` otherwise, with a structured
     ``failure_reasons`` array so the CI consumer can route the
     decision (e.g. open a "tighten quality weights" issue).
   * ``release_gate = "AWAITING_DATA"`` when no events are loaded —
     awaiting_first_run pattern matching §3.1.1 / §D2 / G2/G3.

5. Persists the latest decision to
   ``docs/fvg_quality/release_gate.json`` and
   ``docs/fvg_quality/release_gate.md`` (atomic write).

Determinism / fail-soft
-----------------------
* Stdlib only (uses :mod:`statistics` for quantile boundaries).
* Reuses :mod:`smc_core.fvg_quality` (already production-grade with
  11 unit tests).
* Empty / missing input → ``AWAITING_DATA``, exit 0 (so a daily CI
  job stays green until the benchmark pipeline produces events).
* Never raises on per-event JSON errors — bad lines are skipped and
  reported in ``loader_warnings``.
"""
from __future__ import annotations

# F-V5-A1-2 / F-CI-O1 (2026-05-01) + F-V?-? (2026-05-03): bootstrap repo
# root onto sys.path BEFORE the first-party `from scripts._logging_init`
# import so this file works under both `python -m scripts.X` and
# `python scripts/X.py`. The unconditional `sys.path.insert` (literal
# `sys` name, NOT an alias) also satisfies
# tests/test_workflow_invoked_scripts_import_order.py which detects
# the mutation via AST chain `sys.path.insert` — aliased forms
# (`_v5a12_sys.path.insert`) are not detected and were considered
# late-bootstrap, flagging the early bootstrap import as out-of-order.
import os as _bootstrap_os
import sys as _bootstrap_sys_mod
sys = _bootstrap_sys_mod

_BOOTSTRAP_ROOT = _bootstrap_os.path.dirname(_bootstrap_os.path.dirname(_bootstrap_os.path.abspath(__file__)))
if _BOOTSTRAP_ROOT not in sys.path:
    sys.path.insert(0, _BOOTSTRAP_ROOT)

from scripts._logging_init import init_cli_logging


import argparse
import glob
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from statistics import quantiles
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from smc_core.fvg_quality import score_fvg

DEFAULT_TOP_THRESHOLD = 0.75   # plan §D4 line 326
DEFAULT_BOTTOM_THRESHOLD = 0.55  # plan §D4 line 326
DEFAULT_MIN_EVENTS = 20  # per-quartile floor; protects against rare-event noise
DEFAULT_OUTPUT_JSON = Path("docs/fvg_quality/release_gate.json")
DEFAULT_OUTPUT_MD = Path("docs/fvg_quality/release_gate.md")


# ── data structures ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class QuartileSummary:
    quartile: str  # "Q1" .. "Q4"
    n: int
    hits: int
    hit_rate: float
    score_min: float
    score_max: float


@dataclass
class GateDecision:
    release_gate: str  # "PASS" | "FAIL" | "AWAITING_DATA"
    failure_reasons: list[str] = field(default_factory=list)
    quartiles: list[QuartileSummary] = field(default_factory=list)
    total_events: int = 0
    top_threshold: float = DEFAULT_TOP_THRESHOLD
    bottom_threshold: float = DEFAULT_BOTTOM_THRESHOLD
    min_events_per_quartile: int = DEFAULT_MIN_EVENTS
    loader_warnings: list[str] = field(default_factory=list)
    generated_at: str = ""
    source: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        return d


# ── loading ───────────────────────────────────────────────────────────────


def load_fvg_events(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Read FVG events from a benchmark snapshot tree.

    Returns ``(events, warnings)``. Bad JSON lines are skipped; the
    file path + line number is reported in ``warnings``.
    """
    events: list[dict[str, Any]] = []
    warnings: list[str] = []
    if not root.exists():
        return events, [f"root not found: {root}"]
    files = sorted(glob.glob(str(root / "*" / "*" / "events_*.jsonl")))
    if not files:
        return events, [f"no events_*.jsonl files under {root}"]
    for fp in files:
        try:
            with open(fp, encoding="utf-8") as fh:
                for lineno, line in enumerate(fh, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                    except json.JSONDecodeError as exc:
                        warnings.append(f"{fp}:{lineno}: {exc}")
                        continue
                    if e.get("family") == "FVG":
                        events.append(e)
        except OSError as exc:
            warnings.append(f"{fp}: {exc}")
    return events, warnings


def _hit_strict(event: dict[str, Any]) -> bool:
    """Plan §D4 success criterion uses the strict ≥50% partial-fill label."""
    return bool((event.get("features") or {}).get("label_partial_50"))


def _event_quality_features(event: dict[str, Any]) -> dict[str, Any]:
    """Extract the feature dict ``score_fvg`` expects from a benchmark event.

    Benchmark events store quality features under ``features``; copy
    only the keys the scorer reads so we don't accidentally feed it
    unrelated label/outcome fields.
    """
    feats = event.get("features") or {}
    return {
        "gap_size_atr": feats.get("gap_size_atr", 0.0),
        "htf_aligned": feats.get("htf_aligned", False),
        "distance_to_price_atr": feats.get("distance_to_price_atr", 10.0),
        "is_full_body": feats.get("is_full_body", False),
        "hurst": feats.get("hurst"),
    }


# ── binning + decision ────────────────────────────────────────────────────


def compute_quartile_summaries(
    scored: list[tuple[float, bool]],
) -> list[QuartileSummary]:
    """Bin (score, hit) pairs into quartiles by score; return Q1..Q4 summaries.

    Uses :func:`statistics.quantiles` with ``n=4`` (3 cut points → 4 bins).
    Ties on the boundary go to the *lower* bin (``score <= cutpoint``)
    so the assignment is deterministic and reproducible across runs.

    Returns an empty list when ``len(scored) < 4`` (cannot split into
    quartiles meaningfully).
    """
    if len(scored) < 4:
        return []
    scores = [s for s, _ in scored]
    cuts = quantiles(scores, n=4, method="inclusive")  # 3 cut points
    # Bin index by binary-walk on the cut points.
    bins: list[list[tuple[float, bool]]] = [[], [], [], []]
    for s, h in scored:
        if s <= cuts[0]:
            bins[0].append((s, h))
        elif s <= cuts[1]:
            bins[1].append((s, h))
        elif s <= cuts[2]:
            bins[2].append((s, h))
        else:
            bins[3].append((s, h))
    out: list[QuartileSummary] = []
    for idx, bucket in enumerate(bins, start=1):
        n = len(bucket)
        if n == 0:
            out.append(QuartileSummary(
                quartile=f"Q{idx}", n=0, hits=0, hit_rate=0.0,
                score_min=0.0, score_max=0.0,
            ))
            continue
        hits = sum(1 for _, h in bucket if h)
        scrs = [s for s, _ in bucket]
        out.append(QuartileSummary(
            quartile=f"Q{idx}",
            n=n,
            hits=hits,
            hit_rate=round(hits / n, 4),
            score_min=round(min(scrs), 4),
            score_max=round(max(scrs), 4),
        ))
    return out


def evaluate_gate(
    quartiles_summary: list[QuartileSummary],
    *,
    top_threshold: float,
    bottom_threshold: float,
    min_events: int,
) -> tuple[str, list[str]]:
    """Apply the §D4 release-gate criteria to per-quartile HRs.

    Returns ``(decision, failure_reasons)``. ``decision`` is one of
    ``"PASS"`` / ``"FAIL"``.
    """
    if len(quartiles_summary) != 4:
        return "FAIL", ["quartiles_unavailable (need 4 bins)"]
    q1 = quartiles_summary[0]
    q4 = quartiles_summary[3]
    reasons: list[str] = []
    if q1.n < min_events:
        reasons.append(
            f"q1_n_below_min ({q1.n} < {min_events})"
        )
    if q4.n < min_events:
        reasons.append(
            f"q4_n_below_min ({q4.n} < {min_events})"
        )
    if q4.hit_rate < top_threshold:
        reasons.append(
            f"q4_hit_rate_below_top_threshold "
            f"({q4.hit_rate:.4f} < {top_threshold:.4f})"
        )
    if q1.hit_rate > bottom_threshold:
        reasons.append(
            f"q1_hit_rate_above_bottom_threshold "
            f"({q1.hit_rate:.4f} > {bottom_threshold:.4f})"
        )
    return ("PASS" if not reasons else "FAIL", reasons)


def build_decision(
    events: list[dict[str, Any]],
    *,
    top_threshold: float,
    bottom_threshold: float,
    min_events: int,
    loader_warnings: list[str],
    generated_at: str,
    source: dict[str, Any],
) -> GateDecision:
    """End-to-end: events → scores → quartiles → release-gate decision."""
    if not events:
        return GateDecision(
            release_gate="AWAITING_DATA",
            failure_reasons=["no_events_loaded"],
            total_events=0,
            top_threshold=top_threshold,
            bottom_threshold=bottom_threshold,
            min_events_per_quartile=min_events,
            loader_warnings=loader_warnings,
            generated_at=generated_at,
            source=source,
        )
    scored: list[tuple[float, bool]] = []
    for e in events:
        qs = score_fvg(_event_quality_features(e))
        scored.append((qs.score, _hit_strict(e)))
    qs_summaries = compute_quartile_summaries(scored)
    if not qs_summaries:
        return GateDecision(
            release_gate="AWAITING_DATA",
            failure_reasons=[f"too_few_events ({len(scored)} < 4)"],
            total_events=len(scored),
            top_threshold=top_threshold,
            bottom_threshold=bottom_threshold,
            min_events_per_quartile=min_events,
            loader_warnings=loader_warnings,
            generated_at=generated_at,
            source=source,
        )
    decision, reasons = evaluate_gate(
        qs_summaries,
        top_threshold=top_threshold,
        bottom_threshold=bottom_threshold,
        min_events=min_events,
    )
    return GateDecision(
        release_gate=decision,
        failure_reasons=reasons,
        quartiles=qs_summaries,
        total_events=len(scored),
        top_threshold=top_threshold,
        bottom_threshold=bottom_threshold,
        min_events_per_quartile=min_events,
        loader_warnings=loader_warnings,
        generated_at=generated_at,
        source=source,
    )


# ── rendering ─────────────────────────────────────────────────────────────


def render_markdown(decision: GateDecision) -> str:
    lines = [
        "# §D4 FVG Quality Quartile — Release Gate",
        "",
        f"_Generated: `{decision.generated_at}`_",
        f"_Source root: `{decision.source.get('root', '—')}`_",
        f"_Source commit: `{(decision.source.get('commit_sha') or 'unknown')[:7]}`_",
        "",
        f"**Decision: `{decision.release_gate}`**",
        "",
        "| Parameter | Value |",
        "|---|---|",
        f"| Top-quartile threshold (Q4 HR ≥) | {decision.top_threshold:.4f} |",
        f"| Bottom-quartile threshold (Q1 HR ≤) | {decision.bottom_threshold:.4f} |",
        f"| Min events per quartile | {decision.min_events_per_quartile} |",
        f"| Total FVG events scored | {decision.total_events} |",
        "",
    ]
    if decision.failure_reasons:
        lines.extend([
            "## Failure / awaiting reasons",
            "",
            *[f"- `{r}`" for r in decision.failure_reasons],
            "",
        ])
    if decision.quartiles:
        lines.extend([
            "## Quartile breakdown",
            "",
            "| Quartile | n | hits | hit rate | score min | score max |",
            "|---|---|---|---|---|---|",
        ])
        for q in decision.quartiles:
            lines.append(
                f"| {q.quartile} | {q.n} | {q.hits} | "
                f"{q.hit_rate:.4f} | {q.score_min:.4f} | {q.score_max:.4f} |"
            )
        lines.append("")
    if decision.loader_warnings:
        lines.extend([
            "## Loader warnings",
            "",
            *[f"- {w}" for w in decision.loader_warnings[:20]],
            "",
        ])
    return "\n".join(lines)


# ── persistence ───────────────────────────────────────────────────────────


def write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    # ATOMIC-WRITE-EXEMPT: tmp+replace pattern (atomic by construction).
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


# ── CLI ───────────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=None,
        help="Benchmark snapshot directory containing SYMBOL/TF/events_*.jsonl.",
    )
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    parser.add_argument("--top-threshold", type=float, default=DEFAULT_TOP_THRESHOLD)
    parser.add_argument("--bottom-threshold", type=float, default=DEFAULT_BOTTOM_THRESHOLD)
    parser.add_argument("--min-events", type=int, default=DEFAULT_MIN_EVENTS)
    parser.add_argument(
        "--commit-sha", default=os.environ.get("GITHUB_SHA"),
        help="Source commit SHA (default: $GITHUB_SHA).",
    )
    parser.add_argument(
        "--workflow-run", default=os.environ.get("GITHUB_RUN_ID"),
        help="Source workflow run id (default: $GITHUB_RUN_ID).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    init_cli_logging()  # F-V5-A1-2 (2026-05-01)
    args = _parse_args(argv)
    now = datetime.now(UTC).isoformat()

    if args.root is not None:
        events, warnings = load_fvg_events(args.root)
    else:
        events, warnings = [], ["no --root supplied (awaiting first run)"]

    decision = build_decision(
        events,
        top_threshold=args.top_threshold,
        bottom_threshold=args.bottom_threshold,
        min_events=args.min_events,
        loader_warnings=warnings,
        generated_at=now,
        source={
            "root": str(args.root) if args.root else None,
            "commit_sha": args.commit_sha,
            "workflow_run": args.workflow_run,
        },
    )

    try:
        write_atomic(args.output_json, json.dumps(decision.to_json(), indent=2, sort_keys=True) + "\n")
        write_atomic(args.output_md, render_markdown(decision))
    except OSError as exc:
        print(f"ERROR: cannot write outputs: {exc}", file=sys.stderr)
        return 1

    print(
        f"D4 release-gate: decision={decision.release_gate} "
        f"events={decision.total_events} "
        f"reasons={len(decision.failure_reasons)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
