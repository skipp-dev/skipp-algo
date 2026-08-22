"""Wächter für die hash-gebundenen Skill-Scanner-Mutes.

Arbeitsteilung, damit keine Hälfte für die andere gehalten wird:

* **Hier (CI)** wird der *Vertrag* geprüft — Registry-Schema, und dass
  ``audit_skill_mutes`` jeden Verstoß tatsächlich findet. Die realen Pfade aus
  der Registry liegen unter ``~/.codex/…`` und existieren auf einem Runner
  nicht; ihre Hashes können hier also nicht nachgerechnet werden.
* **Auf der Maschine** prüft der SessionStart-Hook
  ``~/.claude/hooks/skill-mute-drift-warn.sh`` den *Ist-Zustand* bei jeder
  Sitzung, gegen die echte ``settings.json`` und die echten Skill-Bäume.

Die Tests unten sind bewusst als Positivkontrollen gebaut: für jede
Befund-Klasse wird der Defekt synthetisch hergestellt und das Finden verlangt.
Ein Audit, das nur auf einem sauberen Baum grün ist, hat nichts bewiesen —
`absent()` ohne Kontrolle war die teuerste wiederkehrende Fehlklasse hier.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from scripts.audit_skill_mutes import (
    ProbeInvalidError,
    audit,
    load_allowlist,
    load_registry,
    tree_sha256,
)

REPO = Path(__file__).resolve().parent.parent
REGISTRY = REPO / "configs" / "skill_mute_registry.json"
REQUIRED_FIELDS = ("path", "sha256", "granted", "owner", "covers", "reason")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@pytest.fixture(scope="module")
def registry() -> list[dict]:
    return load_registry(REGISTRY)


# --------------------------------------------------------------------------
# Vertrag der Registry
# --------------------------------------------------------------------------


def test_registry_is_not_empty(registry: list[dict]) -> None:
    """Leer wäre kein Erfolg, sondern eine Registry, die nichts bindet."""
    assert registry, "configs/skill_mute_registry.json enthält keinen Mute"


def test_every_mute_carries_the_full_contract(registry: list[dict]) -> None:
    for mute in registry:
        missing = [f for f in REQUIRED_FIELDS if not mute.get(f)]
        assert not missing, f"{mute.get('path', '<ohne Pfad>')}: fehlende Felder {missing}"
        assert _SHA256.match(mute["sha256"]), f"{mute['path']}: sha256 ist kein 64-stelliger Hex-Wert"
        assert _ISO_DAY.match(mute["granted"]), f"{mute['path']}: 'granted' ist kein ISO-Datum"
        assert Path(mute["path"]).is_absolute(), f"{mute['path']}: Pfad muss absolut sein"
        assert isinstance(mute["covers"], list) and mute["covers"], f"{mute['path']}: 'covers' ist leer"


def test_reasons_are_specific_enough_to_re_check(registry: list[dict]) -> None:
    """Ein Grund, den niemand nachprüfen kann, ist kein Grund.

    Die Schwelle ist absichtlich niedrig und rein mechanisch — sie fängt den
    Fall „FP" oder „harmlos" als Begründung, nicht schlechte Prosa.
    """
    for mute in registry:
        assert len(mute["reason"]) >= 80, f"{mute['path']}: Begründung ist zu knapp, um sie nachzuprüfen"


def test_no_duplicate_paths(registry: list[dict]) -> None:
    paths = [m["path"] for m in registry]
    assert len(paths) == len(set(paths)), "derselbe Pfad steht mehrfach in der Registry"


# --------------------------------------------------------------------------
# tree_sha256 — bindet der Hash wirklich den Inhalt?
# --------------------------------------------------------------------------


def _skill(tmp_path: Path, name: str = "demo") -> Path:
    root = tmp_path / name
    (root / "scripts").mkdir(parents=True)
    (root / "SKILL.md").write_text("---\nname: demo\n---\n", encoding="utf-8")
    (root / "scripts" / "run.py").write_text("print('hi')\n", encoding="utf-8")
    return root


def test_hash_is_stable_across_calls(tmp_path: Path) -> None:
    root = _skill(tmp_path)
    assert tree_sha256(root) == tree_sha256(root)


def test_hash_changes_when_a_file_changes(tmp_path: Path) -> None:
    root = _skill(tmp_path)
    before = tree_sha256(root)
    (root / "scripts" / "run.py").write_text("print('hi')  # harmlos?\n", encoding="utf-8")
    assert tree_sha256(root) != before


def test_hash_changes_when_a_file_is_added(tmp_path: Path) -> None:
    """Der gefährliche Fall: nichts Bestehendes wird angefasst, es kommt etwas dazu."""
    root = _skill(tmp_path)
    before = tree_sha256(root)
    (root / "scripts" / "extra.py").write_text("import os\n", encoding="utf-8")
    assert tree_sha256(root) != before


def test_hash_changes_when_a_symlink_is_repointed(tmp_path: Path) -> None:
    """Ein Symlink geht mit seinem ZIEL-Pfad ein, nicht mit dessen Inhalt."""
    root = _skill(tmp_path)
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("a\n", encoding="utf-8")
    link = root / "link"
    link.symlink_to(tmp_path / "a.txt")
    before = tree_sha256(root)
    link.unlink()
    link.symlink_to(tmp_path / "b.txt")
    assert tree_sha256(root) != before


def test_hash_covers_bytecode_and_dotfiles(tmp_path: Path) -> None:
    """Nichts wird ausgeschlossen — eine bösartige Ergänzung kann überall stecken."""
    root = _skill(tmp_path)
    before = tree_sha256(root)
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "x.cpython-312.pyc").write_bytes(b"\x00\x01")
    assert tree_sha256(root) != before
    mid = tree_sha256(root)
    (root / ".hidden").write_text("x\n", encoding="utf-8")
    assert tree_sha256(root) != mid


# --------------------------------------------------------------------------
# audit() — jede Befund-Klasse als Positivkontrolle
# --------------------------------------------------------------------------


def _mute(root: Path) -> dict:
    return {"path": str(root), "sha256": tree_sha256(root), "granted": "2026-08-22"}


def test_clean_state_yields_no_findings(tmp_path: Path) -> None:
    root = _skill(tmp_path)
    assert audit([_mute(root)], [str(root)]) == []


def test_drift_is_found(tmp_path: Path) -> None:
    root = _skill(tmp_path)
    mute = _mute(root)
    (root / "scripts" / "run.py").write_text("import socket\n", encoding="utf-8")
    findings = audit([mute], [str(root)])
    assert len(findings) == 1
    assert "DRIFT" in findings[0]


def test_mute_without_registry_entry_is_found(tmp_path: Path) -> None:
    root = _skill(tmp_path)
    findings = audit([], [str(root)])
    assert len(findings) == 1
    assert "UNBEGRUENDET" in findings[0]


def test_registry_entry_without_mute_is_found(tmp_path: Path) -> None:
    root = _skill(tmp_path)
    findings = audit([_mute(root)], [])
    assert len(findings) == 1
    assert "TOTER EINTRAG" in findings[0]


def test_vanished_path_is_found(tmp_path: Path) -> None:
    """Bewusst ``shutil.rmtree`` statt eines eigenen ``rglob``-Laufs.

    Der Budget-Wächter für baumwandernde Tests zählt jede Testdatei, die
    ``.rglob(...)`` aufruft — er sieht den Aufruf, nicht seinen Gegenstand. Ein
    Lauf über ``tmp_path`` würde das Budget verbrauchen, ohne dass hier
    tatsächlich ein Arbeitsbaum abgelaufen wird.

    Der Wächter wird hier absichtlich nicht beim Modulnamen genannt: ein
    zweiter Wächter im selben Bereich erkennt seine Nutzer per Substring über
    den Dateitext, und ein erklärender Satz würde diese Datei fälschlich zu
    einem repo-weiten Quell-Guard machen. Beide Fehlschläge sind am 2026-08-22
    eingetreten, nacheinander, an genau dieser Stelle.
    """
    root = _skill(tmp_path)
    mute = _mute(root)
    shutil.rmtree(root)
    findings = audit([mute], [str(root)])
    assert len(findings) == 1
    assert "TOTER EINTRAG" in findings[0]


# --------------------------------------------------------------------------
# Fail-closed: eine Sonde, die nicht messen kann, ist nicht "in Ordnung"
# --------------------------------------------------------------------------


def test_missing_registry_raises_instead_of_reporting_clean(tmp_path: Path) -> None:
    with pytest.raises(ProbeInvalidError):
        load_registry(tmp_path / "gibtsnicht.json")


def test_broken_registry_raises_instead_of_reporting_clean(tmp_path: Path) -> None:
    broken = tmp_path / "registry.json"
    broken.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ProbeInvalidError):
        load_registry(broken)


def test_missing_settings_raises_instead_of_reporting_clean(tmp_path: Path) -> None:
    with pytest.raises(ProbeInvalidError):
        load_allowlist(tmp_path / "settings.json")


def test_jsonc_comments_are_stripped_but_urls_survive(tmp_path: Path) -> None:
    """VS Code liest JSONC. Ein naiver `//`-Filter frisst `https://…` mit."""
    settings = tmp_path / "settings.json"
    settings.write_text(
        '{\n  // ein Kommentar\n  "homepage": "https://example.com/x",\n'
        '  "mcp-scanner.allowlist.skills": ["/a"]\n}\n',
        encoding="utf-8",
    )
    assert load_allowlist(settings) == ["/a"]
    assert json.loads(settings.read_text(encoding="utf-8").replace("// ein Kommentar", ""))["homepage"].startswith(
        "https://"
    )
