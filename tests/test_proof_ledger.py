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


# --- Urteiler (Task 4) ------------------------------------------------------


def test_the_partial_save_judge_reads_the_real_run_as_pass():
    """Lauf 32620808573: partiallyRepaired UND saved gefuellt, abandoned leer."""
    from scripts.proof_judges import corpus_for, load_judge

    entry = next(e for e in load_entries() if e.id == "5013")
    judge = load_judge("tv_partial_save")
    corpus = dict(corpus_for("tv_partial_save"))
    verdict = judge.judge(corpus["32620808573"], entry)
    assert verdict.state == "PASS", verdict


def test_a_run_without_the_version_probe_cannot_testify():
    """Inhaltliche Versionsprobe: fehlt das Feld, lief aelterer Code."""
    from scripts.proof_judges import load_judge

    entry = next(e for e in load_entries() if e.id == "5013")
    judge = load_judge("tv_partial_save")
    verdict = judge.judge({"mutations": {"layoutSaveRequested": True}}, entry)
    assert verdict.state == "KANN_NICHT_BEZEUGEN", verdict


def test_a_run_that_never_reached_the_save_phase_is_pending_not_dormant():
    """Der Trennstrich, um den es geht: STEHT_AUS ist nicht SCHLAFEND."""
    from scripts.proof_judges import load_judge

    entry = next(e for e in load_entries() if e.id == "5013")
    judge = load_judge("tv_partial_save")
    verdict = judge.judge(
        {"mutations": {"partiallyRepairedChartUrls": [], "layoutSaveRequested": False}},
        entry,
    )
    assert verdict.state == "STEHT_AUS", verdict


def test_the_judge_never_reads_the_run_conclusion():
    """Lauf 32620808573 war conclusion=failure und tat exakt das Richtige."""
    import inspect

    from scripts.proof_judges import load_judge

    source = inspect.getsource(load_judge("tv_partial_save"))
    assert "conclusion" not in source, (
        "Ein Urteiler, der die Lauf-Conclusion liest, fuehrt einen bestandenen "
        "Beweis als Fehlschlag"
    )


# --- Anti-Vakuitaet (Task 5) ------------------------------------------------


def test_a_judge_declares_at_least_two_branches():
    """Untergrenze: ein AST-Parser, der nichts findet, ist kaputt und nicht
    etwa erfolgreich mit null Zweigen."""
    from scripts.proof_judges import declared_branches, judge_names

    names = judge_names()
    assert names, "kein Urteiler im Ledger — Positivkontrolle leer"
    for name in names:
        assert len(declared_branches(name)) >= 2, name


def test_the_branch_labels_come_from_the_source_not_from_a_copy():
    """Abgeleitet, nicht abgeschrieben: eine Kopie ist blind fuer Zuwachs."""
    from scripts.proof_judges import declared_branches

    branches = declared_branches("tv_partial_save")
    assert "partial_saved" in branches
    assert "save_phase_never_reached" in branches
    assert "clean_run" in branches


# --- Fix-Runde 2 (2026-08-23): Notiz statt Mechanismus abgeschafft ---------


def test_entry_5025_can_never_reach_pre_fix_code():
    """``version_probe = "KEINE"`` macht fuer Eintrag "5025" den ersten Zweig
    in ``tv_repair_only_contract.judge()`` strukturell tot: wegen der
    Kurzschluss-Semantik von ``and`` ist
    ``entry.version_probe != "KEINE" and not has_path(...)`` fuer diesen
    Eintrag IMMER ``False`` -- ``pre_fix_code`` kann nie zurueckkommen, gleich
    welche Evidenz hereinkommt. Bisher stand genau diese Aussage nur als
    Begruendung (Kommentar) in ``proof_ledger.toml`` und im Task-5-Bericht --
    ein Kommentar wird nicht rot, wenn jemand den Kurzschluss umbaut oder
    ``version_probe`` auf ein echtes Feld zurueckstellt. Deckt dieselben drei
    Faelle ab, die ein Pruefer von Hand gefahren hat: leere Evidenz, Evidenz
    ohne ``executionMode``, ``executionMode`` auf einem anderen Wert als
    "repair-only" -- keiner davon darf ``pre_fix_code`` liefern.
    """
    from scripts.proof_judges import load_judge

    entry = next(e for e in load_entries() if e.id == "5025")
    assert entry.version_probe == "KEINE", (
        "Voraussetzung dieses Tests verletzt: version_probe wurde geaendert"
    )
    judge = load_judge("tv_repair_only_contract")
    cases = {
        "leere_evidenz": {},
        "ohne_executionMode": {"mutations": {"sourceSavesCompleted": 0}},
        "executionMode_write": {"executionMode": "write"},
    }
    for label, evidence in cases.items():
        verdict = judge.judge(evidence, entry)
        assert verdict.branch != "pre_fix_code", (label, verdict)


