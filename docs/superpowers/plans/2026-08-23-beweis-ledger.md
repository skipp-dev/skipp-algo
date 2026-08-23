# Beweis-Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ein gemergter Fix, dessen Wirkung die Testsuite prinzipiell nicht sehen kann, bekommt einen Halter mit Frist, Besitzer und maschinellem Urteil — und ein Urteilszweig, den kein echtes Artefakt je erreicht hat, wird rot statt still.

**Architecture:** Eine TOML-Quelle (`proof_ledger.toml`) mit genau einem Loader. Ein Offline-Wächter in fast-gates erzwingt Aufnahme, Wohlgeformtheit und Anti-Willkür-Kopplung — ohne Netz. Reine Urteiler unter `scripts/proof_judges/` entscheiden über Evidenz*inhalt*, nie über die Lauf-Conclusion; ihre Zweige werden per AST aus dem Quelltext abgeleitet und gegen ein Korpus echter Artefakte auf Erreichbarkeit geprüft. Ein scheduled Workflow holt Zeugen, urteilt und meldet Widersprüche in genau ein Issue.

**Tech Stack:** Python 3.12 (stdlib: `tomllib`, `ast`, `json`, `subprocess`, `pathlib`), pytest, GitHub Actions, `gh` CLI.

**Spec:** `docs/superpowers/specs/2026-08-23-beweis-ledger-design.md`

## Global Constraints

- **Arbeitsbaum:** `/Users/spreuss/Documents/skipp-algo-wt-beweisledger`, Branch `docs/beweis-ledger`. Niemals in `/Users/spreuss/Documents/skipp-algo` arbeiten (stale HEAD).
- **Python:** immer `/Users/spreuss/Documents/skipp-algo/.venv/bin/python` (3.12.13). System-`python3` ist 3.9 und erzeugt irreführende `datetime.UTC`-Importfehler.
- **Testaufruf:** `PYTHONPATH=$PWD /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest <datei> -q --no-header -p no:randomly`
- **Vor jedem Testlauf:** `find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null`
- **Wächter laufen als Modul** — `python -m scripts.check_proof_ledger`, nie über den Pfad. Über den Pfad findet er das `scripts`-Paket nicht, außer der Aufrufer exportiert zufällig `PYTHONPATH`; ein Wächter, der in einer Lane still besteht, die eine Variable vergessen hat, ist schlimmer als kein Wächter.
- **Ruff:** `.venv/bin/python -m ruff check .` sauber vor jedem Push. Exception-Klassen brauchen Suffix `Error` (N818); Testfunktionen snake_case (N802).
- **Nie `--no-verify`.** Ein fehlschlagender pre-push-Hook ist Signal.
- **Push** immer backgrounded (`run_in_background: true`). Ein Vordergrund-Timeout verwaist den Hook und meldet einen falschen Exit-Code.
- **Commit-Nachrichten über `-F <datei>`**, nie `-m`: zsh führt Backticks als Kommandosubstitution aus und löscht Namen still aus der Nachricht. Danach `git log -1 --format=%B` gegenprüfen.
- **Kein Netz im Offline-Wächter.** Alles mit `gh`/`urllib` gehört in den Monitor-Workflow.
- **Leeres Ergebnis ist kein Befund.** Jede abgeleitete Menge bekommt eine Untergrenze.
- **Jede Verhaltenszusicherung braucht eine Mutationsprobe:** Feature zurückbauen, Test muss rot werden.

---

## File Structure

| Datei | Verantwortung | Änderung |
|---|---|---|
| `proof_ledger.toml` | Quelle: Einträge, Untergrenzen, deklarierte unerreichbare Zweige | Neu (Task 1) |
| `scripts/proof_ledger.py` | Der **eine** Loader + Schema + `ProofEntry` | Neu (Task 1) |
| `scripts/proof_class.py` | Ableitung der beweispflichtigen Dateiklasse | Neu (Task 2) |
| `scripts/check_proof_ledger.py` | Offline-Wächter für fast-gates | Neu (Task 3) |
| `scripts/proof_judges/__init__.py` | `Verdict`, `judge`-Vertrag, AST-Zweigableitung | Neu (Task 4) |
| `scripts/proof_judges/tv_partial_save.py` | Urteiler für #5013 | Neu (Task 4) |
| `tests/proof_corpus/tv_partial_save/*.json` | Aufgezeichnete echte Artefakte mit Herkunft | Neu (Task 4) |
| `tests/test_proof_ledger.py` | Schema, Untergrenzen, Kopplung, Anti-Vakuität | Neu (Tasks 1–5) |
| `.github/workflows/smc-fast-pr-gates.yml` | Wächter-Schritt + Test-Registrierung | Ändern (Task 6) |
| `.github/workflows/proof-ledger-monitor.yml` | Zeuge holen, urteilen, melden | Neu (Task 7) |

Tasks 1–5 bauen aufeinander auf. Task 6 verdrahtet; Task 7 ist von 6 unabhängig.

---

### Task 0: Die Messung, die den Ansatz trägt oder kippt — AM 2026-08-23 GEFAHREN

**Files:** keine. Ergebnis ist unten festgehalten und wandert als Kommentar in `proof_ledger.toml` (Task 1).

**Abbruchkriterium:** Fallen mehr als **25 %** der letzten 200 gemergten PRs in die Klasse, ist der Mechanismus tot geboren — dann Halt, Ergebnis melden, Trigger-Ableitung neu schneiden. Nicht die Pflicht aufweichen.

> **ERGEBNIS 2026-08-23: 43 von 200 = 21 %, davon 0 Bot-Commits. Schwelle nicht gerissen, der Ansatz trägt.** Alle 43 sind Einzelfälle (kein Titel kommt zweimal vor) — echte Änderungen an TV-Automation, Workflows und `scripts/tv_*`. Der Library-Refresh-Bot fällt **nicht** in die Klasse, weil `.pine`-Dateien Daten sind, die ein Workflow publiziert, und kein Code, den er ausführt. Das war vorher eine Erwartung und ist jetzt eine Messung.

- [x] **Step 1: Die Grundgesamtheit richtig bilden**

**`--merges` liefert hier NULL** — `main` ist squash-basiert, es gibt keine Merge-Commits. Ein Lauf über `git log --merges` hätte eine leere Liste ergeben und ausgesehen wie „0 % beweispflichtig, alles unbedenklich". Jeder Commit auf `main` **ist** ein gemergter PR:

```bash
cd /Users/spreuss/Documents/skipp-algo-wt-beweisledger
git fetch -q origin
git log origin/main -n 200 --format='%H' > /tmp/pl_commits.txt
wc -l < /tmp/pl_commits.txt        # muss 200 sein, nicht 0
```

- [x] **Step 2: Je PR zählen, ob er die Klasse berührt**

```bash
: > /tmp/pl_hits.txt
while read -r sha; do
  if git diff --name-only "${sha}^" "${sha}" 2>/dev/null \
     | grep -qE '^(\.github/workflows/|automation/tradingview/|scripts/tv_)'; then
    printf '%s\n' "$sha" >> /tmp/pl_hits.txt
  fi
done < /tmp/pl_commits.txt
hits=$(wc -l < /tmp/pl_hits.txt | tr -d ' ')
total=$(wc -l < /tmp/pl_commits.txt | tr -d ' ')
echo "beweispflichtig: ${hits} von ${total} = $(( hits * 100 / total )) %"
[ "$hits" -gt 0 ] || echo "POSITIVKONTROLLE ROT — Filter greift daneben, Ergebnis wertlos"
```

Gemessen: `43 von 200 = 21 %`.

- [x] **Step 3: Den Bot gegenprüfen — die Frage, an der es scheitert**

```bash
while read -r sha; do git log -1 --format='%s' "$sha"; done < /tmp/pl_hits.txt \
  | grep -cE 'library refresh|measurement baseline|chore\(deps'
```

Gemessen: **0**. Wäre diese Zahl zweistellig, wäre der Mechanismus tot geboren — bei ~16 Bot-Merges am Tag ersäuft jedes echte Signal.

- [x] **Step 4: Ergebnis festhalten**

Die drei Zahlen stehen im Kasten oben und gehören als datierter Kommentar in `proof_ledger.toml`. Eine Quote, die nur im Kopf steht, ist in zwei Wochen eine Erfindung.

---

### Task 1: Die Ledger-Quelle und ihr Loader

**Files:**
- Create: `proof_ledger.toml`
- Create: `scripts/proof_ledger.py`
- Test: `tests/test_proof_ledger.py`

**Interfaces:**
- Produces: `scripts.proof_ledger.load_entries() -> tuple[ProofEntry, ...]`; `ProofEntry` (frozen dataclass mit `id, kind, claim, state, due_by, owner, judge, witness, witness_job, evidence_source, artifact, version_probe, pass_kind, witness_run, unreachable_because, raw`); `MERGE_STATES`, `TERMINAL_STATES: frozenset[str]`; `ProofLedgerError(Exception)`; `class_floors() -> dict[str, int]`; `declared_unreachable_branches() -> frozenset[tuple[str, str, str]]` (judge, branch, reason). Alle späteren Tasks lesen das Ledger ausschließlich hierüber.

- [ ] **Step 1: Die Ledger-Quelle anlegen**

`proof_ledger.toml` im Repo-Wurzelverzeichnis:

