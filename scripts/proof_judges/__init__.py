#!/usr/bin/env python3
"""Vertrag fuer reine Urteiler ueber Beweis-Evidenz.

Ein Urteiler bekommt Evidenz und einen Ledger-Eintrag und gibt ein Urteil
zurueck. Er holt nichts, er schreibt nichts, er kennt keine Uhr — nur so ist
er gegen ein Korpus laufbar. Der Bash-Urteiler, den das hier abloest, war
nicht laufbar, und genau deshalb konnte einer seiner Zweige einen Tag lang
Urteile drucken, ohne je feuern zu koennen.

Jeder Zweig traegt ein LABEL (``branch=``). Die Labels werden in Task 5 per
AST aus dem Quelltext abgeleitet, nie abgeschrieben — eine abgeschriebene
Liste ist blind fuer Zuwachs.
"""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
CORPUS_ROOT = ROOT / "tests" / "proof_corpus"

VERDICTS = frozenset(
    {"PASS", "FAIL", "SCHLAFEND", "STEHT_AUS", "KANN_NICHT_BEZEUGEN", "PRUEFEN"}
)


@dataclass(frozen=True)
class Verdict:
    state: str
    branch: str
    detail: str = ""

    def __post_init__(self) -> None:
        if self.state not in VERDICTS:
            raise ValueError(f"unbekanntes Urteil {self.state!r}")


def load_judge(name: str) -> ModuleType:
    return importlib.import_module(f"scripts.proof_judges.{name}")


def corpus_for(name: str) -> tuple[tuple[str, dict], ...]:
    """``(run_id, evidenz)`` je aufgezeichnetem echten Artefakt."""
    folder = CORPUS_ROOT / name
    if not folder.exists():
        return ()
    return tuple(
        (path.stem, json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(folder.glob("*.json"))
    )


def dig(evidence: dict, dotted: str):
    """``mutations.partiallyRepairedChartUrls`` aufloesen; ``None``, wenn weg."""
    node = evidence
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def has_path(evidence: dict, dotted: str) -> bool:
    node = evidence
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True
