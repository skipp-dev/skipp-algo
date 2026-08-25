"""Schema- und Disziplin-Tests fuer proof_ledger.toml."""

from __future__ import annotations

import datetime as dt
import inspect
import re

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


def _assert_pass_entry_is_backed(entry) -> None:
    """Beweislast eines terminalen PASS -- gleiche Strenge fuer beide Wege.

    Fix-Runde (Critical 3, 2026-08-24): vorher zwang nur ``live`` einen
    Lauf-Beleg (``witness_run``); ``drill`` verlangte NICHTS. Ein Eintrag
    konnte auf ``state = "PASS"`` / ``pass_kind = "drill"`` gesetzt werden,
    ohne je zu sagen, WAS durchgespielt wurde oder WANN -- terminal, nie
    wieder ueberfaellig, und vom Monitor (evidence_source != "artifact" fuer
    einen reinen Drill) ohnehin uebersprungen. Symmetrisch nachgezogen:
    ``drill_source`` (Herkunft des synthetischen Inputs) und ``drilled_at``
    (Zeitpunkt) sind jetzt fuer ``drill`` genauso Pflicht wie
    ``witness_run`` fuer ``live``.
    """
    assert entry.pass_kind in {"live", "drill"}, entry.id
    if entry.pass_kind == "live":
        assert entry.witness_run, f"{entry.id}: live-PASS ohne Lauf-Id"
    if entry.pass_kind == "drill":
        assert entry.drill_source, f"{entry.id}: drill-PASS ohne Herkunft des Drills"
        assert entry.drilled_at, f"{entry.id}: drill-PASS ohne Zeitpunkt"


def test_a_pass_entry_says_whether_it_was_lived_or_drilled():
    for entry in load_entries():
        if entry.state != "PASS":
            continue
        _assert_pass_entry_is_backed(entry)


def test_a_drill_pass_without_provenance_is_rejected():
    """Rueckbau-artige Mutationsprobe fuer Critical 3: kein echter Ledger-
    Eintrag nutzt ``pass_kind = "drill"`` bisher (deferred minor aus Task 1),
    also kann nur ein SYNTHETISCHER Eintrag zeigen, dass die neue Beweislast
    wirklich feuert. Vor diesem Fix waere ``naked`` unten klaglos
    durchgelaufen -- genau das Szenario aus dem Abschluss-Review: Eintrag
    #5018 (nie bezeugt, kein Korpus, kein witness_run) auf
    ``state = "PASS"`` / ``pass_kind = "drill"`` gesetzt lief in einer
    /tmp-Kopie mit 45 passed durch, alles gruen."""
    from scripts.proof_ledger import ProofEntry

    naked = ProofEntry(
        id="drill-ohne-beweis", kind="fix", claim="c", state="PASS",
        pass_kind="drill", due_by="2026-09-06", owner="operator", raw={},
    )
    with pytest.raises(AssertionError, match="Herkunft des Drills"):
        _assert_pass_entry_is_backed(naked)

    nur_quelle = ProofEntry(
        id="drill-nur-quelle", kind="fix", claim="c", state="PASS",
        pass_kind="drill", drill_source="tests/proof_corpus/x/synth.json",
        due_by="2026-09-06", owner="operator", raw={},
    )
    with pytest.raises(AssertionError, match="ohne Zeitpunkt"):
        _assert_pass_entry_is_backed(nur_quelle)

    vollstaendig = ProofEntry(
        id="drill-vollstaendig", kind="fix", claim="c", state="PASS",
        pass_kind="drill", drill_source="tests/proof_corpus/x/synth.json",
        drilled_at="2026-08-24T00:00:00Z",
        due_by="2026-09-06", owner="operator", raw={},
    )
    _assert_pass_entry_is_backed(vollstaendig)  # darf nicht werfen


def test_dormant_and_unreachable_need_a_repo_coupled_reason():
    """SCHLAFEND ist ein Durchgangszustand, kein Ruhekissen."""
    for entry in load_entries():
        if entry.state in {"SCHLAFEND", "UNERREICHBAR"}:
            assert entry.unreachable_because, entry.id
            assert entry.unreachable_because.startswith(("symbol:", "path:")), entry.id


