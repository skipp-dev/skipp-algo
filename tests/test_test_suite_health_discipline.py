"""Test-suite health discipline pin.

Audit findings (skipp-algo, 2026-04-24):
  * 0 non-strict xfail decorators in the entire ``tests/`` tree.
  * Every skip / skipif marker carries a reason= argument.

This pin freezes that healthy state:

1. No xfail without strict=True. Non-strict xfail silently passes once
   a bug is fixed, hiding the green and accumulating confusion. Strict
   xfail is allowed (it forces the author to remove the marker when the
   underlying bug is resolved).

2. Every skip/skipif must have a non-empty reason= argument. Bare skips
   are review-hostile and tend to outlive the condition that justified
   them.

If you legitimately need a non-strict xfail (e.g. flaky platform-
dependent test), add the file path to _XFAIL_ALLOWLIST below with a
written justification.

2026-08-20: von Regex auf AST umgestellt, nachdem main 13 CI-Läufe lang rot
war. Die alte Textsuche kannte den Unterschied zwischen Code und Zeichenkette
nicht: ``assert "pytestmark = pytest.mark.skipif(" in source`` in
``tests/test_smc_strategy_mirror_deadline_tripwire.py`` (#4911) las sie als
echten Marker ohne ``reason=``. Gemessen über den ganzen Baum sah die Regex
40 Stellen, der AST 29 — die 11 Differenzen waren AUSNAHMSLOS Zeichenketten
und Kommentare in Wächter-Tests, die ihre eigenen verbotenen Formen
zitieren. Zehn davon blieben nur deshalb stumm, weil im selben Literal
zufällig ``reason=`` bzw. ``strict=True`` stand — sie waren dieselbe Bombe
mit längerer Zündschnur. Umgekehrt sah der AST keine Stelle, die die Regex
verpasste (0 Nur-AST-Treffer), die Umstellung kostet also keine Deckung.

Zwei stille Schwächen der Textsuche verschwinden mit ihr: das
12-Zeilen-Fenster sprach einen Marker ohne ``reason=`` frei, sobald ein
BENACHBARTER Dekorator eines trug, und diese Datei musste sich selbst vom
Scan ausnehmen, weil ihre eigene Prosa die verbotenen Formen nennt. Der AST
liest Prosa nicht — die Ausnahme ist ersatzlos entfallen, der Wächter
bewacht sich jetzt selbst.

Die Rückrichtung ist unten festgenagelt: ``test_a_marker_inside_a_string_
literal_is_not_a_marker`` und die drei Positivkontrollen daneben fahren
synthetische Dateien durch ``_iter_markers`` und verlangen beide Urteile.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = REPO_ROOT / "tests"

# Files allowed to use non-strict xfail. Empty by default — add entries
# only with a written justification.
_XFAIL_ALLOWLIST: frozenset[str] = frozenset()

_MARKERS = ("skip", "skipif", "xfail")

_SELF = Path(__file__).resolve()


def _python_test_files() -> list[Path]:
    return sorted(p for p in TESTS_DIR.rglob("test_*.py") if p.is_file())


def _marker_name(node: ast.expr) -> str:
    """``pytest.mark.skipif`` -> ``"skipif"``; anything else -> ``""``."""
    if not isinstance(node, ast.Attribute) or node.attr not in _MARKERS:
        return ""
    owner = node.value
    if not isinstance(owner, ast.Attribute) or owner.attr != "mark":
        return ""
    root = owner.value
    if not isinstance(root, ast.Name) or root.id != "pytest":
        return ""
    return node.attr


def _static_str(node: ast.expr) -> str:
    """Best-effort literal text of a str expression (handles implicit concat)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            v.value
            for v in node.values
            if isinstance(v, ast.Constant) and isinstance(v.value, str)
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _static_str(node.left) + _static_str(node.right)
    return ""


class _Marker(NamedTuple):
    line: int
    name: str
    reason: str
    strict: bool


