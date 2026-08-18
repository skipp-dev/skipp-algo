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