def test_a_fail_entry_without_a_holder_is_refused_loudly(tmp_path, monkeypatch):
    """Mutationsprobe: ``state = "FAIL"`` ohne ``refutation_tracked_by`` darf
    nicht laden -- wie ``pass_kind`` bei ``PASS``, aber hier hart im Schema
    statt nur per Test. Ohne diese Zeile waere ein FAIL-Eintrag ein Schalter
    zum Stummstellen, den niemand zwingt, an einem Halter zu haengen."""
    import scripts.proof_ledger as mod

    broken = tmp_path / "proof_ledger.toml"
    broken.write_text(
        '[class_floors]\nworkflows = 1\nreferenced_code = 1\nderived_class = 1\n\n'
        '[[proof]]\nid = "x"\nkind = "defect"\nclaim = "c"\n'
        'state = "FAIL"\ndue_by = "2026-09-06"\nowner = "operator"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "_LEDGER_PATH", broken)
    mod._load.cache_clear()
    with pytest.raises(ProofLedgerError, match="refutation_tracked_by"):
        mod.load_entries()
    mod._load.cache_clear()


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


def test_a_declared_dead_branch_that_real_evidence_reaches_is_a_contradiction():
    """Die Gegenrichtung zur Deklaration — und sie fehlte.

    ``test_every_judge_branch_is_reached_by_real_evidence_or_is_declared``
    prueft nur die eine Richtung: kein Zweig ohne Korpus-Treffer UND ohne
    Deklaration. Ein Zweig, der tot erklaert ist und den der Korpus INZWISCHEN
    erreicht, faellt dort durch beide Siebe — er ist ja "declared". Die
    Deklaration konnte damit still veralten, und eine veraltete Deklaration ist
    schlimmer als keine: sie behauptet, ein Zweig koenne nicht feuern, waehrend
    er feuert.

    Gemessen 2026-08-24 beim Einbau: 12 Deklarationen, 0 Widersprueche — der
    Test faerbt also nichts nachtraeglich rot, er haelt den Zustand.

    Er ist ausserdem der Mechanismus hinter den vier
    ``artifact_download``-Deklarationen (#5037): die sind "noch nicht geboren",
    nicht "tot". Sobald ein v24-Lauf als Korpus aufgezeichnet wird, faellt
    ``download_geliefert`` hier auf und ERZWINGT die Entfernung seiner
    Deklaration — statt sich auf ein menschliches Gedaechtnis zu verlassen.
    """
    from scripts.proof_judges import corpus_for, judge_names, load_judge

    entries = load_entries()
    dead = {(judge, branch) for judge, branch, _ in declared_unreachable_branches()}
    assert dead, "keine Deklaration im Ledger — Positivkontrolle leer"

    contradictions = []
    for name in sorted(judge_names()):
        entry = next(e for e in entries if e.judge == name)
        judge = load_judge(name)
        for run_id, evidence in corpus_for(name):
            branch = judge.judge(evidence, entry).branch
            if (name, branch) in dead:
                contradictions.append(f"{name}.{branch} erreicht von Korpus {run_id}")

    assert not contradictions, (
        "tot erklaerte Zweige, die echte Evidenz erreicht: "
        f"{sorted(contradictions)}. Die Deklaration in proof_ledger.toml "
        "entfernen — der Zweig feuert."
    )


def test_a_pass_entry_is_backed_by_a_corpus_that_actually_reaches_pass():
    """Der fehlende Ring — ohne ihn haengt der Widerspruchs-Test in der Luft.

    ``test_a_declared_dead_branch_that_real_evidence_reaches_is_a_contradiction``
    feuert nur, WENN jemand den Lauf als Korpus aufzeichnet. Dieser Schritt war
    unmechanisiert: der Monitor koennte einen Zweig in Produktion laufend
    erreichen, waehrend der Korpus alt bleibt und die Tot-Erklaerung ewig
    stehen bleibt. Eine Absicherung, die auf "jemand denkt daran" endet, ist
    keine.

    Hier geschlossen: wer einen Eintrag auf PASS setzt, behauptet, der Beweis
    sei erbracht. Dann muss der Korpus das ZEIGEN koennen. Damit haengt das
    Aufzeichnen nicht mehr am Gedaechtnis, sondern am Abschluss selbst — und
    fuer #5037 schliesst das die Kette: 5037 laesst sich nicht auf PASS setzen
    ohne v24-Korpus, der v24-Korpus erreicht ``download_geliefert``, und das
    macht dessen Tot-Erklaerung im Test darueber rot.

    Gemessen 2026-08-24 beim Einbau: alle vier bestehenden PASS-Eintraege
    (5013, 5025, 5020, task7-proof-ledger-monitor) erfuellen das bereits. Der
    Test haelt den Zustand, er faerbt nichts nachtraeglich rot.
    """
    from scripts.proof_judges import corpus_for, load_judge

    ungedeckt = []
    for entry in load_entries():
        if entry.state != "PASS" or not entry.judge:
            continue
        judge = load_judge(entry.judge)
        states = {judge.judge(ev, entry).state for _, ev in corpus_for(entry.judge)}
        if "PASS" not in states:
            ungedeckt.append(f"{entry.id} ({entry.judge}): Korpus ergibt {sorted(states)}")

    assert not ungedeckt, (
        "PASS behauptet, aber kein aufgezeichneter Lauf erreicht den "
        f"PASS-Zweig: {sorted(ungedeckt)}. Den bezeugenden Lauf unter "
        "tests/proof_corpus/<judge>/<job_id>.json aufzeichnen."
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


# --- Extern-Filter (Halter i1i2-derived-class-missing-extern-filter) -------
#
# Spec (docs/superpowers/specs/2026-08-23-beweis-ledger-design.md, Abschnitt
# "Aufnahme"): Extern = Workflows OHNE pull_request-Trigger. Ein Workflow, der
# auf pull_request laeuft, beweist seine eigene Aenderung im naechsten
# PR-Lauf selbst und gehoert nicht in die beweispflichtige Klasse.


def test_the_on_key_becomes_a_yaml_boolean_and_is_still_found():
    """YAML-Falle, explizit gepinnt: PyYAML parst ein unquotiertes ``on:`` als
    Boolean-Schluessel ``True``, nicht als String ``"on"``. Positivkontrolle,
    dass ``_on_trigger`` genau das handhabt -- ohne die True-Pruefung wuerde
    JEDER Workflow als 'kein Trigger gefunden' durchgehen und faelschlich als
    extern gelten, auch ein pull_request-Workflow."""
    import yaml

    from scripts.proof_class import _on_trigger

    text = "on:\n  pull_request: {}\n"
    parsed = yaml.safe_load(text)
    assert True in parsed and "on" not in parsed, (
        "Testannahme (PyYAML-Bool-Schluessel-Falle) stimmt nicht mehr"
    )
    assert _on_trigger(text) == {"pull_request": {}}


def test_has_pull_request_trigger_parses_the_real_on_block(tmp_path):
    """Geparst ueber den echten ``on:``-Block, nicht per Substring."""
    from scripts.proof_class import _has_pull_request_trigger

    yml = tmp_path / "a.yml"
    yml.write_text("on:\n  pull_request:\n    branches: [main]\njobs: {}\n")
    assert _has_pull_request_trigger(yml) is True


def test_has_pull_request_trigger_is_false_for_other_triggers(tmp_path):
    from scripts.proof_class import _has_pull_request_trigger

    yml = tmp_path / "b.yml"
    yml.write_text(
        "on:\n  schedule:\n    - cron: '0 0 * * *'\n  workflow_dispatch: {}\njobs: {}\n"
    )
    assert _has_pull_request_trigger(yml) is False


def test_has_pull_request_trigger_handles_the_list_and_string_on_forms(tmp_path):
    """Der ``on:``-Block kann ein String, eine Liste oder eine Map sein --
    alle drei Formen kommen in echten GH-Workflows vor."""
    from scripts.proof_class import _has_pull_request_trigger

    list_form = tmp_path / "c.yml"
    list_form.write_text("on: [push, pull_request]\njobs: {}\n")
    assert _has_pull_request_trigger(list_form) is True

    string_form = tmp_path / "d.yml"
    string_form.write_text("on: push\njobs: {}\n")
    assert _has_pull_request_trigger(string_form) is False


def test_a_pull_request_triggered_workflow_is_excluded_from_the_class():
    """Anker am echten Repo: smc-fast-pr-gates.yml ist der EINZIGE required
    Check (ADR-0011) und laeuft auf pull_request -- er beweist seine eigene
    Aenderung im naechsten PR-Lauf selbst. Vor dem Fix lag er (mit ci.yml und
    sechs weiteren) IN der Klasse -- gemessen 2026-08-24: alle 8
    pull_request-Workflows lagen drin, weil workflow_files() jede Datei
    bedingungslos aufnahm."""
    from scripts.proof_class import derive_class, workflow_files

    assert ".github/workflows/smc-fast-pr-gates.yml" not in workflow_files()
    assert ".github/workflows/smc-fast-pr-gates.yml" not in derive_class()
    assert ".github/workflows/ci.yml" not in workflow_files()


def test_the_pull_request_trigger_filter_is_load_bearing(monkeypatch):
    """Rueckbau-Probe: Filter abgeschaltet (jeder Workflow gilt als extern,
    ``_has_pull_request_trigger`` liefert immer False) -- smc-fast-pr-gates.yml
    MUSS dann wieder in der Klasse auftauchen. Ohne diese Zusicherung koennte
    der Trigger-Parser (etwa die on:-Bool-Schluessel-Falle) stillschweigend
    kaputtgehen, ohne dass ein Test es merkt."""
    import scripts.proof_class as mod

    monkeypatch.setattr(mod, "_has_pull_request_trigger", lambda path: False)
    assert ".github/workflows/smc-fast-pr-gates.yml" in mod.workflow_files()
    assert ".github/workflows/smc-fast-pr-gates.yml" in mod.derive_class()


# --- Offline-Gate (Task 3) --------------------------------------------------


def test_the_range_is_widened_to_the_merge_base():
    """`git diff A..B` ist KEIN Bereich, sondern ein Vergleich zweier BAEUME.
    Auf einem PR-Branch meldet er die Aenderungen von main als die eigenen —
    genau so wurde #4373 am 4.8. faelschlich rot."""
    from scripts.check_proof_ledger import _merge_base_range

    assert _merge_base_range("aaa..bbb") == "aaa...bbb"
    assert _merge_base_range("aaa...bbb") == "aaa...bbb"


def _git(tmp_path, *args: str) -> str:
    """Kleiner Helfer fuer die c4-Regressionsprobe unten -- kein Netz, ein
    ECHTES Git-Repo in tmp_path, nie das echte skipp-algo-Repo.

    Umgebungsunabhaengig gehalten (2026-08-25, Gate-Fund: der Test fiel im
    pre-push-Gate -- anderer Interpreter, andere Umgebung -- ohne dass lokal
    (``pytest`` hier, 88 gruen) je etwas auffiel): jede ``GIT_*``-Variable
    wird aus der Subprozess-Umgebung entfernt, bevor ``git`` laeuft. Ein
    umschliessender pre-push-Hook laeuft mit gesetzten Git-Variablen
    (``GIT_DIR``/``GIT_WORK_TREE``/``GIT_INDEX_FILE``/``GIT_OBJECT_DIRECTORY``/
    ``GIT_CONFIG*``, ...) -- ungefiltert durchgereicht wuerden sie dieses
    frische Testrepo auf den ECHTEN Baum umleiten, statt ein isoliertes
    ``tmp_path``-Repo zu bauen. Das ist derselbe Fehler wie eine geborgte
    Uhr: die Testumgebung liefert Zustand, den der Test selbst liefern muss.

    Wirft bei Fehlschlag AssertionError mit Kommando, Rueckgabecode, stdout
    UND stderr -- ein nackter ``CalledProcessError`` (``check=True`` mit
    ``capture_output``) verschluckt genau die stderr-Zeile, die sagt, was
    Git beanstandet hat, und kostet jedem Nachfolger dieselbe Ratesitzung.
    """
    import os
    import subprocess

    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    proc = subprocess.run(
        ["git", *args], cwd=tmp_path, capture_output=True, text=True, env=env,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"git {list(args)!r} (cwd={tmp_path}) exited {proc.returncode}\n"
            f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
        )
    return proc.stdout.strip()


def test_before_is_read_at_the_merge_base_not_the_literal_range_start(tmp_path, monkeypatch):
    """Regression fuer den Halter c4-merge-base-not-merge-commit, nachgestellt
    in einem ECHTEN /tmp-Git-Repo (nicht gegen das echte skipp-algo-Repo).

    Konstruktion, per echtem ``git merge-base`` unter ``/tmp`` verifiziert,
    bevor dieser Test geschrieben wurde:

    1. ``root`` (Ledger leer) --> ``pr1`` aendert ``provable.py``, OHNE
       eigenen Ledger-Eintrag.
    2. Parallel dazu, ebenfalls von ``root``: ``main_a`` traegt einen
       FREMDEN, noch offenen Eintrag ("9999") -- ein anderer PR, der gerade
       gemergt wurde.
    3. Die PR-Branch loest ihren BEHIND-Zustand (Routine in diesem Repo) auf,
       indem sie ``main_a`` mergt --> ``pr2``. Ihre Arbeitskopie traegt jetzt
       "9999", geerbt vom Merge.
    4. main loest den fremden Befund SPAETER auf und ENTFERNT "9999" wieder
       --> ``main_b``. Der zweite (erneut getriggerte) Gate-Lauf bekommt
       dieses main_b als BASE_SHA -- main ist inzwischen weiter als das, was
       die PR-Branch tatsaechlich gemergt hat.

    ``main_b`` ist KEIN Vorfahr von ``pr2`` (die PR-Branch hat main_b nie
    gemergt) -- die echte Merge-Basis von (main_b, pr2) ist ``main_a``, wo
    "9999" noch stand.

    Mit dem alten Code (``base = _merge_base_range(...).split("...")[0]``)
    wird ``before`` am LITERALEN BASE_SHA gelesen: main_b, das "9999" NICHT
    mehr enthaelt. ``after`` (die Arbeitskopie der PR) enthaelt "9999" noch.
    ``after - before`` enthaelt dann "9999", und der Waechter haelt das
    faelschlich fuer einen frischen Beweis dieses PRs -- rc=0, obwohl der PR
    fuer SEINE EIGENE Aenderung (provable.py) nie einen Eintrag angelegt hat.
    Mit ``git merge-base`` (dem Fix) ist ``before`` main_a, wo "9999" noch
    stand -- ``after - before`` ist leer, rc=1 bleibt bestehen.
    """
    import os

    import scripts.check_proof_ledger as gate
    import scripts.proof_ledger as ledger_mod

    # Die Klasse, nicht der Einzelfall (Gate-Fund #2, 2026-08-25): `_git()`
    # baut sich fuer die EIGENEN Aufrufe eine bereinigte Umgebung, aber
    # `gate.main()` ruft INTERN dieselben `git`-Kommandos ueber
    # `check_proof_ledger.py`s eigene subprocess.run()-Aufrufe (_changed_files/
    # _ledger_ids_at/_merge_base_commit) -- OHNE eigenes `env=`, also mit der
    # ererbten Prozessumgebung DIESES Testlaufs. Im pre-push-Gate laeuft
    # dieser Testlauf selbst INNERHALB eines Git-Hooks, der GIT_DIR/GIT_
    # WORK_TREE auf das ECHTE Repo setzt -- ungefiltert wuerden die
    # "git diff"/"git show"/"git merge-base"-Aufrufe von check_proof_ledger.py
    # dann trotz korrektem `cwd=tmp_path` das ECHTE Repo statt des frischen
    # /tmp-Testrepos befragen und mit rc=128 auf Commits scheitern, die es
    # dort nicht gibt (empirisch im Gate beobachtet). Deshalb wird die
    # Prozessumgebung DIESES Tests selbst bereinigt, nicht nur `_git()`s
    # eigene -- das deckt beide Aufrufer derselben git-Kommandos ab.
    for key in list(os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key, raising=False)

    def git(*args: str) -> str:
        return _git(tmp_path, *args)

    # Explizit statt geborgt: Startbranch per `-b` (kein `checkout -b` auf
    # einem ungeborenen HEAD, das je nach `init.defaultBranch` unterschiedlich
    # heissen kann), user.*/gpgsign/hooksPath als Repo-lokale Config statt auf
    # eine (im Gate ggf. fehlende oder anders gesetzte) globale Config zu
    # bauen -- damit weder eine fehlende Identitaet den Commit noch eine
    # fremde Signatur-/Hook-Config den Ablauf zum Stehen bringt.
    git("init", "-q", "-b", "trunk")
    git("config", "user.email", "t@t.example")
    git("config", "user.name", "t")
    git("config", "commit.gpgsign", "false")
    git("config", "core.hooksPath", "/dev/null")

    seed_ledger = (
        '[[proof]]\nid = "root-noop"\nkind = "exempt"\nclaim = "seed"\n'
        'state = "AUSGENOMMEN"\ndue_by = "2026-09-06"\nowner = "t"\n'
    )
    (tmp_path / "provable.py").write_text("v1\n")
    (tmp_path / "proof_ledger.toml").write_text(seed_ledger)
    git("add", "-A")
    git("commit", "-q", "-m", "root")

    git("checkout", "-q", "-b", "pr")
    (tmp_path / "provable.py").write_text("v2\n")
    git("commit", "-q", "-am", "pr1: aendert provable.py, kein Eintrag")

    git("checkout", "-q", "trunk", "-b", "mainline")
    with (tmp_path / "proof_ledger.toml").open("a") as fp:
        fp.write(
            '\n[[proof]]\nid = "9999"\nkind = "defect"\n'
            'claim = "fremder, noch offener Befund"\n'
            'state = "UNGESICHERT"\ndue_by = "2026-09-06"\nowner = "t"\n'
        )
    git("commit", "-q", "-am", "main_a: fremder Eintrag 9999")
    main_a = git("rev-parse", "HEAD")

    git("checkout", "-q", "pr")
    git("merge", "-q", "--no-edit", "mainline")
    pr2 = git("rev-parse", "HEAD")

    git("checkout", "-q", "mainline")
    (tmp_path / "proof_ledger.toml").write_text(seed_ledger)
    git("commit", "-q", "-am", "main_b: 9999 aufgeloest und entfernt")
    main_b = git("rev-parse", "HEAD")

    assert git("merge-base", main_b, pr2) == main_a, (
        "Testaufbau falsch: erwartete Merge-Basis ist main_a"
    )

    git("checkout", "-q", pr2)  # Arbeitskopie = das, was der PR-CI-Job sieht

    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "derive_class", lambda: frozenset({"provable.py"}))
    monkeypatch.setattr(gate, "_coupling_failures", lambda: [])
    monkeypatch.setattr(ledger_mod, "_LEDGER_PATH", tmp_path / "proof_ledger.toml")
    ledger_mod._load.cache_clear()
    try:
        rc = gate.main(["--range", f"{main_b}..{pr2}"])
        assert rc == 1, "provable.py ist beweispflichtig beruehrt, ohne eigenen Eintrag -- muss rc=1 bleiben"
    finally:
        ledger_mod._load.cache_clear()


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
    # _merge_base_commit shells out to real `git merge-base` -- irrelevant to
    # this unit (which only exercises the after-vs-before set logic), so it's
    # stubbed alongside _ledger_ids_at rather than run against fake "aaa"/
    # "bbb" refs that don't exist in this repo.
    monkeypatch.setattr(gate, "_merge_base_commit", lambda rng: "irrelevant")
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
    monkeypatch.setattr(gate, "_merge_base_commit", lambda rng: "irrelevant")
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


# --- Widerlegt-Quittung: refutation_tracked_by-Kopplung (2026-08-24) -------
#
# Ersetzt den Halter "widerlegt-kann-nicht-quittiert-werden". Symmetrisch zu
# den unreachable_because-Proben oben, nur gegen einen ANDEREN Ledger-Eintrag
# statt gegen eine Repo-Tatsache geprueft.


def test_a_refutation_holder_that_does_not_exist_is_reported(monkeypatch):
    """Kopplungsprobe, Variante 'existiert nicht' -- ein geloeschter Halter
    darf die Quittung nicht stillschweigend gueltig lassen."""
    import scripts.check_proof_ledger as gate
    from scripts.proof_ledger import ProofEntry

    fake = ProofEntry(
        id="fake-fail", kind="fix", claim="c", state="FAIL",
        due_by="2026-09-06", owner="operator",
        refutation_tracked_by="geistert-nicht", raw={},
    )
    monkeypatch.setattr(gate, "load_entries", lambda: (fake,))
    problems = gate._coupling_failures()
    assert len(problems) == 1
    assert "geistert-nicht" in problems[0]


def test_a_refutation_holder_that_is_not_a_defect_is_reported(monkeypatch):
    """Kopplungsprobe, Variante 'falsche Art' -- der Halter muss kind=="defect"
    sein, sonst ist er kein Ort, an dem Arbeit haengt."""
    import scripts.check_proof_ledger as gate
    from scripts.proof_ledger import ProofEntry

    holder = ProofEntry(
        id="holder", kind="fix", claim="c", state="OFFEN",
        due_by="2026-09-06", owner="operator", raw={},
    )
    fake = ProofEntry(
        id="fake-fail", kind="fix", claim="c", state="FAIL",
        due_by="2026-09-06", owner="operator",
        refutation_tracked_by="holder", raw={},
    )
    monkeypatch.setattr(gate, "load_entries", lambda: (holder, fake))
    problems = gate._coupling_failures()
    assert len(problems) == 1
    assert "holder" in problems[0]
    assert "kind=" in problems[0]


def test_a_refutation_holder_gone_terminal_makes_the_ack_invalid(monkeypatch):
    """Der Kern der Kopplung: wird der Halter terminal (hier: AUSGENOMMEN),
    ist die Quittung ungueltig -- der Offline-Waechter muss rot werden, nicht
    nur der Monitor still zurueckfallen."""
    import scripts.check_proof_ledger as gate
    from scripts.proof_ledger import ProofEntry

    holder = ProofEntry(
        id="klasse-h", kind="defect", claim="c", state="AUSGENOMMEN",
        due_by="2026-09-06", owner="operator", raw={},
    )
    fake = ProofEntry(
        id="fake-fail", kind="fix", claim="c", state="FAIL",
        due_by="2026-09-06", owner="operator",
        refutation_tracked_by="klasse-h", raw={},
    )
    monkeypatch.setattr(gate, "load_entries", lambda: (holder, fake))
    problems = gate._coupling_failures()
    assert len(problems) == 1
    assert "klasse-h" in problems[0]


def test_a_valid_refutation_holder_passes(monkeypatch):
    """Positivkontrolle: ein offener defect-Halter macht die Kopplung still."""
    import scripts.check_proof_ledger as gate
    from scripts.proof_ledger import ProofEntry

    holder = ProofEntry(
        id="klasse-h", kind="defect", claim="c", state="UNGESICHERT",
        due_by="2026-09-06", owner="operator", raw={},
    )
    fake = ProofEntry(
        id="fake-fail", kind="fix", claim="c", state="FAIL",
        due_by="2026-09-06", owner="operator",
        refutation_tracked_by="klasse-h", raw={},
    )
    monkeypatch.setattr(gate, "load_entries", lambda: (holder, fake))
    assert gate._coupling_failures() == []


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


# --- tv_legend_click: leere Beobachtung ist kein PASS (2026-08-24) ---------
#
# Coordinator-Fund am Live-Monitor: ein Log OHNE openSettingsForScript-Spur
# (Verify-/Repair-Lauf, die Klick-Operation lief nie) fiel vor dem Fix bis
# zum PASS/all_dialogs_opened durch -- "kein Fehlermarker gefunden" und "nie
# versucht" sind verschiedene Aussagen. GEMESSEN an Lauf 32745395799: genau
# das ist am 2026-08-24 live passiert, bevor der Fix landete (ein
# Verify-/Repair-Lauf haette einen Klasse-H-Fix "bewiesen", den er nie
# angefasst hat).


def test_a_log_without_the_settings_marker_is_pending_not_passed():
    """Der Kern: keine Klick-Spur heisst 'nie versucht', nicht 'bestanden'."""
    from scripts.proof_judges import load_judge

    judge = load_judge("tv_legend_click")
    verdict = judge.judge({"log": "irgendein Log ohne jede Skript-Spur"}, None)
    assert verdict.state == "STEHT_AUS", verdict
    assert verdict.branch == "settings_never_attempted", verdict


def test_the_recorded_verify_only_run_is_pending_not_passed():
    """Positivkontrolle am ECHTEN, aufgezeichneten Lauf: 32745395799 war der
    reale Fall, den der Coordinator am Live-Monitor gefunden hat -- ein
    Verify-/Repair-Lauf, der Klasse H nie angefasst hat."""
    from scripts.proof_judges import corpus_for, load_judge

    corpus = dict(corpus_for("tv_legend_click"))
    judge = load_judge("tv_legend_click")
    verdict = judge.judge(corpus["32745395799"], None)
    assert verdict.state == "STEHT_AUS", verdict
    assert verdict.branch == "settings_never_attempted", verdict


def test_identity_mismatch_still_wins_when_the_settings_marker_is_present():
    """Gegenprobe: die bestehenden Zweige bleiben unberuehrt. Ein Log MIT
    identity-mismatch bleibt FAIL -- der neue Zweig steht in der
    Pruefreihenfolge NACH identity-mismatch und darf ihn nicht abfangen."""
    from scripts.proof_judges import corpus_for, load_judge

    corpus = dict(corpus_for("tv_legend_click"))
    judge = load_judge("tv_legend_click")
    verdict = judge.judge(corpus["32556181388"], None)
    assert verdict.state == "FAIL", verdict
    assert verdict.branch == "identity_mismatch", verdict


def test_identity_mismatch_wins_even_without_a_literal_settings_marker():
    """Randfall explizit gepinnt, nicht nur am realen Korpus angenommen: ein
    synthetisches Log mit identity-mismatch, aber OHNE die woertliche
    openSettingsForScript-Spur, muss trotzdem FAIL bleiben -- die Reihenfolge
    (miss -> mismatch -> Abwesenheit -> Praesenz) darf identity-mismatch
    nicht von settings_never_attempted ueberholen lassen."""
    from scripts.proof_judges import load_judge

    judge = load_judge("tv_legend_click")
    verdict = judge.judge({"log": "... identity-mismatch SMC X != SMC Y ..."}, None)
    assert verdict.state == "FAIL", verdict
    assert verdict.branch == "identity_mismatch", verdict


# --- tv_legend_click: Anwesenheit ist kein Erfolg (2026-08-24, Teil 2) -----
#
# Coordinator-Fund am Live-Monitor, zweite Runde: der Anwesenheits-Zweig
# (vormals dialog_stuck_without_miss/PRUEFEN) feuerte auf JEDEM Log mit
# mindestens einem openSettingsForScript-Versuch, egal ob er gelang oder
# haengen blieb -- derselbe Fehler wie eben bei settings_never_attempted,
# nur eine Stufe hoeher: "Fehlermarker A nicht gefunden" wurde als "Erfolg"
# gefuehrt, obwohl das Log Erfolg und Timeout sehr wohl unterscheidet (Suffix
# ": Step timed out" auf derselben Zeile, GEMESSEN an Lauf 32729006391).


def test_a_settings_timeout_without_a_mismatch_trace_fails():
    """Der Kern: ein Timeout ist ein beobachteter Fehlschlag, keine
    Grauzone -- FAIL statt des alten, unbestimmten PRUEFEN."""
    from scripts.proof_judges import load_judge

    judge = load_judge("tv_legend_click")
    log = (
        "[tv-step] start openSettingsForScript:SMC Long-Dip Alerts\n"
        "[tv-step] error openSettingsForScript:SMC Long-Dip Alerts (60002ms): "
        "Step timed out after 60000ms: openSettingsForScript:SMC Long-Dip Alerts"
    )
    verdict = judge.judge({"log": log}, None)
    assert verdict.state == "FAIL", verdict
    assert verdict.branch == "settings_dialog_timed_out", verdict


def test_a_settings_success_without_a_timeout_is_a_pass():
    """Gegenprobe zum Kern: openSettingsForScript OHNE Timeout ist jetzt
    wieder ein echter PASS -- ueber POSITIVE Evidenz (lief durch), nicht ueber
    Abwesenheit von Fehlermarkern."""
    from scripts.proof_judges import load_judge

    judge = load_judge("tv_legend_click")
    log = (
        "[tv-step] start openSettingsForScript:SMC Decision Board\n"
        "[tv-step] ok openSettingsForScript:SMC Decision Board (4332ms)"
    )
    verdict = judge.judge({"log": log}, None)
    assert verdict.state == "PASS", verdict
    assert verdict.branch == "all_dialogs_opened", verdict


def test_the_recorded_healthy_run_reaches_pass_with_real_evidence():
    """Positivkontrolle am ECHTEN, bereits aufgezeichneten Korpus: Lauf
    32357049150 (20 openSettingsForScript-Treffer, 0 Step-timed-out, 0
    identity-mismatch, 0 hit-target-miss) war bisher der Beleg fuer das alte
    PRUEFEN -- unter der neuen Logik ist er der Beleg fuer PASS. Der Zweig
    ist damit wieder per echter Evidenz gedeckt, keine Deklaration mehr
    noetig (siehe die entfernte all_dialogs_opened-Deklaration in
    proof_ledger.toml)."""
    from scripts.proof_judges import corpus_for, load_judge

    corpus = dict(corpus_for("tv_legend_click"))
    judge = load_judge("tv_legend_click")
    verdict = judge.judge(corpus["32357049150"], None)
    assert verdict.state == "PASS", verdict
    assert verdict.branch == "all_dialogs_opened", verdict


def test_a_timeout_on_an_unrelated_step_does_not_fail_the_settings_check():
    """Praezisions-Gegenprobe: runTrackedStep traegt den 60s-Deckel fuer
    MEHRERE getrackte Schritte, nicht nur openSettingsForScript. Ein "Step
    timed out" fuer einen ANDEREN Schritt anderswo im selben Log darf einen
    ansonsten erfolgreichen openSettingsForScript-Durchlauf nicht faelschlich
    als FAIL fuehren -- genau die Verwechslung (Ganzlog-Substring statt
    Aussage ueber DIESES Ereignis), die dialog_stuck_without_miss ausmachte.
    Deshalb wird pro ZEILE geprueft, nicht ueber den gesamten Log-Text."""
    from scripts.proof_judges import load_judge

    judge = load_judge("tv_legend_click")
    log = (
        "[tv-step] start openSettingsForScript:SMC Decision Board\n"
        "[tv-step] ok openSettingsForScript:SMC Decision Board (4332ms)\n"
        "[tv-step] error closeModal (60003ms): Step timed out after 60000ms: closeModal"
    )
    verdict = judge.judge({"log": log}, None)
    assert verdict.state == "PASS", verdict
    assert verdict.branch == "all_dialogs_opened", verdict


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
    assert 'select(.status=="completed")' in query
    # NACHGESCHAERFT 2026-08-24. Vorher stand hier `assert "conclusion" not in
    # query` -- die Abfrage durfte das Wort ueberhaupt nicht enthalten. Das war
    # zu grob: seit dem cancelled-Ausschluss nennt sie `conclusion`, aber
    # AUSSCHLIESSLICH um abgebrochene Laeufe zu verwerfen (die strukturell nie
    # ein Artefakt hochladen). Die geschuetzte Eigenschaft ist nicht "das Wort
    # kommt nicht vor", sondern "ein FAILURE-Lauf bleibt ein gueltiger Zeuge"
    # -- Lauf 32620808573 war conclusion=failure und tat exakt das Richtige.
    # Diese Zusicherung ist damit nicht aufgeweicht, sondern praeziser: sie
    # laesst genau einen Ausschluss zu und verbietet jeden anderen.
    assert 'conclusion!="cancelled"' in query, (
        "der cancelled-Ausschluss fehlt -- abgebrochene Laeufe wuerden wieder "
        "als Zeugen gekuert und der Download scheiterte"
    )
    verworfene = set(re.findall(r'\.conclusion!="(\w+)"', query))
    assert verworfene == {"cancelled"}, (
        f"nur 'cancelled' darf ausgeschlossen werden, hier auch: {verworfene - {'cancelled'}}"
    )
    assert "success" not in query and "failure" not in query, (
        "die Zeugenwahl darf NICHT nach Erfolg filtern -- 32620808573 war rot "
        "und war der richtige Zeuge"
    )


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


# --- Critical 1 (2026-08-24): ein API-Totalausfall darf nie wie OK aussehen
#
# Vorher bildete _gh() JEDEN Nicht-Null-Rueckgabecode auf "" ab, ohne
# Diagnose. Ein Totalausfall (403 / abgelaufener PAT / Rate-Limit / kein
# Netz) sah dadurch identisch aus wie ein leeres, aber gueltiges Ergebnis:
# newest_witness() lieferte "", die Ausgabe sagte KEIN_ZEUGE, und classify()
# nahm fuer ein deklariertes PASS den TERMINAL_STATES-Kurzschluss OHNE je
# versucht zu haben, den Zeugen zu pruefen -- zehn Zeilen OK, exit 0, kein
# Job-Fail, drei davon PASS-Eintraege, bestaetigt auf der Grundlage von
# nichts.


def test_gh_raises_on_a_failed_call_instead_of_returning_empty(monkeypatch):
    """Direkte Rueckbau-Probe an _gh() selbst: ein fehlgeschlagener Aufruf
    muss GhCallError werfen, mit Rueckgabecode und STDERR im Text -- nicht
    mehr "" zurueckgeben. Rueckgebaut (Bericht, Fix-Runde 1): `if
    proc.returncode != 0: raise ...` durch `return proc.stdout if
    proc.returncode == 0 else ""` ersetzt -> dieser Test wird rot
    (`Failed: DID NOT RAISE`), zurueckgesetzt -> wieder gruen."""
    import subprocess

    import scripts.judge_proof_ledger as mod

    class FakeCompletedProcess:
        returncode = 1
        stdout = ""
        stderr = "gh: Bad credentials (HTTP 403)"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeCompletedProcess())
    with pytest.raises(mod.GhCallError, match="403"):
        mod._gh("api", "whatever")