def test_every_judge_branch_is_reached_by_real_evidence_or_is_declared():
    """DER Test. Ein Zweig, den kein echtes Artefakt erreicht, muss in
    proof_ledger.toml als unerreichbar deklariert sein — mit Grund. Sonst ist
    er vakuoes und faellt hier auf, nicht erst nach einem verlorenen Tag."""
    from scripts.proof_judges import (
        corpus_for,
        declared_branches,
        judge_names,
        load_judge,
    )

    entries = load_entries()
    declared_dead = {
        (judge, branch) for judge, branch, _ in declared_unreachable_branches()
    }
    for name in sorted(judge_names()):
        entry = next(e for e in entries if e.judge == name)
        judge = load_judge(name)
        reached = {
            judge.judge(evidence, entry).branch for _, evidence in corpus_for(name)
        }
        orphaned = {
            branch
            for branch in declared_branches(name)
            if branch not in reached and (name, branch) not in declared_dead
        }
        assert not orphaned, (
            f"{name}: Zweige ohne echten Korpus-Treffer und ohne Deklaration: "
            f"{sorted(orphaned)}. Entweder einen echten Lauf aufzeichnen, der "
            f"sie erreicht, oder sie in proof_ledger.toml unter "
            f"[[unreachable_branch]] mit Grund eintragen."
        )


# --- Monitor (Task 7) -------------------------------------------------------


def test_a_declared_pass_that_measures_fail_is_a_contradiction():
    from scripts.judge_proof_ledger import classify
    from scripts.proof_judges import Verdict
    from scripts.proof_ledger import ProofEntry

    entry = ProofEntry(
        id="x", kind="fix", claim="c", state="PASS", pass_kind="live",
        due_by="2026-12-31", owner="operator", raw={},
    )
    assert classify(entry, Verdict("FAIL", branch="b"), "2026-08-23") == "WIDERSPRUCH"


def test_an_open_entry_past_its_deadline_is_overdue():
    from scripts.judge_proof_ledger import classify
    from scripts.proof_judges import Verdict
    from scripts.proof_ledger import ProofEntry

    entry = ProofEntry(
        id="x", kind="fix", claim="c", state="OFFEN",
        due_by="2026-08-01", owner="operator", raw={},
    )
    assert classify(entry, Verdict("STEHT_AUS", branch="b"), "2026-08-23") == "UEBERFAELLIG"


def test_a_terminal_entry_is_never_overdue():
    from scripts.judge_proof_ledger import classify
    from scripts.proof_judges import Verdict
    from scripts.proof_ledger import ProofEntry

    entry = ProofEntry(
        id="x", kind="exempt", claim="c", state="AUSGENOMMEN",
        due_by="2026-08-01", owner="operator", raw={},
    )
    assert classify(entry, Verdict("SCHLAFEND", branch="b"), "2026-08-23") == "OK"


def test_dormant_past_its_deadline_is_overdue_not_ok():
    """SCHLAFEND ist ein Durchgangszustand. Genau hier verdunstet es sonst."""
    from scripts.judge_proof_ledger import classify
    from scripts.proof_judges import Verdict
    from scripts.proof_ledger import ProofEntry

    entry = ProofEntry(
        id="x", kind="fix", claim="c", state="SCHLAFEND",
        due_by="2026-08-01", owner="operator",
        unreachable_because="symbol:scripts/proof_ledger.py#load_entries", raw={},
    )
    assert classify(entry, Verdict("SCHLAFEND", branch="b"), "2026-08-23") == "UEBERFAELLIG"


# --- newest_witness(): Zeugensuche ohne Netz (Fix-Runde 1, 2026-08-24) -----
#
# Vor dieser Runde hatte newest_witness()/_gh()/_judge_entry() null
# Testabdeckung (grep-bestaetigt: 0 Treffer). Genau die drei
# Randbedingungen, die diese Aufgabe traegt -- started_at statt head_sha,
# status statt conclusion, FORM- statt Nichtleer-Pruefung -- waren
# ungepinnt. Alle drei Tests hier laufen OHNE Netz (``_gh`` wird per
# monkeypatch ersetzt) und wurden je per Rueckbau-Probe verifiziert: die
# jeweilige Schutzeigenschaft im Quelltext testweise entfernt/geschwaecht,
# Test lief rot, Aenderung zurueckgesetzt, Test lief wieder gruen. Wortlaut
# im Task-7-Bericht, Abschnitt "Fix-Runde 1".


