"""§5 promotion-gate governed-plane filter (issue #3872 follow-up).

The accumulated FamilyEvent pool is genuinely multi-TF since #2667 and was
5m-dominated by 2026-07-16 — so the bundle's Tier-1 direction metrics
silently measured a plane governance never chose (the docstring's "the
daily gate consumes the 1D pool" assumption had gone stale). These tests
pin the mirror of the shadow daily's fix (#3874): with ``--plane 1D`` only
events whose OWN modal bar cadence is 1D are graded, the filter arithmetic
is disclosed in provenance, and a starved pool yields "not measured"
instead of foreign-plane numbers.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from governance.family_returns import extract_family_returns
from scripts.build_promotion_gate_bundle import main as build_bundle_main

WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github" / "workflows" / "promotion-gate-daily.yml"
)


def _triggered_event(family: str, anchor_ts: float, bar_seconds: float, drift: float = 1.0) -> dict:
    n_forward = 10
    closes = [100.0 + i * drift for i in range(n_forward)]
    return {
        "family": family,
        "anchor_ts": anchor_ts,
        "direction": "UP",
        "entry_mode": "immediate",
        "entry_price": 100.0,
        "score": 1.5,
        "forward_opens": [100.0, *closes[:-1]],
        "forward_closes": closes,
        "forward_highs": [c + 1 for c in closes],
        "forward_lows": [c - 1 for c in closes],
        "forward_timestamps": [anchor_ts + (i + 1) * bar_seconds for i in range(n_forward)],
    }


def _run_bundle(tmp_path: Path, events: list[dict], plane_args: list[str]) -> list[dict]:
    scoring_root = tmp_path / "scoring"
    scoring_root.mkdir()
    events_path = tmp_path / "pool.json"
    events_path.write_text(json.dumps(events), encoding="utf-8")
    output = tmp_path / "bundle.json"
    rc = build_bundle_main(
        [
            "--scoring-root", str(scoring_root),
            "--output", str(output),
            "--date", "2026-07-22",
            "--magnitude-ledger", "",
            "--events", str(events_path),
            *plane_args,
        ]
    )
    assert rc == 0
    return json.loads(output.read_text(encoding="utf-8"))


def _one_d_events(n: int) -> list[dict]:
    # Anchors 25 days apart so forward windows (10 daily bars) + embargo
    # never overlap — the purge in extract_family_returns keeps every
    # return, and PSR's 30-return floor is comfortably cleared.
    day = 86_400.0
    # Varying drift => varying realized returns (a constant series has zero
    # variance and PSR refuses it).
    return [
        _triggered_event("BOS", 1_600_000_000.0 + i * 25 * day, day, drift=0.5 + 0.1 * i)
        for i in range(40)
    ]


def _intraday_events(n: int) -> list[dict]:
    return [_triggered_event("BOS", 1_780_000_000.0 + i * 7_000, 300.0) for i in range(n)]


def test_plane_filter_grades_only_governed_plane_events(tmp_path: Path) -> None:
    one_d = _one_d_events(40)
    intraday = _intraday_events(20)
    expected_returns = len(extract_family_returns(one_d)["BOS"]["returns"])
    assert expected_returns >= 30  # precondition: clears the PSR floor
    bundle = _run_bundle(tmp_path, one_d + intraday, ["--plane", "1D"])
    bos = next(e for e in bundle if e["family"] == "BOS")
    # Tier-1 measured exactly the governed-plane returns — identical to
    # extracting from the 1D subset alone, the intraday events invisible.
    assert bos["extras"]["n_triggered_returns"] == float(expected_returns)
    assert bos["provenance"]["measurement_plane"] == "1D"
    assert bos["provenance"]["governed_plane"] == "1D"
    assert bos["provenance"]["plane_filter_kept"] == len(one_d)
    assert bos["provenance"]["plane_filter_total"] == len(one_d) + len(intraday)


def test_plane_starved_pool_reports_not_measured(tmp_path: Path) -> None:
    intraday = _intraday_events(6)
    bundle = _run_bundle(tmp_path, intraday, ["--plane", "1D"])
    bos = next(e for e in bundle if e["family"] == "BOS")
    # No foreign-plane numbers: fields stay None ("not measured"), and the
    # provenance discloses the starvation instead of hiding it.
    assert bos["psr"] is None
    assert bos["fdr_pvalue"] is None
    assert "n_triggered_returns" not in bos["extras"]
    assert bos["provenance"]["plane_filter_kept"] == 0
    assert bos["provenance"]["plane_filter_total"] == 6
    assert bos["provenance"]["measurement_plane"] == "1D"


def test_without_plane_flag_behaviour_is_unchanged(tmp_path: Path) -> None:
    intraday = _intraday_events(6)
    bundle = _run_bundle(tmp_path, intraday, [])
    bos = next(e for e in bundle if e["family"] == "BOS")
    # Pool-modal plane derivation and unfiltered grading as before —
    # tier1 may or may not clear its own floors, but the plane is derived,
    # not governed, and no filter arithmetic is stamped.
    assert bos["provenance"]["measurement_plane"] == "5m"
    assert "governed_plane" not in bos["provenance"]
    assert "plane_filter_kept" not in bos["provenance"]


def test_workflow_passes_the_governed_plane() -> None:
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    runs = " ".join(
        s.get("run", "")
        for job in wf["jobs"].values()
        for s in job.get("steps", [])
    )
    assert "build_promotion_gate_bundle.py" in runs
    assert "--plane            1D" in runs


def test_coarse_grain_events_are_invisible_to_the_bundle(tmp_path: Path) -> None:
    """ADR-0031, Nachtrag 2026-10-03 IV: the pool also carries BOS events on
    the coarse grain (``pivot_lookup`` 50). Tier-1 measures the record."""
    one_d = _one_d_events(40)
    coarse = []
    for i in range(10):
        event = _triggered_event("BOS", 1_600_000_000.0 + 12 * 86_400.0 + i * 25 * 86_400.0, 86_400.0, drift=-2.0)
        event["pivot_lookup"] = 50
        coarse.append(event)
    with_coarse = _run_bundle(tmp_path, one_d + coarse, ["--plane", "1D"])
    reference_dir = tmp_path / "ref"
    reference_dir.mkdir()
    without = _run_bundle(reference_dir, one_d, ["--plane", "1D"])
    bos_with = next(e for e in with_coarse if e["family"] == "BOS")
    bos_without = next(e for e in without if e["family"] == "BOS")
    assert bos_with["extras"]["n_triggered_returns"] == bos_without["extras"]["n_triggered_returns"]
    assert bos_with["extras"] == bos_without["extras"]
    assert bos_with["provenance"]["plane_filter_total"] == len(one_d)  # the grain filter runs first
