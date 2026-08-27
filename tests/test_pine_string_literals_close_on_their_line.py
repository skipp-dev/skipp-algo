"""Every single-line Pine string literal must close on its own code line (CE10017).

Born 2026-08-27 from a live operator report: ``SMC_Long_Dip_Alerts.pine`` line
46 carried a single-quoted tooltip containing the raw apostrophe in
``Suite's`` — the apostrophe terminated the literal early and the line's final
quote opened a string that never closed. TradingView's editor rejects exactly
this as CE10017 ("Missing enclosing character in the literal string ... on the
same code line"), so the SAVED consumer script stopped compiling on 2026-08-12
(#4639/#4650) while every repo-side check stayed green: the save chain compares
sha256 of the source text and never compiles it, and no CI step parses Pine.
Chart instances silently stayed pinned on the last compiling revision.

This test is the missing compile-shaped check for that failure class: it walks
EVERY ``.pine`` file in the repository (population, not a sample) and
simulates Pine's string lexing — backslash escapes, both quote styles, ``//``
comments outside strings, and ``\"\"\"…\"\"\"`` multiline templates. The
multiline form is NOT treated as an error: ``SMC_Long_Dip_Dashboard.pine``
has shipped one since April 2026 and that script saved, re-added and verified
64/64 bindings for months (run 32957051467, 2026-08-27) — live TradingView
accepts it, and a checker built on an older mental model of Pine flagged it
falsely on first run. A ``'…'`` / ``"…"`` literal left open at end of line is
exactly what TradingView refuses, so it fails here first. Since 2026-08-27 the
``validate`` shards are required on main (ADR-0012), so a plain test IS the
merge gate.
"""
from __future__ import annotations

from pathlib import Path

from tests._guard_corpus import iter_tracked_files

REPO_ROOT = Path(__file__).resolve().parents[1]

TRIPLE = '"""'


def _scan_file(text: str, rel: str, violations: list[str]) -> None:
    in_multiline = False
    for lineno, line in enumerate(text.splitlines(), start=1):
        i = 0
        in_single = False
        in_double = False
        escaped = False
        while i < len(line):
            ch = line[i]
            if in_multiline:
                if line[i : i + 3] == TRIPLE:
                    in_multiline = False
                    i += 3
                    continue
                i += 1
                continue
            if escaped:
                escaped = False
            elif ch == "\\" and (in_single or in_double):
                escaped = True
            elif in_single:
                if ch == "'":
                    in_single = False
            elif in_double:
                if ch == '"':
                    in_double = False
            elif line[i : i + 3] == TRIPLE:
                in_multiline = True
                i += 3
                continue
            elif ch == "/" and line[i : i + 2] == "//":
                break  # comment outside any string: rest of line is inert
            elif ch == "'":
                in_single = True
            elif ch == '"':
                in_double = True
            i += 1
        if in_single or in_double:
            delimiter = "'" if in_single else '"'
            violations.append(
                f"{rel}:{lineno} ends inside an open {delimiter}…{delimiter} "
                "literal (TradingView CE10017; an apostrophe inside a "
                "single-quoted string terminates it early — use double "
                "quotes or escape it)"
            )
    if in_multiline:
        violations.append(f'{rel}: file ends inside an open """…""" template')


def test_every_pine_string_literal_closes_on_its_line() -> None:
    pine_files = iter_tracked_files("*.pine", exclude_dirs=())
    assert len(pine_files) >= 12, (
        "population witness: the repo carries the 12 consumer sources alone; "
        f"the corpus found only {len(pine_files)} .pine files — an empty "
        "sweep would be a vacuous pass"
    )
    violations: list[str] = []
    for path in pine_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        _scan_file(text, str(path.relative_to(REPO_ROOT)), violations)
    assert violations == [], "\n".join(violations)


def test_the_checker_still_sees_the_alerts_defect() -> None:
    """Mutation guard: the exact line 46 shape must stay detectable.

    Without this, a later 'simplification' of the lexer could go blind to the
    very defect that motivated the file, and the population test above would
    pass vacuously on a healthy tree either way.
    """
    violations: list[str] = []
    _scan_file(
        "s = input.source(close, 'X', tooltip = 'the Suite's dropdown order.')",
        "synthetic.pine",
        violations,
    )
    assert len(violations) == 1 and "synthetic.pine:1" in violations[0]
    clean: list[str] = []
    _scan_file(
        's = input.source(close, "X", tooltip = "the Suite\'s dropdown order.")\n'
        'f = str.format("""a\nb {0}\nc""", 1)  // multiline template is legal\n'
        "g = 'don\\'t break on an escaped quote'",
        "synthetic.pine",
        clean,
    )
    assert clean == []