def _iter_markers(path: Path):
    """Yield every ``pytest.mark.<skip|skipif|xfail>`` marker in ``path``.

    Ein SyntaxError wird bewusst NICHT geschluckt: eine nicht parsbare
    Testdatei bricht ohnehin die Sammlung, und ein stiller ``except`` würde
    genau die Datei unbeobachtet lassen, die am ehesten kaputt ist. Gemessen
    2026-08-20: 0 von 1702 ``test_*.py`` sind nicht parsbar.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    # Ein ast.Call trägt sein eigenes func-Attribute; ohne diese Menge würde
    # jeder aufgerufene Marker zusätzlich als "bare" Marker gemeldet.
    called = {id(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _marker_name(node.func)
            if not name:
                continue
            reason = ""
            strict = False
            for kw in node.keywords:
                if kw.arg == "reason":
                    reason = _static_str(kw.value)
                elif kw.arg == "strict":
                    strict = isinstance(kw.value, ast.Constant) and kw.value.value is True
            yield _Marker(node.lineno, name, reason, strict)
        elif isinstance(node, ast.Attribute) and id(node) not in called:
            name = _marker_name(node)
            if name:
                # Bare ``@pytest.mark.skip`` — no arguments at all, so no
                # reason and (for xfail) non-strict by default.
                yield _Marker(node.lineno, name, "", False)


def test_no_non_strict_xfail_in_test_suite() -> None:
    offenders: list[str] = []
    for path in _python_test_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in _XFAIL_ALLOWLIST:
            continue
        for marker in _iter_markers(path):
            if marker.name != "xfail" or marker.strict:
                continue
            offenders.append(f"{rel}:{marker.line}")
    assert not offenders, (
        "Found xfail decorator without strict=True in:\n  - "
        + "\n  - ".join(offenders)
        + "\n\nNon-strict xfail silently passes once the underlying bug is "
        "fixed, hiding the green. Either add strict=True (preferred) or "
        "add the file path to _XFAIL_ALLOWLIST in "
        f"{_SELF.name} with a written justification."
    )


def test_every_skip_marker_has_a_reason() -> None:
    offenders: list[str] = []
    for path in _python_test_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        for marker in _iter_markers(path):
            if marker.name not in ("skip", "skipif"):
                continue
            if marker.reason.strip():
                continue
            offenders.append(f"{rel}:{marker.line} ({marker.name})")
    assert not offenders, (
        "Found skip/skipif marker without an explicit non-empty reason= in:\n  - "
        + "\n  - ".join(offenders)
        + "\n\nEvery skip must explain why it is skipped so reviewers can "
        "tell whether the condition still applies. ``reason=\"\"``, "
        "``reason=''`` and ``reason=None`` do NOT satisfy this pin."
    )


# --- Der Wächter über dem Wächter ------------------------------------------
# Die beiden Tests oben sind über dem heutigen Baum GRÜN. Grün heißt hier aber
# nur "nichts gefunden" — es beweist nicht, dass sie noch etwas finden KÖNNEN.
# Die vier Proben unten fahren synthetische Dateien durch ``_iter_markers`` und
# verlangen beide Urteile: die Zeichenkette darf nicht zünden, der echte
# Verstoß muss es.


def _markers_of(tmp_path: Path, source: str) -> list[_Marker]:
    probe = tmp_path / "test_probe.py"
    probe.write_text(source, encoding="utf-8")
    return list(_iter_markers(probe))


def test_a_marker_inside_a_string_literal_is_not_a_marker(tmp_path: Path) -> None:
    """Der Fehler, der main am 2026-08-20 rot machte, wörtlich nachgestellt."""
    markers = _markers_of(
        tmp_path,
        'def test_x():\n'
        '    assert "pytestmark = pytest.mark.skipif(" in source, (\n'
        '        "der Spiegel traegt den erwarteten Modul-skipif nicht mehr"\n'
        '    )\n'
        '# auch als Kommentar: pytest.mark.skip(\n',
    )
    assert markers == [], (
        f"eine Zeichenkette/ein Kommentar wurde als Marker gelesen: {markers} — "
        "genau dieser Fehlalarm hielt main 13 CI-Laeufe lang rot"
    )


def test_a_module_level_marker_without_a_reason_is_still_caught(tmp_path: Path) -> None:
    """Positivkontrolle: die Form, für die _PYTESTMARK_CALL_RE gebaut wurde."""
    markers = _markers_of(tmp_path, "import pytest\npytestmark = pytest.mark.skipif(True)\n")
    assert [(m.name, m.reason) for m in markers] == [("skipif", "")], (
        f"ein Modul-skipif ohne reason= wird nicht mehr gesehen: {markers}"
    )


def test_a_bare_decorator_is_still_caught(tmp_path: Path) -> None:
    """Positivkontrolle: ``@pytest.mark.skip`` ganz ohne Klammern."""
    markers = _markers_of(
        tmp_path, "import pytest\n\n\n@pytest.mark.skip\ndef test_x():\n    pass\n"
    )
    assert [(m.name, m.reason) for m in markers] == [("skip", "")], (
        f"ein blanker Dekorator ohne reason= wird nicht mehr gesehen: {markers}"
    )


def test_a_neighbouring_reason_no_longer_acquits(tmp_path: Path) -> None:
    """Positivkontrolle gegen die alte Falsch-Negativ-Seite der Textsuche.

    Das 12-Zeilen-Fenster sprach einen Marker frei, sobald irgendwo darunter
    ``reason=`` stand — auch wenn es zum NÄCHSTEN Dekorator gehörte.
    """
    markers = _markers_of(
        tmp_path,
        "import pytest\n\n\n"
        "@pytest.mark.skipif(True)\n"
        "def test_x():\n    pass\n\n\n"
        '@pytest.mark.skipif(True, reason="echt begruendet")\n'
        "def test_y():\n    pass\n",
    )
    without_reason = [m for m in markers if not m.reason.strip()]
    assert len(without_reason) == 1, (
        f"der reason= des Nachbarn spricht den Verstoss immer noch frei: {markers}"
    )


def test_a_non_strict_xfail_is_still_caught(tmp_path: Path) -> None:
    """Positivkontrolle für den zweiten Test dieser Datei."""
    markers = _markers_of(
        tmp_path,
        'import pytest\n\n\n@pytest.mark.xfail(reason="x")\ndef test_x():\n    pass\n',
    )
    assert [(m.name, m.strict) for m in markers] == [("xfail", False)], (
        f"ein nicht-strikter xfail wird nicht mehr gesehen: {markers}"
    )
