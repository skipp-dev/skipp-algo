"""Executing tests for the R1 pin-drift watcher.

Fixtures statt Live-Baum: contract targets und Manifest werden als Parameter
injiziert, damit jeder Arm (Drift, kein Drift, pin-los, leer, kaputt)
ausführbar ist. Der Live-Smoke-Test am Ende läuft gegen den echten Baum.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.check_r1_pin_drift import compute_pin_drift


def _manifest(tmp_path: Path, published: int) -> Path:
    p = tmp_path / "library_release_manifest.json"
    p.write_text(
        json.dumps({"manifestVersion": 2, "library": {"publishedVersion": published}}),
        encoding="utf-8",
    )
    return p


def _targets(pin: int | None) -> list[dict]:
    event: dict = {"path": "SMC_Event_Overlay.pine", "scriptName": "SMC Event Overlay"}
    if pin is not None:
        event["libraryPin"] = {
            "importPath": "preuss_steffen/smc_micro_profiles_generated",
            "version": pin,
        }
    exit_signal = {"path": "SMC_Exit_Signal.pine", "scriptName": "SMC Exit Signal"}
    return [event, exit_signal]


def test_lag_of_three_reports_drift(tmp_path: Path) -> None:
    report = compute_pin_drift(
        _manifest(tmp_path, 186), targets=_targets(183), threshold=3
    )
    assert report["drifted"] is True
    assert report["maxLag"] == 3


def test_lag_of_two_reports_no_drift(tmp_path: Path) -> None:
    report = compute_pin_drift(
        _manifest(tmp_path, 185), targets=_targets(183), threshold=3
    )
    assert report["drifted"] is False
    assert report["maxLag"] == 2


def test_pinless_target_is_listed_as_not_drift_capable(tmp_path: Path) -> None:
    report = compute_pin_drift(
        _manifest(tmp_path, 186), targets=_targets(183), threshold=3
    )
    exit_rows = [t for t in report["targets"] if t["path"] == "SMC_Exit_Signal.pine"]
    assert exit_rows and exit_rows[0]["driftCapable"] is False


def test_empty_target_roster_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="empty"):
        compute_pin_drift(_manifest(tmp_path, 186), targets=[], threshold=3)


def test_all_pinless_roster_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="drift-capable"):
        compute_pin_drift(
            _manifest(tmp_path, 186), targets=_targets(None), threshold=3
        )


def test_unreadable_manifest_raises(tmp_path: Path) -> None:
    with pytest.raises((OSError, json.JSONDecodeError, KeyError)):
        compute_pin_drift(tmp_path / "missing.json", targets=_targets(183), threshold=3)


def test_live_tree_smoke() -> None:
    """Vacuity-Anker: gegen den echten Baum liefert der Wächter ein Verdikt."""
    report = compute_pin_drift(None, targets=None, threshold=3)
    assert report["maxLag"] >= 0
    assert any(t["driftCapable"] for t in report["targets"])


def test_main_writes_all_three_github_outputs(tmp_path: Path) -> None:
    """The workflow's issue step consumes exactly these keys -- drifted,
    max_lag, threshold. A dropped key surfaces as an empty env var under
    `set -u` only at 06:30 UTC; this catches it at test time."""
    from scripts.check_r1_pin_drift import main

    out = tmp_path / "gh_output"
    rc = main(["--out", str(tmp_path / "report.json"), "--github-output", str(out)])
    assert rc == 0
    lines = out.read_text(encoding="utf-8").splitlines()
    keys = {line.split("=", 1)[0] for line in lines}
    assert keys == {"drifted", "max_lag", "threshold"}