def test_a_total_api_outage_never_reads_as_ok(monkeypatch, tmp_path):
    """DER Test fuer Critical 1: beweist, dass ein Totalausfall der API NICHT
    zu lauter OK-Meldung fuehrt. _gh() wird komplett durch einen Stub
    ersetzt, der bei JEDEM Aufruf GhCallError wirft (wie bei 403 / kein
    Netz), und main() laeuft gegen das ECHTE proof_ledger.toml.

    Rueckbau-Probe (Bericht, Fix-Runde 1): mit dem VORHERIGEN classify() (ohne
    ``unreachable``-Parameter, TERMINAL_STATES-Kurzschluss ungeschuetzt)
    wollte dieser Test bei Eintrag 5013 (state=PASS) ``class != "OK"``
    pruefen -- rot, weil der Kurzschluss unabhaengig vom Ausfall OK lieferte.
    Mit dem Fix: gruen.
    """
    import json

    import scripts.judge_proof_ledger as mod

    def boom(*args: str) -> str:
        raise mod.GhCallError("boom: rc=1: HTTP 403: Bad credentials")

    monkeypatch.setattr(mod, "_gh", boom)
    out_path = tmp_path / "report.json"
    rc = mod.main(["--today", "2026-08-24", "--json", str(out_path)])
    rows = json.loads(out_path.read_text(encoding="utf-8"))

    assert rc != 0, "Totalausfall darf nicht still mit Exit 0 enden"

    # Eintraege, die aktiv beurteilt werden (evidence_source == "artifact",
    # kind == "fix", judge gesetzt, echter merged_at) -- darunter DREI
    # deklarierte PASS-Eintraege (5013, 5025, 5020), die vor dem Fix ueber
    # den TERMINAL_STATES-Kurzschluss stillschweigend als OK durchliefen.
    judged_ids = {"5013", "5025", "5020"}
    judged_rows = [r for r in rows if r["id"] in judged_ids]
    assert len(judged_rows) == 3, "Positivkontrolle: erwartete PASS-Eintraege fehlen im Report"
    for row in judged_rows:
        assert row["measured"].startswith("KEIN_URTEIL (API nicht erreichbar")
        assert row["measured"] != "KEIN_ZEUGE"
        assert row["class"] != "OK", row


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


