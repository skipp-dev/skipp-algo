"""ADR-0023 Stage-1 shadow ledger: daily move-size resolution monitoring.

Stage 1 of the ADR-0023 live rollout (see
``docs/governance/adr0023_live_rollout_handover.md`` §4) is *measure-only*: on
each run it grades every family against the pre-registered §2 move-size
acceptance bar and appends one row per family to an append-only JSONL ledger.
Nothing is wired into the promotion gate here — this is the passive shadow feed
that the weekly k-of-n judgement reads.

All four families are recorded every run:

* ``BOS`` / ``SWEEP`` are the **candidates** (they cleared the §2 bar on real
  data); we confirm they stay stably above the bar.
* ``FVG`` / ``OB`` are the **negative control** (real-but-sub-threshold); we
  confirm they stay below. If all four pass on the same day that is a
  data/pipeline-artifact red flag, not skill.

The bar itself is frozen in ``governance.magnitude_resolution_gate`` and is
neither relaxed nor re-tuned here.

Input
-----
A JSON file containing a list of ``FamilyEvent`` records (same shape as
``run_magnitude_resolution_gate.py``), or ``-`` to read that list from stdin.

Ledger
------
Append-only JSONL, default ``artifacts/governance/magnitude_resolution_shadow.jsonl``.
Each line is one ``(date, family)`` observation. Re-running for the same
``(date, family, events_hash)`` is idempotent: the latest row replaces the
earlier one rather than duplicating it. History is never truncated.

Exit codes
----------
* ``0`` -- at least one family PASSES the §2 bar on this run.
* ``2`` -- families were measurable but NONE passes (expected negative run).
* ``3`` -- no family produced a verdict (every sample too thin).
* ``5`` -- stale events feed: this exact event content (same ``events_hash``)
  was already graded under an **earlier** date; nothing is appended.
  Re-grading unchanged events under a newer date would manufacture an
  independent daily vote for the weekly k-of-n out of zero new evidence
  (W7-2). A same-day re-run with the same hash stays a normal idempotent
  merge, and a backfill onto an earlier date than an existing row is a
  legitimate re-run, not a stale feed.
* ``1`` -- usage/config error (bad path, malformed JSON, empty event list,
  corrupt existing ledger).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from datetime import date as _date
from itertools import pairwise
from typing import Any

from governance.family_returns import (
    DEFAULT_COST_BPS,
    LEGACY_RETURN_RULE,
    RETURN_RULE,
    extract_family_calibration_samples,
)
from governance.magnitude_resolution_gate import (
    DEFAULT_N_BOOTSTRAP,
    DEFAULT_N_PERMUTATION,
    DEFAULT_SEED,
)
from scripts.run_magnitude_resolution_gate import (
    _load_events,
    _verdict_exit_code,
    build_report,
)
from scripts.smc_atomic_write import atomic_write_text

DEFAULT_LEDGER = "artifacts/governance/magnitude_resolution_shadow.jsonl"

# All four magnitude families, in a stable order (matches governance.types
# EventFamily). Used to emit a complete heartbeat row-set on a thin day.
ALL_FAMILIES: tuple[str, ...] = ("BOS", "OB", "FVG", "SWEEP")

# Families that cleared the ADR-0023 §2 bar on real data; the rest are tracked
# as the negative-control group. This is a *monitoring designation*, not a
# bar — a control that later crosses above the unchanged bar is recorded as a
# PASS just the same.
CANDIDATE_FAMILIES = frozenset({"BOS", "SWEEP"})

# Ledger column order (documented in the handover §4.2).
LEDGER_COLUMNS = (
    "date",
    "events_hash",
    "seed",
    "family",
    "role",
    "n_oos",
    "magnitude_auc",
    "auc_ci_low",
    "baseline_resolution",
    "perm_null_p95",
    "perm_p",
    "passes",
    "status",
    "fail_reasons",
    "plane",
    "return_rule",
)


def row_return_rule(row: dict[str, Any]) -> str:
    """The return rule a ledger row was graded under.

    Rows written before 2026-10-02 carry no ``return_rule``; they were graded
    under Variant A (``touch_then_horizon_close``), the only rule there was.
    """
    value = row.get("return_rule")
    return str(value) if value else LEGACY_RETURN_RULE


def rows_under_current_rule(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Rows graded under ``RETURN_RULE``, and a count of the others per rule.

    The move-size target is the size of the realized return, so a row is an
    observation of the rule it was graded under. Rows of different rules are
    different experiments — a k-of-n over both, or a proof under one rule
    presented as evidence for the other, would pool them (ADR-0031, Nachtrag
    2026-10-02 II).
    """
    current: list[dict[str, Any]] = []
    others: Counter[str] = Counter()
    for row in rows:
        rule = row_return_rule(row)
        if rule == RETURN_RULE:
            current.append(row)
        else:
            others[rule] += 1
    return current, dict(others)


