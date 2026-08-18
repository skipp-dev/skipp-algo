"""Evidence-freshness snapshot producer — the missing monitoring layer.

Background (2026-07-06 post-mortem). The ADR-0023 magnitude ledger froze on
2026-06-11 and the ``data/phase-a-audit`` branch froze on 2026-06-12, yet
Grafana stayed green for weeks. Root cause: the daemon only exports metrics
for things it can *see* — the live-overlay feed and the rolling-benchmark
snapshot, both of which kept running. Nothing measured the **output freshness**
of the evidence chain (ledger rows, audit-branch commits, paper fills), so a
silently frozen producer was invisible. Status-based CI alerting could not help
either: the failing crons routed to disabled GitHub Issues.

This script computes the freshness signals directly from the repo (it runs in
CI where the full checkout + both branches are available) and writes a single
compact snapshot JSON that the live-overlay daemon serves as Prometheus gauges
(see ``services/live_overlay_daemon/evidence_freshness_bridge.py``). The daemon
side is deliberately thin: one fetch, fail-soft, with built-in snapshot-age
alerting — so if THIS producer ever stops, the snapshot ages out and the
``Evidence snapshot stale`` alert fires (the failure mode is self-covering,
unlike the silent freeze it replaces).

Snapshot schema (``artifacts/monitoring/evidence_freshness.json``)::

    {
      "generated_at_unix": 1751800000.0,
      "ledger":       {"newest_date": "2026-06-11", "plane": "15m",
                       "rows": 4, "candidate_pass": 2},
      "audit_branch": {"last_commit_date": "2026-06-12"},
      "fills":        {"filled_cumulative": 0, "closed_cumulative": 0,
                       "target": 20, "newest_incubation_date": "2026-07-06"},
      "wsh":          {"newest_date": "2026-06-23", "status": "degraded:no-events"}
    }

The pure ``summarize_*`` / ``build_snapshot`` functions take already-loaded
data so they unit-test without git or network; ``main()`` does the git I/O.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

# Reuse the exact fill/close vocabulary the reconcile + backfill stages write,
# so the §5 counter here can never drift from what those stages consider a
# fill / a closed trade.
from governance.magnitude_stage_policy import classification_of
from scripts.backfill_live_outcomes import _CLOSED_ACTIONS
from scripts.run_magnitude_shadow_ledger import ALL_FAMILIES, CANDIDATE_FAMILIES
from scripts.smc_atomic_write import atomic_write_json
from scripts.summarize_portfolio_shadow import summarize_portfolio_shadow

DEFAULT_OUTPUT = "artifacts/monitoring/evidence_freshness.json"
DEFAULT_LEDGER = "artifacts/governance/magnitude_resolution_shadow.jsonl"
DEFAULT_AUDIT_BRANCH = "data/phase-a-audit"

# The real distance to a §5 (and §2) verdict is per-family usable FamilyEvent
# samples: run_epnl_after_cost_gate.py reads FamilyEvent records and needs
# MIN_TRADES = MIN_OOS_SAMPLES = 40 triggered score+return samples PER FAMILY
# (below that a family is INCONCLUSIVE, not passable). That count is exactly
# the per-family n_oos the daily ledger already records. §5 does NOT consume
# the C13 paper fills (open-prep swing trades carry no SMC family).
SAMPLES_TARGET = 40

# C13 paper-trading fill counts. This is operational activity (is the paper
# pipeline alive and filling?), NOT the §5 gate — kept for visibility but
# clearly distinguished from the §5 sample progress above.
FILLS_TARGET = SAMPLES_TARGET


def _parse_iso_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def summarize_ledger(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Newest date / plane / row-count / candidate-PASS from ledger rows.

    ``plane`` is taken from the newest row's ``plane`` column (absent on the
    legacy 2026-06-11 seed rows, which were graded on 15m events — mirror the
    handover's "absent means 15m" convention so the info metric is never
    empty).
    """
    if not rows:
        return {"newest_date": "", "plane": "", "rows": 0, "candidate_pass": 0}
    dated = [(d, r) for r in rows if (d := _parse_iso_date(r.get("date"))) is not None]
    if not dated:
        return {"newest_date": "", "plane": "", "rows": len(rows), "candidate_pass": 0}
    newest_date, _ = max(dated, key=lambda pair: pair[0])
    newest_iso = newest_date.isoformat()
    newest_rows = [r for d, r in dated if d == newest_date]
    plane = next(
        (str(r["plane"]) for r in newest_rows if r.get("plane")),
        "15m",  # legacy seed rows predate the plane column
    )
    candidate_pass = sum(
        1
        for r in newest_rows
        if r.get("family") in CANDIDATE_FAMILIES and (r.get("status") == "PASS" or r.get("passes") is True)
    )
    # Per-family usable-sample count on the newest date (n_oos): the real
    # distance to §2/§5 measurability (need SAMPLES_TARGET each). Present on
    # both measured rows and thin-day heartbeat rows.
    usable_samples: dict[str, int] = {}
    for r in newest_rows:
        fam = r.get("family")
        n = r.get("n_oos")
        if isinstance(fam, str) and isinstance(n, (int, float)) and not isinstance(n, bool):
            usable_samples[fam] = int(n)
    return {
        "newest_date": newest_iso,
        "plane": plane,
        "rows": len(rows),
        "candidate_pass": candidate_pass,
        "usable_samples": usable_samples,
    }