def test_an_entry_without_merged_at_is_marked_unjudged_not_missing_witness():
    """Pinnt den EXAKTEN Text des merged_at-Zweigs, nicht nur, dass irgendein
    Grund zurueckkommt.

    UMGEZOGEN 2026-08-24: Diese Zusicherung pinnte urspruenglich den Text des
    job_log-Zweigs ("job_log — Monitor holt keine Logs"). Dieser Zweig ist
    ENTFERNT, seit der Monitor Job-Logs wirklich holt -- die Zusicherung ist
    also nicht aufgeweicht worden, ihr Gegenstand ist verschwunden. Was
    erhalten bleibt, ist ihr eigentlicher Wert: den KONKRETEN Zweig pinnen,
    nicht eine Teilzeichenkette. Der Fund des Pruefers, der dazu fuehrte:
    ``repr("job_log")`` enthaelt "job_log", also blieb ein ``in``-Test auch
    dann gruen, wenn der generische Fallback statt des gemeinten Zweigs
    feuerte. Dieselbe Falle steht hier weiterhin offen -- ``repr('')``
    enthaelt keine sprechende Zeichenkette, aber ein ``in``-Test auf
    "merged_at" waere ebenso blind gegen einen falschen Zweig.

    Die neue Deckung fuer job_log liegt bei
    ``test_a_job_log_entry_is_no_longer_skipped``.
    """
    from scripts.judge_proof_ledger import unjudged_reason
    from scripts.proof_ledger import ProofEntry

    entry = ProofEntry(
        id="5018", kind="fix", claim="c", state="OFFEN", due_by="2026-12-31",
        owner="operator", judge="tv_legend_click", witness="tv-save-consumer-source",
        witness_job="save", evidence_source="job_log", raw={},
    )
    assert unjudged_reason(entry) == "merged_at='' ist kein ISO-8601-Zeitstempel (Platzhalter?)"


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
        witness_job="save", evidence_source="artifact",
        raw={"merged_at": "2026-08-22T16:42:54Z"},
    )
    assert unjudged_reason(entry) == ""


