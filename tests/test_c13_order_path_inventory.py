"""The C13 freshness guard measures a DERIVED order-path population.

2026-08-18 (Doppelgaenger-Sweep E1): the deploy-hygiene guard in
``run-c13-phase-a.sh`` hand-listed five files while the real order path is the
import closure of the submit entry points (~95 files incl. the sourced ET gate
and the risk-limits config). A fix in ``scripts/live_risk_limits.py`` kept
``submit_code_behind_commits=0`` and the stale-checkout alert silent — the
#3297 gap, one import level deeper. These tests pin the derivation and its
wiring so the population cannot silently shrink back to a hand list.
"""

from __future__ import annotations

import re
from pathlib import Path

import scripts.c13_order_path_inventory as inventory

REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / "automation" / "launchd" / "run-c13-phase-a.sh"

# Files whose absence would prove the derivation went blind again: the entry
# points themselves, the deepest known risk/gating dependencies (the E1
# finding), and the non-Python order-path files.
WITNESSES = (
    "scripts/build_phase_a_inputs.py",
    "scripts/run_smc_live_incubation.py",
    "scripts/smc_to_ibkr_adapter.py",
    "scripts/execute_ibkr_watchlist.py",
    "scripts/live_risk_limits.py",
    "governance/portfolio_risk.py",
    "smc_integration/earnings_filter.py",
    "automation/launchd/run-c13-phase-a.sh",
    "automation/launchd/lib_c13_et_gate.sh",
    "configs/portfolio_risk_limits.json",
)


LAUNCHD = REPO / "automation" / "launchd"


def _drivers_that_submit() -> dict[str, tuple[str, ...]]:
    """Driver -> submit entry points it invokes, DERIVED from the driver text.

    The entry points are the modules that place orders. Any launchd driver
    that runs one of them is on the order path, and an import closure cannot
    see a shell file — so the coupling has to be measured here instead of
    trusted to a hand list.
    """
    tokens = {
        entry: re.compile(
            r"scripts[./]" + re.escape(Path(entry).stem) + r"(?![A-Za-z0-9_])"
        )
        for entry in inventory.ENTRY_POINTS
    }
    out: dict[str, tuple[str, ...]] = {}
    for driver in sorted(LAUNCHD.glob("run-c13-*.sh")):
        text = driver.read_text(encoding="utf-8")
        hits = tuple(entry for entry, rx in tokens.items() if rx.search(text))
        if hits:
            out[driver.relative_to(REPO).as_posix()] = hits
    return out


def test_every_launchd_driver_that_submits_is_in_the_inventory() -> None:
    """The population is derived from the drivers, not from memory.

    2026-08-19 (Geburtsfehler-Sweep): the inventory was born listing the
    phase-a driver only, while run-c13-commercial-shadow.sh runs the second
    real paper submitter. Both are order path; a fix in either is a fix the
    stale-checkout alert must see.
    """
    submitting = _drivers_that_submit()
    # Floor: the detection must not silently collapse to nothing and make the
    # membership assertion below vacuous.
    assert len(submitting) >= 3, f"driver detection collapsed to {sorted(submitting)}"
    files = set(inventory.order_path_files())
    missing = sorted(driver for driver in submitting if driver not in files)
    assert not missing, (
        f"launchd drivers invoke submit entry points but are absent from the "
        f"order-path inventory: {missing} — a merged fix in exactly these "
        "files would leave submit_code_behind_commits=0 and the stale-checkout "
        "alert silent."
    )


def test_the_coupling_catches_a_dropped_driver() -> None:
    """Mutation proof: restore the pre-sweep list and the coupling goes red."""
    pre_sweep = (
        "automation/launchd/run-c13-phase-a.sh",
        "automation/launchd/run-c13-eod-flatten.sh",
        "automation/launchd/lib_c13_et_gate.sh",
        "automation/launchd/lib_c13_data_push.sh",
        "configs/portfolio_risk_limits.json",
    )
    files = set(_files_with_non_python(pre_sweep))
    missing = sorted(driver for driver in _drivers_that_submit() if driver not in files)
    assert missing == ["automation/launchd/run-c13-commercial-shadow.sh"], (
        "the pre-sweep inventory must still look blind to the commercial "
        f"submitter — got {missing}"
    )


def _files_with_non_python(non_python: tuple[str, ...]) -> tuple[str, ...]:
    """``order_path_files()`` computed against a substituted non-Python set."""
    original = inventory.NON_PYTHON_ORDER_PATH
    inventory.NON_PYTHON_ORDER_PATH = non_python
    try:
        return inventory.order_path_files()
    finally:
        inventory.NON_PYTHON_ORDER_PATH = original


def test_the_derived_population_is_large_real_and_sorted() -> None:
    files = inventory.order_path_files()
    # Measured 2026-08-18: 95 files. The floor guards against a silent
    # derivation collapse, with headroom for legitimate refactors.
    assert len(files) >= 80, f"closure collapsed to {len(files)} files"
    assert list(files) == sorted(files)
    missing = [f for f in files if not (REPO / f).is_file()]
    assert not missing, f"inventory names non-existent files: {missing}"


def test_the_known_blind_spots_are_covered() -> None:
    files = set(inventory.order_path_files())
    absent = [w for w in WITNESSES if w not in files]
    assert not absent, (
        f"order-path witnesses missing from the inventory: {absent} — the "
        "guard would be blind to a merged fix in exactly these files again."
    )


def test_the_driver_consumes_the_derivation_not_a_hand_list() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    assert "scripts.c13_order_path_inventory" in source
    # The old hand list must be gone: its uniquely-identifying member was the
    # literal path list inside _publish_checkout_freshness. The entry-point
    # names legitimately appear elsewhere in the driver (they are executed),
    # so pin the absence of the ARRAY literal, not of the names.
    assert "local -a paths=(\n        scripts/execute_ibkr_watchlist.py" not in source
    # And a collapsed derivation must skip the measurement loudly instead of
    # publishing a blind zero.
    assert "inventory derivation failed" in source


def test_a_collapsed_derivation_refuses_to_emit(monkeypatch, capsys) -> None:
    monkeypatch.setattr(inventory, "ENTRY_POINTS", ("scripts/does_not_exist.py",))
    monkeypatch.setattr(inventory, "NON_PYTHON_ORDER_PATH", ())
    assert inventory.main() == 1
    captured = capsys.readouterr()
    assert "refusing to emit" in captured.err
    assert captured.out == ""