```toml
# proof_ledger.toml — offene Beweise gemergter Aenderungen.
#
# Ein Eintrag je Aenderung, deren Wirkung die Testsuite prinzipiell nicht
# sehen kann (Browser-Automation, Workflow-YAML, externe Dienste).
#
# Geladen NUR ueber scripts/proof_ledger.py — nie direkt geparst, damit das
# Schema an genau einer Stelle erzwingbar bleibt (gleiche Regel wie
# tests/_pin_registry.py fuer pin_registry.toml, ADR-0009).
#
# Zustaende:
#   OFFEN         Beweis erwartet, Frist laeuft
#   PASS          bezeugt; pass_kind = live | drill
#   FAIL          bezeugt und widerlegt
#   SCHLAFEND     Bedingung trat nicht ein — DURCHGANGSZUSTAND, nie terminal
#   UNERREICHBAR  deklariert; braucht unreachable_because (Repo-Kopplung)
#   UNGESICHERT   akzeptiert ohne Beweis; braucht Besitzer und Frist
#
# Editier-Regeln:
#   * Zustand nur mit datiertem Kommentar aendern, der die MESSUNG nennt.
#   * SCHLAFEND und UNERREICHBAR brauchen unreachable_because; der Wert wird
#     gegen den Baum geprueft, nicht geglaubt.
#   * Einen Eintrag entfernen ist zulaessig, wenn die Aenderung zurueckgerollt
#     wurde. Fristablauf ist KEIN Entfernungsgrund.

# ---------------------------------------------------------------------------
# Untergrenzen der abgeleiteten Dateiklasse (scripts/proof_class.py).
# Auf die in Task 2 GEMESSENEN Werte setzen, dann minus 10 % als Puffer.
# Ein Parser unter diesen Zahlen ist kaputt, nicht erfolgreich.
# ---------------------------------------------------------------------------
[class_floors]
workflows = 1
referenced_code = 1
derived_class = 1

# ---------------------------------------------------------------------------
# Urteilszweige ohne echten Korpus-Treffer, die trotzdem stehen bleiben.
# Jeder Eintrag ist ein Gestaendnis und braucht einen Grund.
# ---------------------------------------------------------------------------
[[unreachable_branch]]
judge  = "tv_partial_save"
branch = "pruefen_partial_not_saved"
reason = """
2026-08-23: In 396 Artefakten (24.7.-22.8.) war partiallyRepairedChartUrls nie
gefuellt; seit dem ersten Feuern am 23.8. (Lauf 32620808573) lag es stets AUCH
in savedChartUrls. Ein partial-Layout, das NICHT gespeichert wurde, ist nie
beobachtet worden. Der Zweig bleibt, weil er den Fall benennt, in dem der
#5013-Fix nur halb wirkt.
"""

# ---------------------------------------------------------------------------
# Eintraege. Stand 2026-08-23 05:49Z.
#
# Aufnahmequote, GEMESSEN 2026-08-23 (Task 0): 43 von 200 gemergten PRs = 21 %,
# davon 0 Bot-Commits. Die 43 sind durchweg Einzelfaelle — kein Titel kommt
# zweimal vor. Der Library-Refresh-Bot faellt NICHT in die Klasse, weil
# .pine-Dateien Daten sind, die ein Workflow publiziert, und kein Code, den er
# ausfuehrt. Faellt diese Quote je ueber 25 %, ist der Trigger neu zu
# schneiden — nicht die Pflicht aufzuweichen.
# ---------------------------------------------------------------------------

[[proof]]
id              = "5013"
kind            = "fix"
merged_at       = "2026-08-22T16:42:54Z"
merge_sha       = "7733f988c"
claim           = "Ein unerreichbares Ziel fuehrt zum Partial-Save statt zum Verwerfen"
witness         = "tv-save-consumer-source"
witness_job     = "save"
evidence_source = "artifact"
artifact        = "tradingview-consumer-bindings"
version_probe   = "mutations.partiallyRepairedChartUrls"
judge           = "tv_partial_save"
# 2026-08-23 05:49Z GEMESSEN: Lauf 32620808573 (vom Layout-Waechter angefordert)
# zeigt partiallyRepairedChartUrls [vWgAWyfC] UND savedChartUrls [vWgAWyfC] bei
# leerem abandonedChartUrls, 98 Bindungen repariert. Der Lauf war
# conclusion=failure — ein roter Lauf, der exakt das Richtige tat.
state           = "PASS"
pass_kind       = "live"
witness_run     = "32620808573"
due_by          = "2026-09-06"
owner           = "operator"

[[proof]]
id              = "5025"
kind            = "fix"
merged_at       = "2026-08-23T00:30:20Z"
merge_sha       = "9803e4253"
claim           = "Der Layout-Waechter dispatcht repair-only, und der repariert und speichert"
witness         = "tv-save-consumer-source"
witness_job     = "save"
evidence_source = "artifact"
artifact        = "tradingview-consumer-bindings"
version_probe   = "executionMode"
judge           = "tv_repair_only_contract"
# 2026-08-23: derselbe Lauf 32620808573 traegt executionMode=repair-only und
# haelt den Vertrag: sourceSavesCompleted 0, producerInstancesRemoved 0,
# consumerInstancesRemoved 0 — nichts deployt, nichts zerlegt.
state           = "PASS"
pass_kind       = "live"
witness_run     = "32620808573"
due_by          = "2026-09-06"
owner           = "operator"

[[proof]]
id              = "5020"
kind            = "fix"
merged_at       = "2026-08-22T21:16:15Z"
merge_sha       = "6826873e1"
claim           = "Ein endgueltig gescheitertes Ziel hinterlaesst eine Beweisdatei"
witness         = "tv-save-consumer-source"
witness_job     = "save"
evidence_source = "artifact"
artifact        = "tradingview-consumer-bindings"
version_probe   = "bindings.evidence"
judge           = "tv_failure_evidence"
# 2026-08-23 00:2xZ GEMESSEN an Lauf 32556181388: eine Beweisdatei geschrieben
# (…-settings-failure-smc-long-dip-alerts.json).
state           = "PASS"
pass_kind       = "live"
witness_run     = "32556181388"
due_by          = "2026-09-06"
owner           = "operator"

[[proof]]
id              = "5018"
kind            = "fix"
merged_at       = "2026-08-22T20:32:49Z"
merge_sha       = "1ae9e5ca8"
claim           = "Der Legenden-Doppelklick trifft seine eigene Zeile, nicht die Nachbarzeile"
witness         = "tv-save-consumer-source"
witness_job     = "save"
# Die -hit-target-miss-Spur geht ins JOB-LOG, nie ins Artefakt. Genau diese
# Verwechslung machte den Sondenzweig vom 22.8. vakuoes: er suchte in
# bindings.failed[].error nach einem Wert, der dort nie steht.
evidence_source = "job_log"
artifact        = ""
# KEINE inhaltliche Versionsprobe moeglich: die neuen Spuren erscheinen nur im
# Fehlerfall, ihr Fehlen beweist nichts ueber die Code-Version. Allein der
# Job-Start traegt — das ist bewusst schwaecher und wird hier benannt statt
# stillschweigend in Kauf genommen.
version_probe   = "KEINE"
version_probe_reason = "Spur nur im Fehlerfall; Abwesenheit ist kein Versionsbeweis"
judge           = "tv_legend_click"
# 2026-08-23: Lauf 32556181388 zeigt hit-target-miss 0 und box-degenerate 0 —
# der Klick traf seine Zeile, der Dialog ging trotzdem nicht auf. Der
# Rechenfehler war real, aber nicht die Ursache. Klasse H besteht fort.
state           = "OFFEN"
due_by          = "2026-09-06"
owner           = "operator"

[[proof]]
id              = "5027"
kind            = "fix"
merged_at       = "2026-08-23T00:58:56Z"
merge_sha       = "d3c0f5e7e"
claim           = "Die Identitaetspruefung sucht den passenden Dialog, nicht den ersten"
witness         = "tv-save-consumer-source"
witness_job     = "save"
# Wie #5018: die Spur steht im Log, nicht im Artefakt.
evidence_source = "job_log"
artifact        = ""
# KEINE inhaltliche Versionsprobe eingetragen, obwohl es eine geben KOENNTE:
# #5027 schreibt die Anzahl gleichzeitig offener Dialoge in die Spur. Sobald
# deren exakter Text an einem echten Lauf gemessen ist, gehoert er hierhin —
# bis dahin waere ein geratenes Suchmuster eine Versionsprobe, die nichts
# probiert.
version_probe   = "KEINE"
version_probe_reason = "Dialoganzahl-Spur existiert, Wortlaut noch nicht gemessen"
judge           = "tv_legend_click"
state           = "OFFEN"
due_by          = "2026-09-06"
owner           = "operator"

[[proof]]
id              = "klasse-h"
kind            = "defect"
claim           = "openSettingsForScript laeuft bei SMC Long-Dip Alerts in den Timeout; Ursache offen"
# Aktueller Kandidat (2026-08-23): mehrere Dialoge gleichzeitig offen, die
# Identitaetspruefung nimmt den ERSTEN statt den passenden (#5027).
state           = "UNGESICHERT"
due_by          = "2026-09-06"
owner           = "operator"

[[proof]]
id              = "waechter-in-flight-text"
kind            = "defect"
claim           = "Der in_flight-Grund des Waechters nennt einen Reparaturlauf, den es nicht gibt"
# 2026-08-23 gefunden: in_flight zaehlt JEDEN wartenden workflow_dispatch, auch
# die read-only-Verifikation, die die Verify-Kette selbst dispatcht. Der
# Mechanismus ist richtig (ein wartender Lauf belegt den Ein-Platz-Slot), der
# TEXT behauptet etwas Falsches und schickt den Leser auf die Suche nach einem
# Lauf, den es nicht gibt. Nicht behoben.
state           = "UNGESICHERT"
due_by          = "2026-09-06"
owner           = "operator"
```

Die `<TREFFER>`/`<MERGES>`/`<ANTEIL>`-Platzhalter im Kommentarblock mit den Zahlen aus Task 0 ersetzen.

- [ ] **Step 2: Den fehlschlagenden Schema-Test schreiben**

`tests/test_proof_ledger.py`:

```python
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
    assert set(floors) == {"workflows", "referenced_code", "derived_class"}
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
```

- [ ] **Step 3: Testlauf, der fehlschlagen MUSS**

```bash
cd /Users/spreuss/Documents/skipp-algo-wt-beweisledger
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
PYTHONPATH=$PWD /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest \
  tests/test_proof_ledger.py -q --no-header -p no:randomly
```

Erwartet: Collection-Error — `ModuleNotFoundError: No module named 'scripts.proof_ledger'`.

- [ ] **Step 4: Den Loader schreiben**

`scripts/proof_ledger.py`:

