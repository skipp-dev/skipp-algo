"""Local dry-run simulator for the F2 rollback chain.

End-to-end synthetic walkthrough of the §2.4 G2 rollback flow:

  1. Seed a temporary F2 spec + treatment artifact (status=production).
  2. Write N synthetic promotion-gate reports.
  3. Run the helper chain against them:
       append-history  (rc=0 days)
       render-issue    (rc=2 day, title+body captured)
       revert          (rc=2 day, artifact demoted, journal written)
       rotate          (operator reset)
       summarize       (history digest)
       inspect         (status digest)
       weekly digest   (rolled-up view)
  4. Collect the resulting file tree + a tiny narrative into a
     ``simulation_manifest.json`` the operator can eyeball.

Designed for local demos, regression fixture generation, and smoke-
testing the chain after refactors without waiting for CI.

Nothing in this script talks to GitHub or the network. It is the
read-only counterpart of the e2e test, not of the live daily workflow.

Exit codes
----------
  0 = simulation completed, manifest written
  1 = I/O or config error
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.f2_append_rollback_history import append_history
from scripts.f2_inspect_status import build_status
from scripts.f2_render_rollback_issue import render_body, render_title
from scripts.f2_revert_contextual_weights import revert_contextual_weights
from scripts.f2_rotate_rollback_history import rotate_history
from scripts.f2_summarize_history import build_summary
from scripts.f2_weekly_digest import build_digest
from scripts.smc_atomic_write import atomic_write_text

SIM_SCHEMA_VERSION = 1


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(json.dumps(payload, indent=2) + "\n", path)


def _synthetic_report(*, decision: str, brier_delta: float) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "experiment": "f2-dry-run",
        "decision": decision,
        "reason": f"dry-run fixture ({decision})",
        "actions": [],
        "sprt": {
            "decision": "continue" if decision != "rollback" else "accept_h0",
            "n": 100, "k": 55, "llr": 0.05,
            "p0": 0.55, "p1": 0.60, "alpha": 0.05, "beta": 0.20,
        },
        "kpi_metrics": [
            {"metric": "calibrated_brier", "delta": brier_delta},
            {"metric": "hit_rate_pct", "delta": -1.0},
        ],
    }


def simulate(
    *,
    workdir: Path,
    days: list[tuple[str, str, float]] | None = None,
) -> dict[str, Any]:
    """Walk the full rollback chain in ``workdir``.

    ``days`` is a list of ``(date, decision, brier_delta)`` triples.
    Default: 2 clean green days followed by 2 worse days ending in
    ``decision='rollback'``.
    """
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    if days is None:
        days = [
            ("2026-04-18", "hold",     -0.005),
            ("2026-04-19", "hold",     -0.003),
            ("2026-04-20", "hold",      0.011),
            ("2026-04-21", "rollback",  0.018),
        ]

    # --- Seed spec + treatment artifact --------------------------------
    artifact_path = workdir / "treatment_calibration.json"
    _write_json(artifact_path, {
        "status": "production",
        "weights": {"OB": 1.0, "FVG": 0.8},
    })
    spec_path = workdir / "spec.json"
    _write_json(spec_path, {
        "schema_version": 1,
        "name": "f2-dry-run",
        "arms": {
            "control": {"label": "static"},
            "treatment": {
                "label": "contextual",
                "calibration_artifact": str(artifact_path),
            },
        },
    })

    reports_dir = workdir / "reports"
    history_path = workdir / "rollback_history.json"
    revert_journal = workdir / "revert_journal.jsonl"

    narrative: list[str] = []
    rollback_report: Path | None = None

    # --- Day-by-day walk ----------------------------------------------
    for date, decision, delta in days:
        report = _synthetic_report(decision=decision, brier_delta=delta)
        report_path = reports_dir / f"f2_promotion_gate_{date}.json"
        _write_json(report_path, report)

        if decision == "rollback":
            rollback_report = report_path
            narrative.append(
                f"{date}: decision=rollback -> issue + auto-revert"
            )
            break

        append_history(report=report, history_path=history_path)
        narrative.append(
            f"{date}: decision={decision} delta={delta:+.6f} -> ring appended"
        )

    # --- Rollback-day actions -----------------------------------------
    issue_title: str | None = None
    issue_body_path: Path | None = None
    revert_record: dict[str, Any] | None = None
    if rollback_report is not None:
        report = json.loads(rollback_report.read_text(encoding="utf-8"))
        issue_title = render_title(report, date=rollback_report.stem.split("_")[-1])
        issue_body = render_body(
            report,
            date=rollback_report.stem.split("_")[-1],
            workflow_run_url="https://example.invalid/run/dry-run",
            report_path=str(rollback_report),
        )
        issue_body_path = workdir / "issue_body.md"
        atomic_write_text(issue_body, issue_body_path)

        revert_record = revert_contextual_weights(
            spec_path=spec_path,
            report_path=rollback_report,
            journal_path=revert_journal,
            timestamp="2026-04-21T10-00-00Z",
        )
        narrative.append(
            f"auto-revert: action={revert_record['action']} "
            f"new_status={revert_record.get('new_status', '—')}"
        )

        rotate_record = rotate_history(
            history_path=history_path,
            timestamp="2026-04-21T11-00-00Z",
        )
        narrative.append(
            f"operator rotate: archived_len={rotate_record['archived_len']}"
        )
    else:
        rotate_record = None

    # --- Post-run digests ---------------------------------------------
    summary = build_summary(
        history_path=history_path,
        reports_dir=reports_dir,
        trend_window=30,
    )
    status = build_status(
        spec_path=spec_path,
        revert_journal=revert_journal,
        reports_dir=reports_dir,
    )
    weekly = build_digest(reports_dir=reports_dir, window_days=7)

    # --- Manifest ------------------------------------------------------
    manifest = {
        "schema_version": SIM_SCHEMA_VERSION,
        "workdir": str(workdir),
        "days": days,
        "narrative": narrative,
        "spec": str(spec_path),
        "artifact": str(artifact_path),
        "reports_dir": str(reports_dir),
        "history_path": str(history_path),
        "revert_journal": str(revert_journal),
        "issue_title": issue_title,
        "issue_body": str(issue_body_path) if issue_body_path else None,
        "revert_record": revert_record,
        "rotate_record": rotate_record,
        "summary": summary,
        "status": status,
        "weekly_digest": weekly,
    }
    _write_json(workdir / "simulation_manifest.json", manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Local dry-run simulator for the F2 rollback chain."
    )
    parser.add_argument("--workdir", type=Path, required=True,
                        help="Directory to populate with the simulated run.")
    parser.add_argument("--quiet", action="store_true",
                        help="Print only the final manifest path instead of the narrative.")
    args = parser.parse_args(argv)

    try:
        manifest = simulate(workdir=args.workdir)
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.quiet:
        print(str(args.workdir / "simulation_manifest.json"))
    else:
        print("# F2 dry-run simulation")
        print(f"workdir: {args.workdir}")
        for line in manifest["narrative"]:
            print(f"  - {line}")
        print(f"manifest: {args.workdir / 'simulation_manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
