"""scripts/check_customer_surface_vocabulary.py — Kundenoberflächen sprechen
kein internes Klempnerdeutsch.

Die Regeln standen bis 2026-08-13 nur in `tests/test_customer_surface_vocabulary.py`
und liefen damit nur dort, wo pytest läuft. Genau das war die Lücke: Auf der
`bot/*`-Spur von `smc-fast-pr-gates.yml` werden die schweren Gates
übersprungen, weil ein Bibliothekslauf legitim nur Daten und `.pine` anfasst —
und deshalb sah niemand zu, als der Refresh am 12.08. (#4646), 13.08. (#4665)
und dazwischen dieselben vier Kundenoberflächen dreimal auf den Stand vor der
Bereinigung zurückdrehte. Dreimal musste ein Mensch es hinterher reparieren
(#4650, #4652, #4666).

Deshalb liegt die Prüfung hier: **nur Stdlib**, damit die Pine-Spur sie ohne
Python-Setup in Sekunden fahren kann. `tests/test_customer_surface_vocabulary.py`
importiert dieselben Konstanten und Funktionen — es gibt keine zweite Kopie der
Regeln, die auseinanderlaufen könnte.

Was geprüft wird und was bewusst nicht, steht unverändert im Test.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = REPO_ROOT / "spec" / "hero_surface_input_map.json"

# Group VARIABLES whose inputs the customer is told not to touch: the chart-link
# bindings that SMC Onboarding fills automatically, the debug mirrors and the
# manual internal overrides.
INTERNAL_GROUP_VARS: dict[str, frozenset[str]] = {
    "SMC_Long_Dip_Dashboard.pine": frozenset({
        "g_bus_lifecycle", "g_bus_diag", "g_bus_plan", "g_bus_diag_rows",
        "g_bus_blockers", "g_bus_detail", "g_bus_lean", "g_bus_preset",
        "g_local_debug", "g_operator_ops",
    }),
    "SMC_Long_Dip_Mobile.pine": frozenset({"g_bus"}),
    "SMC_Long_Dip_Alerts.pine": frozenset({"g_bus"}),
    "SMC_Long_Dip_Suite.pine": frozenset(),
}

# Lower bounds on what the parser must still find. Without them a broken regex
# would empty the population and report a clean surface (the failure mode the
# 2026-08 vacuity sweep kept finding: a guard that passes by measuring nothing).
# Measured 2026-08-12 and pinned at the measured value, so removing a customer
# input is a deliberate pin update rather than a silent shrink. Adding inputs
# never trips these.
MIN_INPUTS: dict[str, int] = {
    "SMC_Long_Dip_Dashboard.pine": 11,
    "SMC_Long_Dip_Mobile.pine": 5,
    "SMC_Long_Dip_Alerts.pine": 2,
    "SMC_Long_Dip_Suite.pine": 227,
}

# Same, for settings-group labels. Cross-checked 2026-08-12 against
# `grep -cE "^\s*(var\s+)?(string\s+)?g_[a-z_0-9]+\s*="`: 26/12/3/3, identical.
MIN_GROUP_LABELS: dict[str, int] = {
    "SMC_Long_Dip_Dashboard.pine": 12,
    "SMC_Long_Dip_Mobile.pine": 3,
    "SMC_Long_Dip_Alerts.pine": 3,
    "SMC_Long_Dip_Suite.pine": 26,
}

# Vocabulary that belongs to internal plumbing rather than a product UX.
PLUMBING_PATTERNS: dict[str, str] = {
    "BUS channel name": r"\bBUS\b",
    "operator role": r"\boperator\b",
    "sidecar": r"\bsidecar\b",
    "internal plan reference": r"\bPlan\s*(?:§|W\d|\d+\.\d)|\bAddendum\s+\d",
    "work-package id": r"\bWP-[A-Z]+\d*\b",
    "repo path": r"\b(?:docs|pine|scripts|artifacts|smc_core)/[\w./-]+",
    "internal library name": r"\bsmc_[a-z_]+\b",
    "retired umbrella name": r"\bCore Engine\b|\bSkippALGO\b",
}

# Terms that look internal but are legitimate customer vocabulary, each with the
# reason it is allowed. Applied before the patterns run.
ALLOWED_TERMS: dict[str, str] = {
    "SMC_Hold_Manager": "real TradingView script name a customer adds to the chart",
    "SMC_Exit_Signal": "real TradingView script name a customer adds to the chart",
}

_INPUT_RE = re.compile(
    r"^(?:var\s+)?(?:(?:bool|int|float|string|color)\s+)?(?P<var>\w+)\s*=\s*input(?:\.\w+)?\("
)
_GROUP_RE = re.compile(r"\bgroup\s*=\s*(?P<var>\w+)")
_TITLE_RE = re.compile(r"""input(?:\.\w+)?\(\s*(?:[^,]*,\s*)?["'](?P<t>[^"']{2,})["']""")
_TOOLTIP_RE = re.compile(r"""\btooltip\s*=\s*["'](?P<t>(?:[^"'\\]|\\.)*)["']""")
# All three declaration styles in the tree: `var string g_x = "..."` (Dashboard),
# `var g_x = '...'` (Suite) and a bare `g_x = '...'` (Alerts). Missing one of them
# silently shrinks the population — the Suite alone declares its groups as `var
# g_x` and a `var string`-only pattern saw 1 of its 40 labels.
_GROUP_DEF_RE = re.compile(
    r"""^\s*(?:var\s+)?(?:string\s+)?(?P<var>g_\w+)\s*=\s*["'](?P<label>[^"']+)["']\s*$"""
)

PINE_FILES = sorted(INTERNAL_GROUP_VARS)


def leaks(text: str) -> list[str]:
    for term in ALLOWED_TERMS:
        text = text.replace(term, "")
    return [
        name for name, pattern in PLUMBING_PATTERNS.items()
        if re.search(pattern, text, re.IGNORECASE)
    ]


def read_lines(pine_file: str) -> list[str]:
    return (REPO_ROOT / pine_file).read_text(encoding="utf-8").splitlines()


def input_leaks(pine_file: str) -> tuple[list[str], int]:
    """Fundstellen und die GRÖSSE der geprüften Menge.

    Die Menge wird mitgegeben, weil eine leere Menge sonst als sauberes
    Ergebnis durchginge — der Fehler, den der Vakuitäts-Sweep reihenweise fand.
    """
    internal = INTERNAL_GROUP_VARS[pine_file]
    found: list[str] = []
    population = 0

    for lineno, line in enumerate(read_lines(pine_file), 1):
        match = _INPUT_RE.match(line.strip())
        if not match:
            continue
        group_match = _GROUP_RE.search(line)
        group = group_match.group("var") if group_match else None
        if group in internal:
            continue
        population += 1

        title_match, tooltip_match = _TITLE_RE.search(line), _TOOLTIP_RE.search(line)
        title = title_match.group("t") if title_match else ""
        tooltip = tooltip_match.group("t") if tooltip_match else ""
        for where, text in (("title", title), ("tooltip", tooltip)):
            for leak in leaks(text):
                found.append(f"{pine_file}:{lineno} {match.group('var')} {where} -> {leak}")
    return found, population


def group_label_leaks(pine_file: str) -> tuple[list[str], int]:
    found: list[str] = []
    labels = 0
    for lineno, line in enumerate(read_lines(pine_file), 1):
        match = _GROUP_DEF_RE.match(line)
        if not match:
            continue
        labels += 1
        for leak in leaks(match.group("label")):
            found.append(f"{pine_file}:{lineno} {match.group('label')!r} -> {leak}")
    return found, labels


def spec_partition_disagreements() -> list[str]:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    return [
        f"{pine_file}: spec operator_only_groups and INTERNAL_GROUP_VARS disagree"
        for pine_file, spec_entry in spec["files"].items()
        if set(spec_entry["operator_only_groups"]) != set(INTERNAL_GROUP_VARS[pine_file])
    ]


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(prog="check_customer_surface_vocabulary").parse_args(argv)

    problems: list[str] = []
    for pine_file in PINE_FILES:
        found, population = input_leaks(pine_file)
        if population < MIN_INPUTS[pine_file]:
            problems.append(
                f"{pine_file}: only {population} customer-visible inputs parsed, "
                f"expected at least {MIN_INPUTS[pine_file]} — the parser broke, "
                "so a pass here would be vacuous"
            )
        problems.extend(found)

        found, labels = group_label_leaks(pine_file)
        if labels < MIN_GROUP_LABELS[pine_file]:
            problems.append(
                f"{pine_file}: only {labels} group labels parsed, expected at least "
                f"{MIN_GROUP_LABELS[pine_file]} — the parser broke, so a pass here "
                "would be vacuous"
            )
        problems.extend(found)

    problems.extend(spec_partition_disagreements())

    if problems:
        print(
            "::error::internal plumbing on a customer chart surface — this is what "
            "the library refresh reverted three times (#4646, #4665); see "
            "docs/commercial/PHASE2_CUSTOMER_PLANE.md",
            file=sys.stderr,
        )
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1

    print(
        f"customer surfaces clean: {len(PINE_FILES)} files, "
        f"{sum(MIN_INPUTS.values())}+ inputs and {sum(MIN_GROUP_LABELS.values())}+ "
        "group labels inspected"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