def test_an_unparseable_merged_at_is_named_not_silently_skipped():
    """Der merged_at-Platzhalter (2026-08-24): ``"<wird beim Merge
    nachgetragen>"`` (der aktuelle Wert von task7-proof-ledger-monitor) macht
    in newest_witness() JEDEN Zeitstempelvergleich strukturell False ('<' ist
    ASCII-groesser als jede Ziffer) -- der Zweig lief bislang STILL in ""
    durch und erschien als KEIN_ZEUGE, ununterscheidbar von einer echten
    erfolglosen Zeugensuche. unjudged_reason() muss das jetzt VOR der Suche
    abfangen und benennen. Rueckbau-Probe (Bericht, Fix-Runde 1): den
    merged_at-Formzweig aus unjudged_reason() entfernt -> dieser Test wird
    rot (`assert '' != ''` schlaegt fehl, weil reason wieder "" ist),
    zurueckgesetzt -> wieder gruen."""
    from scripts.judge_proof_ledger import unjudged_reason
    from scripts.proof_ledger import ProofEntry

    entry = ProofEntry(
        id="task7-proof-ledger-monitor", kind="fix", claim="c", state="OFFEN",
        due_by="2026-12-31", owner="operator", judge="proof_ledger_monitor_self",
        witness="proof-ledger-monitor", witness_job="judge", evidence_source="artifact",
        raw={"merged_at": "<wird beim Merge nachgetragen>"},
    )
    reason = unjudged_reason(entry)
    assert reason != ""
    assert reason != "KEIN_ZEUGE"
    assert "ISO-8601" in reason


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


