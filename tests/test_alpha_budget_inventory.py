"""Sprint X1 — Alpha-Budget Ledger inventory & enforcement tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from governance import alpha_ledger as al
from governance.alpha_ledger import (
    GLOBAL_ALPHA_BUDGET,
    PER_FAMILY_ALPHA_BUDGET,
    AlphaReservation,
    list_reservations,
    per_family_alpha,
    register,
    reset,
    total_alpha,
)

# ---------------------------------------------------------------------------
# Inventory snapshot — enforces the budget across the actual ledger file.
# ---------------------------------------------------------------------------


def test_default_ledger_loads() -> None:
    items = list_reservations()
    assert items, "ledger must not be empty"
    for r in items:
        assert set(r.keys()) >= {"sprint", "family", "alpha", "method", "rationale"}


def test_global_alpha_budget_not_exceeded() -> None:
    assert total_alpha() <= GLOBAL_ALPHA_BUDGET + 1e-12, (
        f"global alpha {total_alpha()} > budget {GLOBAL_ALPHA_BUDGET}"
    )


def test_per_family_alpha_budget_not_exceeded() -> None:
    per = per_family_alpha()
    for family, total in per.items():
        assert total <= PER_FAMILY_ALPHA_BUDGET + 1e-12, (
            f"family {family}: {total} > {PER_FAMILY_ALPHA_BUDGET}"
        )


def test_alpha_budget_buffer_present() -> None:
    """Deep-Review 2026-04-27: total committed alpha must leave at least
    ``ALPHA_BUDGET_BUFFER`` headroom below the global cap so unforeseen
    new consumers can register without tripping the gate."""
    from governance.alpha_ledger import ALPHA_BUDGET_BUFFER

    headroom = GLOBAL_ALPHA_BUDGET - total_alpha()
    assert headroom + 1e-12 >= ALPHA_BUDGET_BUFFER, (
        f"alpha headroom {headroom} below required buffer {ALPHA_BUDGET_BUFFER}; "
        "lower an existing reservation before adding new ones."
    )


def test_inventory_keys_unique() -> None:
    items = list_reservations()
    keys = [(r["sprint"], r["family"], r["method"]) for r in items]
    assert len(keys) == len(set(keys)), keys


# ---------------------------------------------------------------------------
# Behavioural: register / idempotency / conflict.
# ---------------------------------------------------------------------------


def _resv(alpha: float = 0.005) -> AlphaReservation:
    return AlphaReservation(
        sprint="TESTSPRINT",
        family="TEST",
        alpha=alpha,
        method="dummy_test",
        rationale="unit test fixture",
    )


def test_register_persists_to_isolated_path(tmp_path: Path) -> None:
    p = tmp_path / "ledger.json"
    register(_resv(0.01), path=p)
    items = al._load(p)
    assert len(items) == 1
    assert items[0]["sprint"] == "TESTSPRINT"


def test_register_idempotent_same_alpha(tmp_path: Path) -> None:
    p = tmp_path / "ledger.json"
    register(_resv(0.01), path=p)
    register(_resv(0.01), path=p)  # no-op
    assert len(al._load(p)) == 1


def test_register_conflict_raises(tmp_path: Path) -> None:
    p = tmp_path / "ledger.json"
    register(_resv(0.01), path=p)
    with pytest.raises(ValueError, match="alpha conflict"):
        register(_resv(0.02), path=p)


def test_register_validates_alpha_range(tmp_path: Path) -> None:
    p = tmp_path / "ledger.json"
    with pytest.raises(ValueError, match="alpha must be"):
        register(_resv(0.0), path=p)
    with pytest.raises(ValueError, match="alpha must be"):
        register(_resv(1.5), path=p)


def test_total_and_per_family_helpers(tmp_path: Path) -> None:
    p = tmp_path / "ledger.json"
    register(
        AlphaReservation(
            sprint="A", family="X", alpha=0.01, method="m1", rationale="r"
        ),
        path=p,
    )
    register(
        AlphaReservation(
            sprint="B", family="X", alpha=0.005, method="m2", rationale="r"
        ),
        path=p,
    )
    items = al._load(p)
    assert total_alpha(items) == pytest.approx(0.015)
    assert per_family_alpha(items) == {"X": pytest.approx(0.015)}


def test_reset_removes_isolated_ledger(tmp_path: Path) -> None:
    p = tmp_path / "ledger.json"
    register(_resv(0.01), path=p)
    assert p.exists()
    reset(p)
    assert not p.exists()


def test_reset_refuses_default_path() -> None:
    with pytest.raises(ValueError, match="non-default"):
        reset(None)
    with pytest.raises(ValueError, match="DEFAULT_LEDGER_PATH"):
        reset(al.DEFAULT_LEDGER_PATH)


def test_register_enforces_global_budget(tmp_path: Path) -> None:
    p = tmp_path / "ledger.json"
    for i, fam in enumerate(["F1", "F2"]):
        register(
            AlphaReservation(
                sprint=f"S{i}", family=fam, alpha=0.02, method="m", rationale=""
            ),
            path=p,
        )
    with pytest.raises(ValueError, match="global alpha budget"):
        register(
            AlphaReservation(
                sprint="X", family="F3", alpha=0.02, method="m", rationale=""
            ),
            path=p,
        )


def test_register_enforces_per_family_budget(tmp_path: Path) -> None:
    p = tmp_path / "ledger.json"
    register(
        AlphaReservation(
            sprint="A", family="F1", alpha=0.02, method="m1", rationale=""
        ),
        path=p,
    )
    with pytest.raises(ValueError, match="per-family alpha budget"):
        register(
            AlphaReservation(
                sprint="B", family="F1", alpha=0.01, method="m2", rationale=""
            ),
            path=p,
        )
