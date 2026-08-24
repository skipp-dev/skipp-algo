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
    {
        "OFFEN",
        "PASS",
        "FAIL",
        "SCHLAFEND",
        "UNERREICHBAR",
        "UNGESICHERT",
        # Eine Beruehrung der Klasse, die keinen Beweis braucht (Kommentar,
        # Umbenennung, Formatierung). Terminal, aber DEKLARIERT: sie steht im
        # Ledger und im Diff, statt durch Nichtstun zu entstehen.
        "AUSGENOMMEN",
    }
)
#: Zustaende, die keine Frist mehr brauchen. SCHLAFEND ist ABSICHTLICH nicht
#: dabei: es ist ein Durchgangszustand mit genau drei Ausgaengen (Drill,
#: deklariert unerreichbar, akzeptiert ungesichert).
TERMINAL_STATES = frozenset({"PASS", "FAIL", "UNERREICHBAR", "AUSGENOMMEN"})

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
    # Beweislast fuer pass_kind == "drill", symmetrisch zu witness_run fuer
    # "live" (Critical 3, 2026-08-24): ohne diese zwei Felder war "drill" ein
    # Ein-Wort-Ausgang ohne Beleg -- ein Eintrag konnte auf PASS/drill gesetzt
    # werden, ohne je zu sagen, WAS durchgespielt wurde (drill_source) oder
    # WANN (drilled_at). Durchgesetzt in
    # tests/test_proof_ledger.py::test_a_pass_entry_says_whether_it_was_lived_or_drilled.
    drill_source: str = ""
    drilled_at: str = ""
    unreachable_because: str = ""
    # Kopplung fuer state == "FAIL" (2026-08-24, ersetzt den Halter
    # "widerlegt-kann-nicht-quittiert-werden"): die id eines
    # kind=="defect"-Eintrags, an dem die Arbeit haengt. Dieselbe
    # Anti-Willkuer-Regel wie bei unreachable_because oben, nur gegen einen
    # ANDEREN Ledger-Eintrag statt gegen eine Repo-Tatsache geprueft
    # (scripts/check_proof_ledger.py::_coupling_failures) -- ohne diese
    # Kopplung waere ein quittiertes FAIL ein Schalter zum Stummstellen.
    refutation_tracked_by: str = ""
    raw: dict[str, Any] | None = None


@lru_cache(maxsize=1)
def _load() -> dict[str, Any]:
    """Lies und parse das Ledger. Wandelt jede Lesepanne in ``ProofLedgerError``,
    damit der einzige Aufrufer, der das abfaengt (``check_proof_ledger.main``),
    sie von einem echten Befund (rc=1) unterscheiden kann (rc=2). Ungefangen
    waeren ``TOMLDecodeError``/``FileNotFoundError`` ein Traceback, den
    ``main()`` als rc=1 verwechselbar macht — genau die Klasse, die dieser
    Waechter selbst adressiert.
    """
    try:
        with _LEDGER_PATH.open("rb") as fp:
            return tomllib.load(fp)
    except FileNotFoundError as exc:
        raise ProofLedgerError(f"{_LEDGER_PATH}: Datei nicht gefunden") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ProofLedgerError(
            f"{_LEDGER_PATH}: nicht wohlgeformtes TOML: {exc}"
        ) from exc


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
    # Wie pass_kind bei PASS: state == "FAIL" ohne einen benannten Halter ist
    # keine Deklaration, sondern ein Wort, das sich ohne Beleg umschreiben
    # laesst. Der Halter selbst wird nicht hier, sondern in
    # scripts/check_proof_ledger.py::_coupling_failures geprueft (existiert
    # er, ist er kind=="defect", steht er NICHT-terminal) -- diese Zeile
    # erzwingt nur, dass ueberhaupt einer benannt ist.
    if raw["state"] == "FAIL" and not raw.get("refutation_tracked_by"):
        raise ProofLedgerError(
            f"Eintrag {raw['id']!r}: state=\"FAIL\" braucht refutation_tracked_by "
            "-- sonst ist ein widerlegter Fix dauerhaft laut, ohne dass sich das "
            "quittieren liesse"
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
        drill_source=str(raw.get("drill_source", "")),
        drilled_at=str(raw.get("drilled_at", "")),
        unreachable_because=str(raw.get("unreachable_because", "")),
        refutation_tracked_by=str(raw.get("refutation_tracked_by", "")),
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