def test_the_judge_job_carries_actions_read_for_its_three_gh_api_calls():
    """Pinnt ``actions: read`` auf dem ``judge``-Job wortwoertlich, nicht nur
    als Kommentar. Restbefund aus dem Abschluss-Review (2026-08-24): der
    Reviewer hat die Zeile entfernt und die volle 47-Datei-Waechter-Batterie
    gefahren -- identisches (gruenes) Ergebnis. Nichts schuetzte sie.

    Der Job braucht das Recht fuer alle drei GitHub-API-Aufrufe in
    ``scripts/judge_proof_ledger.py`` (Lauflisten-Abfrage in
    ``newest_witness()``, Job-Liste desselben Laufs, ``gh run download`` in
    ``_judge_entry()``) -- fehlt es, traegt der Fallback-Token
    (``secrets.GH_PAT`` leer -> `github.token`) nur noch ``contents: read``
    und alle drei Aufrufe scheitern mit 403 (``GhCallError``), was als
    ``KEIN_URTEIL (API nicht erreichbar: ...)`` durchlaeuft statt als klarer
    Konfigurationsfehler aufzufallen. Dasselbe Muster pinnen
    ``test_workflow_tv_save_consumer_source_contract.py`` (Zeile ~1768,
    ``wf["permissions"].get("actions") == "read"``) und
    ``test_phase_b_promotion_readiness_workflow_contract.py``
    (``test_permissions_minimal_read_only``) -- hier auf Job-Ebene, weil
    dieser Workflow ``actions: read`` nicht auf Workflow-Ebene traegt
    (dort nur ``contents: read``, s. o.), sondern per Least-Privilege im
    ``judge``-Job selbst deklariert.

    Rueckbau-Probe (Bericht dieser Aenderung): Zeile ``actions: read`` unter
    `jobs.judge.permissions` entfernt -> dieser Test wird rot; Zeile wieder
    eingesetzt -> gruen.
    """
    import yaml

    from scripts.proof_ledger import ROOT

    path = ROOT / ".github" / "workflows" / "proof-ledger-monitor.yml"
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    job_permissions = workflow["jobs"]["judge"]["permissions"]
    assert job_permissions.get("actions") == "read", (
        "the judge job's gh api / gh run download calls (newest_witness(), "
        "_judge_entry()) need actions: read on the job itself; the workflow-level "
        "permissions block only grants contents: read"
    )


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


# --- Log-basierte Urteiler im Monitor (2026-08-24) --------------------------


def _job_log_entry(**over):
    """Ein job_log-Eintrag wie #5018/#5027, per Schluesselwort anpassbar."""
    from scripts.proof_ledger import ProofEntry

    fields = dict(
        id="5018",
        kind="fix",
        claim="c",
        state="OFFEN",
        due_by="2026-12-31",
        owner="operator",
        judge="tv_legend_click",
        witness="tv-save-consumer-source",
        witness_job="save",
        evidence_source="job_log",
        artifact="",
        version_probe="KEINE",
        raw={"merged_at": "2026-08-22T20:32:49Z"},
    )
    fields.update(over)
    return ProofEntry(**fields)


def test_a_job_log_entry_is_no_longer_skipped():
    """Solange unjudged_reason() hier einen Grund liefert, kann der Urteiler
    noch so gut sein — main() ruft ihn nie auf."""
    from scripts.judge_proof_ledger import unjudged_reason

    assert unjudged_reason(_job_log_entry()) == ""


def test_the_job_log_path_picks_the_named_job_not_the_first_one():
    """Der Job wird nach NAMEN gefiltert, nicht nach Position.

    Ein Lauf hat mehrere Jobs. Wird der falsche genommen, urteilt der
    Monitor ueber ein fremdes Log und meldet ein plausibles, falsches
    Ergebnis — schlimmer als kein Urteil."""
    import scripts.judge_proof_ledger as mod

    seen = {}

    def fake_gh(*args):
        if args[0] == "api" and "/jobs?" in args[1]:
            # Der Aufruf MUSS nach dem Namen filtern; wir geben die Id zurueck,
            # die zu 'save' gehoert, nur wenn der Filter sie auch nennt.
            assert "save" in args[-1], f"Job-Filter nennt den Namen nicht: {args[-1]}"
            return "97105473851\n"
        if args[0] == "api" and args[1].endswith("/logs"):
            seen["log_url"] = args[1]
            return "…identity-mismatch SMC Long-Dip Alerts != SMC Setup Check…\n"
        raise AssertionError(f"unerwarteter gh-Aufruf: {args}")

    monkeypatch_target = mod
    old = monkeypatch_target._gh
    monkeypatch_target._gh = fake_gh
    try:
        log = mod._fetch_job_log(_job_log_entry(), "32556181388")
    finally:
        monkeypatch_target._gh = old

    assert "97105473851" in seen["log_url"], seen
    assert "identity-mismatch" in log


