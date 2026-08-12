"""scripts/check_pine_consumer_repin.py — der Bibliothekslauf darf an einer
Kundenoberfläche GENAU EINE Zeile ändern: den Import-Pin.

Warum es das braucht (Vorfall 2026-08-12, PR #4646 / Lauf 1192):

`smc-library-refresh` checkt `main` beim Start aus und läuft danach bis zu einem
Tag weiter — es wartet auf den TradingView-Publish. Am Ende committet es die
Consumer-`.pine` **vollständig** aus diesem tagealten Arbeitsbaum, aber auf
einen frischen Elternteil. Alles, was in der Zwischenzeit an diesen Dateien
gemergt wurde, steht damit im Commit als absichtliche Rücknahme.

Genau das ist passiert: #4639 hatte das Operator-Vokabular aus vier
Kundenoberflächen entfernt, Lauf 1192 hat es 59 Sekunden nach seinem eigenen
PR wieder eingesetzt — und niemand hat es gesehen, weil `bot/*`-PRs die
schweren Gates überspringen und automatisch mergen.

Der Fehler ist deshalb nicht „der Text ist falsch", sondern **„eine Änderung
ist unbemerkt durchgegangen"**. Dagegen hilft kein besserer Text, sondern eine
Behauptung, die der Lauf über sich selbst beweisen muss: an diesen Dateien
ändere ich die Pin-Zeile und sonst nichts. Trifft das nicht zu, bricht der Lauf
ab, statt still zurückzudrehen.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

#: Die Import-Zeile, die der Refresh umschreiben DARF.
PIN_LINE = re.compile(
    r"^import\s+preuss_steffen/smc_micro_profiles_generated/(\d+)\s+as\s+\w+\s*$"
)


def pin_only_violations(
    base_text: str, new_text: str, *, expected_version: str
) -> list[str]:
    """Was an dieser Datei geändert wurde, das KEIN Pin ist.

    Reine Funktion, damit sie prüfbar ist, ohne ein Git-Repository zu bauen —
    ein Wächter, den man nur im Vollbetrieb testen kann, wird nicht getestet.

    Leere Liste heißt: der Lauf hat sich an seine eigene Zusage gehalten.
    """
    base_lines = base_text.splitlines()
    new_lines = new_text.splitlines()

    if len(base_lines) != len(new_lines):
        return [
            f"line count changed: {len(base_lines)} -> {len(new_lines)}; "
            "a repin never adds or removes a line"
        ]

    violations: list[str] = []
    saw_pin = False
    for number, (before, after) in enumerate(zip(base_lines, new_lines), start=1):
        if before == after:
            # Auch eine UNVERÄNDERTE Pin-Zeile muss auf der Zielversion stehen:
            # sonst bliebe ein Consumer stillschweigend auf der alten Bibliothek
            # zurück, und genau dafür läuft der Schritt.
            match = PIN_LINE.match(after)
            if match:
                saw_pin = True
                if match.group(1) != expected_version:
                    violations.append(
                        f"line {number}: pin left at {match.group(1)}, "
                        f"expected {expected_version}"
                    )
            continue

        before_match = PIN_LINE.match(before)
        after_match = PIN_LINE.match(after)
        if before_match and after_match:
            saw_pin = True
            if after_match.group(1) != expected_version:
                violations.append(
                    f"line {number}: repinned to {after_match.group(1)}, "
                    f"expected {expected_version}"
                )
            continue

        violations.append(f"line {number}: changed, and it is not the library pin")

    if not saw_pin:
        violations.append("no library pin line found; this file is not a consumer")
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check_pine_consumer_repin")
    parser.add_argument(
        "--base-dir",
        required=True,
        type=Path,
        help="Verzeichnis mit den Vergleichsfassungen, die der Aufrufer aus dem "
        "AKTUELLEN main gelegt hat (`git show FETCH_HEAD:<datei>`) — nicht aus "
        "dem Checkout vom Laufbeginn. Das Lesen bleibt beim Aufrufer, damit "
        "dieses Skript keinen Prozess startet.",
    )
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("files", nargs="+")
    arguments = parser.parse_args(argv)

    failed = False
    for path in arguments.files:
        base_path = arguments.base_dir / path
        if not base_path.is_file():
            # Eine Datei, die es auf dem aktuellen Stand nicht gibt, ist neu —
            # dann gibt es nichts zurückzudrehen.
            print(f"::notice::{path} does not exist on main — new file")
            continue
        violations = pin_only_violations(
            base_path.read_text(encoding="utf-8"),
            Path(path).read_text(encoding="utf-8"),
            expected_version=arguments.expected_version,
        )
        if violations:
            failed = True
            print(
                f"::error file={path}::the library refresh changed more than the "
                f"library pin. It checked out main when the run started and may be "
                f"a day behind; committing this file whole would silently revert "
                f"whatever landed since. Findings:",
                file=sys.stderr,
            )
            for violation in violations:
                print(f"  {path}: {violation}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
