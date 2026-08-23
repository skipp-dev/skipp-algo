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


def test_the_test_imported_floor_is_enforced(monkeypatch):
    """Der Floor-Guard fuer ``test_imported`` (Fix-Runde 1, ``proof_class.py``
    Zeilen um 124-128) hatte keine Positivkontrolle IN der Suite -- nur eine
    manuelle Probe ausserhalb, die nie committet wurde (Fix-Runde 2,
    Reviewer-Befund, per grep verifiziert: kein Test drueckte ``test_imported``
    unter seinen Floor). Ein Waechter, dessen Feuern nur ausserhalb der Suite
    gezeigt wurde, ist IN der Suite unbewacht: wuerde der Zweig versehentlich
    entfernt oder der Vergleich invertiert (``<`` zu ``>``), bliebe alles gruen.
    Das ist dieselbe Fehlerklasse wie der vakuoese Anker und die fehlende
    Untergrenze aus Runde 1 -- diesmal am Waechter, der die Untergrenze
    durchsetzt, statt an der Untergrenze selbst.

    Symmetrisch zur bestehenden Positivkontrolle ueber ``root=mod.ROOT / "docs"``
    fuer die anderen drei Mengen: Floor absurd hoch gesetzt (echter Wert bleibt
    bei ~691), ``derive_class()`` muss werfen.
    """
    import scripts.proof_class as mod

    floors = dict(class_floors())
    floors["test_imported"] = 999_999
    monkeypatch.setattr(mod, "class_floors", lambda: floors)
    with pytest.raises(mod.ProofClassError, match="Untergrenze"):
        mod.derive_class()


def test_the_derivation_refuses_to_succeed_empty():
    """Leeres Ergebnis ist kein Befund: ein kaputter Parser muss rot werden."""
    import scripts.proof_class as mod

    with pytest.raises(mod.ProofClassError, match="Untergrenze"):
        mod.derive_class(root=mod.ROOT / "docs")


def test_the_class_is_derived_from_the_workflows_not_copied():
    """Mutationsprobe im Test: faellt eine Workflow-Referenz weg, schrumpft die
    Klasse. Ein hartkodierter Vergleich waere blind fuer Zuwachs.

    Alle vier Kollektoren im selben Muster (Fix-Runde 2, Reviewer-Befund: die
    ersten drei standen hier, ``test_imported`` fehlte -- eine Asymmetrie ohne
    Grund, die vierte Menge gehoert dazu)."""
    from scripts.proof_class import referenced_code, test_imported, workflow_files

    assert len(workflow_files()) >= class_floors()["workflows"]
    assert len(referenced_code()) >= class_floors()["referenced_code"]
    assert len(test_imported()) >= class_floors()["test_imported"]


# --- Offline-Gate (Task 3) --------------------------------------------------


def test_the_range_is_widened_to_the_merge_base():
    """`git diff A..B` ist KEIN Bereich, sondern ein Vergleich zweier BAEUME.
    Auf einem PR-Branch meldet er die Aenderungen von main als die eigenen —
    genau so wurde #4373 am 4.8. faelschlich rot."""
    from scripts.check_proof_ledger import _merge_base_range

    assert _merge_base_range("aaa..bbb") == "aaa...bbb"
    assert _merge_base_range("aaa...bbb") == "aaa...bbb"


def test_a_coupled_reason_must_hold_in_the_tree():
    """Anti-Willkuer: SCHLAFEND/UNERREICHBAR nur mit pruefbarer Repo-Tatsache."""
    from scripts.check_proof_ledger import _coupling_failures

    assert _coupling_failures() == []


def test_a_dangling_symbol_reference_is_reported(tmp_path, monkeypatch):
    """Mutationsprobe: zeigt die Begruendung ins Leere, muss es auffallen."""
    import scripts.check_proof_ledger as gate
    from scripts.proof_ledger import ProofEntry

    fake = ProofEntry(
        id="fake",
        kind="fix",
        claim="c",
        state="UNERREICHBAR",
        due_by="2026-09-06",
        owner="operator",
        unreachable_because="symbol:scripts/proof_ledger.py#gibtEsNicht",
        raw={},
    )
    monkeypatch.setattr(gate, "load_entries", lambda: (fake,))
    problems = gate._coupling_failures()
    assert len(problems) == 1
    assert "gibtEsNicht" in problems[0]


def test_touching_the_class_without_a_new_entry_fails(monkeypatch, capsys):
    import scripts.check_proof_ledger as gate

    monkeypatch.setattr(gate, "_changed_files", lambda rng: frozenset({"scripts/x.ts"}))
    monkeypatch.setattr(gate, "derive_class", lambda: frozenset({"scripts/x.ts"}))
    monkeypatch.setattr(gate, "_ledger_ids_at", lambda rev: frozenset({"5013"}))
    monkeypatch.setattr(gate, "load_entries", lambda: ())
    monkeypatch.setattr(gate, "_coupling_failures", lambda: [])

    rc = gate.main(["--range", "aaa..bbb"])

    err = capsys.readouterr().err
    assert rc == 1
    assert "scripts/x.ts" in err
    assert "proof_ledger.toml" in err


