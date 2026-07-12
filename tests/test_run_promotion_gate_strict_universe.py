"""CI-hook tests for ``run_promotion_gate.py`` strict-universe pre-flight (#2352).

Pins the contract:

- ``--strict-universe --universe-trade-date <iso>`` exits 1 when no snapshot.
- ``--strict-universe`` without ``--universe-trade-date`` exits 1.
- ``--universe-trade-date`` (no strict) is tolerant: missing snapshot -> still
  runs the gate (falls back to the live vendor with a survivorship warning).
- With a snapshot present, the strict pre-flight is satisfied and the gate
  proceeds to its usual exit code (1/2 depending on the bundle).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

import databento_universe as universe_mod
from databento_universe import save_universe_snapshot
from scripts.run_promotion_gate import main as run_gate_main


@pytest.fixture(autouse=True)
def _stub_live_vendor(monkeypatch: pytest.MonkeyPatch) -> None:
    """Block any real network call from the fallback path."""
    monkeypatch.setattr(
        universe_mod,
        "_fetch_us_equity_universe_via_nasdaq_trader",
        lambda *a, **kw: pd.DataFrame({"symbol": ["AAPL", "MSFT"]}),
    )


@pytest.fixture(autouse=True)
def _isolate_archive_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``run_promotion_gate`` archives a timestamped copy to the default
    ``governance/promotion_decisions`` dir resolved *relative to cwd*. Chdir
    into ``tmp_path`` so these CLI tests never write into the real repo tree."""
    monkeypatch.chdir(tmp_path)


def _bundle_path(tmp_path: Path) -> Path:
    path = tmp_path / "bundle.json"
    path.write_text("[]", encoding="utf-8")
    return path


def test_strict_universe_without_snapshot_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    snap_root = tmp_path / "universe"
    rc = run_gate_main(
        [
            "--metrics",
            str(_bundle_path(tmp_path)),
            "--output",
            str(tmp_path / "out.json"),
            "--strict-universe",
            "--universe-trade-date",
            "2024-01-15",
            "--snapshot-root",
            str(snap_root),
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "2024-01-15" in err
    assert "snapshot" in err.lower()


def test_strict_universe_without_trade_date_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = run_gate_main(
        [
            "--metrics",
            str(_bundle_path(tmp_path)),
            "--output",
            str(tmp_path / "out.json"),
            "--strict-universe",
        ]
    )
    assert rc == 1
    assert "universe-trade-date" in capsys.readouterr().err


def test_non_strict_universe_missing_snapshot_falls_back(
    tmp_path: Path,
) -> None:
    snap_root = tmp_path / "universe"
    rc = run_gate_main(
        [
            "--metrics",
            str(_bundle_path(tmp_path)),
            "--output",
            str(tmp_path / "out.json"),
            "--universe-trade-date",
            "2024-01-15",
            "--snapshot-root",
            str(snap_root),
        ]
    )
    # Non-strict + missing snapshot => live-vendor fallback with
    # survivorship_bias_risk=True. The empty bundle promotes nothing (vacuous),
    # but the default enforcement demotes-not-promotes: rc 2 (observe, don't
    # PROMOTE a survivorship-biased run) instead of the old rc 0. #3453.
    assert rc == 2
    out = json.loads((tmp_path / "out.json").read_text())
    assert out["universe_survivorship_bias_risk"] is True


def test_strict_universe_with_snapshot_passes_preflight(tmp_path: Path) -> None:
    snap_root = tmp_path / "universe"
    save_universe_snapshot(
        ["AAPL", "MSFT"],
        trade_date=date(2024, 1, 15),
        source_schema="test",
        root=snap_root,
    )
    out_path = tmp_path / "out.json"
    rc = run_gate_main(
        [
            "--metrics",
            str(_bundle_path(tmp_path)),
            "--output",
            str(out_path),
            "--strict-universe",
            "--universe-trade-date",
            "2024-01-15",
            "--snapshot-root",
            str(snap_root),
        ]
    )
    assert rc == 0
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["decisions"] == []


def test_demote_survivorship_flips_promoted_and_adds_blocker() -> None:
    # M2: a survivorship-biased run must not read as PROMOTED anywhere — the
    # exit code AND the per-decision flags in the artifact are demoted, so the
    # decision-first panel / family_verdict (which render ``promoted`` directly)
    # agree with the gate's refusal instead of showing PROMOTED.
    from scripts.run_promotion_gate import (
        _demote_survivorship_biased_run,
        _report_exit_code,
    )

    decisions: list[dict] = [
        {"family": "BOS", "promoted": True, "blockers": []},
        {"family": "OB", "promoted": True, "blockers": [{"check": "psr_minimum"}]},
    ]
    _demote_survivorship_biased_run(decisions)

    assert all(d["promoted"] is False for d in decisions)
    for d in decisions:
        checks = [b["check"] for b in d["blockers"]]
        assert "provenance.universe_survivorship_bias_risk" in checks
    # a pre-existing blocker is preserved, not clobbered
    assert any(b["check"] == "psr_minimum" for b in decisions[1]["blockers"])
    # the demoted decisions now drive rc 2 on their own (belt to the main() guard)
    assert _report_exit_code({"decisions": decisions}) == 2


def test_survivorship_demoted_decision_renders_blocked_in_panel() -> None:
    # Prove the consumer side of M2: once demoted, the decision-first panel
    # renders BLOCKED (not PROMOTED) with the survivorship reason as top blocker.
    from dashboard.decision_first_panel import build_card, render_card
    from scripts.run_promotion_gate import _demote_survivorship_biased_run

    decisions: list[dict] = [{"family": "BOS", "promoted": True, "blockers": [], "metrics": {}}]
    _demote_survivorship_biased_run(decisions)
    text = render_card(build_card(decisions[0]))

    assert "BLOCKED" in text
    assert "PROMOTED" not in text
    assert "survivorship" in text.lower()