def summarize_fills(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Cumulative filled + closed paper trades across incubation records.

    * filled  — a real entry fill was stamped (``fill_price`` set to a finite
      positive number by the reconcile stage).
    * closed  — the trade reached a terminal action (``_CLOSED_ACTIONS``); this
      is the count that feeds the ADR-0023 §5 gate.
    * submit_failed — the paper submitter placed a bracket but no leg rested
      (all cancelled/rejected, e.g. IB error-110). Distinguishes "submits are
      dying" from "just hasn't filled yet"; powers the submit-failed alert.
    """
    filled = 0
    closed = 0
    submit_failed = 0
    for record in records:
        fill_price = record.get("fill_price")
        if isinstance(fill_price, (int, float)) and not isinstance(fill_price, bool) and fill_price > 0:
            filled += 1
        if record.get("action") in _CLOSED_ACTIONS:
            closed += 1
        if record.get("action") == "submit_failed":
            submit_failed += 1
    return {
        "filled_cumulative": filled,
        "closed_cumulative": closed,
        "submit_failed_cumulative": submit_failed,
    }


def build_snapshot(
    *,
    ledger_rows: list[dict[str, Any]],
    incubation_records: list[dict[str, Any]],
    audit_commit_date: str,
    newest_incubation_date: str,
    wsh_date: str,
    wsh_status: str,
    generated_at_unix: float,
    submit_code_behind_commits: int | None = None,
    portfolio_reconciliations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assemble the snapshot dict from already-loaded inputs (pure).

    ``submit_code_behind_commits`` is how many commits touching the paper-submit
    order path the C13 Mac's checkout is behind origin/main (published by the
    submit cron; see ``automation/launchd/run-c13-phase-a.sh``). ``None`` when
    the Mac never published a reading — surfaced as ``known=0`` so the
    stale-checkout alert stays silent rather than falsely green (2026-07-09).
    """
    ledger = summarize_ledger(ledger_rows)
    fills = summarize_fills(incubation_records)
    fills["target"] = FILLS_TARGET
    fills["newest_incubation_date"] = newest_incubation_date
    # The §2/§5 progress track: per-family usable samples toward SAMPLES_TARGET,
    # each tagged with its governance classification so the dashboard can grey
    # out non-operational families (SWEEP = proof_of_concept_15m; FVG/OB =
    # control). This — not the C13 fills — is the honest distance to §5.
    #
    # Clamp to SAMPLES_TARGET (post-review finding: n_oos means "usable
    # calibration samples" on a thin heartbeat row but "OOS walk-forward
    # fold size" — hundreds/thousands — on a MEASURED row). Reporting the raw
    # count would make a family jump from "16/40" to "2370/40" the day it
    # becomes measurable. Clamping shows "40/40" = "at/over the bar", so the
    # gauge reads as honest progress-to-measurability in both regimes.
    per_family = ledger.get("usable_samples") or {}
    samples = {
        "target": SAMPLES_TARGET,
        "per_family": {
            fam: {
                "usable": min(int(per_family.get(fam, 0)), SAMPLES_TARGET),
                "classification": classification_of(fam),
            }
            for fam in ALL_FAMILIES
        },
    }
    portfolio_shadow = summarize_portfolio_shadow(
        incubation_records,
        portfolio_reconciliations or [],
    )

    return {
        "generated_at_unix": float(generated_at_unix),
        "ledger": ledger,
        "samples": samples,
        "audit_branch": {"last_commit_date": audit_commit_date},
        "fills": fills,
        "portfolio_shadow": portfolio_shadow,
        "wsh": {"newest_date": wsh_date, "status": wsh_status},
        "submitter": {
            "submit_code_behind_commits": int(submit_code_behind_commits or 0),
            "known": 1 if submit_code_behind_commits is not None else 0,
        },
    }


# --------------------------------------------------------------------------- #
# git I/O (thin; not unit-tested — exercised by the workflow smoke run)
# --------------------------------------------------------------------------- #


def _git(args: list[str]) -> str:
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


# The freshness signal must track the TWS-session producers (audit-push /
# reconcile artifacts under cache/live/) and NOT the commercial-shadow
# campaign report: that driver commits cache/live/commercial_campaign/ up to
# six times per trading day with no TWS dependency, so an unscoped
# `git log -1 <branch>` would keep this signal fresh while the whole phase-a
# chain is dead — re-arming the invisible 2026-06-12 freeze this module
# exists to catch (Grenzgänger-Sweep B1, 2026-08-18).
_AUDIT_PRODUCER_PATHSPEC = ("cache/live", ":(exclude)cache/live/commercial_campaign")


def _audit_branch_last_commit_date(branch: str) -> str:
    """``%cs`` of the newest commit touching the TWS-session artifact paths."""
    return _git(
        ["log", "-1", "--format=%cs", branch, "--", *_AUDIT_PRODUCER_PATHSPEC]
    ).strip()


def _load_ledger_rows(ledger_path: Path) -> list[dict[str, Any]]:
    if not ledger_path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def _audit_branch_files(branch: str, prefix: str) -> list[str]:
    try:
        out = _git(["ls-tree", "-r", "--name-only", branch])
    except subprocess.CalledProcessError:
        return []
    return sorted(p for p in out.splitlines() if p.startswith(prefix) and p.endswith(".jsonl"))


def _portfolio_reconciliation_files(branch: str) -> list[str]:
    try:
        out = _git(["ls-tree", "-r", "--name-only", branch])
    except subprocess.CalledProcessError:
        return []
    return sorted(
        path
        for path in out.splitlines()
        if path.startswith("artifacts/portfolio/reconciliation_") and path.endswith(".monitoring.json")
    )


def _read_audit_file(branch: str, path: str) -> str:
    try:
        return _git(["show", f"{branch}:{path}"])
    except subprocess.CalledProcessError:
        return ""


def _date_from_incubation_path(path: str) -> str:
    # cache/live/incubation_2026-07-06.jsonl -> 2026-07-06
    stem = Path(path).stem
    _, _, tail = stem.partition("incubation_")
    return tail if _parse_iso_date(tail) else ""


def _date_from_wsh_path(path: str) -> str:
    # cache/wsh/2026-06-23.jsonl -> 2026-06-23
    stem = Path(path).stem
    return stem if _parse_iso_date(stem) else ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", default=DEFAULT_LEDGER)
    parser.add_argument("--audit-branch", default=DEFAULT_AUDIT_BRANCH)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    ledger_rows = _load_ledger_rows(Path(args.ledger))

    # Cumulative fills across every incubation file on the audit branch.
    incubation_paths = _audit_branch_files(args.audit_branch, "cache/live/incubation_")
    incubation_records: list[dict[str, Any]] = []
    newest_incubation_date = ""
    for path in incubation_paths:
        d = _date_from_incubation_path(path)
        if d and d > newest_incubation_date:
            newest_incubation_date = d
        for line in _read_audit_file(args.audit_branch, path).splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                incubation_records.append(parsed)

    # Audit-branch commit date (the freeze signal that stayed invisible).
    try:
        audit_commit_date = _audit_branch_last_commit_date(args.audit_branch)
    except subprocess.CalledProcessError:
        audit_commit_date = ""

    # Newest WSH snapshot on the audit branch (secondary earnings filter).
    wsh_paths = _audit_branch_files(args.audit_branch, "cache/wsh/")
    wsh_date = ""
    for path in wsh_paths:
        d = _date_from_wsh_path(path)
        if d and d > wsh_date:
            wsh_date = d
    wsh_status = ""
    if wsh_date:
        summary_raw = _read_audit_file(args.audit_branch, f"cache/wsh/{wsh_date}.summary.json")
        try:
            wsh_status = str(json.loads(summary_raw).get("status", "")) if summary_raw else ""
        except json.JSONDecodeError:
            wsh_status = ""

    # Deploy-hygiene: how far the C13 Mac's checkout is behind origin/main on the
    # paper-submit order path, published by the submit cron (run-c13-phase-a.sh).
    # None when never published (surfaced downstream as known=0, alert silent).
    submit_code_behind_commits: int | None = None
    freshness_raw = _read_audit_file(args.audit_branch, "cache/live/checkout_freshness.json")
    if freshness_raw:
        try:
            _behind = json.loads(freshness_raw).get("submit_code_behind_commits")
        except json.JSONDecodeError:
            _behind = None
        if isinstance(_behind, int) and not isinstance(_behind, bool) and _behind >= 0:
            submit_code_behind_commits = _behind

    portfolio_reconciliations: list[dict[str, Any]] = []
    for path in _portfolio_reconciliation_files(args.audit_branch):
        raw = _read_audit_file(args.audit_branch, path)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            portfolio_reconciliations.append(parsed)
    snapshot = build_snapshot(
        ledger_rows=ledger_rows,
        incubation_records=incubation_records,
        audit_commit_date=audit_commit_date,
        newest_incubation_date=newest_incubation_date,
        wsh_date=wsh_date,
        wsh_status=wsh_status,
        generated_at_unix=datetime.now(UTC).timestamp(),
        submit_code_behind_commits=submit_code_behind_commits,
        portfolio_reconciliations=portfolio_reconciliations,
    )
    atomic_write_json(snapshot, Path(args.output), indent=2, sort_keys=True)
    print(
        f"evidence_freshness: wrote {args.output} — "
        f"ledger={snapshot['ledger']['newest_date'] or 'none'}({snapshot['ledger']['plane']}) "
        f"audit={snapshot['audit_branch']['last_commit_date'] or 'none'} "
        f"fills_closed={snapshot['fills']['closed_cumulative']}/{snapshot['fills']['target']} "
        f"wsh={snapshot['wsh']['newest_date'] or 'none'}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
