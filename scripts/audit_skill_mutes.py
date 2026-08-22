#!/usr/bin/env python3
"""Prüft, ob die pfadweisen Skill-Scanner-Mutes noch das sind, was geprüft wurde.

Hintergrund (2026-08-22, PR #5001)
==================================

Der Cisco AI Security Scanner kennt nur einen pfadweisen, **ganz-Skill**-Mute
(``mcp-scanner.allowlist.skills``). Ein Eintrag dort blendet auch jeden
*künftigen* Befund in diesem Skill aus — und er hat weder Verfall noch Bindung
an den Inhalt. Genau die Pfade, die man so stummschaltet, sind Fremdcode, den
ein Vendor-Update jederzeit austauscht: ``~/.codex/skills/.system/`` wird von
Codex bei jedem Update neu installiert.

Ein Satz wie „bei einem Update erneut prüfen" ist an dieser Stelle wertlos —
nichts liest ihn zum richtigen Zeitpunkt. Dieses Skript ist der Mechanismus
stattdessen: jeder Mute trägt in ``configs/skill_mute_registry.json`` den
sha256 des Skill-Baums, wie er zum Zeitpunkt der Freigabe geprüft wurde.
Ändert sich auch nur ein Byte, verliert der Mute seine Grundlage und das hier
wird laut.

Aufruf
------

::

    python3 scripts/audit_skill_mutes.py               # prüfen
    python3 scripts/audit_skill_mutes.py --print-hash <pfad>

Es gibt bewusst **kein** ``--bless``/``--update``. Ein Mute neu zu erteilen
heißt, den Fremdcode erneut zu lesen; ein Ein-Befehl-Neusegen würde genau den
Schritt wegautomatisieren, für den es das Skript gibt. Der Hash wird gedruckt
und von Hand in die Registry übernommen.

Exit-Codes
----------

* ``0`` — jeder Mute ist begründet, existiert und ist unverändert.
* ``3`` — Befund: Drift, unbegründeter Mute, oder toter Registry-Eintrag.
* ``9`` — Sonde ungültig (Registry oder settings.json unlesbar).

``9`` ist bewusst von ``0`` getrennt: eine Sonde, die ihre Eingabe nicht lesen
kann, hat nichts gemessen. Sie darf nicht wie „alles in Ordnung" aussehen.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REGISTRY_PATH = REPO / "configs" / "skill_mute_registry.json"
SETTINGS_PATH = Path.home() / "Library" / "Application Support" / "Code" / "User" / "settings.json"
ALLOWLIST_KEY = "mcp-scanner.allowlist.skills"

# VS Code liest settings.json als JSONC. Nur ganze Kommentarzeilen entfernen —
# ein `//` mitten in einem String (etwa "https://…") darf nicht angetastet werden.
_LINE_COMMENT = re.compile(r"^\s*//.*$", re.MULTILINE)


class ProbeInvalidError(RuntimeError):
    """Die Sonde konnte nicht messen — Exit 9, niemals Exit 0."""


def tree_sha256(root: Path) -> str:
    """Deterministischer Hash über den gesamten Skill-Baum.

    Es wird bewusst NICHTS ausgeschlossen: eine bösartige Ergänzung kann in
    jeder Datei stecken, auch in einer ``.pyc`` oder einer Punktdatei. Ein
    Symlink geht mit seinem Ziel-*Pfad* ein, nicht mit dessen Inhalt — sonst
    verändert eine Umbiegung nach außen den Hash nicht.
    """
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda p: p.relative_to(root).as_posix()):
        rel = path.relative_to(root).as_posix().encode()
        if path.is_symlink():
            digest.update(b"L\0" + rel + b"\0" + str(path.readlink()).encode() + b"\0")
        elif path.is_dir():
            digest.update(b"D\0" + rel + b"\0")
        elif path.is_file():
            digest.update(b"F\0" + rel + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def load_registry(path: Path = REGISTRY_PATH) -> list[dict]:
    if not path.is_file():
        raise ProbeInvalidError(f"Registry fehlt: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProbeInvalidError(f"Registry ist kein gültiges JSON: {exc}") from exc
    mutes = data.get("mutes")
    if not isinstance(mutes, list):
        raise ProbeInvalidError("Registry hat kein 'mutes'-Array")
    return mutes


def load_allowlist(path: Path = SETTINGS_PATH) -> list[str]:
    if not path.is_file():
        raise ProbeInvalidError(f"settings.json fehlt: {path}")
    try:
        data = json.loads(_LINE_COMMENT.sub("", path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as exc:
        raise ProbeInvalidError(f"settings.json nicht parsebar: {exc}") from exc
    entries = data.get(ALLOWLIST_KEY, [])
    if not isinstance(entries, list):
        raise ProbeInvalidError(f"{ALLOWLIST_KEY} ist keine Liste")
    return [str(e) for e in entries]


def audit(mutes: list[dict], allowlist: list[str]) -> list[str]:
    """Gibt die Befunde zurück. Leere Liste = jeder Mute trägt noch."""
    findings: list[str] = []
    registered = {m.get("path") for m in mutes}

    for entry in allowlist:
        if entry not in registered:
            findings.append(
                f"UNBEGRUENDET: '{entry}' ist stummgeschaltet, steht aber nicht in "
                f"{REGISTRY_PATH.name}. Jeder Mute braucht dort Grund, Datum und Hash."
            )

    for mute in mutes:
        path_str = mute.get("path", "")
        target = Path(path_str)
        if path_str not in allowlist:
            findings.append(f"TOTER EINTRAG: '{path_str}' steht in der Registry, ist aber nicht stummgeschaltet.")
            continue
        if not target.is_dir():
            findings.append(f"TOTER EINTRAG: '{path_str}' existiert nicht mehr — Mute und Registry-Zeile entfernen.")
            continue
        actual = tree_sha256(target)
        expected = mute.get("sha256", "")
        if actual != expected:
            findings.append(
                f"DRIFT: '{path_str}' hat sich seit der Freigabe am {mute.get('granted', '?')} geändert.\n"
                f"        erwartet {expected[:16]}… · jetzt {actual[:16]}…\n"
                f"        Der Mute deckt eine Fassung ab, die es nicht mehr gibt. Fremdcode erneut lesen, "
                f"dann den neuen Hash via --print-hash uebernehmen."
            )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--print-hash", metavar="PFAD", help="sha256 eines Skill-Baums drucken (fuer die Registry)")
    parser.add_argument("--quiet", action="store_true", help="bei 0 Befunden nichts ausgeben (fuer Hooks)")
    args = parser.parse_args()

    if args.print_hash:
        target = Path(args.print_hash).expanduser()
        if not target.is_dir():
            print(f"kein Verzeichnis: {target}", file=sys.stderr)
            return 9
        print(tree_sha256(target))
        return 0

    try:
        findings = audit(load_registry(), load_allowlist())
    except ProbeInvalidError as exc:
        print(f"SONDE UNGUELTIG: {exc}", file=sys.stderr)
        return 9

    if not findings:
        if not args.quiet:
            print("Skill-Mutes: alle begruendet, vorhanden und unveraendert.")
        return 0

    print("Skill-Mute-Audit — Befunde:", file=sys.stderr)
    for finding in findings:
        print(f"  - {finding}", file=sys.stderr)
    return 3


if __name__ == "__main__":
    sys.exit(main())
