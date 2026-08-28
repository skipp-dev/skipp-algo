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
    # 2026-08-28: population grown from the four incident surfaces to every
    # onboarding consumer the Chart-Link rename (#4639) could reach — it had
    # reached only three of seven, and no guard watched the other surfaces a
    # customer can open. The internal sets are each file's BUS binding groups
    # (input TITLES in them are the frozen 64-channel binding contract).
    # SMC_Exit_Signal.pine stays OUT: it is R1-attested (hash frozen against
    # the registered rollout evidence), so its rename — and with it the one
    # rendered "BUS" table cell it still paints — must ride the next mutating
    # TradingView re-attestation session. SMC_Hold_Manager.pine stays OUT for
    # the sibling reason: its shadow lane's deployed receiver rejects any
    # build other than contract.source.build (the live alerts emit build 3),
    # so its rename must ride the lane's next build-advance sitting. Both
    # exceptions carry tripwires in tests/test_customer_surface_vocabulary.py.
    "SMC_Setup_Check.pine": frozenset({"g_bus"}),
    "SMC_Breakout_Overlay.pine": frozenset({"g_bus"}),
    "SMC_Confluence_Hub.pine": frozenset({"g_bus"}),
    "SMC_Long_Dip_Strategy.pine": frozenset({"g_bus_entry", "g_bus_plan"}),
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
    # 2026-08-28, measured after the Chart-Link rename. Setup Check is honest
    # 0: its ONLY inputs are the six binding rows in the internal group.
    "SMC_Setup_Check.pine": 0,
    "SMC_Breakout_Overlay.pine": 23,
    "SMC_Confluence_Hub.pine": 11,
    "SMC_Long_Dip_Strategy.pine": 8,
}

# Same, for settings-group labels. Cross-checked 2026-08-12 against
# `grep -cE "^\s*(var\s+)?(string\s+)?g_[a-z_0-9]+\s*="`: 26/12/3/3, identical.
MIN_GROUP_LABELS: dict[str, int] = {
    "SMC_Long_Dip_Dashboard.pine": 12,
    "SMC_Long_Dip_Mobile.pine": 3,
    "SMC_Long_Dip_Alerts.pine": 3,
    "SMC_Long_Dip_Suite.pine": 26,
    # 2026-08-28, measured after the Chart-Link rename.
    "SMC_Setup_Check.pine": 1,
    "SMC_Breakout_Overlay.pine": 7,
    "SMC_Confluence_Hub.pine": 6,
    "SMC_Long_Dip_Strategy.pine": 5,
}