def _today_utc() -> str:
    return datetime.now(UTC).date().isoformat()


def _parse_row_date(value: Any) -> _date | None:
    """Parse a ledger row ``date``; malformed values yield ``None``."""
    try:
        return _date.fromisoformat(str(value))
    except ValueError:
        return None


def events_content_hash(events: list[dict[str, Any]]) -> str:
    """Stable short content hash of the event list (order-sensitive)."""
    canonical = json.dumps(events, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


# Human-readable labels for the bar intervals the event feeds actually
# ship. Anything else is rendered as raw seconds — a label must never
# hide an unexpected cadence.
_PLANE_LABELS: dict[int, str] = {
    300: "5m",
    600: "10m",
    900: "15m",
    1800: "30m",
    3600: "1H",
    14400: "4H",
    86400: "1D",
}


def _forward_interval_counter(event: dict[str, Any]) -> Counter[int]:
    """Positive pairwise deltas of one event's ``forward_timestamps``."""
    intervals: Counter[int] = Counter()
    for first, second in pairwise(event.get("forward_timestamps") or []):
        try:
            delta = int(float(second) - float(first))
        except (TypeError, ValueError):
            continue
        if delta > 0:
            intervals[delta] += 1
    return intervals


def event_measurement_plane(event: dict[str, Any]) -> str | None:
    """Modal forward-bar interval of ONE event, as a human-readable label.

    The per-event twin of ``derive_measurement_plane``: since #2667 the
    rolling benchmark scores every chart TF on real per-TF structure, so the
    accumulated pool is genuinely multi-cadence (observed 2026-07-20: 5m/10m/
    15m/30m/1H side by side, zero 1D). A pool-level modal label cannot govern
    such a mix — filtering must happen per event, against each event's own
    cadence.
    """
    intervals = _forward_interval_counter(event)
    if not intervals:
        return None
    modal = intervals.most_common(1)[0][0]
    return _PLANE_LABELS.get(modal, f"{modal}s")


def derive_measurement_plane(events: list[dict[str, Any]]) -> str | None:
    """Modal forward-bar interval of *events*, as a human-readable label.

    Derived from the data, never asserted: the feed switched planes once
    already (the 2026-06-11 seed rows were graded on 15m events from the
    local production store, the CI rolling-bench pool ships 1D events).
    Stamping each ledger row with its measured plane keeps the weekly
    k-of-n evaluator and every downstream reader able to tell the two
    populations apart — pooling BOS@15m with BOS@1D under one family name
    would silently mix two different experiments. The mode is robust
    against weekend/overnight gaps, which appear as rare large intervals
    next to the dominant in-session cadence.
    """
    intervals: Counter[int] = Counter()
    for event in events:
        intervals.update(_forward_interval_counter(event))
    if not intervals:
        return None
    modal = intervals.most_common(1)[0][0]
    return _PLANE_LABELS.get(modal, f"{modal}s")


def classify_family(result: dict[str, Any]) -> tuple[str, list[str]]:
    """Map a §2 result dict to a daily status + fail reasons (handover §4.3).

    * ``INCONCLUSIVE`` -- too few OOS samples to judge (``min_sample_pass``).
    * ``PASS`` -- clears the full §2 bar.
    * ``FAIL`` -- measurable but misses at least one sub-condition.
    """
    if not result.get("min_sample_pass", False):
        return "INCONCLUSIVE", ["n_oos_below_min"]
    if result.get("passes", False):
        return "PASS", []
    reasons: list[str] = []
    if not result.get("auc_floor_pass", False):
        reasons.append("auc_floor")
    if not result.get("auc_ci_pass", False):
        reasons.append("auc_ci")
    if not result.get("resolution_pass", False):
        reasons.append("resolution_null")
    return "FAIL", reasons


def build_ledger_rows(
    report: dict[str, Any],
    *,
    date: str,
    events_hash: str,
    plane: str | None = None,
) -> list[dict[str, Any]]:
    """One tidy ledger row per measured family, sorted by family."""
    seed = int(report.get("seed", DEFAULT_SEED))
    rows: list[dict[str, Any]] = []
    for family, result in sorted(report.get("results", {}).items()):
        status, fail_reasons = classify_family(result)
        rows.append(
            {
                "date": date,
                "events_hash": events_hash,
                "seed": seed,
                "family": family,
                "role": "candidate" if family in CANDIDATE_FAMILIES else "control",
                "n_oos": result.get("n_oos"),
                "magnitude_auc": result.get("mag_auc"),
                "auc_ci_low": result.get("auc_ci_low"),
                "baseline_resolution": result.get("baseline_resolution"),
                "perm_null_p95": result.get("perm_null_p95"),
                "perm_p": result.get("perm_p_value"),
                "passes": bool(result.get("passes", False)),
                "status": status,
                "fail_reasons": fail_reasons,
                # Measurement plane derived from the events' forward bars
                # (e.g. "1D" / "15m"); None when underivable. Rows graded
                # on different planes are different experiments — the
                # weekly k-of-n must never pool across plane values.
                "plane": plane,
                # The rule the realized returns behind this row were computed
                # under; rows of another rule are another experiment too.
                "return_rule": RETURN_RULE,
            }
        )
    return rows


def build_heartbeat_rows(
    events: list[dict[str, Any]],
    *,
    date: str,
    events_hash: str,
    plane: str | None,
    cost_bps: float,
    seed: int = DEFAULT_SEED,
    fail_reason: str = "all_thin",
) -> list[dict[str, Any]]:
    """One INCONCLUSIVE heartbeat row per family for a fresh-but-thin day.

    When the walk-forward measures NO family (every family too thin to
    assemble MIN_OOS shared points) the run used to append nothing, which
    froze the committed ledger date and made the commit-back gap guard fire
    red every day — indistinguishable from a genuinely dead pipeline (the
    2026-07 blind-spot). These heartbeat rows record that the pipeline RAN on
    fresh events but had thin input: ``status="INCONCLUSIVE"`` (the exact same
    verdict a below-``MIN_OOS`` family already gets, so the weekly k-of-n and
    auto-demotion treat them identically — they never vote and never count
    toward ``window_size``), with ``n_oos`` carrying the per-family usable
    sample count and ``fail_reasons=["all_thin"]`` recording WHY.

    Only called on the fresh-feed path: a re-served frozen feed returns rc=5
    (W7-2) before reaching here, so a truly stalled pipeline still stops
    advancing the ledger and the gap guard still escalates.
    """
    samples = extract_family_calibration_samples(events, cost_bps=cost_bps)
    rows: list[dict[str, Any]] = []
    for family in ALL_FAMILIES:
        n_usable = len(samples.get(family, {}).get("scores", []))
        rows.append(
            {
                "date": date,
                "events_hash": events_hash,
                "seed": int(seed),
                "family": family,
                "role": "candidate" if family in CANDIDATE_FAMILIES else "control",
                "n_oos": n_usable,
                "magnitude_auc": None,
                "auc_ci_low": None,
                "baseline_resolution": None,
                "perm_null_p95": None,
                "perm_p": None,
                "passes": False,
                "status": "INCONCLUSIVE",
                "fail_reasons": [fail_reason],
                "plane": plane,
                "return_rule": RETURN_RULE,
            }
        )
    return rows


def load_ledger(path: str) -> list[dict[str, Any]]:
    """Read an existing JSONL ledger, failing CLOSED on malformed lines.

    W7-1 (stat-review wave 7, 2026-06-13): silently skipping malformed lines
    was fail-open in three decision-bearing consumers at once —

    * weekly k-of-n: corrupt rows turn weeks INCONCLUSIVE, so an armed
      family's full demotion window can never assemble ("partial window
      never demotes") and corrupting FAIL rows flips a strict weekly
      majority to PASS;
    * gate wiring: ``latest_rows_by_family`` picks the newest *parseable*
      row, so a corrupt FAIL row for today silently resurrects yesterday's
      PASS as the gate verdict.

    A malformed or non-object line therefore raises :class:`ValueError`
    (with ``path:lineno``) instead of being dropped, as does an unreadable
    existing file (permissions / IO errors) — consumers map ValueError to
    rc 1. A missing file is still a legitimate cold-start and yields ``[]``.
    """
    rows: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as handle:
            for lineno, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"malformed ledger line {path}:{lineno}: {exc}"
                    ) from exc
                if not isinstance(parsed, dict):
                    raise ValueError(
                        f"malformed ledger line {path}:{lineno}: "
                        f"expected a JSON object, got {type(parsed).__name__}"
                    )
                rows.append(parsed)
    except FileNotFoundError:
        return []
    except OSError as exc:
        # An EXISTING but unreadable ledger (permissions, IO error) is not
        # a cold-start — fail closed like a corrupt line, so consumers get
        # their mapped rc 1 instead of an unhandled stacktrace.
        raise ValueError(f"unreadable ledger {path}: {exc}") from exc
    return rows