def test_the_job_log_reaches_the_judge_as_a_log_field(monkeypatch):
    """tv_legend_click erwartet {"log": <text>} — nicht den nackten String und
    nicht das Artefakt-Schema."""
    import scripts.judge_proof_ledger as mod

    entry = _job_log_entry()
    monkeypatch.setattr(mod, "newest_witness", lambda e: "32556181388")
    monkeypatch.setattr(mod, "_fetch_job_log", lambda e, r: "…-hit-target-miss…")
    verdict, run_id = mod._judge_entry(entry)

    assert run_id == "32556181388"
    assert verdict is not None
    assert verdict.branch == "click_missed_its_row", verdict


def test_a_measured_fail_on_an_open_entry_is_loud():
    """Der Kern: ein widerlegter Fix darf nicht bis zum Fristablauf schweigen.
    Vorher lief OFFEN + FAIL ueber den Schluss von classify() als OK durch."""
    from scripts.judge_proof_ledger import classify
    from scripts.proof_judges import Verdict

    entry = _job_log_entry(state="OFFEN", due_by="2026-12-31")
    assert classify(entry, Verdict("FAIL", branch="identity_mismatch"), "2026-08-24") == "WIDERLEGT"


def test_a_measured_fail_on_a_declared_pass_stays_a_contradiction():
    """WIDERSPRUCH und WIDERLEGT sind verschiedene Aussagen: das Ledger luegt
    gegen der Fix wirkt nicht. Beide laut, aber nicht dasselbe."""
    from scripts.judge_proof_ledger import classify
    from scripts.proof_judges import Verdict

    entry = _job_log_entry(state="PASS", pass_kind="live", witness_run="1")
    assert classify(entry, Verdict("FAIL", branch="identity_mismatch"), "2026-08-24") == "WIDERSPRUCH"


def test_a_measured_pass_on_an_open_entry_stays_quiet():
    """Gegenprobe: WIDERLEGT darf nicht jedes Urteil einfaerben."""
    from scripts.judge_proof_ledger import classify
    from scripts.proof_judges import Verdict

    entry = _job_log_entry(state="OFFEN", due_by="2026-12-31")
    assert classify(entry, Verdict("PASS", branch="all_dialogs_opened"), "2026-08-24") == "OK"


# --- Widerlegt-Quittung: classify()s refutation_acknowledged (2026-08-24) --
#
# Ersetzt den Halter "widerlegt-kann-nicht-quittiert-werden". Der urspruengliche
# Defekt: state="FAIL" + gemessen FAIL lief IMMER als WIDERLEGT, unabhaengig
# vom deklarierten Zustand -- der WIDERLEGT-Zweig griff VOR dem
# TERMINAL_STATES-Kurzschluss. classify() bleibt rein: refutation_acknowledged
# wird fertig hereingereicht, nicht selbst nachgeschlagen.


def test_an_acknowledged_fail_is_quiet():
    """Der Kern des Fixes: state=FAIL + gemessen FAIL + ein zuvor gepruefter,
    gueltiger Halter ist quittiert -- OK statt WIDERLEGT."""
    from scripts.judge_proof_ledger import classify
    from scripts.proof_judges import Verdict

    entry = _job_log_entry(state="FAIL", due_by="2026-12-31", refutation_tracked_by="klasse-h")
    assert classify(
        entry, Verdict("FAIL", branch="identity_mismatch"), "2026-08-24",
        refutation_acknowledged=True,
    ) == "OK"


def test_a_declared_fail_without_acknowledgement_stays_loud():
    """Regressionsprobe fuer den urspruenglichen Defekt: derselbe deklarierte
    FAIL-Eintrag bleibt WIDERLEGT, solange refutation_acknowledged nicht wahr
    ist (Halter fehlt, ist kein defect, oder ist terminal geworden -- das
    wird in main() geprueft, hier nur die Konsequenz in classify())."""
    from scripts.judge_proof_ledger import classify
    from scripts.proof_judges import Verdict

    entry = _job_log_entry(state="FAIL", due_by="2026-12-31", refutation_tracked_by="klasse-h")
    assert classify(
        entry, Verdict("FAIL", branch="identity_mismatch"), "2026-08-24",
    ) == "WIDERLEGT"


def test_acknowledgement_never_leaks_onto_a_non_fail_declaration():
    """Verteidigung in der Tiefe: selbst wenn main() faelschlich
    refutation_acknowledged=True fuer einen deklarierten OFFEN-Eintrag
    berechnen wuerde, verlangt classify() zusaetzlich entry.state == 'FAIL'."""
    from scripts.judge_proof_ledger import classify
    from scripts.proof_judges import Verdict

    entry = _job_log_entry(state="OFFEN", due_by="2026-12-31")
    assert classify(
        entry, Verdict("FAIL", branch="identity_mismatch"), "2026-08-24",
        refutation_acknowledged=True,
    ) == "WIDERLEGT"


def test_main_looks_up_the_real_klasse_h_holder_for_5018_and_5027(monkeypatch, tmp_path):
    """End-to-End gegen das ECHTE Ledger: main() muss den
    refutation_tracked_by-Halter selbst nachschlagen (das ist neuer Code in
    main(), nicht nur in classify() isoliert getestet). klasse-h steht im
    echten proof_ledger.toml auf UNGESICHERT (nicht-terminal); #5018 und #5027
    tragen refutation_tracked_by = "klasse-h". Ein gemessenes FAIL fuer beide
    muss also OK liefern, nicht WIDERLEGT -- das ist die eigentliche Reparatur,
    die den Cron 06:47Z wieder unterscheidungsfaehig macht."""
    import json

    import scripts.judge_proof_ledger as mod
    from scripts.proof_judges import Verdict

    def fake_judge_entry(entry):
        if entry.id in {"5018", "5027"}:
            return Verdict("FAIL", branch="identity_mismatch"), "32729006391"
        return None, ""

    monkeypatch.setattr(mod, "_judge_entry", fake_judge_entry)
    out_path = tmp_path / "report.json"
    mod.main(["--today", "2026-08-24", "--json", str(out_path)])
    rows = json.loads(out_path.read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in rows}

    assert by_id["5018"]["declared"] == "FAIL", "Voraussetzung verletzt: #5018 nicht mehr FAIL"
    assert by_id["5027"]["declared"] == "FAIL", "Voraussetzung verletzt: #5027 nicht mehr FAIL"
    assert by_id["5018"]["class"] == "OK", by_id["5018"]
    assert by_id["5027"]["class"] == "OK", by_id["5027"]


# --- Zeugenwahl: abgebrochene Laeufe sind keine Zeugen (2026-08-24) ---------


def test_newest_witness_skips_cancelled_runs():
    """Ein abgebrochener Lauf laedt NIE ein Artefakt hoch -- die
    upload-Bedingung im Workflow verlangt success oder failure. Wird er
    trotzdem als Zeuge gewaehlt, scheitert der Download und der Monitor meldet
    "API nicht erreichbar", obwohl die API einwandfrei antwortet.

    GEMESSEN 2026-08-24 an Lauf 32729923497: status=completed,
    conclusion=cancelled, save-Job cancelled, 0 Artefakte -- und
    newest_witness() kuerte ihn zum Zeugen, weil der Filter nur auf
    status=="completed" prueft. Das Wissen stand in der Vorgaenger-Sonde
    (tv_gate_probe_check.sh) und ging beim Portieren verloren."""
    import scripts.judge_proof_ledger as mod

    assert 'conclusion!="cancelled"' in inspect.getsource(mod.newest_witness), (
        "der Laufliste-Filter schliesst abgebrochene Laeufe nicht aus"
    )