```python
#!/usr/bin/env python3
"""Loader for ``proof_ledger.toml`` — the single source of pending proofs.

Ein Eintrag haelt fest, dass eine gemergte Aenderung ihre Wirkung noch nicht
gezeigt hat. Tests und Waechter importieren AUSSCHLIESSLICH hier — nie die
TOML direkt parsen, sonst zerfaellt das Schema in so viele Auslegungen, wie es
Leser gibt (dieselbe Regel wie ``tests/_pin_registry.py``, ADR-0009).

Warum das Ledger ueber EVIDENZINHALT urteilt und nie ueber die Lauf-
Conclusion: Lauf 32620808573 (2026-08-23) war ``conclusion: failure`` und hat
dabei exakt das Richtige getan — ``report.ok`` haengt an einem nicht leeren
``partiallyRepairedChartUrls``. Wer die Conclusion liest, fuehrt einen
bestandenen Beweis als Fehlschlag.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
_LEDGER_PATH = ROOT / "proof_ledger.toml"

MERGE_STATES = frozenset(
    {"OFFEN", "PASS", "FAIL", "SCHLAFEND", "UNERREICHBAR", "UNGESICHERT"}
)
#: Zustaende, die keine Frist mehr brauchen. SCHLAFEND ist ABSICHTLICH nicht
#: dabei: es ist ein Durchgangszustand mit genau drei Ausgaengen (Drill,
#: deklariert unerreichbar, akzeptiert ungesichert).
TERMINAL_STATES = frozenset({"PASS", "FAIL", "UNERREICHBAR"})

_REQUIRED_ALWAYS = ("id", "kind", "claim", "state", "due_by", "owner")
_REQUIRED_FIX = ("witness", "witness_job", "evidence_source", "version_probe", "judge")


class ProofLedgerError(Exception):
    """Das Ledger ist nicht wohlgeformt."""


@dataclass(frozen=True)
class ProofEntry:
    id: str
    kind: str
    claim: str
    state: str
    due_by: str
    owner: str
    judge: str = ""
    witness: str = ""
    witness_job: str = ""
    evidence_source: str = ""
    artifact: str = ""
    version_probe: str = ""
    pass_kind: str = ""
    witness_run: str = ""
    unreachable_because: str = ""
    raw: dict[str, Any] | None = None


@lru_cache(maxsize=1)
def _load() -> dict[str, Any]:
    with _LEDGER_PATH.open("rb") as fp:
        return tomllib.load(fp)


def _entry_from(raw: dict[str, Any]) -> ProofEntry:
    missing = [key for key in _REQUIRED_ALWAYS if not raw.get(key)]
    if raw.get("kind") == "fix":
        missing += [key for key in _REQUIRED_FIX if not raw.get(key)]
    if missing:
        raise ProofLedgerError(
            f"Eintrag {raw.get('id', '<ohne id>')!r}: Pflichtfelder fehlen: "
            f"{', '.join(sorted(missing))}"
        )
    if raw["state"] not in MERGE_STATES:
        raise ProofLedgerError(
            f"Eintrag {raw['id']!r}: unbekannter Zustand {raw['state']!r}"
        )
    return ProofEntry(
        id=str(raw["id"]),
        kind=str(raw["kind"]),
        claim=str(raw["claim"]),
        state=str(raw["state"]),
        due_by=str(raw["due_by"]),
        owner=str(raw["owner"]),
        judge=str(raw.get("judge", "")),
        witness=str(raw.get("witness", "")),
        witness_job=str(raw.get("witness_job", "")),
        evidence_source=str(raw.get("evidence_source", "")),
        artifact=str(raw.get("artifact", "")),
        version_probe=str(raw.get("version_probe", "")),
        pass_kind=str(raw.get("pass_kind", "")),
        witness_run=str(raw.get("witness_run", "")),
        unreachable_because=str(raw.get("unreachable_because", "")),
        raw=dict(raw),
    )


def load_entries() -> tuple[ProofEntry, ...]:
    """Alle Eintraege, validiert. Wirft bei jeder Unwohlgeformtheit."""
    entries = tuple(_entry_from(raw) for raw in _load().get("proof", []))
    seen: set[str] = set()
    for entry in entries:
        if entry.id in seen:
            raise ProofLedgerError(f"doppelte id {entry.id!r}")
        seen.add(entry.id)
    return entries


def class_floors() -> dict[str, int]:
    """Untergrenzen der abgeleiteten Dateiklasse."""
    return {name: int(value) for name, value in _load()["class_floors"].items()}


def declared_unreachable_branches() -> frozenset[tuple[str, str, str]]:
    """``(judge, branch, reason)`` je bewusst unerreichbar erklaertem Zweig."""
    return frozenset(
        (str(item["judge"]), str(item["branch"]), str(item["reason"]))
        for item in _load().get("unreachable_branch", [])
    )
```

- [ ] **Step 5: Testlauf, der bestehen MUSS**

```bash
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
PYTHONPATH=$PWD /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest \
  tests/test_proof_ledger.py -q --no-header -p no:randomly
```

Erwartet: 7 passed.

- [ ] **Step 6: Mutationsprobe von Hand**

In `proof_ledger.toml` bei `id = "5013"` die Zeile `owner = "operator"` auskommentieren, Test erneut laufen lassen. Erwartet: `ProofLedgerError: Eintrag '5013': Pflichtfelder fehlen: owner`. Danach zurücknehmen und den Test erneut grün sehen.

- [ ] **Step 7: Ruff und Commit**

```bash
/Users/spreuss/Documents/skipp-algo/.venv/bin/python -m ruff check .
git add proof_ledger.toml scripts/proof_ledger.py tests/test_proof_ledger.py
git commit -F /tmp/pl_commit_1.txt
git log -1 --format=%B
```

`/tmp/pl_commit_1.txt`:

```
feat(proof-ledger): eine Quelle fuer Beweise, die noch nicht erbracht sind

Ein gemergter Fix, dessen Wirkung die Suite nicht sehen kann, hatte bisher
keinen Halter. Sein Zustand lebte in einem Bash-Skript im op-tree, das ein
Mensch aufrufen musste — am 23.8. lag #5013 dreizehn Stunden lang auf einem
Zustand, der von "schlafend, also wohl in Ordnung" nicht zu unterscheiden war.

Das Ledger trennt, was bisher gleich aussah: SCHLAFEND (die Bedingung trat
nicht ein) von STEHT AUS (die Bedingung trat ein, der Zweig wurde nicht
erreicht). SCHLAFEND ist ausdruecklich KEIN Endzustand.

Geurteilt wird ueber Evidenzinhalt, nie ueber die Lauf-Conclusion: Lauf
32620808573 war conclusion=failure und tat exakt das Richtige.
```

---

### Task 2: Die abgeleitete Dateiklasse

**Files:**
- Create: `scripts/proof_class.py`
- Modify: `proof_ledger.toml` (`[class_floors]` auf die gemessenen Werte)
- Test: `tests/test_proof_ledger.py` (anhängen)

**Interfaces:**
- Consumes: `scripts.proof_ledger.class_floors`, `ProofLedgerError`
- Produces: `scripts.proof_class.derive_class(root: Path = ROOT) -> frozenset[str]` (repo-relative POSIX-Pfade); `workflow_files(root) -> frozenset[str]`; `referenced_code(root) -> frozenset[str]`; `test_imported(root) -> frozenset[str]`; `class ProofClassError(Exception)`

- [ ] **Step 1: Den fehlschlagenden Test schreiben**

An `tests/test_proof_ledger.py` anhängen:

```python
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
```

- [ ] **Step 2: Fehlschlag bestätigen**

```bash
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
PYTHONPATH=$PWD /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest \
  tests/test_proof_ledger.py -q --no-header -p no:randomly -k "class or derived or derivation"
```

Erwartet: `ModuleNotFoundError: No module named 'scripts.proof_class'`.

- [ ] **Step 3: Die Ableitung schreiben**

`scripts/proof_class.py`:

```python
#!/usr/bin/env python3
"""Leite die beweispflichtige Dateiklasse ab — Code, den ein Workflow
ausfuehrt und den keine Testdatei importiert.

Warum ABGELEITET und nicht aufgezaehlt: Eine hartkodierte Liste faengt genau
die Drift nicht, vor der sie warnt. Gemessen am 2026-08-22 an
``tv-post-mutation-verify.yml``, dessen Kopplungstest acht ``mutations``-Felder
hartkodiert hielt — #5013 fuegte ein neuntes hinzu, der Test blieb gruen, der
Waechter war nicht mehr erschoepfend.

Der Schnitt: Ein Test, der eine Datei importiert, macht ihre Wirkung sichtbar.
Was nur im Workflow laeuft und von keinem Test angefasst wird, zeigt sich
ausschliesslich im echten Lauf — genau dort braucht es einen Ledger-Eintrag.
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts.proof_ledger import class_floors

ROOT = Path(__file__).resolve().parents[1]

#: Dateiendungen, die als ausfuehrbarer Code zaehlen. `.pine` ist ABSICHTLICH
#: nicht dabei: Pine-Quellen sind Daten, die ein Workflow publiziert, kein Code,
#: den er ausfuehrt. Ohne diese Grenze faellt der Library-Refresh-Bot mit ~16
#: Merges am Tag in die Klasse und der Mechanismus ist tot geboren (Task 0).
_CODE_SUFFIXES = (".py", ".ts", ".sh", ".mjs")

#: Matcht ueberall im rohen Workflow-Dateitext -- NICHT nur innerhalb eines
#: `run:`-Blocks, sondern auch in YAML-Kommentaren und Prosa; die Regex kennt
#: keine YAML-Struktur, nur Zeichenketten. Gemessen 2026-08-23 (Task-2-
#: Mutationsprobe): eine reine Kommentar-Erwaehnung in smc-r4-context-
#: readback.yml hielt einen Pfad in referenced_code(), obwohl beide echten
#: Aufrufstellen bereits entfernt waren. Bewusst so belassen: die
#: Grosszuegigkeit irrt in Richtung einer GROESSEREN Klasse -- fail-safe, nicht
#: fail-open. Ein Treffer hier ist notwendig, aber nicht hinreichend fuer
#: "wird ausgefuehrt"; erst wenn test_imported() die Datei NICHT sieht, landet
#: sie in der beweispflichtigen Klasse.
_REF = re.compile(
    r"(?<![\w./-])((?:scripts|automation|tools|services)/[\w./-]+"
    r"\.(?:py|ts|sh|mjs))(?![\w/])"
)
#: `python -m scripts.foo` — Modulform, die keinen Pfad schreibt.
_MODULE_REF = re.compile(r"python3?\s+-m\s+((?:scripts|tools)\.[\w.]+)")

#: Ein Test, der eine Datei als TEXT liest und Teilstrings pinnt, sieht ihre
#: Bytes — nicht ihre Wirkung. Gemessen 2026-08-23 an
#: tests/test_workflow_tv_save_consumer_source_contract.py: 20 woertliche
#: Vorkommen des Pfades von tv_batch_consumer_rollout.ts, kein einziger Aufruf.
#: Wer solche Nennungen als Deckung zaehlt, nimmt ausgerechnet das Skript aus
#: der Klasse, das am 2026-08-22 das gehandelte Layout zerlegt hat.
_TS_IMPORT = re.compile(r"""(?:from|require\(|import\()\s*['"]([^'"]+)['"]""")
_PY_IMPORT = re.compile(r"^\s*(?:from|import)\s+((?:scripts|tools)[\w.]*)", re.M)


class ProofClassError(Exception):
    """Die Ableitung hat ihre Untergrenze unterschritten."""


def workflow_files(root: Path = ROOT) -> frozenset[str]:
    """Alle Workflow-Definitionen, repo-relativ."""
    wf_dir = root / ".github" / "workflows"
    return frozenset(
        p.relative_to(root).as_posix()
        for p in sorted(wf_dir.glob("*.yml")) + sorted(wf_dir.glob("*.yaml"))
    )


def referenced_code(root: Path = ROOT) -> frozenset[str]:
    """Repo-Dateien, die irgendein Workflow ausfuehrt."""
    hits: set[str] = set()
    for rel in workflow_files(root):
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        hits.update(_REF.findall(text))
        for module in _MODULE_REF.findall(text):
            candidate = Path(*module.split(".")).with_suffix(".py")
            hits.add(candidate.as_posix())
    return frozenset(h for h in hits if (root / h).exists())


def test_imported(root: Path = ROOT) -> frozenset[str]:
    """Dateien, die eine Testdatei IMPORTIERT — nicht solche, die sie nur nennt.

    Die Unterscheidung ist der Kern: ein Kontrakttest, der Quelltext als String
    pint, beobachtet keine Ausfuehrung. Er gehoert nicht zur Deckung.
    """
    named: set[str] = set()
    for tests_dir in ((root / "tests"), (root / "automation")):
        if not tests_dir.exists():
            continue
        for path in tests_dir.rglob("*"):
            if not path.is_file():
                continue
            if not (path.name.startswith("test_") or ".test." in path.name):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for spec in _TS_IMPORT.findall(text):
                named.add(Path(spec).name)
                named.add(Path(spec).stem)
            for module in _PY_IMPORT.findall(text):
                rel = Path(*module.split(".")).with_suffix(".py").as_posix()
                named.add(rel)
                named.add(Path(rel).stem)
    return frozenset(named)


def derive_class(root: Path = ROOT) -> frozenset[str]:
    """Die beweispflichtige Klasse. Wirft, wenn eine Zwischenmenge zu klein ist."""
    floors = class_floors()
    workflows = workflow_files(root)
    if len(workflows) < floors["workflows"]:
        raise ProofClassError(
            f"Untergrenze verletzt: {len(workflows)} Workflows < {floors['workflows']}"
        )
    referenced = referenced_code(root)
    if len(referenced) < floors["referenced_code"]:
        raise ProofClassError(
            f"Untergrenze verletzt: {len(referenced)} referenzierte Dateien "
            f"< {floors['referenced_code']}"
        )
    covered = test_imported(root)
    if len(covered) < floors["test_imported"]:
        raise ProofClassError(
            f"Untergrenze verletzt: {len(covered)} von Tests importierte Dateien "
            f"< {floors['test_imported']}"
        )
    unseen = {
        rel
        for rel in referenced
        if rel.endswith(_CODE_SUFFIXES)
        and rel not in covered
        and Path(rel).stem not in covered
    }
    derived = frozenset(unseen | workflows)
    if len(derived) < floors["derived_class"]:
        raise ProofClassError(
            f"Untergrenze verletzt: Klasse hat {len(derived)} Eintraege "
            f"< {floors['derived_class']}"
        )
    return derived


def main() -> int:
    for rel in sorted(derive_class()):
        print(rel)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Die Untergrenzen MESSEN und eintragen**

```bash
PYTHONPATH=$PWD /Users/spreuss/Documents/skipp-algo/.venv/bin/python - <<'PY'
from scripts.proof_class import derive_class, referenced_code, workflow_files
print("workflows       =", len(workflow_files()))
print("referenced_code =", len(referenced_code()))
print("derived_class   =", len(derive_class()))
PY
```

Die drei Zahlen minus 10 % (abgerundet) in `proof_ledger.toml` unter `[class_floors]` eintragen, mit datiertem Kommentar `# 2026-08-23 gemessen: <werte>`.