# Same, for RENDERED chart strings (third population arm, 2026-08-28): string
# literals inside `table.cell(...)` / `label.new(...)` statements — multi-line
# concatenations joined by paren balance — plus literals in assignments to
# variables those statements (or derived render wrappers such as the
# Dashboard's `dashboard_row_tt`) consume directly. Measured 2026-08-28 and
# pinned at the measured value. Deliberately NOT chased: `plot()`/input TITLES
# (the frozen binding contract), strings returned by helper functions, and
# var-to-var flow deeper than one assignment level.
MIN_RENDERED: dict[str, int] = {
    "SMC_Long_Dip_Dashboard.pine": 562,
    "SMC_Long_Dip_Mobile.pine": 54,
    "SMC_Long_Dip_Alerts.pine": 3,
    "SMC_Long_Dip_Suite.pine": 23,
    # 2026-08-28, measured after the Chart-Link rename.
    "SMC_Setup_Check.pine": 52,
    "SMC_Breakout_Overlay.pine": 20,
    "SMC_Confluence_Hub.pine": 40,
    "SMC_Long_Dip_Strategy.pine": 28,
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
# Pine-korrekt seit 2026-08-28 (dieselbe Klasse wie beim Tooltip darunter):
# das ÄUSSERE Delimiter bestimmt das Ende. Die alte Zeichenklasse schloss
# BEIDE Quotezeichen aus, also beendete ein eingebettetes Anführungszeichen
# des jeweils anderen Typs den Titel-Capture — der Schwanz shippte ungeprüft.
_TITLE_RE = re.compile(
    r"""input(?:\.\w+)?\(\s*(?:[^,]*,\s*)?(?P<q>["'])(?P<t>(?:\\.|(?!(?P=q))[^\\]){2,})(?P=q)"""
)
# Pine-korrekt seit 2026-08-28: das ÄUSSERE Delimiter bestimmt das Ende. Die
# alte Zeichenklasse schloss BEIDE Quotezeichen aus, also beendete ein
# eingebettetes Anführungszeichen des jeweils anderen Typs den Capture — 13 von
# 90 Tooltips wurden trunkiert und ihr Schwanz shippte ungeprüft.
_TOOLTIP_RE = re.compile(
    r"""\btooltip\s*=\s*(?P<q>["'])(?P<t>(?:\\.|(?!(?P=q))[^\\])*)(?P=q)"""
)
# All three declaration styles in the tree: `var string g_x = "..."` (Dashboard),
# `var g_x = '...'` (Suite) and a bare `g_x = '...'` (Alerts). Missing one of them
# silently shrinks the population — the Suite alone declares its groups as `var
# g_x` and a `var string`-only pattern saw 1 of its 40 labels. When the Hold
# Manager joins the population (its lane's next build sitting), the variable
# arm must learn its camelCase family (`gBus`, `gSource`, ...) — a `g_`-only
# pattern sees 0 of its 6 labels.
_GROUP_DEF_RE = re.compile(
    r"""^\s*(?:var\s+)?(?:string\s+)?(?P<var>g_\w+)\s*=\s*["'](?P<label>[^"']+)["']\s*$"""
)

PINE_FILES = sorted(INTERNAL_GROUP_VARS)


def leaks(text: str) -> list[str]:
    for term in ALLOWED_TERMS:
        text = text.replace(term, "")
    # Pine-Escapes sind im Quelltext ZWEI Zeichen: das literale `\n` vor
    # `Plan 1.4` ließ `\bPlan` nie feuern, weil `n` ein Wortzeichen ist
    # (Live-Fall min_htf_alignment_count, 2026-08-28). Vor dem Mustermatch
    # werden `\n`/`\t` deshalb zu Leerzeichen normalisiert.
    text = text.replace("\\n", " ").replace("\\t", " ")
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


# --- Dritter Populations-Arm (2026-08-28): gerenderte Chart-Strings ---------
# Input-Deklarationen und Gruppen-Labels waren die einzige Population; die
# Strings, die TradingView tatsächlich AUF DEN CHART malt (table.cell- und
# label.new-Texte, auch mehrzeilig konkateniert), sah der Wächter nie — dort
# lebten die Mobile-Fallback-Zeile, die Dashboard-Versionswarnung und der
# Hero-Tooltip. Ein einfach-/doppelt-quotierter Pine-String endet nie auf der
# Folgezeile (tests/test_pine_string_literals_close_on_their_line.py), deshalb
# reicht ein zeilenweiser Scanner mit Quote-Zustand pro Zeile. Die
# `\"\"\"`-Multiline-Templates (Dashboard-Tooltips) landen über das
# Statement-Joining trotzdem als EIN Literal in der Population — die leeren
# ""-Artefakte davor sind harmlos.

# Ein String-Literal: das ÖFFNENDE Delimiter bestimmt das Ende; Escapes des
# anderen Quotes (\' bzw. \") bleiben Teil des Literals.
_STRING_LITERAL_RE = re.compile(
    r"""(?P<q>["'])(?P<t>(?:\\.|(?!(?P=q))[^\\])*)(?P=q)"""
)
_FUNC_DEF_RE = re.compile(r"^(?P<name>[A-Za-z_]\w*)\(")
_ASSIGN_RE = re.compile(
    r"^\s*(?:var\s+)?(?:(?:string|bool|int|float|color|label|table|box|line)\s+)?"
    r"(?P<name>[A-Za-z_]\w*)\s*:?=(?!=)\s*(?P<rhs>.*)$"
)
_RENDER_SINK_ROOTS = ("table.cell", "label.new")


def _code_and_paren_delta(line: str) -> tuple[str, int]:
    """Zeile ohne `//`-Kommentar plus Klammer-Saldo AUSSERHALB von Strings."""
    out: list[str] = []
    delta = 0
    quote = ""
    index = 0
    while index < len(line):
        char = line[index]
        if quote:
            if char == "\\":
                out.append(line[index : index + 2])
                index += 2
                continue
            out.append(char)
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
            out.append(char)
        elif char == "/" and line.startswith("//", index):
            break
        else:
            if char == "(":
                delta += 1
            elif char == ")":
                delta -= 1
            out.append(char)
        index += 1
    return "".join(out), delta


def _statements(scanned: list[tuple[str, int]]) -> list[tuple[int, str]]:
    """Mehrzeilige Aufrufe per Klammer-Saldo zu EINEM Statement zusammenziehen.

    Genau die Mechanik, an der die Dashboard-Versionswarnung (label.new über
    fünf Zeilen) und die Hero-Konkatenationen vorher unsichtbar waren.
    """
    statements: list[tuple[int, str]] = []
    parts: list[str] = []
    start = 0
    depth = 0
    for lineno, (code, delta) in enumerate(scanned, 1):
        if not parts:
            if not code.strip():
                continue
            start = lineno
            parts = [code]
        else:
            parts.append(code.strip())
        depth += delta
        if depth <= 0:
            statements.append((start, " ".join(parts)))
            parts = []
            depth = 0
    if parts:
        statements.append((start, " ".join(parts)))
    return statements


def _render_wrapper_names(code_lines: list[str]) -> set[str]:
    """Render-Sinks ABLEITEN statt hartkodieren: table.cell/label.new plus jede
    Funktion, deren Rumpf (transitiv, Fixpunkt) einen Sink erreicht — im
    Dashboard z. B. `dashboard_row` -> `dashboard_row_tt` -> `section_row`."""
    bodies: dict[str, list[str]] = {}
    current: str | None = None
    for line in code_lines:
        if not line.strip():
            continue
        if not line[0].isspace():
            match = _FUNC_DEF_RE.match(line)
            current = match.group("name") if match and "=>" in line else None
            continue
        if current is not None:
            bodies.setdefault(current, []).append(line)
    sinks = set(_RENDER_SINK_ROOTS)
    changed = True
    while changed:
        changed = False
        for name, body in bodies.items():
            if name in sinks:
                continue
            text = "\n".join(body)
            if any(
                re.search(rf"(?<![.\w]){re.escape(sink)}\(", text) for sink in sinks
            ):
                sinks.add(name)
                changed = True
    return sinks


def _sink_argument_names(code: str) -> set[str]:
    """Variablen, die ein Sink-Statement konsumiert (eine Zuweisungs-Ebene)."""
    code = _STRING_LITERAL_RE.sub(" ", code)
    names: set[str] = set()
    for match in re.finditer(r"[A-Za-z_]\w*", code):
        start, end = match.span()
        if start and code[start - 1] == ".":
            continue  # Attributzugriff (label.style_label_down)
        tail = code[end:].lstrip()
        if tail.startswith(("(", ".")):
            continue  # Funktionsaufruf oder Namespace
        if tail.startswith("=") and not tail.startswith("=="):
            continue  # Keyword-Argument-NAME (bgcolor = ...)
        names.add(match.group())
    return names


def rendered_string_leaks(pine_file: str) -> tuple[list[str], int]:
    """Fundstellen und die GRÖSSE der geprüften Menge gerenderter Literale.

    Bewusst NICHT verfolgt (im Namen ehrlich bleiben): `plot()`- und
    Input-TITEL (der eingefrorene Binding-Contract), Rückgaben von
    Hilfsfunktionen sowie Variable-zu-Variable-Fluss tiefer als eine
    Zuweisungs-Ebene.
    """
    scanned = [_code_and_paren_delta(line) for line in read_lines(pine_file)]
    statements = _statements(scanned)
    sinks = _render_wrapper_names([code for code, _ in scanned])
    sink_re = re.compile(
        "|".join(rf"(?<![.\w]){re.escape(sink)}\(" for sink in sorted(sinks))
    )

    rendered: list[tuple[int, str]] = []
    argument_names: set[str] = set()
    sink_linenos: set[int] = set()
    for lineno, code in statements:
        if _FUNC_DEF_RE.match(code) and code.rstrip().endswith("=>"):
            continue  # Funktions-SIGNATUR, kein Aufruf
        if not sink_re.search(code):
            continue
        sink_linenos.add(lineno)
        rendered.extend((lineno, literal) for literal in _string_literals(code))
        argument_names |= _sink_argument_names(code)

    for lineno, code in statements:
        if lineno in sink_linenos:
            continue
        if _INPUT_RE.match(code.strip()):
            # Input-Deklarationen sind die Population des ERSTEN Arms; ihre
            # TITEL in internen Gruppen sind der eingefrorene Binding-Contract
            # und bleiben bewusst draußen. Ohne diesen Filter zöge die
            # Variablen-Verfolgung z. B. `src_bus_schema_version` (Argument der
            # Versionswarnung) samt seinem "BUS SchemaVersion"-Titel herein.
            continue
        match = _ASSIGN_RE.match(code)
        if not match or match.group("name") not in argument_names:
            continue
        rendered.extend(
            (lineno, literal) for literal in _string_literals(match.group("rhs"))
        )

    found = [
        f"{pine_file}:{lineno} rendered {literal[:60]!r} -> {leak}"
        for lineno, literal in rendered
        for leak in leaks(literal)
    ]
    return found, len(rendered)


def _string_literals(code: str) -> list[str]:
    return [match.group("t") for match in _STRING_LITERAL_RE.finditer(code)]


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

        found, rendered = rendered_string_leaks(pine_file)
        if rendered < MIN_RENDERED[pine_file]:
            problems.append(
                f"{pine_file}: only {rendered} rendered chart strings parsed, "
                f"expected at least {MIN_RENDERED[pine_file]} — the parser broke, "
                "so a pass here would be vacuous"
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
        f"{sum(MIN_INPUTS.values())}+ inputs, {sum(MIN_GROUP_LABELS.values())}+ "
        f"group labels and {sum(MIN_RENDERED.values())}+ rendered chart strings "
        "inspected"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
