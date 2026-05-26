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
    # Empty bundle => no families to block, all-promoted vacuous truth => rc 0.
    assert rc == 0


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