- [ ] **Step 5: Tests grün**

```bash
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
PYTHONPATH=$PWD /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest \
  tests/test_proof_ledger.py -q --no-header -p no:randomly
```

Erwartet: 11 passed.

- [ ] **Step 6: Mutationsprobe — die Klasse muss auf Quellenänderung reagieren**

In `.github/workflows/tv-save-consumer-source.yml` die Zeile, die `scripts/tv_batch_consumer_rollout.ts` nennt, temporär auskommentieren. Dann:

```bash
PYTHONPATH=$PWD /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest \
  tests/test_proof_ledger.py -q --no-header -p no:randomly \
  -k "browser_automation"
```

Erwartet: **rot** (`tv_batch_consumer_rollout.ts` nicht mehr in der Klasse). Danach `git checkout -- .github/workflows/tv-save-consumer-source.yml` und erneut grün sehen.

> **Warnung:** `git checkout --` hat in dieser Codebasis dreimal eigene Edits gefressen. Vor dieser Probe **committen** (Step 7 vorziehen), damit das Zurücknehmen nichts anderes mitnimmt.

- [ ] **Step 7: Ruff und Commit**

```bash
/Users/spreuss/Documents/skipp-algo/.venv/bin/python -m ruff check .
git add scripts/proof_class.py proof_ledger.toml tests/test_proof_ledger.py
git commit -F /tmp/pl_commit_2.txt
```

`/tmp/pl_commit_2.txt`:

```
feat(proof-ledger): die beweispflichtige Klasse wird abgeleitet, nicht gelistet

Code, den ein Workflow ausfuehrt und den keine Testdatei importiert, zeigt
seine Wirkung nur im echten Lauf. Genau diese Menge wird jetzt aus den
Workflow-Dateien geparst und um alles bereinigt, was ein Test anfasst.

Eine hartkodierte Liste haette es nicht getan: am 22.8. hielt der
Kopplungstest zu tv-post-mutation-verify.yml acht mutations-Felder als Kopie,
#5013 fuegte ein neuntes hinzu, und der Test blieb gruen.

Untergrenzen aus pin-Registry-Manier: eine Ableitung, die unter die gemessene
Zahl faellt, ist kaputt und nicht erfolgreich.
```

---

### Task 3: Das Offline-Gate

**Files:**
- Create: `scripts/check_proof_ledger.py`
- Modify: `scripts/proof_ledger.py` (Zustand `AUSGENOMMEN` ergänzen)
- Test: `tests/test_proof_ledger.py` (anhängen)

**Interfaces:**
- Consumes: `scripts.proof_class.derive_class`, `scripts.proof_ledger.load_entries`
- Produces: `scripts.check_proof_ledger.main(argv: list[str] | None = None) -> int` (0 = sauber, 1 = Befund, 2 = Ledger unlesbar); `_merge_base_range(commit_range: str) -> str`

- [ ] **Step 1: `AUSGENOMMEN` im Loader ergänzen**

In `scripts/proof_ledger.py`:

```python
MERGE_STATES = frozenset(
    {
        "OFFEN",
        "PASS",
        "FAIL",
        "SCHLAFEND",
        "UNERREICHBAR",
        "UNGESICHERT",
        # Eine Beruehrung der Klasse, die keinen Beweis braucht (Kommentar,
        # Umbenennung, Formatierung). Terminal, aber DEKLARIERT: sie steht im
        # Ledger und im Diff, statt durch Nichtstun zu entstehen.
        "AUSGENOMMEN",
    }
)
TERMINAL_STATES = frozenset({"PASS", "FAIL", "UNERREICHBAR", "AUSGENOMMEN"})
```

- [ ] **Step 2: Den fehlschlagenden Test schreiben**

An `tests/test_proof_ledger.py` anhängen:

```python
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
```

- [ ] **Step 3: Fehlschlag bestätigen**

```bash
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
PYTHONPATH=$PWD /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest \
  tests/test_proof_ledger.py -q --no-header -p no:randomly -k "range or coupl or touching or dangling"
```

Erwartet: `ModuleNotFoundError: No module named 'scripts.check_proof_ledger'`.

- [ ] **Step 4: Den Wächter schreiben**

`scripts/check_proof_ledger.py`:

```python
#!/usr/bin/env python3
"""Fail a PR that changes proof-bearing code without declaring a proof.

Diff-bezogen und ohne Netz, aus zwei Gruenden, die beide gemessen sind:

* **Diff statt Ist-Zustand.** ``check_r1_attested_sources.py`` hat es
  vorgemacht: main ist bereits driftend, ein Zustandscheck hier wuerde jeden
  PR rot machen, auch den, der repariert.
* **Kein Netz.** fast-gates ist der EINZIGE required Check (ADR-0011). Ein
  Wachter, der die GitHub-API befragt, macht den Merge-Pfad von API-Zustand
  und Actions-Budget abhaengig. Alles Netzgebundene lebt im Monitor-Workflow.

Als Modul aufrufen: ``python -m scripts.check_proof_ledger --range A..B``.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from pathlib import Path

from scripts.proof_class import derive_class
from scripts.proof_ledger import ROOT, ProofLedgerError, load_entries

_REMEDY = """
Dieser PR aendert Code, dessen Wirkung die Testsuite prinzipiell nicht sehen
kann — er laeuft nur in einem Workflow, und kein Test importiert ihn.

Trage in proof_ledger.toml einen Eintrag nach:

  [[proof]]
  id              = "<PR-Nummer>"
  kind            = "fix"
  merged_at       = "<wird beim Merge nachgetragen>"
  merge_sha       = "<dito>"
  claim           = "<was soll diese Aenderung bewirken>"
  witness         = "<Workflow, der einen Zeugen erzeugt>"
  witness_job     = "<Job, dessen started_at zaehlt — NIE head_sha>"
  evidence_source = "artifact"        # oder "job_log"
  artifact        = "<Artefaktname>"
  version_probe   = "<Feld, das es erst seit dieser Aenderung gibt>"
  judge           = "<Modul unter scripts/proof_judges/>"
  state           = "OFFEN"
  due_by          = "<YYYY-MM-DD>"
  owner           = "<wer misst nach>"

Braucht die Aenderung keinen Beweis (Kommentar, Umbenennung, Formatierung),
dann sag das ausdruecklich statt es wegzulassen:

  [[proof]]
  id     = "<PR-Nummer>"
  kind   = "exempt"
  claim  = "<warum hier nichts zu beweisen ist>"
  state  = "AUSGENOMMEN"
  due_by = "<Merge-Datum, ohne Wirkung>"
  owner  = "<wer das entschieden hat>"
""".strip()


def _merge_base_range(commit_range: str) -> str:
    """``A..B`` zu ``A...B`` weiten, damit der Diff an der Merge-Basis beginnt.

    ``git diff A..B`` ist kein Bereich, sondern ein Vergleich zweier BAEUME.
    Auf einem PR-Branch, der aelter ist als eine Aenderung auf main, meldet er
    mains Aenderung als die dieses PRs — gemessen am 2026-08-04 an #4373.
    """
    if "..." in commit_range:
        return commit_range
    if ".." in commit_range:
        return commit_range.replace("..", "...", 1)
    return commit_range


def _changed_files(commit_range: str) -> frozenset[str]:
    proc = subprocess.run(
        ["git", "diff", "--name-only", _merge_base_range(commit_range)],
        capture_output=True, text=True, check=True, cwd=ROOT,
    )
    return frozenset(line.strip() for line in proc.stdout.splitlines() if line.strip())


def _ledger_ids_at(rev: str) -> frozenset[str]:
    """Eintrags-Ids, wie sie bei ``rev`` standen. Leer, wenn es sie nicht gab."""
    proc = subprocess.run(
        ["git", "show", f"{rev}:proof_ledger.toml"],
        capture_output=True, text=True, cwd=ROOT,
    )
    if proc.returncode != 0:
        return frozenset()
    data = tomllib.loads(proc.stdout)
    return frozenset(str(e["id"]) for e in data.get("proof", []) if e.get("id"))


def _coupling_failures() -> list[str]:
    """Begruendungen, die ins Leere zeigen.

    Eine Deklaration, die niemand pruefen kann, ist ein Wort — und ein Wort
    laesst sich umschreiben, um einen Beweis stillzulegen. Das Muster stammt
    aus ``_DEPLOYMENT_IS_CONFIGURED``: die Deklaration ist nur ehrlich,
    solange die Sache existiert, auf die sie sich beruft.
    """
    problems: list[str] = []
    for entry in load_entries():
        ref = entry.unreachable_because
        if not ref:
            continue
        kind, _, rest = ref.partition(":")
        if kind == "path":
            if not (ROOT / rest).exists():
                problems.append(f"{entry.id}: Pfad {rest!r} existiert nicht mehr")
        elif kind == "symbol":
            rel, _, name = rest.partition("#")
            target = ROOT / rel
            if not target.exists():
                problems.append(f"{entry.id}: Datei {rel!r} existiert nicht mehr")
            elif name not in target.read_text(encoding="utf-8", errors="replace"):
                problems.append(
                    f"{entry.id}: Symbol {name!r} steht nicht mehr in {rel!r} — "
                    "die Begruendung traegt nicht mehr"
                )
        else:
            problems.append(f"{entry.id}: unbekannte Kopplungsart {kind!r}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--range", dest="commit_range", required=True)
    args = parser.parse_args(argv)

    try:
        entries = load_entries()
    except ProofLedgerError as exc:
        print(f"proof_ledger.toml ist nicht wohlgeformt: {exc}", file=sys.stderr)
        return 2

    problems = _coupling_failures()
    if problems:
        print("Ledger-Begruendungen, die nicht mehr tragen:", file=sys.stderr)
        for line in problems:
            print(f"  {line}", file=sys.stderr)
        return 1

    touched = sorted(_changed_files(args.commit_range) & derive_class())
    if not touched:
        return 0

    base = _merge_base_range(args.commit_range).split("...")[0]
    before = _ledger_ids_at(base)
    after = frozenset(entry.id for entry in entries)
    if after - before:
        return 0

    print("Beweispflichtige Dateien in diesem PR:", file=sys.stderr)
    for rel in touched:
        print(f"  {rel}", file=sys.stderr)
    print("", file=sys.stderr)
    print(_REMEDY, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Tests grün**

```bash
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
PYTHONPATH=$PWD /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest \
  tests/test_proof_ledger.py -q --no-header -p no:randomly