def merge_rows(
    existing: list[dict[str, Any]], new: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Append-only merge, idempotent on ``(date, family, events_hash)``.

    A re-run for the same day/data/family overwrites the earlier observation
    rather than duplicating it. Rows are returned sorted by ``(date, family)``
    so the file is stable and diff-friendly; history is never dropped.
    """
    def key(row: dict[str, Any]) -> tuple[Any, Any, Any]:
        return (row.get("date"), row.get("family"), row.get("events_hash"))

    merged: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    for row in existing:
        merged[key(row)] = row
    for row in new:
        merged[key(row)] = row
    return sorted(
        merged.values(),
        key=lambda r: (str(r.get("date")), str(r.get("family"))),
    )


def append_rows(
    rows: list[dict[str, Any]], *, ledger_path: str = DEFAULT_LEDGER
) -> list[dict[str, Any]]:
    """Merge *rows* into the ledger and write it atomically; return *rows*.

    Shared persist path for both measured verdicts and thin-day heartbeats.
    Raises ``ValueError`` (via ``load_ledger``) on a corrupt existing ledger
    so callers surface rc 1 instead of overwriting history.
    """
    merged = merge_rows(load_ledger(ledger_path), rows)
    rendered = "\n".join(json.dumps(row, sort_keys=True) for row in merged)
    atomic_write_text(rendered + "\n", ledger_path)
    return rows


def append_shadow_ledger(
    report: dict[str, Any],
    *,
    ledger_path: str = DEFAULT_LEDGER,
    date: str | None = None,
    events_hash: str,
    plane: str | None = None,
) -> list[dict[str, Any]]:
    """Build today's rows, merge into the ledger, and write it atomically."""
    date = date or _today_utc()
    new_rows = build_ledger_rows(
        report, date=date, events_hash=events_hash, plane=plane
    )
    return append_rows(new_rows, ledger_path=ledger_path)


def _summarize(new_rows: list[dict[str, Any]]) -> str:
    parts = []
    for row in new_rows:
        parts.append(
            f"{row['family']}({row['role']}): {row['status']}"
            + (f" [{','.join(row['fail_reasons'])}]" if row["fail_reasons"] else "")
        )
    return " | ".join(parts) if parts else "no families measured"


def _thin_input_diagnostics(
    events: list[dict[str, Any]], *, cost_bps: float
) -> str:
    """One-line per-family input profile for the all_thin verdict.

    2026-06-10 review: weeks of `all_thin` runs were indistinguishable
    from an adapter regression because the only output was "no families
    measured". The dominant cause was structural input thinness — only
    ~9% of rolling-bench events carry a `score` plus a triggered return,
    and all usable samples cluster in ~3 anchor days, so the purged
    walk-forward cannot assemble MIN_OOS shared points. Surfacing the
    usable-sample and anchor-day counts lets the operator tell
    "needs more accumulation days" apart from "extractor broke".
    """
    samples = extract_family_calibration_samples(events, cost_bps=cost_bps)
    if not samples:
        return "0 usable samples in any family (score+triggered-return filter)"
    parts = []
    for family, bundle in sorted(samples.items()):
        days = {
            datetime.fromtimestamp(t, UTC).date() for t in bundle["anchor_ts"]
        }
        parts.append(f"{family}: {len(bundle['scores'])} samples / {len(days)} anchor days")
    return " | ".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "events",
        help="path to a JSON list of FamilyEvent records, or '-' for stdin",
    )
    parser.add_argument(
        "--ledger",
        default=DEFAULT_LEDGER,
        help=f"append-only JSONL ledger path (default: {DEFAULT_LEDGER})",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="observation date YYYY-MM-DD (default: today UTC)",
    )
    parser.add_argument(
        "--cost-bps",
        type=float,
        default=DEFAULT_COST_BPS,
        help=f"round-trip cost in basis points (default: {DEFAULT_COST_BPS})",
    )
    parser.add_argument(
        "--mag-q",
        type=float,
        default=0.5,
        help="per-fold |return| quantile for the magnitude label (default: 0.5)",
    )
    parser.add_argument(
        "--n-bootstrap",
        type=int,
        default=DEFAULT_N_BOOTSTRAP,
        help=f"AUC bootstrap resamples (default: {DEFAULT_N_BOOTSTRAP})",
    )
    parser.add_argument(
        "--n-permutation",
        type=int,
        default=DEFAULT_N_PERMUTATION,
        help=f"resolution label-permutations (default: {DEFAULT_N_PERMUTATION})",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"RNG seed for the CI/null (default: {DEFAULT_SEED})",
    )
    parser.add_argument(
        "--plane",
        default=None,
        help=(
            "governed measurement plane (e.g. '1D'): grade only events whose "
            "OWN modal forward-bar interval matches, so a multi-TF pool can "
            "never flip the ledger's plane or mix cadences inside one row "
            "(2026-07-16..21 regression: the accumulated pool went "
            "5m-dominated and three mixed-pool gradings were stamped '5m', "
            "wedging the weekly k-of-n's plane guard). With zero matching "
            "events the run appends plane_starved heartbeat rows instead of "
            "grading foreign-cadence evidence."
        ),
    )
    args = parser.parse_args(argv)

    if args.date is not None:
        try:
            _date.fromisoformat(args.date)
        except ValueError:
            print(
                f"error: --date {args.date!r} is not YYYY-MM-DD "
                "(ledger consumers compare dates; a malformed value would "
                "silently mis-order latest-row selection)",
                file=sys.stderr,
            )
            return 1

    try:
        events = _load_events(args.events)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: could not load events: {exc}", file=sys.stderr)
        return 1

    if not events:
        print("error: event list is empty", file=sys.stderr)
        return 1

    plane_starved = False
    if args.plane:
        total = len(events)
        events = [
            event
            for event in events
            if event_measurement_plane(event) == args.plane
        ]
        print(
            f"plane filter: kept {len(events)}/{total} events on governed "
            f"plane {args.plane}",
            file=sys.stderr,
        )
        # Zero matching events is NOT an input error (rc 1 would red a run
        # that DID inspect fresh evidence) and must not grade foreign-cadence
        # events either: record a distinguishable heartbeat so the ledger
        # advances, and let the stale-feed guard (rc 5) + the 10-day
        # commit-back gap guard escalate if the governed plane stays starved.
        plane_starved = not events

    # Hash the FILTERED evidence — it is what gets graded; the stale-feed
    # guard below must compare exactly that, not the raw multi-TF pool.
    events_hash = events_content_hash(events)
    obs_date = args.date or _today_utc()
    try:
        existing = load_ledger(args.ledger)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    obs_parsed = _date.fromisoformat(obs_date)
    stale_dates = sorted(
        {
            str(r.get("date"))
            for r in existing
            if r.get("events_hash") == events_hash
            # Same events under ANOTHER return rule were a different
            # measurement, not an earlier copy of this vote.
            and row_return_rule(r) == RETURN_RULE
            and (parsed := _parse_row_date(r.get("date"))) is not None
            and parsed < obs_parsed
        }
    )
    if stale_dates:
        # W7-2: the benchmark feed has not produced new events since the
        # cited EARLIER date(s) — the downloaded artifact is the SAME
        # content being re-served. Appending it under today's date would
        # let one frozen observation vote once per day in the weekly
        # k-of-n, and the growing ledger would also blind the commit-back
        # gap guard. Skip the append: if the feed stays frozen, the gap
        # guard escalates after its budget. Only strictly earlier dates
        # count — a backfill onto a date BEFORE an existing row re-grades
        # history deliberately and must not be blocked (review follow-up).
        print(
            f"stale events feed: events_hash {events_hash} was already "
            f"graded on {', '.join(stale_dates)}; refusing to append a "
            f"duplicate daily vote for {obs_date} (no new evidence)",
            file=sys.stderr,
        )
        return 5

    if plane_starved:
        # The pool carried events, just none on the governed plane: append
        # plane_starved heartbeats (stamped with the governed plane so the
        # ledger stays single-plane) and report rc 3 — the same "nothing
        # measured" verdict an all-thin day gets. Day 2 of an unchanged
        # starved pool exits rc 5 above; a starvation outlasting the gap
        # budget turns the gap guard red.
        try:
            new_rows = append_rows(
                build_heartbeat_rows(
                    [],
                    date=obs_date,
                    events_hash=events_hash,
                    plane=args.plane,
                    cost_bps=args.cost_bps,
                    seed=args.seed,
                    fail_reason="plane_starved",
                ),
                ledger_path=args.ledger,
            )
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(
            f"shadow ledger {args.ledger}: {_summarize(new_rows)}",
            file=sys.stderr,
        )
        return 3

    report = build_report(
        events,
        cost_bps=args.cost_bps,
        mag_q=args.mag_q,
        n_boot=args.n_bootstrap,
        n_perm=args.n_permutation,
        seed=args.seed,
    )

    # With an active filter every event's OWN modal interval equals the
    # governed plane, so stamp that directly: the pooled mode could still be
    # tipped by rare off-modal intervals (gaps) inside the kept events.
    plane = args.plane if args.plane else derive_measurement_plane(events)
    try:
        if report["results"]:
            new_rows = append_shadow_ledger(
                report,
                ledger_path=args.ledger,
                date=obs_date,
                events_hash=events_hash,
                plane=plane,
            )
        else:
            # All-thin on a FRESH feed: append INCONCLUSIVE heartbeat rows so
            # the ledger tracks pipeline liveness (the gap guard) rather than
            # verdict production. A frozen feed returned rc=5 above, so this
            # only advances the ledger on genuinely-new-but-thin evidence.
            new_rows = append_rows(
                build_heartbeat_rows(
                    events,
                    date=obs_date,
                    events_hash=events_hash,
                    plane=plane,
                    cost_bps=args.cost_bps,
                    seed=args.seed,
                ),
                ledger_path=args.ledger,
            )
    except ValueError as exc:
        # W7-1: corrupt existing ledger — refuse to merge/rewrite on top of
        # it. Surfacing rc 1 turns the daily workflow red instead of
        # silently dropping history.
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"shadow ledger {args.ledger}: {_summarize(new_rows)}", file=sys.stderr)
    if not report["results"]:
        print(
            "thin-input profile: "
            + _thin_input_diagnostics(events, cost_bps=args.cost_bps),
            file=sys.stderr,
        )
    return _verdict_exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
