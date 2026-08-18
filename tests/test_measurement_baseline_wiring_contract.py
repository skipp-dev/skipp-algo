"""Contract pins for the measurement-baseline feed (wired 2026-07-28, B-sweep).

Before this wiring, ``--measurement-baseline-summary`` had NO feeder anywhere
and evidence summaries lived only as per-run workflow artifacts, so the
regression half of the measurement-shadow governance could never fire. These
pins keep every edge of the new feed present:

  producer  smc-deeper-integration-gates (scheduled) -> merge script -> bot PR
  storage   reports/smc_measurement_baseline_summary.json (committed)
  consumers all four run_smc_release_gates invocations pass the flag
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.run_smc_release_gates import _load_measurement_history_rows

REPO = Path(__file__).resolve().parents[1]
BASELINE = "reports/smc_measurement_baseline_summary.json"
FLAG_LINE = f"--measurement-baseline-summary {BASELINE}"


def _workflow(name: str) -> str:
    return (REPO / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_all_four_gate_invocations_pass_the_baseline_flag() -> None:
    deeper = _workflow("smc-deeper-integration-gates.yml")
    refresh = _workflow("smc-library-refresh.yml")
    publish = _workflow("smc-library-publish.yml")
    release = _workflow("smc-release-gates.yml")
    assert deeper.count(FLAG_LINE) == 1, "deeper measurement lane export must pass the baseline"
    # 2026-08-13: Der Split hat die Aufrufe getrennt — das VOR-Tor blieb im
    # Refresh, das NACH-Tor zog mit der Veroeffentlichung um. Beide muessen
    # die Grundlinie weiterhin bekommen, deshalb einzeln gepinnt statt als
    # Summe: eine Summe von 2 waere auch dann erfuellt, wenn ein Workflow
    # beide traegt und der andere keinen.
    assert refresh.count(FLAG_LINE) == 1, "pre-release gate must pass the baseline"
    assert publish.count(FLAG_LINE) == 1, "post-release gate must pass the baseline"
    assert release.count(FLAG_LINE) == 1, "strict release gates must pass the baseline"


def test_scheduled_commit_job_feeds_the_baseline() -> None:
    deeper = _workflow("smc-deeper-integration-gates.yml")
    assert "measurement-baseline-commit:" in deeper
    # Schedule-only commit: push-triggered runs must never commit (loop guard).
    assert "if: github.event_name == 'schedule'" in deeper
    # The job merges THIS run's evidence summary into the committed baseline.
    assert "scripts/update_measurement_baseline_summary.py" in deeper
    assert f"--baseline {BASELINE}" in deeper
    assert f"--out {BASELINE}" in deeper
    assert "name: smc-deeper-gate-evidence" in deeper  # artifact round-trip
    # GH_PAT discipline (GITHUB_TOKEN-created PRs strand the required check).
    assert "secrets.GH_PAT != '' && secrets.GH_PAT || secrets.GITHUB_TOKEN" in deeper
    assert f"git add {BASELINE}" in deeper
    assert "--auto --squash --delete-branch" in deeper


def test_committed_seed_is_loader_compatible() -> None:
    payload = json.loads((REPO / BASELINE).read_text(encoding="utf-8"))
    assert payload["report_kind"] == "measurement_baseline_summary"
    assert isinstance(payload["measurement_history"]["history_by_pair"], dict)
    rows, note = _load_measurement_history_rows(str(REPO / BASELINE), symbol="SPY", timeframe="1D")
    assert note is None, f"seed must parse cleanly for the loader, got note: {note}"
    # 2026-08-18 (Verdrahtungs-Sweep B/G-1): the previous `rows == []` pinned
    # the BROKEN state (22/22 rolls transported zero rows) — and would have
    # turned the first HONEST roll red. Loader compatibility is the contract;
    # row count is the feed's business.
    assert isinstance(rows, list)


def test_aggregate_pair_results_shape_transports_rows() -> None:
    """2026-08-18 (Verdrahtungs-Sweep B/G-1): the EDGE pin this file lacked.

    The scheduled release-gate run writes ONE aggregate ``measurement_lane``
    row (``details`` = ``pairs_checked`` + ``pair_results``); the flat reader
    silently dropped that shape — every baseline roll since the 2026-07-28
    wiring carried ``rows_total: 0`` and all six MEASUREMENT_*_REGRESSION
    codes were constructively dead. The aggregate shape must yield one entry
    per pair, with the gate's status as the per-pair default.
    """
    from scripts.collect_smc_gate_evidence import _extract_measurement_entries

    report = {
        "gates": [
            {
                "name": "measurement_lane",
                "status": "green",
                "details": {
                    "pairs_checked": 2,
                    "pair_results": [
                        {"symbol": "SPY", "timeframe": "1D"},
                        {"symbol": "AAPL", "timeframe": "15m"},
                    ],
                },
            }
        ],
    }

    entries, errors = _extract_measurement_entries(
        report,
        Path("/nonexistent/report.json"),
        checked_at=1.0,
        commit="abc1234",
    )

    assert errors == []
    assert sorted(e["pair"] for e in entries) == ["AAPL/15m", "SPY/1D"]
    assert all(e["status"] == "green" for e in entries)