```

Erwartet: 17 passed.

- [ ] **Step 6: Der Wächter gegen den eigenen Branch — die Positivkontrolle**

```bash
PYTHONPATH=$PWD /Users/spreuss/Documents/skipp-algo/.venv/bin/python \
  -m scripts.check_proof_ledger --range "origin/main..HEAD"; echo "rc=$?"
```

Erwartet `rc=0`: Dieser Branch berührt die Klasse nicht (nur `scripts/*.py`, die von `tests/test_proof_ledger.py` importiert werden, plus `docs/`). Erwartet der Wächter hier etwas anderes, ist die Ableitung zu breit — **nicht** die Pflicht aufweichen, sondern `test_imported` nachschärfen.

- [ ] **Step 7: Ruff und Commit**

```bash
/Users/spreuss/Documents/skipp-algo/.venv/bin/python -m ruff check .
git add scripts/check_proof_ledger.py scripts/proof_ledger.py tests/test_proof_ledger.py
git commit -F /tmp/pl_commit_3.txt
```

`/tmp/pl_commit_3.txt`:

```
feat(proof-ledger): das Offline-Gate erzwingt Aufnahme und Kopplung

Ein PR, der Code aendert, den nur ein Workflow ausfuehrt und kein Test
importiert, braucht jetzt einen Ledger-Eintrag oder eine ausdrueckliche
Ausnahme. Vorbei an dem Gate kommt man nicht durch Nichtstun.

Diff-bezogen wie check_r1_attested_sources, aus demselben Grund: ein
Zustandscheck auf main wuerde jeden PR rot machen, auch den reparierenden.
Der Bereich wird auf drei Punkte geweitet — `git diff A..B` vergleicht zwei
Baeume und meldet mains Aenderungen als die eigenen (#4373 am 4.8.).

Ohne Netz, damit der einzige required Check nicht von der GitHub-API und vom
Actions-Budget abhaengt.

Die Anti-Willkuer-Kopplung nach dem Muster von _DEPLOYMENT_IS_CONFIGURED:
SCHLAFEND und UNERREICHBAR brauchen eine pruefbare Repo-Tatsache. Verschwindet
sie, wird der Waechter rot — ein Beweis laesst sich nicht durch Umschreiben
eines Wortes stilllegen.
```

---

### Task 4: Der Urteiler-Vertrag und die vier Urteiler

**Files:**
- Create: `scripts/proof_judges/__init__.py`
- Create: `scripts/proof_judges/tv_partial_save.py`
- Create: `tests/proof_corpus/tv_partial_save/32620808573.json`
- Test: `tests/test_proof_ledger.py` (anhängen)

**Interfaces:**
- Produces: `scripts.proof_judges.Verdict` (frozen dataclass: `state: str`, `branch: str`, `detail: str = ""`); `VERDICTS: frozenset[str]`; `load_judge(name: str)`; `corpus_for(name: str) -> tuple[tuple[str, dict], ...]` (Paare aus Lauf-Id und Evidenz); `dig`, `has_path`. Vier Urteiler mit identischer Signatur `judge(evidence: dict, entry: ProofEntry) -> Verdict`: `tv_partial_save` (#5013), `tv_repair_only_contract` (#5025), `tv_failure_evidence` (#5020), `tv_legend_click` (#5018, liest `{"log": …}` statt eines Artefakts). **Jeder im Ledger benannte Urteiler muss existieren** — `judge_names()` leitet die Menge aus den Einträgen ab, ein fehlendes Modul bricht Task 5.

- [ ] **Step 1: Das echte Artefakt als Korpus-Eintrag ziehen**

```bash
mkdir -p tests/proof_corpus/tv_partial_save
tmp=$(mktemp -d)
gh run download 32620808573 -R skipp-dev/skipp-algo \
  -n tradingview-consumer-bindings -D "$tmp"
/Users/spreuss/Documents/skipp-algo/.venv/bin/python - "$tmp" <<'PY'
import json, pathlib, sys
src = next(pathlib.Path(sys.argv[1]).rglob("tradingview_consumer_bindings.json"))
full = json.loads(src.read_text())
reduced = {
    "_herkunft": {
        "run_id": "32620808573",
        "geladen_am": "2026-08-23",
        "warum": "erster Lauf, in dem der #5013-Partial-Save gefeuert hat",
        "lauf_conclusion": "failure",
    },
    "executionMode": full.get("executionMode"),
    "generatedAt": full.get("generatedAt"),
    "mutations": full.get("mutations", {}),
    "bindings": {
        "checkedConsumers": (full.get("bindings") or {}).get("checkedConsumers"),
        "mismatches": (full.get("bindings") or {}).get("mismatches"),
    },
}
out = pathlib.Path("tests/proof_corpus/tv_partial_save/32620808573.json")
out.write_text(json.dumps(reduced, indent=2, sort_keys=True) + "\n")
print("geschrieben:", out, "-", out.stat().st_size, "bytes")
PY
```

> Läuft der Download nicht (Artefakt abgelaufen, `gh` nicht angemeldet), **nicht** von Hand eine Datei erfinden. Ohne echten Korpus-Eintrag startet der Urteiler in Task 5 korrekt als `DRILL_ONLY` — das ist das ehrliche Ergebnis, keine Panne.

- [ ] **Step 2: Den fehlschlagenden Test schreiben**

An `tests/test_proof_ledger.py` anhängen:

```python
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
```

- [ ] **Step 3: Fehlschlag bestätigen**

```bash
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
PYTHONPATH=$PWD /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest \
  tests/test_proof_ledger.py -q --no-header -p no:randomly -k "judge or partial_save or save_phase"
```

Erwartet: `ModuleNotFoundError: No module named 'scripts.proof_judges'`.

- [ ] **Step 4: Vertrag und Urteiler schreiben**

`scripts/proof_judges/__init__.py`:

```python
#!/usr/bin/env python3
"""Vertrag fuer reine Urteiler ueber Beweis-Evidenz.

Ein Urteiler bekommt Evidenz und einen Ledger-Eintrag und gibt ein Urteil
zurueck. Er holt nichts, er schreibt nichts, er kennt keine Uhr — nur so ist
er gegen ein Korpus laufbar. Der Bash-Urteiler, den das hier abloest, war
nicht laufbar, und genau deshalb konnte einer seiner Zweige einen Tag lang
Urteile drucken, ohne je feuern zu koennen.

Jeder Zweig traegt ein LABEL (``branch=``). Die Labels werden in Task 5 per
AST aus dem Quelltext abgeleitet, nie abgeschrieben — eine abgeschriebene
Liste ist blind fuer Zuwachs.
"""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
CORPUS_ROOT = ROOT / "tests" / "proof_corpus"

VERDICTS = frozenset(
    {"PASS", "FAIL", "SCHLAFEND", "STEHT_AUS", "KANN_NICHT_BEZEUGEN", "PRUEFEN"}
)


@dataclass(frozen=True)
class Verdict:
    state: str
    branch: str
    detail: str = ""

    def __post_init__(self) -> None:
        if self.state not in VERDICTS:
            raise ValueError(f"unbekanntes Urteil {self.state!r}")


def load_judge(name: str) -> ModuleType:
    return importlib.import_module(f"scripts.proof_judges.{name}")


def corpus_for(name: str) -> tuple[tuple[str, dict], ...]:
    """``(run_id, evidenz)`` je aufgezeichnetem echten Artefakt."""
    folder = CORPUS_ROOT / name
    if not folder.exists():
        return ()
    return tuple(
        (path.stem, json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(folder.glob("*.json"))
    )


def dig(evidence: dict, dotted: str):
    """``mutations.partiallyRepairedChartUrls`` aufloesen; ``None``, wenn weg."""
    node = evidence
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def has_path(evidence: dict, dotted: str) -> bool:
    node = evidence
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True
```

`scripts/proof_judges/tv_partial_save.py`:

```python
#!/usr/bin/env python3
"""Urteiler fuer #5013 (Partial-Save) und #5025 (Layout-Waechter).

Liest AUSSCHLIESSLICH Artefaktinhalt. Lauf 32620808573 war ``conclusion:
failure`` und hat dabei exakt das Richtige getan — ``report.ok`` haengt an
einem nicht leeren ``partiallyRepairedChartUrls``. Wer die Conclusion liest,
fuehrt einen bestandenen Beweis als Fehlschlag.
"""

from __future__ import annotations

from scripts.proof_judges import Verdict, dig, has_path


def judge(evidence: dict, entry) -> Verdict:
    # Inhaltliche Versionsprobe zuerst: ohne das Feld lief aelterer Code, und
    # dann ist JEDES weitere Urteil eine Aussage ueber den falschen Baum.
    if entry.version_probe != "KEINE" and not has_path(evidence, entry.version_probe):
        return Verdict(
            "KANN_NICHT_BEZEUGEN",
            branch="pre_fix_code",
            detail=f"Artefakt ohne {entry.version_probe}",
        )

    mutations = evidence.get("mutations") or {}
    partial = set(mutations.get("partiallyRepairedChartUrls") or [])
    saved = set(mutations.get("savedChartUrls") or [])
    abandoned = set(mutations.get("abandonedChartUrls") or [])

    if partial and (partial & saved):
        return Verdict(
            "PASS",
            branch="partial_saved",
            detail=f"{len(partial)} Layout(s) unvollstaendig repariert UND gespeichert",
        )
    if partial:
        return Verdict(
            "PRUEFEN",
            branch="pruefen_partial_not_saved",
            detail=f"partiallyRepaired={sorted(partial)} nicht in savedChartUrls",
        )
    if not mutations.get("layoutSaveRequested"):
        # Die Bedingung mag vorgelegen haben — der Lauf ist nur nie so weit
        # gekommen. Das ist STEHT_AUS, nicht SCHLAFEND, und die beiden zu
        # verwechseln kostete am 23.8. dreizehn Stunden.
        return Verdict(
            "STEHT_AUS",
            branch="save_phase_never_reached",
            detail="layoutSaveRequested=false",
        )
    if abandoned:
        return Verdict(
            "PRUEFEN",
            branch="abandoned_after_fix",
            detail=f"abandoned={sorted(abandoned)} — nach #5013 nur noch per "
            "unbestaetigtem Save erreichbar",
        )
    return Verdict(
        "SCHLAFEND",
        branch="clean_run",
        detail="sauberer Durchlauf, der Zweig wurde nicht betreten",
    )
```

- [ ] **Step 5: Die drei übrigen Urteiler schreiben**

Das Ledger benennt vier Urteiler. `judge_names()` leitet sie aus den Einträgen ab, also bricht Task 5, sobald einer fehlt — jeder benannte Urteiler muss existieren.

`scripts/proof_judges/tv_repair_only_contract.py` (für #5025):

```python
#!/usr/bin/env python3
"""Urteiler fuer #5025: haelt ``repair-only`` seinen Vertrag?

Er darf genau zwei Dinge — Bindungen reparieren und das Layout speichern — und
weder Quellen deployen noch Instanzen entfernen. Am 2026-08-23 (Lauf
32620808573) gemessen: sourceSavesCompleted 0, producerInstancesRemoved 0,
consumerInstancesRemoved 0.
"""

from __future__ import annotations

from scripts.proof_judges import Verdict, has_path


def judge(evidence: dict, entry) -> Verdict:
    if entry.version_probe != "KEINE" and not has_path(evidence, entry.version_probe):
        return Verdict(
            "KANN_NICHT_BEZEUGEN",
            branch="pre_fix_code",
            detail=f"Artefakt ohne {entry.version_probe}",
        )
    if evidence.get("executionMode") != "repair-only":
        return Verdict(
            "STEHT_AUS",
            branch="not_a_repair_run",
            detail=f"executionMode={evidence.get('executionMode')!r}",
        )
    mutations = evidence.get("mutations") or {}
    verletzt = {
        name: mutations.get(name)
        for name in (
            "sourceSavesCompleted",
            "producerInstancesRemoved",
            "consumerInstancesRemoved",
        )
        if mutations.get(name)
    }
    if verletzt:
        return Verdict(
            "FAIL",
            branch="contract_broken",
            detail=f"repair-only hat mutiert: {verletzt}",
        )
    return Verdict(
        "PASS",
        branch="contract_held",
        detail="nichts deployt, nichts zerlegt",
    )
```

`scripts/proof_judges/tv_failure_evidence.py` (für #5020):

```python
#!/usr/bin/env python3
"""Urteiler fuer #5020: hinterlaesst ein gescheitertes Ziel eine Beweisdatei?

Beweisdateien entstehen NUR beim endgueltigen Scheitern eines Ziels. Ohne
Fehlschlag kein Beweis — das ist SCHLAFEND, nicht PASS.
"""

from __future__ import annotations

from scripts.proof_judges import Verdict, has_path


def judge(evidence: dict, entry) -> Verdict:
    if entry.version_probe != "KEINE" and not has_path(evidence, entry.version_probe):
        return Verdict(
            "KANN_NICHT_BEZEUGEN",
            branch="pre_fix_code",
            detail=f"Artefakt ohne {entry.version_probe}",
        )
    bindings = evidence.get("bindings") or {}
    beweise = bindings.get("evidence") or []
    gescheitert = bindings.get("failed") or []
    if beweise:
        return Verdict(
            "PASS",
            branch="evidence_written",
            detail=f"{len(beweise)} Beweisdatei(en)",
        )
    if gescheitert:
        return Verdict(
            "PRUEFEN",
            branch="failed_without_evidence",
            detail=f"{len(gescheitert)} Ziel(e) gescheitert, keine Beweisdatei",
        )
    return Verdict(
        "SCHLAFEND",
        branch="nothing_failed",
        detail="kein Ziel endgueltig gescheitert",
    )
```

`scripts/proof_judges/tv_legend_click.py` (für #5018):

```python
#!/usr/bin/env python3
"""Urteiler fuer #5018 — liest das JOB-LOG, nicht das Artefakt.

Der Sondenzweig vom 2026-08-22 suchte ``hit-target-miss`` in
``bindings.failed[].error``. Diese Spur geht ins Log und steht dort nie; der
Zweig konnte nie feuern und druckte trotzdem einen Tag lang Urteile. Deshalb
traegt der Ledger-Eintrag ``evidence_source = "job_log"`` und dieser Urteiler
bekommt ``{"log": "<text>"}``, nicht den Artefakt-Snapshot.
"""

from __future__ import annotations

from scripts.proof_judges import Verdict


def judge(evidence: dict, entry) -> Verdict:
    del entry  # keine inhaltliche Versionsprobe moeglich, siehe Ledger
    log = str(evidence.get("log") or "")
    if not log:
        return Verdict("KANN_NICHT_BEZEUGEN", branch="no_log", detail="Log leer")
    if "-hit-target-miss" in log:
        return Verdict(
            "FAIL",
            branch="click_missed_its_row",
            detail="Klickpunkt lag ausserhalb der Zeile",
        )
    if "identity-mismatch" in log:
        return Verdict(
            "FAIL",
            branch="identity_mismatch",
            detail="es ging der falsche Dialog auf",
        )
    if "openSettingsForScript" in log:
        return Verdict(
            "PRUEFEN",
            branch="dialog_stuck_without_miss",
            detail="Timeout, aber der Klick traf — Ursache liegt woanders",
        )
    return Verdict("PASS", branch="all_dialogs_opened", detail="keine Klick-Spur")
```

- [ ] **Step 6: Korpus für die drei nachziehen**

`tv_repair_only_contract` teilt sich den Zeugen mit `tv_partial_save`:

```bash
mkdir -p tests/proof_corpus/tv_repair_only_contract \
         tests/proof_corpus/tv_failure_evidence tests/proof_corpus/tv_legend_click
cp tests/proof_corpus/tv_partial_save/32620808573.json \
   tests/proof_corpus/tv_repair_only_contract/32620808573.json
```

Für `tv_failure_evidence` den Lauf `32556181388` ziehen (dort steht die Beweisdatei), nach demselben Reduktionsmuster wie in Step 1, zusätzlich mit `bindings.evidence` und `bindings.failed`.

Für `tv_legend_click` das Job-Log desselben Laufs:

```bash
job=$(gh api repos/skipp-dev/skipp-algo/actions/runs/32556181388/jobs \
        --jq '[.jobs[]|select(.name=="save")][0].id')
gh run view --job="$job" --log > /tmp/pl_log.txt
/Users/spreuss/Documents/skipp-algo/.venv/bin/python - <<'PY'
import json, pathlib
text = pathlib.Path("/tmp/pl_log.txt").read_text(errors="replace")
keep = [ln for ln in text.splitlines()
        if any(k in ln for k in ("hit-target", "identity-mismatch",
                                 "openSettingsForScript", "box-degenerate"))]
out = pathlib.Path("tests/proof_corpus/tv_legend_click/32556181388.json")
out.write_text(json.dumps({
    "_herkunft": {"run_id": "32556181388", "geladen_am": "2026-08-23",
                  "warum": "Lauf MIT #5018: hit-target-miss 0, Dialog trotzdem zu"},
    "log": "\n".join(keep),
}, indent=2) + "\n")
print("Zeilen behalten:", len(keep))
PY
```

> Ist `len(keep) == 0`, **nicht** weitermachen: dann greift der Filter daneben, und ein leeres Korpus sähe aus wie ein sauberer Lauf. Erst den Filter am echten Log prüfen.

Zweige, die danach keinen Treffer haben, gehören als `[[unreachable_branch]]` mit Grund ins Ledger — Task 5 nennt sie beim Namen.

- [ ] **Step 7: Tests grün**

```bash
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
PYTHONPATH=$PWD /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest \
  tests/test_proof_ledger.py -q --no-header -p no:randomly
```

Erwartet: 21 passed.

- [ ] **Step 8: Ruff und Commit**

```bash
/Users/spreuss/Documents/skipp-algo/.venv/bin/python -m ruff check .
git add scripts/proof_judges tests/proof_corpus tests/test_proof_ledger.py
git commit -F /tmp/pl_commit_4.txt
```

`/tmp/pl_commit_4.txt`:

```
feat(proof-ledger): reine Urteiler ueber Evidenzinhalt, mit echtem Korpus

Ein Urteiler bekommt Evidenz und einen Eintrag und gibt ein Urteil zurueck —
kein Netz, keine Uhr, keine Lauf-Conclusion. Nur so ist er gegen ein Korpus
laufbar, und genau diese Laufbarkeit fehlte dem Bash-Urteiler, dessen
#5018-Zweig einen Tag lang Urteile druckte, ohne feuern zu koennen.

Der erste Korpus-Eintrag ist der Lauf, der #5013 zum ersten Mal hat feuern
sehen: 32620808573, partiallyRepairedChartUrls UND savedChartUrls gefuellt,
abandonedChartUrls leer. Derselbe Lauf war conclusion=failure — deshalb pinnt
ein Test, dass im Urteiler das Wort conclusion nicht vorkommt.

STEHT_AUS und SCHLAFEND sind getrennte Zweige mit getrennten Labels.
```

---

### Task 5: Anti-Vakuität — ein Zweig, den nichts erreicht, wird rot

Das Herz des Ganzen. Am 2026-08-22 druckte ein Sondenzweig einen Tag lang Urteile, obwohl er strukturell nie feuern konnte: Er suchte `hit-target-miss` in `bindings.failed[].error`, aber diese Spur geht ins Job-Log. Diese Aufgabe macht genau das rot.

**Files:**
- Modify: `scripts/proof_judges/__init__.py` (AST-Ableitung anhängen)
- Test: `tests/test_proof_ledger.py` (anhängen)

**Interfaces:**
- Produces: `scripts.proof_judges.declared_branches(name: str) -> frozenset[str]`; `judge_names() -> frozenset[str]`; `class VacuityError(Exception)`

- [ ] **Step 1: Den fehlschlagenden Test schreiben**

An `tests/test_proof_ledger.py` anhängen:

```python
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
```

- [ ] **Step 2: Fehlschlag bestätigen**

```bash
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
PYTHONPATH=$PWD /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest \
  tests/test_proof_ledger.py -q --no-header -p no:randomly -k "branch or vacu or declares"
```

Erwartet: `ImportError: cannot import name 'declared_branches'`.

- [ ] **Step 3: Die AST-Ableitung schreiben**

An `scripts/proof_judges/__init__.py` anhängen (und `import ast` oben ergänzen):

```python
class VacuityError(Exception):
    """Die Zweig-Ableitung hat ihre Untergrenze unterschritten."""


def judge_names() -> frozenset[str]:
    """Alle im Ledger benannten Urteiler — abgeleitet, nicht gelistet."""
    from scripts.proof_ledger import load_entries

    return frozenset(entry.judge for entry in load_entries() if entry.judge)


def declared_branches(name: str) -> frozenset[str]:
    """Zweig-Labels aus dem QUELLTEXT des Urteilers ableiten.

    Nicht abschreiben. Eine Liste, die eine Kopie der bewachten Struktur ist,
    kann genau die Drift nicht fangen, vor der sie warnt — gemessen am
    2026-08-22, als #5013 ein neuntes ``mutations``-Feld hinzufuegte und der
    hartkodierte Kopplungstest gruen blieb.
    """
    module = load_judge(name)
    source = Path(module.__file__).read_text(encoding="utf-8")
    labels: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        called = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if called != "Verdict":
            continue
        for keyword in node.keywords:
            if (
                keyword.arg == "branch"
                and isinstance(keyword.value, ast.Constant)
                and isinstance(keyword.value.value, str)
            ):
                labels.add(keyword.value.value)
    if len(labels) < 2:
        raise VacuityError(
            f"{name}: nur {len(labels)} Zweig-Label(s) gefunden — der Parser ist "
            "kaputt, oder der Urteiler hat keine Verzweigung. Beides ist ein "
            "Befund, kein Ergebnis."
        )
    return frozenset(labels)
```

- [ ] **Step 4: Tests grün**

```bash
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
PYTHONPATH=$PWD /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest \
  tests/test_proof_ledger.py -q --no-header -p no:randomly
```

Erwartet: 24 passed. Schlägt `test_every_judge_branch_is_reached...` fehl, ist das **kein Testfehler** — dann fehlt ein Korpus-Eintrag oder eine Deklaration. Die Fehlermeldung nennt beide Auswege.

- [ ] **Step 5: Die Mutationsprobe, um die es geht — den #5018-Defekt nachstellen**

Vorher committen (Step 6 vorziehen), dann in `scripts/proof_judges/tv_partial_save.py` **vor** dem `return Verdict("SCHLAFEND", ...)` einen Zweig einbauen, der nie feuern kann:

```python
    if "hit-target-miss" in str(evidence.get("bindings", {}).get("failed", "")):
        return Verdict("PASS", branch="hit_target_miss_wirkt", detail="vakuoes")
```

Dann:

```bash
PYTHONPATH=$PWD /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest \
  tests/test_proof_ledger.py -q --no-header -p no:randomly \
  -k "every_judge_branch_is_reached"
```

Erwartet: **rot**, mit `tv_partial_save: Zweige ohne echten Korpus-Treffer und ohne Deklaration: ['hit_target_miss_wirkt']`. Das ist der Beweis, dass der Mechanismus genau den Defekt vom 22.8. am Tag seines Entstehens gefangen hätte. Danach den Zweig entfernen und erneut grün sehen.

- [ ] **Step 6: Ruff und Commit**

```bash
/Users/spreuss/Documents/skipp-algo/.venv/bin/python -m ruff check .
git add scripts/proof_judges/__init__.py tests/test_proof_ledger.py
git commit -F /tmp/pl_commit_5.txt
```

`/tmp/pl_commit_5.txt`:

```
feat(proof-ledger): ein Urteilszweig ohne echten Korpus-Treffer wird rot

Am 22.8. druckte ein Sondenzweig einen Tag lang Urteile, obwohl er
strukturell nie feuern konnte: Er suchte hit-target-miss in
bindings.failed[].error, aber diese Spur geht ins Job-Log. Niemand hat es
bemerkt, weil ein schweigender Zweig genauso aussieht wie ein gesunder.

Jetzt werden die Zweig-Labels per AST aus dem Quelltext des Urteilers
abgeleitet und gegen das Korpus aufgezeichneter ECHTER Artefakte gehalten.
Ein Zweig ohne Treffer muss in proof_ledger.toml mit Grund deklariert werden.

Handgeschriebene Fixtures reichen dafuer ausdruecklich nicht: eine
Positivkontrolle beweist, dass der Detektor das Signal SEHEN kann — nicht,
dass die gestellte Frage es enthalten kann.

Mutationsprobe gefahren: den vakuoesen Zweig nachgebaut, Test rot; entfernt,
Test gruen.
```

---

### Task 6: Verdrahtung in fast-gates

**Files:**
- Modify: `.github/workflows/smc-fast-pr-gates.yml`

**Interfaces:**
- Consumes: `scripts.check_proof_ledger.main`

- [ ] **Step 1: Den Wächter-Schritt einfügen**

Direkt **nach** dem Schritt `- name: Guard R1-attested sources` einfügen. Die `if:`- und `env:`-Form ist von dort übernommen, weil sie die Lane-Bedingungen dieses Jobs bereits korrekt trifft:

```yaml
      # Ein PR, der Code aendert, den nur ein Workflow ausfuehrt und kein Test
      # importiert, zeigt seine Wirkung erst im echten Lauf. Ohne Ledger-
      # Eintrag verdunstet "noch nicht bewiesen" still zu "wird schon stimmen":
      # am 2026-08-23 lag #5013 dreizehn Stunden auf einem Zustand, der von
      # "schlafend, also in Ordnung" nicht zu unterscheiden war.
      # Diff-bezogen und OHNE Netz — fast-gates ist der einzige required Check.
      - name: Guard the proof ledger
        if: (steps.gate.outputs.run_heavy == 'true') && github.event_name == 'pull_request'
        env:
          BASE_SHA: ${{ github.event.pull_request.base.sha }}
          HEAD_SHA: ${{ github.event.pull_request.head.sha }}
        run: |
          git fetch --depth=500 origin "$BASE_SHA" "$HEAD_SHA" 2>/dev/null || true
          python -m scripts.check_proof_ledger --range "${BASE_SHA}..${HEAD_SHA}"
```

- [ ] **Step 2: Den Test auf die feste fast-gates-Liste setzen**

In derselben Datei, in der langen `python -m pytest ... \`-Liste, direkt nach der Zeile `tests/test_prod_print_ledger.py \` einfügen:

```
            tests/test_proof_ledger.py \
```

- [ ] **Step 3: Die Workflow-Lints laufen lassen**

Dieses Repo hat drei Formwächter, die einen neuen oder geänderten Workflow rot machen, wenn er `defaults: run: shell: bash`, `permissions` oder `PYTHONUNBUFFERED` vermissen lässt:

```bash
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
PYTHONPATH=$PWD /Users/spreuss/Documents/skipp-algo/.venv/bin/python scripts/lint_workflow_defaults.py
PYTHONPATH=$PWD /Users/spreuss/Documents/skipp-algo/.venv/bin/python scripts/lint_workflow_permissions.py
PYTHONPATH=$PWD /Users/spreuss/Documents/skipp-algo/.venv/bin/python scripts/lint_workflow_pythonunbuffered.py
```

Erwartet: alle drei `rc=0`.

- [ ] **Step 4: Den Guard-Selektor gegenprüfen**

```bash
PYTHONPATH=$PWD /Users/spreuss/Documents/skipp-algo/.venv/bin/python \
  -m scripts.select_workflow_guards .github/workflows/smc-fast-pr-gates.yml
```

Erwartet: eine nicht leere Liste. Ist sie leer, liest kein Wächter diesen Workflow — dann meldet fast-gates `::warning::no guard reads the changed workflows`, und die Änderung ist unbewacht.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/smc-fast-pr-gates.yml
git commit -F /tmp/pl_commit_6.txt
```

`/tmp/pl_commit_6.txt`:

```
feat(proof-ledger): das Gate laeuft in fast-gates mit

Wachter-Schritt nach dem R1-Wachter, gleiche Lane-Bedingung, gleiche
Diff-Bezogenheit, kein Netz. Der Ledger-Test kommt auf die feste Liste,
damit er nicht erst nach dem Merge im main-Push-Job laeuft — genau durch
dieses Loch ist der Library-Refresh-Bot am 31.7. zweimal gegangen.
```

---

### Task 7: Der Monitor — Zeugen holen, urteilen, Widersprüche melden

**Files:**
- Create: `scripts/judge_proof_ledger.py`
- Create: `.github/workflows/proof-ledger-monitor.yml`
- Test: `tests/test_proof_ledger.py` (anhängen)

**Interfaces:**
- Consumes: `scripts.proof_ledger.load_entries`, `TERMINAL_STATES`, `scripts.proof_judges.load_judge`
- Produces: `scripts.judge_proof_ledger.classify(entry, verdict, today: str) -> str` (`"OK" | "UEBERFAELLIG" | "WIDERSPRUCH"`); `main(argv) -> int`

- [ ] **Step 1: Den fehlschlagenden Test schreiben**

An `tests/test_proof_ledger.py` anhängen:

```python
# --- Monitor (Task 7) -------------------------------------------------------


def test_a_declared_pass_that_measures_fail_is_a_contradiction():
    from scripts.judge_proof_ledger import classify
    from scripts.proof_ledger import ProofEntry
    from scripts.proof_judges import Verdict

    entry = ProofEntry(
        id="x", kind="fix", claim="c", state="PASS", pass_kind="live",
        due_by="2026-12-31", owner="operator", raw={},
    )
    assert classify(entry, Verdict("FAIL", branch="b"), "2026-08-23") == "WIDERSPRUCH"


def test_an_open_entry_past_its_deadline_is_overdue():
    from scripts.judge_proof_ledger import classify
    from scripts.proof_ledger import ProofEntry
    from scripts.proof_judges import Verdict

    entry = ProofEntry(
        id="x", kind="fix", claim="c", state="OFFEN",
        due_by="2026-08-01", owner="operator", raw={},
    )
    assert classify(entry, Verdict("STEHT_AUS", branch="b"), "2026-08-23") == "UEBERFAELLIG"


def test_a_terminal_entry_is_never_overdue():
    from scripts.judge_proof_ledger import classify
    from scripts.proof_ledger import ProofEntry
    from scripts.proof_judges import Verdict

    entry = ProofEntry(
        id="x", kind="exempt", claim="c", state="AUSGENOMMEN",
        due_by="2026-08-01", owner="operator", raw={},
    )
    assert classify(entry, Verdict("SCHLAFEND", branch="b"), "2026-08-23") == "OK"


def test_dormant_past_its_deadline_is_overdue_not_ok():
    """SCHLAFEND ist ein Durchgangszustand. Genau hier verdunstet es sonst."""
    from scripts.judge_proof_ledger import classify
    from scripts.proof_ledger import ProofEntry
    from scripts.proof_judges import Verdict

    entry = ProofEntry(
        id="x", kind="fix", claim="c", state="SCHLAFEND",
        due_by="2026-08-01", owner="operator",
        unreachable_because="symbol:scripts/proof_ledger.py#load_entries", raw={},
    )
    assert classify(entry, Verdict("SCHLAFEND", branch="b"), "2026-08-23") == "UEBERFAELLIG"
```

- [ ] **Step 2: Fehlschlag bestätigen**

```bash
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
PYTHONPATH=$PWD /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest \
  tests/test_proof_ledger.py -q --no-header -p no:randomly -k "contradiction or overdue or terminal_entry"
```

Erwartet: `ModuleNotFoundError: No module named 'scripts.judge_proof_ledger'`.

- [ ] **Step 3: Den Monitor schreiben**

`scripts/judge_proof_ledger.py`:

```python
#!/usr/bin/env python3
"""Hole je Ledger-Eintrag den Zeugen, urteile, melde Widersprueche.

Dies ist die netzgebundene Haelfte. Sie laeuft im scheduled Workflow, nie in
fast-gates: der einzige required Check darf nicht von der GitHub-API abhaengen.

Der Monitor schreibt das Ledger NICHT zurueck. Zustandsaenderungen macht ein
Mensch im PR, wo das Offline-Gate sie prueft. Ein Bot mit Schreibrecht auf die
Beweisfuehrung ist genau die Konstruktion, durch die der Library-Refresh-Bot
am 31.7. zweimal durch den R1-Vertrag gelaufen ist.

Zeugensuche: nach ``started_at`` des benannten JOBS fragen, nie nach
``head_sha``. Der Save-Workflow hat einen Fast-forward-Schritt, ein Lauf misst
also mit dem main-Stand seines Job-Starts. Wer head_sha nimmt, verwirft
gueltige Zeugen und wartet auf einen Beweis, den er selbst wegdefiniert hat.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys

from scripts.proof_ledger import TERMINAL_STATES, ProofEntry, load_entries
from scripts.proof_judges import Verdict, load_judge

REPO = "skipp-dev/skipp-algo"


def classify(entry: ProofEntry, verdict: Verdict | None, today: str) -> str:
    """``OK`` | ``UEBERFAELLIG`` | ``WIDERSPRUCH``."""
    if verdict is not None:
        declared_good = entry.state == "PASS"
        measured_bad = verdict.state in {"FAIL", "STEHT_AUS"}
        if declared_good and measured_bad:
            return "WIDERSPRUCH"
        if entry.state == "UNERREICHBAR" and verdict.state in {"PASS", "FAIL"}:
            return "WIDERSPRUCH"
    if entry.state in TERMINAL_STATES:
        return "OK"
    if dt.date.fromisoformat(entry.due_by) < dt.date.fromisoformat(today):
        return "UEBERFAELLIG"
    return "OK"


def _gh(*args: str) -> str:
    proc = subprocess.run(
        ["gh", *args], capture_output=True, text=True, check=False
    )
    return proc.stdout if proc.returncode == 0 else ""


def newest_witness(entry: ProofEntry) -> str:
    """Lauf-Id des juengsten Laufs, dessen Zeugen-JOB nach dem Merge startete."""
    raw = _gh(
        "api",
        f"repos/{REPO}/actions/workflows/{entry.witness}.yml/runs?per_page=50",
        "-q",
        '.workflow_runs[] | select(.status=="completed") | .id',
    )
    for run_id in raw.split():
        started = _gh(
            "api",
            f"repos/{REPO}/actions/runs/{run_id}/jobs?per_page=100",
            "-q",
            f'[.jobs[] | select(.name=="{entry.witness_job}") | .started_at][0] // ""',
        ).strip()
        # Auf FORM pruefen, nicht auf "nicht leer": `gh api` schreibt seinen
        # Fehler-Body nach STDOUT. Ein 404 liefert `{"message":...}`, und weil
        # '{' groesser ist als jede Ziffer, kuerte ein reiner Groessenvergleich
        # einen Lauf ohne Zeugen-Job zum Zeugen.
        if len(started) != 20 or not started.endswith("Z") or not started[:4].isdigit():
            continue
        if started > (entry.raw or {}).get("merged_at", ""):
            return str(run_id)
    return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--today", default=dt.date.today().isoformat())
    parser.add_argument("--json", dest="json_out", default="")
    args = parser.parse_args(argv)

    rows: list[dict] = []
    for entry in load_entries():
        verdict: Verdict | None = None
        run_id = ""
        if entry.kind == "fix" and entry.evidence_source == "artifact" and entry.judge:
            run_id = newest_witness(entry)
            if run_id:
                out = _gh(
                    "run", "download", run_id, "-R", REPO,
                    "-n", entry.artifact, "-D", f"/tmp/pl_{run_id}",
                )
                del out
                try:
                    with open(
                        f"/tmp/pl_{run_id}/tradingview_consumer_bindings.json",
                        encoding="utf-8",
                    ) as fh:
                        verdict = load_judge(entry.judge).judge(json.load(fh), entry)
                except (OSError, json.JSONDecodeError):
                    verdict = None
        rows.append(
            {
                "id": entry.id,
                "declared": entry.state,
                "measured": verdict.state if verdict else "KEIN_ZEUGE",
                "branch": verdict.branch if verdict else "",
                "run": run_id,
                "owner": entry.owner,
                "due_by": entry.due_by,
                "class": classify(entry, verdict, args.today),
            }
        )

    loud = [r for r in rows if r["class"] != "OK"]
    for row in rows:
        print(
            f"{row['class']:14s} {row['id']:24s} deklariert={row['declared']:12s} "
            f"gemessen={row['measured']:20s} faellig={row['due_by']} ({row['owner']})"
        )
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, indent=2, sort_keys=True)
    if loud:
        print(f"\n{len(loud)} Eintrag/Eintraege brauchen einen Menschen.", file=sys.stderr)
    return 1 if loud else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Tests grün**

```bash
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
PYTHONPATH=$PWD /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest \
  tests/test_proof_ledger.py -q --no-header -p no:randomly
```

Erwartet: 28 passed.

- [ ] **Step 5: Den Monitor gegen die echte Lage laufen lassen**

```bash
PYTHONPATH=$PWD /Users/spreuss/Documents/skipp-algo/.venv/bin/python \
  -m scripts.judge_proof_ledger --today "$(date -u +%F)"; echo "rc=$?"
```

Erwartet: sechs Zeilen. Die drei PASS-Einträge auf `OK`, `#5018` auf `OK` (Frist 6.9.), die zwei `defect`-Einträge auf `OK` (Frist 6.9.). Meldet der Lauf einen `WIDERSPRUCH`, ist das ein **echter Befund** — dann zuerst messen, welche Seite lügt, und erst dann irgendetwas ändern.

- [ ] **Step 6: Den Workflow anlegen**

`.github/workflows/proof-ledger-monitor.yml`:

```yaml
name: proof-ledger-monitor

# Die netzgebundene Haelfte des Beweis-Ledgers. Sie holt Zeugen, urteilt und
# meldet — und schreibt das Ledger NIE zurueck. Zustandsaenderungen macht ein
# Mensch im PR, wo das Offline-Gate sie prueft.
on:
  schedule:
    - cron: "17 6 * * *"
  workflow_dispatch:

permissions:
  contents: read
  issues: write

defaults:
  run:
    shell: bash

concurrency:
  group: proof-ledger-monitor
  cancel-in-progress: false

jobs:
  judge:
    runs-on: ubuntu-latest
    env:
      PYTHONUNBUFFERED: "1"
    steps:
      - name: Checkout
        uses: actions/checkout@v5

      - name: Set up pinned Python
        uses: ./.github/actions/setup-python-pinned

      - name: Judge the ledger
        id: judge
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          set +e
          python -m scripts.judge_proof_ledger \
            --today "$(date -u +%F)" --json proof_ledger_report.json \
            | tee -a "$GITHUB_STEP_SUMMARY"
          echo "loud=$?" >> "$GITHUB_OUTPUT"

      - name: Open or update the one issue
        if: steps.judge.outputs.loud != '0'
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          title="Beweis-Ledger: Eintraege brauchen einen Menschen"
          body="$(python - <<'PY'
          import json
          rows = json.load(open("proof_ledger_report.json"))
          loud = [r for r in rows if r["class"] != "OK"]
          print("Stand des automatischen Urteils. Das Ledger wird NICHT vom Bot")
          print("geaendert — Zustandsaenderungen gehoeren in einen PR.\n")
          for r in loud:
              print(f"- **{r['class']}** `{r['id']}` — deklariert `{r['declared']}`, "
                    f"gemessen `{r['measured']}` (Zweig `{r['branch']}`), "
                    f"faellig {r['due_by']}, Halter @{r['owner']}"
                    + (f", Lauf {r['run']}" if r["run"] else ""))
          PY
          )"
          existing="$(gh issue list --repo "$GITHUB_REPOSITORY" --state open \
            --search "$title in:title" --json number --jq '.[0].number // ""')"
          if [ -n "$existing" ]; then
            gh issue edit "$existing" --repo "$GITHUB_REPOSITORY" --body "$body"
          else
            gh issue create --repo "$GITHUB_REPOSITORY" --title "$title" --body "$body"
          fi
```

- [ ] **Step 7: Workflow-Lints und Guard-Selektor**

```bash
PYTHONPATH=$PWD /Users/spreuss/Documents/skipp-algo/.venv/bin/python scripts/lint_workflow_defaults.py
PYTHONPATH=$PWD /Users/spreuss/Documents/skipp-algo/.venv/bin/python scripts/lint_workflow_permissions.py
PYTHONPATH=$PWD /Users/spreuss/Documents/skipp-algo/.venv/bin/python scripts/lint_workflow_pythonunbuffered.py
PYTHONPATH=$PWD /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest \
  tests/test_workflow_runner_pinned.py tests/test_workflow_upload_artifact_uniform_version.py \
  -q --no-header -p no:randomly
```

Alle vier müssen sauber sein. `test_workflow_runner_pinned` verlangt gegebenenfalls die Runner-Auflösung über `scripts/resolve_workflow_runner.py` statt `runs-on: ubuntu-latest` — dann die Form von einem bestehenden scheduled Workflow übernehmen, nicht raten.

- [ ] **Step 8: Ruff, Volllauf, Commit**

```bash
/Users/spreuss/Documents/skipp-algo/.venv/bin/python -m ruff check .
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
PYTHONPATH=$PWD /Users/spreuss/Documents/skipp-algo/.venv/bin/python -m pytest \
  tests/test_proof_ledger.py -q --no-header -p no:randomly
git add scripts/judge_proof_ledger.py .github/workflows/proof-ledger-monitor.yml \
  tests/test_proof_ledger.py
git commit -F /tmp/pl_commit_7.txt
```

`/tmp/pl_commit_7.txt`:

```
feat(proof-ledger): der Monitor findet Widersprueche, nicht nur Fristen

Taeglich: je Eintrag den Zeugen holen (nach started_at des JOBS, nie nach
head_sha — der Save-Workflow forwardet auf aktuelles main, ein Lauf misst mit
dem Stand seines Job-Starts), urteilen, und das Urteil gegen den DEKLARIERTEN
Zustand halten.

Zwei Alarmklassen. UEBERFAELLIG faengt das Verdunsten. WIDERSPRUCH ist der
eigentliche Gewinn: er macht aus dem Ledger eine ueberpruefbare Behauptung
statt einer Wunschliste. Ein Eintrag, der faelschlich auf PASS steht, wird
widerlegt statt geglaubt.

Der Bot schreibt das Ledger nicht zurueck und meldet in genau ein Issue.
```

---

## Reihenfolge und Abbruchpunkte

Task 0 zuerst und allein: Fällt die Aufnahmequote über 25 %, **hier anhalten** und die Trigger-Ableitung neu schneiden. Danach 1 → 2 → 3 → 4 → 5 in dieser Reihenfolge; 6 und 7 sind voneinander unabhängig.

Nach Task 5 ist der Kern fertig und der Mechanismus beweisbar wirksam (Mutationsprobe in Task 5, Step 5). Tasks 6 und 7 machen ihn wirksam **ohne dass jemand daran denkt** — ohne sie bleibt das Ganze ein Skript, das man aufrufen muss, und damit genau das, was es ablösen soll.
