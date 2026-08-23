"""Schema- und Disziplin-Tests fuer proof_ledger.toml."""

from __future__ import annotations

import datetime as dt

import pytest

from scripts.proof_ledger import (
    MERGE_STATES,
    ProofLedgerError,
    class_floors,
    declared_unreachable_branches,
    load_entries,
)


def test_every_entry_carries_owner_deadline_and_a_known_state():
    for entry in load_entries():
        assert entry.state in MERGE_STATES, entry.id
        assert entry.owner, entry.id
        dt.date.fromisoformat(entry.due_by)


def test_a_fix_entry_names_its_witness_and_version_probe():
    """Ohne Zeuge und Versionsprobe ist ein Urteil nicht zurechenbar."""
    fixes = [e for e in load_entries() if e.kind == "fix"]
    assert fixes, "Ledger ohne fix-Eintrag — Positivkontrolle leer"
    for entry in fixes:
        assert entry.witness, entry.id
        assert entry.witness_job, entry.id
        assert entry.evidence_source in {"artifact", "job_log"}, entry.id
        assert entry.version_probe, entry.id
        if entry.version_probe == "KEINE":
            assert entry.raw.get("version_probe_reason"), (
                f"{entry.id}: 'KEINE' braucht einen Grund, kein Schweigen"
            )


def test_a_pass_entry_says_whether_it_was_lived_or_drilled():
    for entry in load_entries():
        if entry.state != "PASS":
            continue
        assert entry.pass_kind in {"live", "drill"}, entry.id
        if entry.pass_kind == "live":
            assert entry.witness_run, f"{entry.id}: live-PASS ohne Lauf-Id"


def test_dormant_and_unreachable_need_a_repo_coupled_reason():
    """SCHLAFEND ist ein Durchgangszustand, kein Ruhekissen."""
    for entry in load_entries():
        if entry.state in {"SCHLAFEND", "UNERREICHBAR"}:
            assert entry.unreachable_because, entry.id
            assert entry.unreachable_because.startswith(("symbol:", "path:")), entry.id


def test_the_class_floors_are_positive():
    floors = class_floors()
    assert set(floors) == {
        "workflows",
        "referenced_code",
        "test_imported",
        "derived_class",
    }
    for name, value in floors.items():
        assert value >= 1, name


def test_every_declared_unreachable_branch_carries_a_reason():
    for judge, branch, reason in declared_unreachable_branches():
        assert judge and branch, (judge, branch)
        assert len(reason.strip()) >= 40, (
            f"{judge}.{branch}: ein Einzeiler ist keine Begruendung"
        )


def test_a_malformed_entry_is_refused_loudly(tmp_path, monkeypatch):
    """Mutationsprobe: ein Eintrag ohne owner darf nicht still durchrutschen."""
    import scripts.proof_ledger as mod

    broken = tmp_path / "proof_ledger.toml"
    broken.write_text(
        '[class_floors]\nworkflows = 1\nreferenced_code = 1\nderived_class = 1\n\n'
        '[[proof]]\nid = "x"\nkind = "defect"\nclaim = "c"\n'
        'state = "OFFEN"\ndue_by = "2026-09-06"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "_LEDGER_PATH", broken)
    mod._load.cache_clear()
    with pytest.raises(ProofLedgerError, match="owner"):
        mod.load_entries()
    mod._load.cache_clear()


# --- abgeleitete Dateiklasse (Task 2) ---------------------------------------


def test_the_derived_class_holds_the_browser_automation_and_the_workflows():
    from scripts.proof_class import derive_class

    derived = derive_class()
    assert "scripts/tv_batch_consumer_rollout.ts" in derived
    assert ".github/workflows/tv-save-consumer-source.yml" in derived


def test_a_file_a_test_actually_imports_is_excluded_by_the_mechanism():
    """Anker getauscht (Fix-Runde 1, 2026-08-23): der alte Anker
    (automation/tradingview/tv_shared.ts) war VAKUOS. Nachgemessen:
    ``automation/tradingview/tv_shared.ts`` steht nie in ``referenced_code()`` --
    der echte Pfad ist ``automation/tradingview/lib/tv_shared.ts``, und kein
    Workflow ruft die Library direkt auf. "Nicht in der Klasse" war also trivial
    wahr und waere selbst gruen geblieben, haette man ``test_imported()``
    komplett abgeschaltet.

    Dieser Anker liegt dagegen ZUERST in ``referenced_code()`` (ein Workflow
    fuehrt ihn aus, siehe ``.github/workflows/*.yml``) und wird NUR durch die
    Ausschluss-Mechanik entfernt: ``tests/test_check_r1_attested_sources.py``
    Zeile 35 importiert ihn wirklich (``from scripts.check_r1_attested_sources
    import attested_sources, find_offenders``), kein Text-Pin. Ohne
    ``test_imported()`` bliebe er drin -- der Test in Teil 2 unten beweist genau
    das per Mutationsprobe.
    """
    from scripts.proof_class import derive_class, referenced_code

    target = "scripts/check_r1_attested_sources.py"
    assert target in referenced_code(), "Anker-Voraussetzung verletzt: nicht referenziert"
    assert target not in derive_class()


def test_the_exclusion_mechanism_is_load_bearing(monkeypatch):
    """Echte Mutationsprobe: schaltet ``test_imported()`` auf leer. Der Anker aus
    dem Test oben MUSS dann in der Klasse auftauchen -- das ist die Zusicherung,
    die vorher fehlte. Ohne sie kann eine kaputte ``test_imported()`` nie rot
    werden: liefert sie leer, WAECHST ``derived_class`` nur, wird also nie
    kleiner, und der bestehende ``derived_class``-Floor kann das strukturell
    nicht fangen (Fix-Runde 1, 2026-08-23).

    Der ``test_imported``-Floor aus Teil 3 wird hier bewusst auf 0 gesetzt: der
    fiele sonst selbst zuerst (0 < gemessene Untergrenze) und die Probe wuerde
    nie bis zur Ausschluss-Verdrahtung kommen, die dieser Test eigentlich prueft.
    Der Floor selbst hat seine eigene Zusicherung ueber
    ``test_the_class_floors_are_positive`` und die dortige Schluesselmenge.
    """
    import scripts.proof_class as mod

    floors = dict(class_floors())
    floors["test_imported"] = 0
    monkeypatch.setattr(mod, "class_floors", lambda: floors)
    monkeypatch.setattr(mod, "test_imported", lambda root=mod.ROOT: frozenset())
    assert "scripts/check_r1_attested_sources.py" in mod.derive_class()


def test_the_derivation_refuses_to_succeed_empty():
    """Leeres Ergebnis ist kein Befund: ein kaputter Parser muss rot werden."""
    import scripts.proof_class as mod

    with pytest.raises(mod.ProofClassError, match="Untergrenze"):
        mod.derive_class(root=mod.ROOT / "docs")


def test_the_class_is_derived_from_the_workflows_not_copied():
    """Mutationsprobe im Test: faellt eine Workflow-Referenz weg, schrumpft die
    Klasse. Ein hartkodierter Vergleich waere blind fuer Zuwachs."""
    from scripts.proof_class import referenced_code, workflow_files

    assert len(workflow_files()) >= class_floors()["workflows"]
    assert len(referenced_code()) >= class_floors()["referenced_code"]
