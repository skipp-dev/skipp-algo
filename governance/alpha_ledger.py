"""Sprint X1 — Alpha-Budget Ledger.

Multiple sprints (C4 permutation/FDR, C6 PSR-significance, C5 regime
stratification, C10 per-family ML) consume Type-I error budget
independently. Without a central ledger nothing prevents the same
α=0.05 from being silently spent five times across the pipeline.

This module is the ledger. Each call site that consumes alpha registers
a TypedDict ``AlphaReservation`` at import time; the file
``governance/alpha_ledger.json`` is the persistent inventory and the
test ``tests/test_alpha_budget_inventory.py`` enforces:
- global sum ≤ 0.05
- per-family sum ≤ 0.025

The ledger does not change Bonferroni/Holm logic (that lives in C4).
It is purely an audit-and-budget layer.

Roadmap: docs/IMPROVEMENTS_C2_C12_ROADMAP_2026-04-26.md#x1
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import TypedDict
import contextlib

GLOBAL_ALPHA_BUDGET = 0.05
PER_FAMILY_ALPHA_BUDGET = 0.025

# Deep-Review 2026-04-27: explicit reserved buffer below the global cap.
# New consumers (unforeseen at sprint X1) must fit within this buffer
# before the global cap is approached. The corresponding ledger update
# lowered each existing reservation from 0.010 → 0.008 (5 * 0.008 = 0.04).
ALPHA_BUDGET_BUFFER = 0.01

DEFAULT_LEDGER_PATH = Path(__file__).resolve().parent / "alpha_ledger.json"


class AlphaReservation(TypedDict):
    sprint: str
    family: str
    alpha: float
    method: str
    rationale: str


_LOCK = threading.Lock()


def _load(path: Path) -> list[AlphaReservation]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"alpha_ledger.json must be a JSON array, got {type(raw)}")
    return [AlphaReservation(**item) for item in raw]


def _dump(path: Path, items: Iterable[AlphaReservation]) -> None:
    payload = json.dumps(list(items), indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(path)
    except Exception:
        if tmp.exists():
            with contextlib.suppress(OSError):
                tmp.unlink()
        raise


def _key(r: AlphaReservation) -> tuple[str, str, str]:
    return (r["sprint"], r["family"], r["method"])


def list_reservations(path: Path | None = None) -> list[AlphaReservation]:
    """Return current reservations from disk."""
    return _load(path or DEFAULT_LEDGER_PATH)


def register(
    reservation: AlphaReservation, *, path: Path | None = None
) -> AlphaReservation:
    """Persist a reservation. Idempotent: re-register with identical
    (sprint, family, method) is a no-op iff alpha matches; raises
    ``ValueError`` on conflicting double-registration."""
    p = path or DEFAULT_LEDGER_PATH
    if not (0.0 < reservation["alpha"] <= 1.0):
        raise ValueError(f"alpha must be in (0, 1], got {reservation['alpha']}")
    with _LOCK:
        items = _load(p)
        key = _key(reservation)
        for existing in items:
            if _key(existing) == key:
                if abs(existing["alpha"] - reservation["alpha"]) > 1e-12:
                    raise ValueError(
                        f"alpha conflict for {key}: "
                        f"existing {existing['alpha']} vs new {reservation['alpha']}"
                    )
                return existing
        new_global = float(sum(r["alpha"] for r in items) + reservation["alpha"])
        if new_global > GLOBAL_ALPHA_BUDGET + 1e-12:
            raise ValueError(
                "global alpha budget exceeded: attempted total "
                f"{new_global} > budget {GLOBAL_ALPHA_BUDGET} for {key}"
            )
        new_family = float(
            sum(r["alpha"] for r in items if r["family"] == reservation["family"])
            + reservation["alpha"]
        )
        if new_family > PER_FAMILY_ALPHA_BUDGET + 1e-12:
            raise ValueError(
                "per-family alpha budget exceeded: family "
                f"{reservation['family']!r} attempted total {new_family} > "
                f"budget {PER_FAMILY_ALPHA_BUDGET}"
            )
        items.append(reservation)
        _dump(p, items)
        return reservation


def reset(path: Path | None = None) -> None:
    """Test/utility helper — wipe an explicitly provided ledger path.

    Refuses to operate on ``DEFAULT_LEDGER_PATH`` to avoid accidental
    deletion of the checked-in repository ledger.
    """
    if path is None:
        raise ValueError("reset() requires an explicit non-default path")
    if path.resolve() == DEFAULT_LEDGER_PATH.resolve():
        raise ValueError("reset() refuses to delete DEFAULT_LEDGER_PATH")
    if path.exists():
        path.unlink()


def total_alpha(items: Iterable[AlphaReservation] | None = None) -> float:
    items = list(items) if items is not None else list_reservations()
    return float(sum(r["alpha"] for r in items))


def per_family_alpha(
    items: Iterable[AlphaReservation] | None = None,
) -> dict[str, float]:
    items = list(items) if items is not None else list_reservations()
    out: dict[str, float] = {}
    for r in items:
        out[r["family"]] = out.get(r["family"], 0.0) + r["alpha"]
    return out


__all__ = [
    "DEFAULT_LEDGER_PATH",
    "GLOBAL_ALPHA_BUDGET",
    "PER_FAMILY_ALPHA_BUDGET",
    "AlphaReservation",
    "list_reservations",
    "per_family_alpha",
    "register",
    "reset",
    "total_alpha",
]