def _fake_gh(list_output: str, job_responses: dict[str, str]):
    """Ersatz fuer ``scripts.judge_proof_ledger._gh`` ohne Netz.

    ``list_output``: was die ERSTE Abfrage (Laufliste des Workflows) liefert,
    roh wie jq eine Lauf-Id je Zeile ausgeben wuerde. ``job_responses``:
    Lauf-Id -> was die ZWEITE Abfrage (Job-Liste dieses Laufs) liefert, roh
    wie der ``-q``-Filter sie ausgeben wuerde. Zeichnet jeden Aufruf auf
    (``.calls``), damit ein Test die tatsaechlich gebaute jq-Abfrage
    inspizieren kann -- nicht nur das Ergebnis.
    """
    calls: list[tuple[str, ...]] = []

    def fake(*args: str) -> str:
        calls.append(args)
        joined = " ".join(args)
        if "/runs?per_page=50" in joined:
            return list_output
        for run_id, response in job_responses.items():
            if f"/runs/{run_id}/jobs" in joined:
                return response
        return ""

    fake.calls = calls
    return fake


def test_newest_witness_uses_job_started_at_never_head_sha(monkeypatch):
    """Ein Lauf mit veraltetem ``merge_sha`` (Save-Workflow forwardet auf
    main, der Lauf misst also nicht denselben Commit wie der Merge), dessen
    Zeugen-JOB aber NACH ``merged_at`` startete, muss trotzdem als Zeuge
    gelten -- die Entscheidung haengt ausschliesslich an ``started_at``.
    """
    import scripts.judge_proof_ledger as mod
    from scripts.proof_ledger import ProofEntry

    entry = ProofEntry(
        id="x", kind="fix", claim="c", state="OFFEN", due_by="2026-12-31",
        owner="operator", witness="tv-save-consumer-source", witness_job="save",
        raw={"merged_at": "2026-08-22T16:42:54Z", "merge_sha": "STALE_SHA_NOT_THE_RUN"},
    )
    fake = _fake_gh(
        list_output="32620808573\n",
        job_responses={"32620808573": "2026-08-23T05:38:38Z"},
    )
    monkeypatch.setattr(mod, "_gh", fake)
    assert mod.newest_witness(entry) == "32620808573"


def test_newest_witness_lists_by_status_not_conclusion(monkeypatch):
    """Lauf 32620808573 (2026-08-23) hatte ``conclusion: failure`` und war
    trotzdem der richtige Zeuge. Zwei Belege in einem Test: (1) die
    tatsaechlich gebaute jq-Abfrage filtert nur auf ``status=="completed"``,
    nie auf ``conclusion`` -- das ist die Eigenschaft selbst, nicht nur ihre
    Auswirkung; (2) ein solcher Lauf wird trotzdem als Zeuge akzeptiert.
    """
    import scripts.judge_proof_ledger as mod
    from scripts.proof_ledger import ProofEntry

    entry = ProofEntry(
        id="5013", kind="fix", claim="c", state="OFFEN", due_by="2026-12-31",
        owner="operator", witness="tv-save-consumer-source", witness_job="save",
        raw={"merged_at": "2026-08-22T16:42:54Z"},
    )
    # Simuliert den roten Lauf: die Liste enthaelt seine Id ueberhaupt nur,
    # WEIL die echte jq-Abfrage status statt conclusion filtert -- das prueft
    # die Assertion unten an der tatsaechlichen Abfrage-Zeichenkette, nicht
    # an diesem Stub (ein Stub kann jq-Semantik nicht ausfuehren).
    fake = _fake_gh(
        list_output="32620808573\n",
        job_responses={"32620808573": "2026-08-23T05:38:38Z"},
    )
    monkeypatch.setattr(mod, "_gh", fake)

    result = mod.newest_witness(entry)

    assert result == "32620808573"
    list_call = next(c for c in fake.calls if "/runs?per_page=50" in " ".join(c))
    query = list_call[-1]
    assert query == '.workflow_runs[] | select(.status=="completed") | .id'
    assert "conclusion" not in query