def test_newest_witness_skips_a_superseded_job(monkeypatch):
    """Dieselbe Klasse wie der cancelled-Ausschluss, eine Ebene tiefer: der
    LAUF ist gruen (status completed, conclusion success, besteht den
    cancelled-Filter klaglos), aber der ZEUGEN-JOB wurde vom Supersessions-
    Gate der TV-Session-Gruppe uebersprungen (by design seit #4998 -- das Gate
    cancelt nie, es ueberspringt den nachgelagerten 'save'-Job). Ein
    uebersprungener Job hat 0 Steps, kein Log, kein Artefakt -- aber einen
    FORM-gueltigen ``started_at``, besteht also die Zeitstempel-Formpruefung
    und wuerde ohne eigenen Ausschluss zum Zeugen gekuert.

    GEMESSEN 2026-08-24 an Lauf 32754064777: status=completed,
    conclusion=success, save-Job completed/skipped,
    started_at=2026-08-24T19:50:53Z. Das Wissen stand in der Vorgaenger-Sonde
    (tv_gate_probe_check.sh, eigenes Urteil "PASS -- SUPERSEDED") und ging
    beim Portieren zum DRITTEN Mal verloren -- nach dem cancelled-Ausschluss
    und der Job-Namensfilterung.

    Der Fake bildet echtes jq-Verhalten nach (wertet den ``name``- UND, falls
    in der tatsaechlich gebauten Query vorhanden, den
    ``conclusion!="skipped"``-Filter selbst aus) statt ein vorgefertigtes
    Ergebnis zurueckzugeben -- eine entfernte Ausschlussklausel im
    Quelltext macht diesen Test dadurch wirklich rot, nicht nur eine eigene
    Fixture-Annahme.
    """
    import scripts.judge_proof_ledger as mod
    from scripts.proof_ledger import ProofEntry

    entry = ProofEntry(
        id="x", kind="fix", claim="c", state="OFFEN", due_by="2026-12-31",
        owner="operator", witness="tv-save-consumer-source", witness_job="save",
        raw={"merged_at": "2026-08-22T16:42:54Z"},
    )
    # Neuester Lauf zuerst, wie die echte Laufliste sie liefert.
    jobs_by_run = {
        "32754064777": [
            {"name": "supersession-gate", "conclusion": "success",
             "started_at": "2026-08-24T19:50:41Z"},
            {"name": "save", "conclusion": "skipped",
             "started_at": "2026-08-24T19:50:53Z"},
        ],
        "32729006391": [
            {"name": "save", "conclusion": "failure",
             "started_at": "2026-08-24T12:47:00Z"},
        ],
    }

    def fake(*args: str) -> str:
        joined = " ".join(args)
        if "/runs?per_page=50" in joined:
            return "32754064777\n32729006391\n"
        for run_id, jobs in jobs_by_run.items():
            if f"/runs/{run_id}/jobs" not in joined:
                continue
            query = args[-1]
            candidates = [j for j in jobs if j["name"] == entry.witness_job]
            if 'conclusion!="skipped"' in query:
                candidates = [j for j in candidates if j["conclusion"] != "skipped"]
            return candidates[0]["started_at"] if candidates else ""
        return ""

    monkeypatch.setattr(mod, "_gh", fake)
    assert mod.newest_witness(entry) == "32729006391", (
        "der Lauf mit uebersprungenem save-Job wurde als Zeuge gekuert, statt "
        "auf den naechsten Lauf mit einem save-Job zurueckzufallen, der "
        "wirklich lief"
    )


def test_newest_witness_still_accepts_a_red_run_as_a_witness(monkeypatch):
    """Gegenprobe zur Vorgabe: der neue skipped-Ausschluss darf success/
    failure als Zeugen-JOB-Conclusion nicht anfassen -- ein roter Lauf bleibt
    ein gueltiger Zeuge (32620808573 war conclusion=failure und tat exakt das
    Richtige). Explizit nachgemessen, nicht angenommen: derselbe
    jq-nachbildende Fake wie oben, hier mit einem save-Job auf
    conclusion=failure statt skipped."""
    import scripts.judge_proof_ledger as mod
    from scripts.proof_ledger import ProofEntry

    entry = ProofEntry(
        id="5013", kind="fix", claim="c", state="OFFEN", due_by="2026-12-31",
        owner="operator", witness="tv-save-consumer-source", witness_job="save",
        raw={"merged_at": "2026-08-22T16:42:54Z"},
    )
    jobs_by_run = {
        "32620808573": [
            {"name": "save", "conclusion": "failure",
             "started_at": "2026-08-23T05:38:38Z"},
        ],
    }

    def fake(*args: str) -> str:
        joined = " ".join(args)
        if "/runs?per_page=50" in joined:
            return "32620808573\n"
        for run_id, jobs in jobs_by_run.items():
            if f"/runs/{run_id}/jobs" not in joined:
                continue
            query = args[-1]
            candidates = [j for j in jobs if j["name"] == entry.witness_job]
            if 'conclusion!="skipped"' in query:
                candidates = [j for j in candidates if j["conclusion"] != "skipped"]
            return candidates[0]["started_at"] if candidates else ""
        return ""

    monkeypatch.setattr(mod, "_gh", fake)
    assert mod.newest_witness(entry) == "32620808573", (
        "ein roter (conclusion=failure) Zeugen-Job wurde faelschlich verworfen"
    )


def test_a_missing_artifact_is_not_reported_as_an_api_outage(monkeypatch):
    """"Artefakt in diesem Lauf nicht vorhanden" und "API nicht erreichbar"
    sind verschiedene Aussagen. Sie zu verschmelzen erzeugt einen lauten
    Fehlalarm ueber eine gesunde API -- und verdeckt zugleich den echten
    Befund (der Zeuge trug keine Evidenz)."""
    import scripts.judge_proof_ledger as mod

    entry = _job_log_entry(evidence_source="artifact", artifact="x-y", judge="tv_partial_save")
    monkeypatch.setattr(mod, "newest_witness", lambda e: "999")

    def boom(*args):
        if args[0] == "run":
            raise mod.GhCallError("gh run download ... -> rc=1: no valid artifacts found to download")
        return ""

    monkeypatch.setattr(mod, "_gh", boom)
    verdict, run_id = mod._judge_entry(entry)

    assert verdict is None
    assert run_id == "999"


def test_a_witness_that_could_not_testify_is_not_an_accusation():
    """STEHT_AUS auf einem deklarierten PASS heisst "dieser Lauf hat den Zweig
    nicht erreicht" -- nicht "das Ledger luegt". Der Eintrag traegt seinen
    eigenen Beleg (witness_run); ein spaeterer Lauf, der nichts sagen konnte,
    widerlegt ihn nicht.

    GEMESSEN 2026-08-24 an Lauf 32729006391: er starb an Klasse H
    (identity_mismatch), erreichte die Save-Phase nie und lieferte fuer #5013
    save_phase_never_reached. Als WIDERSPRUCH gemeldet waere das eine falsche
    Anschuldigung gegen das Ledger -- und wuerde zugleich die echte Information
    verdecken, naemlich dass der Zweig seit Tagen nicht mehr erreicht wird.
    Deshalb LAUT, aber unter eigenem Namen."""
    from scripts.judge_proof_ledger import classify
    from scripts.proof_judges import Verdict

    entry = _job_log_entry(state="PASS", pass_kind="live", witness_run="32620808573")
    assert classify(entry, Verdict("STEHT_AUS", branch="save_phase_never_reached"), "2026-08-24") == "NICHT_ERREICHT"


def test_a_declared_pass_measured_fail_stays_an_accusation():
    """Gegenprobe zur Trennung: FAIL bleibt WIDERSPRUCH. Wer beides
    verschmilzt, verliert die Unterscheidung zwischen 'das Ledger luegt' und
    'dieser Lauf konnte nichts sagen'."""
    from scripts.judge_proof_ledger import classify
    from scripts.proof_judges import Verdict

    entry = _job_log_entry(state="PASS", pass_kind="live", witness_run="32620808573")
    assert classify(entry, Verdict("FAIL", branch="identity_mismatch"), "2026-08-24") == "WIDERSPRUCH"