def test_touching_the_class_with_a_new_entry_passes(monkeypatch):
    import scripts.check_proof_ledger as gate
    from scripts.proof_ledger import ProofEntry

    neu = ProofEntry(
        id="9999", kind="defect", claim="c", state="OFFEN",
        due_by="2026-09-06", owner="operator", raw={},
    )
    monkeypatch.setattr(gate, "_changed_files", lambda rng: frozenset({"scripts/x.ts"}))
    monkeypatch.setattr(gate, "derive_class", lambda: frozenset({"scripts/x.ts"}))
    monkeypatch.setattr(gate, "_ledger_ids_at", lambda rev: frozenset({"5013"}))
    monkeypatch.setattr(gate, "load_entries", lambda: (neu,))
    monkeypatch.setattr(gate, "_coupling_failures", lambda: [])

    assert gate.main(["--range", "aaa..bbb"]) == 0


def test_a_pr_that_touches_nothing_in_the_class_passes(monkeypatch):
    import scripts.check_proof_ledger as gate

    monkeypatch.setattr(gate, "_changed_files", lambda rng: frozenset({"README.md"}))
    monkeypatch.setattr(gate, "derive_class", lambda: frozenset({"scripts/x.ts"}))
    monkeypatch.setattr(gate, "load_entries", lambda: ())
    monkeypatch.setattr(gate, "_coupling_failures", lambda: [])

    assert gate.main(["--range", "aaa..bbb"]) == 0


# --- Offline-Gate Fix-Runde 1: der Exit-Code-Vertrag (rc=2) -----------------


def test_a_malformed_toml_yields_exit_code_two(tmp_path, monkeypatch):
    """rc=2 heisst 'Ledger unlesbar', rc=1 heisst 'echter Befund' — beide duerfen
    nicht zusammenfallen. Kaputtes TOML darf auch nicht als ungefangener
    Traceback enden: main()s ``try/except ProofLedgerError`` greift nur, wenn
    ``_load()`` ``TOMLDecodeError`` tatsaechlich in ``ProofLedgerError`` uebersetzt."""
    import scripts.check_proof_ledger as gate
    import scripts.proof_ledger as mod

    broken = tmp_path / "proof_ledger.toml"
    broken.write_text("[[[ das ist kein gueltiges TOML", encoding="utf-8")
    monkeypatch.setattr(mod, "_LEDGER_PATH", broken)
    mod._load.cache_clear()
    assert gate.main(["--range", "aaa..bbb"]) == 2
    mod._load.cache_clear()


def test_a_missing_ledger_file_yields_exit_code_two(tmp_path, monkeypatch):
    """Symmetrisch zum kaputten TOML: eine fehlende Datei ist ``FileNotFoundError``
    statt ``TOMLDecodeError``, muss aber denselben rc=2-Pfad treffen."""
    import scripts.check_proof_ledger as gate
    import scripts.proof_ledger as mod

    missing = tmp_path / "existiert-nicht.toml"
    monkeypatch.setattr(mod, "_LEDGER_PATH", missing)
    mod._load.cache_clear()
    assert gate.main(["--range", "aaa..bbb"]) == 2
    mod._load.cache_clear()


def test_a_dangling_path_reference_is_reported(monkeypatch):
    """Positivkontrolle fuer den `path:`-Zweig von `_coupling_failures()` —
    symmetrisch zur bestehenden Probe fuer `symbol:`."""
    import scripts.check_proof_ledger as gate
    from scripts.proof_ledger import ProofEntry

    fake = ProofEntry(
        id="fake-path",
        kind="fix",
        claim="c",
        state="UNERREICHBAR",
        due_by="2026-09-06",
        owner="operator",
        unreachable_because="path:scripts/gibtEsNicht.py",
        raw={},
    )
    monkeypatch.setattr(gate, "load_entries", lambda: (fake,))
    problems = gate._coupling_failures()
    assert len(problems) == 1
    assert "scripts/gibtEsNicht.py" in problems[0]


def test_an_unknown_coupling_kind_is_reported(monkeypatch):
    """Positivkontrolle fuer den `else`-Zweig von `_coupling_failures()` — eine
    unbekannte Kopplungsart darf nicht stillschweigend als geprueft gelten."""
    import scripts.check_proof_ledger as gate
    from scripts.proof_ledger import ProofEntry

    fake = ProofEntry(
        id="fake-kind",
        kind="fix",
        claim="c",
        state="UNERREICHBAR",
        due_by="2026-09-06",
        owner="operator",
        unreachable_because="voodoo:irgendwas",
        raw={},
    )
    monkeypatch.setattr(gate, "load_entries", lambda: (fake,))
    problems = gate._coupling_failures()
    assert len(problems) == 1
    assert "voodoo" in problems[0]