def test_newest_witness_never_crowns_a_json_error_body_as_a_witness(monkeypatch):
    """Ein `gh api`-Fehlerkoerper (roh wie er STDOUT erreichen wuerde, waere
    er nicht schon durch den Rueckgabecode-Filter in ``_gh()`` verworfen --
    2026-08-24 gemessen: ein echter 404 liefert ``returncode=1``, `_gh()`
    gibt dafuer bereits "" zurueck) darf NIE als Zeitstempel durchgehen: '{'
    ist ASCII-groesser als jede Ziffer, ein reiner Groessenvergleich wuerde
    jeden echten Zeitstempel schlagen. Die Formpruefung ist die zweite,
    von ``_gh()``s Filter unabhaengige Verteidigungslinie -- dieser Test
    haelt SIE fest, unabhaengig davon, ob der 404-Pfad sie in der Praxis
    heute erreicht.
    """
    import scripts.judge_proof_ledger as mod
    from scripts.proof_ledger import ProofEntry

    entry = ProofEntry(
        id="x", kind="fix", claim="c", state="OFFEN", due_by="2026-12-31",
        owner="operator", witness="tv-save-consumer-source", witness_job="save",
        raw={"merged_at": "2026-08-22T16:42:54Z"},
    )
    error_body = (
        '{"message":"Not Found","documentation_url":'
        '"https://docs.github.com/rest/actions/workflow-jobs'
        '#list-jobs-for-a-workflow-run","status":"404"}'
    )
    fake = _fake_gh(
        list_output="999999999\n",
        job_responses={"999999999": error_body},
    )
    monkeypatch.setattr(mod, "_gh", fake)
    assert mod.newest_witness(entry) == ""


# --- Monitor: uebersprungen darf nie wie "kein Zeuge" aussehen -------------
#
# Der Monitor urteilt nur ueber evidence_source == "artifact" -- er holt keine
# Job-Logs. #5018/#5027 (evidence_source == "job_log") werden deshalb
# strukturell uebersprungen. Ohne diese Unterscheidung wuerde main() sie mit
# "KEIN_ZEUGE" beschriften -- demselben Text wie einen artifact-Eintrag, fuer
# den wirklich gesucht und nichts gefunden wurde. Eine uebersprungene Pruefung,
# die wie eine bestandene (oder wie eine erfolglos durchgefuehrte) aussieht,
# ist genau der Defekt, gegen den dieses Ledger gebaut wurde -- deshalb ist
# unjudged_reason() eine eigene, getestete Funktion und kein Kommentar.


def test_a_job_log_entry_is_marked_unjudged_not_missing_witness():
    """Pinnt den EXAKTEN Text des dedizierten job_log-Zweigs, nicht nur, dass
    "job_log" irgendwo im Ergebnis vorkommt. Fix-Runde 1 (2026-08-24), Fund
    des Pruefers: entfernt man den dedizierten Zweig, faengt der generische
    Fallback (``evidence_source != "artifact"``) dieselbe Fixture auf und
    liefert ``"evidence_source='job_log' unbekannt"`` -- ein
    ``in``-Substring-Test bleibt gruen, weil ``repr("job_log")`` die
    Zeichenkette "job_log" enthaelt, obwohl der FALSCHE Zweig feuerte."""
    from scripts.judge_proof_ledger import unjudged_reason
    from scripts.proof_ledger import ProofEntry

    entry = ProofEntry(
        id="5018", kind="fix", claim="c", state="OFFEN", due_by="2026-12-31",
        owner="operator", judge="tv_legend_click", witness="tv-save-consumer-source",
        witness_job="save", evidence_source="job_log", raw={},
    )
    assert unjudged_reason(entry) == "job_log — Monitor holt keine Logs"


def test_a_defect_entry_without_a_judge_is_marked_unjudged():
    """Pinnt den EXAKTEN Text des ``kind != "fix"``-Zweigs. Fix-Runde 1
    (2026-08-24), Fund des Pruefers: diese Fixture hat AUCH kein ``judge``
    gesetzt -- entfernt man den ``kind != "fix"``-Zweig, faengt der
    nachfolgende ``not entry.judge``-Zweig dieselbe Fixture auf und liefert
    "kein Urteiler deklariert". Ein reiner Wahrheitswert-Test (``assert
    unjudged_reason(entry)``) unterscheidet die beiden Zweige nicht."""
    from scripts.judge_proof_ledger import unjudged_reason
    from scripts.proof_ledger import ProofEntry

    entry = ProofEntry(
        id="klasse-h", kind="defect", claim="c", state="UNGESICHERT",
        due_by="2026-12-31", owner="operator", raw={},
    )
    assert unjudged_reason(entry) == "kein fix-Eintrag"


