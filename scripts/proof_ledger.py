#!/usr/bin/env python3
"""Loader for ``proof_ledger.toml`` — the single source of pending proofs.

Ein Eintrag haelt fest, dass eine gemergte Aenderung ihre Wirkung noch nicht
gezeigt hat. Tests und Waechter importieren AUSSCHLIESSLICH hier — nie die
TOML direkt parsen, sonst zerfaellt das Schema in so viele Auslegungen, wie es
Leser gibt (dieselbe Regel wie ``tests/_pin_registry.py``, ADR-0009).

Warum das Ledger ueber EVIDENZINHALT urteilt und nie ueber die Lauf-
Conclusion: Lauf 32620808573 (2026-08-23) war ``conclusion: failure`` und hat
dabei exakt das Richtige getan — ``report.ok`` haengt an einem nicht leeren
``partiallyRepairedChartUrls``. Wer die Conclusion liest, fuehrt einen
bestandenen Beweis als Fehlschlag.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
_LEDGER_PATH = ROOT / "proof_ledger.toml"

MERGE_STATES = frozenset(
    {"OFFEN", "PASS", "FAIL", "SCHLAFEND", "UNERREICHBAR", "UNGESICHERT"}
)
#: Zustaende, die keine Frist mehr brauchen. SCHLAFEND ist ABSICHTLICH nicht
#: dabei: es ist ein Durchgangszustand mit genau drei Ausgaengen (Drill,
#: deklariert unerreichbar, akzeptiert ungesichert).
TERMINAL_STATES = frozenset({"PASS", "FAIL", "UNERREICHBAR"})

_REQUIRED_ALWAYS = ("id", "kind", "claim", "state", "due_by", "owner")
_REQUIRED_FIX = ("witness", "witness_job", "evidence_source", "version_probe", "judge")


class ProofLedgerError(Exception):
    """Das Ledger ist nicht wohlgeformt."""


@dataclass(frozen=True)
class ProofEntry:
    id: str
    kind: str
    claim: str
    state: str
    due_by: str
    owner: str
    judge: str = ""
    witness: str = ""
    witness_job: str = ""
    evidence_source: str = ""
    artifact: str = ""
    version_probe: str = ""
    pass_kind: str = ""
    witness_run: str = ""
    unreachable_because: str = ""
    raw: dict[str, Any] | None = None


@lru_cache(maxsize=1)
def _load() -> dict[str, Any]:
    with _LEDGER_PATH.open("rb") as fp:
        return tomllib.load(fp)


def _entry_from(raw: dict[str, Any]) -> ProofEntry:
    missing = [key for key in _REQUIRED_ALWAYS if not raw.get(key)]
    if raw.get("kind") == "fix":
        missing += [key for key in _REQUIRED_FIX if not raw.get(key)]
    if missing:
        raise ProofLedgerError(
            f"Eintrag {raw.get('id', '<ohne id>')!r}: Pflichtfelder fehlen: "
            f"{', '.join(sorted(missing))}"
        )
    if raw["state"] not in MERGE_STATES:
        raise ProofLedgerError(
            f"Eintrag {raw['id']!r}: unbekannter Zustand {raw['state']!r}"
        )
    return ProofEntry(
        id=str(raw["id"]),
        kind=str(raw["kind"]),
        claim=str(raw["claim"]),
        state=str(raw["state"]),
        due_by=str(raw["due_by"]),
        owner=str(raw["owner"]),
        judge=str(raw.get("judge", "")),
        witness=str(raw.get("witness", "")),
        witness_job=str(raw.get("witness_job", "")),
        evidence_source=str(raw.get("evidence_source", "")),
        artifact=str(raw.get("artifact", "")),
        version_probe=str(raw.get("version_probe", "")),
        pass_kind=str(raw.get("pass_kind", "")),
        witness_run=str(raw.get("witness_run", "")),
        unreachable_because=str(raw.get("unreachable_because", "")),
        raw=dict(raw),
    )


def load_entries() -> tuple[ProofEntry, ...]:
    """Alle Eintraege, validiert. Wirft bei jeder Unwohlgeformtheit."""
    entries = tuple(_entry_from(raw) for raw in _load().get("proof", []))
    seen: set[str] = set()
    for entry in entries:
        if entry.id in seen:
            raise ProofLedgerError(f"doppelte id {entry.id!r}")
        seen.add(entry.id)
    return entries


def class_floors() -> dict[str, int]:
    """Untergrenzen der abgeleiteten Dateiklasse."""
    return {name: int(value) for name, value in _load()["class_floors"].items()}


def declared_unreachable_branches() -> frozenset[tuple[str, str, str]]:
    """``(judge, branch, reason)`` je bewusst unerreichbar erklaertem Zweig."""
    return frozenset(
        (str(item["judge"]), str(item["branch"]), str(item["reason"]))
        for item in _load().get("unreachable_branch", [])
    )