def test_an_artifact_fix_entry_with_a_judge_is_not_skipped():
    """Positivkontrolle: unjudged_reason() darf nicht pauschal alles ausschliessen."""
    from scripts.judge_proof_ledger import unjudged_reason
    from scripts.proof_ledger import ProofEntry

    entry = ProofEntry(
        id="5013", kind="fix", claim="c", state="PASS", due_by="2026-12-31",
        owner="operator", judge="tv_partial_save", witness="tv-save-consumer-source",
        witness_job="save", evidence_source="artifact", raw={},
    )
    assert unjudged_reason(entry) == ""


# --- Monitor-Workflow-Vertrag (Task 7) --------------------------------------


def test_the_monitor_workflow_calls_the_judge_and_never_writes_the_ledger_back():
    """Zwei Dinge in einem Test:

    1. Orphan-Inventory-Pflicht (``tests/test_workflow_orphan_inventory.py``):
       jeder Workflow braucht mindestens eine echte Testreferenz auf seinen
       Basisnamen -- eine ``ALLOWED_ORPHANS``-Ausnahme waere Prosa statt
       Mechanismus fuer genau die Klasse, die dieses Ledger abbauen soll.
    2. Der eigentliche Vertrag: der Monitor ruft ``scripts.judge_proof_ledger``
       auf und schreibt proof_ledger.toml NIE zurueck -- ein Bot mit
       Schreibrecht auf die Beweisfuehrung ist genau die Konstruktion, durch
       die der Library-Refresh-Bot am 31.7. zweimal durch den R1-Vertrag lief.
    """
    import yaml

    from scripts.proof_ledger import ROOT

    path = ROOT / ".github" / "workflows" / "proof-ledger-monitor.yml"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "python -m scripts.judge_proof_ledger" in text
    assert "git commit" not in text
    assert "git push" not in text

    workflow = yaml.safe_load(text)
    # PyYAML parst den bloss stehenden Schluessel `on:` als Bool True, nicht
    # als String "on" -- derselbe Rueckfall wie in
    # tests/test_workflow_live_window_posture.py::_trigger_keys.
    triggers = workflow.get(True, workflow.get("on", {}))
    assert "schedule" in triggers


# --- proof_ledger_monitor_self: der Monitor urteilt ueber den eigenen Report
#
# Der Monitor ist selbst beweispflichtig (proof_ledger.toml, Eintrag
# "task7-proof-ledger-monitor"). Alle drei Zweige stehen als
# [[unreachable_branch]] im Ledger -- der Workflow hat noch nie gelaufen,
# also gibt es noch keinen echten Korpus. Diese drei Tests pruefen den
# Urteiler trotzdem direkt (derselbe Stil wie test_entry_5025_can_never_reach_pre_fix_code
# oben), damit die Logik selbst schon VOR dem ersten echten Lauf abgesichert ist.


def test_proof_ledger_monitor_self_fails_on_an_empty_report():
    from scripts.proof_judges import proof_ledger_monitor_self

    verdict = proof_ledger_monitor_self.judge([], None)
    assert verdict.state == "FAIL"
    assert verdict.branch == "report_empty"


def test_proof_ledger_monitor_self_fails_when_a_skip_looks_like_a_missing_witness():
    """Genau der Defekt, gegen den Task 7 gebaut wurde: ein uebersprungener
    Eintrag (evidence_source != "artifact", z. B. #5018 mit job_log), der im
    Report als KEIN_ZEUGE erscheint statt als KEIN_URTEIL(...)."""
    from scripts.proof_judges import proof_ledger_monitor_self

    report = [{"id": "5018", "evidence_source": "job_log", "measured": "KEIN_ZEUGE"}]
    verdict = proof_ledger_monitor_self.judge(report, None)
    assert verdict.state == "FAIL"
    assert verdict.branch == "skip_mislabeled_as_missing_witness"


def test_proof_ledger_monitor_self_passes_on_a_well_shaped_report():
    """Positivkontrolle: ein job_log-Eintrag, der ehrlich als KEIN_URTEIL
    beschriftet ist, darf den Selbst-Urteiler nicht faelschlich FAILen."""
    from scripts.proof_judges import proof_ledger_monitor_self

    report = [
        {"id": "5013", "evidence_source": "artifact", "measured": "PASS"},
        {
            "id": "5018",
            "evidence_source": "job_log",
            "measured": "KEIN_URTEIL (job_log — Monitor holt keine Logs)",
        },
    ]
    verdict = proof_ledger_monitor_self.judge(report, None)
    assert verdict.state == "PASS"
    assert verdict.branch == "report_shaped_as_expected"
