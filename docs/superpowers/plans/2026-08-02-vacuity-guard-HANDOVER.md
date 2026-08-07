# Handover — Vakuitäts-Guard (repo-weit, Python + TypeScript)

**Stand:** 2026-08-02, Ende der Vorsession. Der Plan ist **noch nicht geschrieben**; diese
Datei enthält die vollständige Recherche, auf der er aufsetzt, damit die neue Session nicht
neu messen muss.

**Nächster Schritt:** `/superpowers:writing-plans` mit diesem Dokument als Spec ausführen und
den Plan nach `docs/superpowers/plans/2026-08-02-vacuity-guard.md` schreiben.

> Diese Datei ist **untracked**. `git status` zeigte in der Vorsession bereits `.tmp/`,
> `docs/demos/`, `scratchpad/` als untracked — das ist der Normalzustand hier, kein Defekt.

---

## 1. Ausgangslage

Alle Arbeitsstränge der Vorsession sind **geschlossen**:

- **#4303** (`fix(tv): give the rollout one provenance field it did not write itself`) —
  **gemergt** 2026-08-01T11:15:49Z.
- **Rotes main** durch #4297 — **repariert** (nicht von mir). `tests/test_workflow_databento_handoff_concurrency.py:62`
  importiert jetzt `SHARED_GROUP` statt den Literalwert zu wiederholen, mit dem Kommentar
  `# Imported, not re-spelled: #4297 moved smc-library-refresh into the shared …`.
- Alle Verifikations-Worktrees belegt entfernt.

**Repo-Stand bei Übergabe:** lokales `HEAD=5e5243fd3`, `origin/main=887f6f1be` (5 Merges der
Parallelarbeit voraus: #4324–#4328). **Der lokale Checkout hängt hinterher** — für die Arbeit
Worktree off `origin/main`, Lesen via `git show origin/main:<datei>`.

---

## 2. Der Auftrag

Vom Nutzer aus drei Optionen gewählt: **Vakuitäts-Guard, repo-weit**.

**Bug-Klasse:** Eine Prüfung, die grün meldet, ohne etwas beobachtet zu haben — nicht „Kante
fehlt" (das ist der Verdrahtungs-Sweep, in drei Pässen erledigt), sondern „Menge ist leer,
Schleife läuft null Mal, Assertion feuert nie".

Belegte Präzedenzfälle des Nutzers:
- Archiv-Gate in `tests/test_pine_surface_registry.py` — iterierte über null archivierte Surfaces.
- `getVisibleChartScriptError` in `automation/tradingview/lib/tv_shared.ts:8125` — leere
  Legend-Menge ⇒ `null` ⇒ „sauber".

Umfang: **Python UND TypeScript, Tests UND Produktivcode.**

---

## 3. Gemessene Fakten (alle empirisch, nicht geschätzt)

### 3.1 Größe der Klasse

Prototyp-Detektor (AST) über `tests/**/*.py`:

| Messung | Wert |
|---|---|
| Test-Dateien gescannt | 1622 |
| Naiver Detektor (jede Schleife mit `assert`) | **922** Treffer in 332 Dateien |
| Verschärft auf **entdeckte/gefilterte** Iterables | **29** Treffer in **17** Dateien |

Die Verschärfung ist der Kern: `for flag in ("--start-date", "--end-date")` und
`for i in range(2)` iterieren über **Literale, die nie leer sein können** — keine Vakuität.
Die echte Klasse sind Mengen, die zur Laufzeit leer werden können:

- **Discovery:** `.glob()`, `.rglob()`, `.iterdir()`, `re.finditer()`, `re.findall()`
- **Gefilterte Comprehension:** `[x for x in Y if COND]` ← die Form des Archiv-Gates
- Namen, die im selben Scope an eines von beiden gebunden sind
- Helper-Funktionen, die eines von beiden zurückgeben

Aufschlüsselung der 29: 12 `local filtered-comprehension (all/any)`, 9 `helper returns
filtered set`, 5 `discovery call`, 1 `helper returns discovery (all/any)`,
1 `local discovery-call`, 1 `local filtered-comprehension`.

Die Prototypen liegen unter
`/private/tmp/claude-501/-Users-spreuss/f3e74ddd-.../scratchpad/vacuity_probe.py` und
`vacuity_probe2.py` — **session-lokal, gehen verloren.** `vacuity_probe2.py` ist der
verschärfte; seine Logik ist unten in §5 beschrieben und muss in der neuen Session als
`scripts/detect_vacuous_claims.py` TDD-mäßig neu gebaut werden (nicht kopiert — der
Prototyp hat bekannte Schwächen, siehe §3.3).

**Kalibrierung:** Der Detektor findet den vom Nutzer genannten Präzedenzfall selbst wieder —
`tests/test_pine_surface_registry.py:240` und `:292`.

### 3.2 Der stärkste Einzelbeleg

`tests/test_enrichment_contract_integration.py`, zwei **direkt benachbarte** Tests derselben
Klasse mit identischer Form:

```python
    def test_pine_syntax_valid(self, base_csv: Path, tmp_path: Path):      # Zeile 374
        text = _run_pipeline(base_csv, tmp_path, enrichment=_full_enrichment())
        assert text.startswith("//@version=6\n")
        export_lines = _export_lines(text)
        type_pat = re.compile(r'^export const (string|int|float|bool) [A-Z0-9_]+ = .+')
        for line in export_lines:                    # <-- KEIN Zeuge. Leer ⇒ grün.
            assert type_pat.match(line), f"Bad export line: {line}"

    def test_no_python_booleans(self, base_csv: Path, tmp_path: Path):     # Zeile 382
        text = _run_pipeline(base_csv, tmp_path, enrichment=_full_enrichment())
        bool_lines = [ln for ln in text.splitlines() if "const bool " in ln]
        # See test_smc_library_pipeline_integration.test_booleans_lowercase:
        # an empty list makes this gate pass without checking anything.
        assert bool_lines, "generator emitted no 'const bool' export — Python-bool pin would pass vacuously"
        for line in bool_lines:
            assert "True" not in line and "False" not in line, f"Python bool in: {line}"
```

Jemand hat die Klasse erkannt, **einen** Fall geheilt und den identischen Nachbarn direkt
darüber stehen lassen. Das ist das Argument gegen Handarbeit — in einem Satz und mit Beleg.

### 3.3 Bekannte False Positives des Prototyps (müssen im echten Detektor weg)

**Das `frozen site`-Idiom** — `tests/test_global_statement_budget.py:394` und
`tests/test_http_client_discipline.py:288`. Beide sehen vakuum-verdächtig aus, sind es aber
**nicht**:

```python
    for node in ast.walk(tree):
        if isinstance(node, ast.Global) and node.lineno == lineno:
            ...
            return
    raise AssertionError(f"{rel}:{lineno}: ``global`` statement no longer present — …")
```

Findet die Schleife nichts, fällt sie in ein explizites `raise`. **Das ist das korrekte
Anti-Vakuitäts-Idiom** und muss als Zeuge anerkannt werden (ebenso `for … else: raise`).

**Zeuge muss pro Iterable binden, nicht pro Test.** Der Prototyp verlässt die Funktion bei
*irgendeinem* Zeugen. Falsch: `assert bool_lines` beweist nichts über `export_lines`.
Belegt an §3.2.

**Teil-Vakuität.** `tests/test_pytest_marker_bucket_discipline.py:179`: der Test als Ganzes
prüft echt etwas (Sentinel-Check, `not_fast`-Check), aber die *eine* Glob-Behauptung darin
ist vakuum-anfällig. Der Guard bewertet die **Behauptung**, nicht den Test.

### 3.4 Zweiter Vektor: leeres `parametrize`

```python
@pytest.mark.parametrize(("rel", "lineno", "names"), sorted(_FROZEN_SITES))
def test_frozen_global_site_still_present(...)
```

Wäre `_FROZEN_SITES` leer, sammelt pytest **null Tests** ein und meldet nichts — kein
Skip, kein Fail, keine Zeile. **Verifiziert: für `_FROZEN_SITES` und `_FROZEN_URLOPEN_SITES`
existiert kein Nicht-Leer-Test** (`grep -rn "assert _FROZEN_SITES" tests/…` → 0 Treffer).
Fix-Idiom: ein `test_<ledger>_roster_is_not_empty`.

### 3.5 Das Repo kennt den Begriff schon

**34 Erwähnungen** von „vacuous/vacuity" in `tests/`, u. a.:

- `tests/test_live_overlay_dashboard_contract.py:135` —
  `assert timelines, "no state-timeline panel found — legend pin would pass vacuously"`
- `tests/test_enrichment_contract_integration.py:387` — s. §3.2
- `tests/test_smc_r1_rollout_contract.py:116` — `"""The anti-vacuity pin.`
- `tests/test_databento_env_vars_documented.py:63` — `"regex broke; this test would otherwise pass vacuously"`

⇒ Es fehlt **nicht die Einsicht und nicht das Idiom**, sondern die Durchsetzung. Der Guard
kodifiziert eine bereits gelebte Konvention; das ist der Rahmen für die PR-Beschreibung.

Ein Vakuitäts-Guard existiert noch nicht (`grep -rln 'vacuo|vacuit|Vakuit'` über `*.py *.ts
*.yml *.md` zeigt nur Doku/Kommentare, keinen Prüfer).

---

## 4. Registrierungspunkte (exakt, verifiziert)

### Python
- **Pin-Registry:** `pin_registry.toml` (Top-Level-Tabelle pro Ledger-Test), geladen **nur**
  über `tests/_pin_registry.py` — Accessor-Funktion pro Slice, nie direkt parsen.
  ADR: `docs/adr/0009-pin-ledger-consolidation.md`.
- **fast-gates:** `.github/workflows/smc-fast-pr-gates.yml`, Step
  `- name: Run pin / ledger drift guard` (bei Zeile 397). Die Datei-Liste dort ist die
  Single Source of Truth, aus der `scripts/run_ledger_drift_guard.sh` per `awk` liest.
- **Diff-getriebene Auswahl (neu, 2026-08-01):** Step
  `- name: Run every guard that reads a workflow this PR changed` (Zeile 577), gestützt auf
  `scripts/select_workflow_guards.py`. Dessen Docstring ist die **Stilvorlage** für den neuen
  Guard: erst messen, dann behaupten; die Klasse schließen, nicht die Instanz.
  ⚠️ Der Step enthält selbst eine vakuitäts-förmige Stelle:
  `if [ -z "${guards}" ]; then echo "::warning::no guard reads the changed workflows"; exit 0; fi`
  — null ausgewählte Guards ⇒ Warnung ⇒ grün. Ehrlich (es warnt), aber unbeobachtet.

### TypeScript
- **Tests:** `automation/tradingview/tests/*.test.ts`, `node:test` via
  `npx tsx --test`. Lokal: `npm run tv:test`.
- **Registrierung (Pflicht, zwei Stellen):** `.github/workflows/tv-onboarding-packages.yml` —
  (a) `paths:`-Trigger oben, (b) der Step `- name: Test hermetic TV pins` (Zeile 186–190),
  eine einzige lange Datei-Liste in der `run:`-Zeile. Ein neuer Test, der dort nicht steht,
  läuft in CI **nicht**.
- **Tri-State-Vorbild:** `resolveLibraryPublishObservation` in
  `automation/tradingview/lib/tv_consumer_rollout_evidence.ts` (aus #4303) —
  `match | drift | unknown`, `unknown` wird NICHT zu `match` gerundet.
- **Produktivcode-Ziel:** `automation/tradingview/lib/tv_shared.ts:8125`
  `getVisibleChartScriptError` → delegiert an `probeVisibleChartScriptError` und mappt
  `CHART_ERROR_PROBE_UNREADABLE` auf `null`, also „unlesbar" auf „sauber".

---

## 5. Bereits festgelegte Design-Entscheidungen

**Modul:** `scripts/detect_vacuous_claims.py` — eigenständig, importierbar, mit CLI
(`python -m scripts.detect_vacuous_claims tests/`), modelliert nach
`scripts/select_workflow_guards.py`.

**Datentyp:**
```python
@dataclass(frozen=True)
class VacuousClaim:
    path: str      # repo-relativ, posix
    lineno: int
    test: str
    iterable: str  # ast.unparse des iterierten Ausdrucks
    kind: str
```

**Regel:** Eine Behauptung ist vakuum-anfällig, wenn eine `assert`-tragende Iteration über
ein Iterable läuft, das leer sein *kann* (§3.1), und **für genau dieses Iterable** kein
Zeuge existiert.

**Zeugen (alle vier müssen anerkannt werden):**
1. `assert <name>` (bloße Wahrheitsprüfung) — das gelebte Idiom aus §3.5
2. `assert len(<name>) …`
3. `assert <name> == <nicht-leeres Literal>`
4. Schleifen-Erschöpfung: `raise` direkt nach der Schleife, oder `for … else: raise`

**Ausnahmen** in `pin_registry.toml` unter `[vacuous_claim_guard.exemptions]`, Key
`"tests/x.py::test_y::iterable"`, Wert = **datierte Begründung**. Das Archiv-Gate gehört
dorthin: seine Leere ist deklariert und wird von
`test_the_archived_population_is_declared_rather_than_incidental` (Zeile 205 ff., mit
`assert [surface.file for surface in _archived_surfaces()] == []`) gepinnt, die Regel selbst
in `tests/test_archived_surface_consumers.py` **auf Daten** bewiesen.

**Der Guard muss sich selbst anwenden.** `assert undeclared == []` über eine leere Liste ist
genau die Form, die er verbietet. Er braucht deshalb einen eigenen Zeugen:
```python
assert len(scanned) > 1_000, "analyzer scanned nothing — this guard would pass vacuously"
```
Das ist der stärkste Teil des Entwurfs und gehört in die PR-Beschreibung.

**Stale-Ausnahmen:** jede Exemption muss weiterhin einem erkannten Claim entsprechen, sonst
rot — analog zu den `frozen site still present`-Tests.

---

## 6. Vorgeschlagener Task-Zuschnitt (7 Tasks)

1. **Analyzer-Kern** — anfällige Iterables erkennen (`scripts/detect_vacuous_claims.py` +
   `tests/test_detect_vacuous_claims.py`). Rot-zuerst: Literal-Tupel **nicht** flaggen,
   gefilterte Comprehension und Discovery **flaggen**.
2. **Zeugen-Erkennung, pro Iterable** — die vier Formen aus §5. Rot-Test muss die echten
   Repo-Formen enthalten: das Paar aus §3.2 und das `frozen site`-Idiom aus §3.3.
3. **Leeres `parametrize`** (§3.4) + Fix-Idiom `test_<ledger>_roster_is_not_empty`.
4. **Guard + Exemption-Registry + fast-gates-Verdrahtung** — inkl. Selbstanwendung.
   ⚠️ Workflow-Edit ⇒ zusätzlich `pytest tests/ -k workflow` (≈2100 Tests, ≈4 min).
5. **Baseline-Triage** der 29 Treffer: echte fixen mit dem gelebten Idiom, deklariert-leere
   in die Registry, False Positives als Detektor-Verschärfung zurückspielen.
6. **TS-Analyzer + Guard** über `automation/tradingview/tests/`, beide Registrierungsstellen.
7. **TS-Produktivcode: Tri-State** für die `getVisibleChartScriptError`-Klasse.
   ⚠️ **Verhaltensänderung auf der Live-Operator-Fläche** — muss dem Nutzer **vorgelegt**
   werden, darf nicht als Bugfix durchgeschoben werden. Eigener PR, eigenes Signal.

Tasks 1–5 (Python) sind unabhängig von 6–7 (TypeScript) lieferbar.

---

## 7. Verbindliche Randbedingungen (teils hook-erzwungen)

- **Nie mergen ohne explizites Signal des Nutzers.** Ausnahme in der Vorsession war
  ausschließlich die Reparatur einer eigenen Regression aus einem bereits freigegebenen PR.
- Sibling-Worktree off `origin/main` (z. B. `/Users/spreuss/Documents/skipp-algo-wt-vacuity`).
  **Nie** verschachtelt, **nie** unter `.claude/worktrees/` — sonst False Positives in den
  Budget-Guards.
- **Ledger-Guard nur mit** `PYTEST_XDIST_AUTO_NUM_WORKERS=4` (hook-erzwungen; `-n auto`
  SIGKILLt mit rc=137 auf dem 16-GB-Mac). `ruff check .` **separat** — der Guard deckt ihn nicht.
- **Repo-`.venv`** (`/Users/spreuss/Documents/skipp-algo/.venv/bin/python`, 3.12), nie System-3.9.
- `git push` **immer** `run_in_background=true` (Foreground-Timeout verwaist den pre-push-Hook).
- **Nie `--no-verify`.**
- Netto-Null-Edits nahe line-gepinnten `.py`; vorher prüfen, ob unter der Änderung Pins liegen.
- `fast-gates` ist der **einzige** required Check (ADR-0011) — ein grüner PR kann main
  trotzdem rot machen. Für Workflow-Edits gilt §6/Task 4.
- **Parallelarbeit hat Vorrang.** Auf demselben Account läuft ein schneller Bug-Hunt;
  `origin/main` bewegt sich mehrmals täglich. Vor jedem Branch neu `git fetch` und offene
  PRs prüfen (`gh pr list`).
- **cwd-Falle:** Die Shell springt gelegentlich auf `/Users/spreuss` zurück. Der
  `bash-cwd-context.sh`-Hook meldet das nach jedem Bash-Call — **lesen**. In der Vorsession
  hat das zweimal verhindert, dass Messungen gegen den falschen Baum liefen. Absolute Pfade
  benutzen.

---

## 8. Was ausdrücklich NICHT getan ist

- Der Plan selbst (`docs/superpowers/plans/2026-08-02-vacuity-guard.md`) ist **nicht geschrieben**.
- Kein Code, kein Branch, kein Worktree, kein PR.
- Die 29 Treffer sind **nicht einzeln triagiert** — nur vier davon habe ich am Code
  angesehen (§3.2, §3.3). Der Rest ist unbewertet; die True-Positive-Quote der verbleibenden
  25 ist **unbekannt** und darf nicht behauptet werden.
- Die Messung lief gegen den **lokalen** Checkout `5e5243fd3`, nicht gegen
  `origin/main=887f6f1be`. Vor dem Baseline-Task neu messen.
  → **Erledigt in Session 3 (§9.1): Baseline trägt, weiterhin 29/17.**

---

## 9. Nachtrag Session 3 (2026-08-03) — alles verifiziert, Plan weiterhin ungeschrieben

Session 3 (API-Abbruch-Fortsetzung) hat **keinen Code geschrieben** und **keinen Plan** —
nur weiterrecherchiert. Alles Folgende ist gemessen, nicht geschätzt.

### 9.1 Baseline gilt gegen origin/main

`git diff --name-only HEAD origin/main` (5e5243fd3 → 887f6f1be) berührt **weder `tests/`
noch `scripts/`** (nur `pin_registry.toml` +7/-0, TS-lib, Workflows, Docs). Loop-Probe neu
gelaufen: **weiterhin 29 Treffer in 17 Dateien**, identische Liste. §8-Punkt „neu messen"
ist damit erledigt.

### 9.2 Registrierungsmechanik vollständig kartiert (ersetzt §4-Python teilweise)

**Der neue Guard registriert sich selbst als Pflicht:** `_pinned_ledgers()` in
`tests/test_fast_gates_silent_skip_coverage.py` erkennt jede Testdatei, die den String
`pin_registry` enthält (dritter Zweig der Discovery, nach Line-Pins und Count-Pins).
Sobald `tests/test_vacuous_claim_guard.py` die Registry liest, verlangt
`test_every_pinned_ledger_is_on_the_required_path` (Zeile 478) seine Aufnahme — sonst rot.
**Drei Flächen, alle im selben PR:**

1. `.github/workflows/smc-fast-pr-gates.yml` — Step „Run pin / ledger drift guard",
   Datei-Liste endet Zeile 568 (`tests/test_update_overlay_dashboard.py`). Dort anfügen.
   `_drift_guard_step_text()` (Zeile 300–312) scoped von „Run pin / ledger drift guard"
   bis „Run fast SMC integration tests" und **strippt Kommentare**.
2. `FULL_REQUIRED_PATH_TRIPWIRES` in `tests/test_fast_gates_silent_skip_coverage.py:98`
   — der Roster-Check ist **bidirektional** (Zeile 340 missing + Zeile 352 extra):
   Step-Eintrag ohne Roster-Eintrag ist genauso rot.
3. `FAST_TEST_FILES` in `tests/_fast_inventory.py` (ADR-0012-Partition;
   `tests/test_pytest_marker_bucket_discipline.py` prüft Lock-Step mit dem Workflow).

`scripts/run_ledger_drift_guard.sh` liest die Liste per `awk` aus dem Workflow-Step —
**keine vierte Fläche**, läuft automatisch mit.

**Kein Schema-Guard auf `pin_registry.toml`:** Die neue Tabelle
`[vacuous_claim_guard.exemptions]` braucht nur einen Accessor in `tests/_pin_registry.py`
(nie direkt parsen, ADR-0009). Kein weiterer Test kennt das TOML-Schema als Ganzes.

**Das Selbst-Zeugen-Idiom lebt schon dreimal in den Meta-Guards** — exakt die §5-Form:
`assert len(ledgers) >= 15` (Z. 495), `assert len(guards) >= 15` (Z. 565),
`assert len(all_ts) >= 20` (Z. 929). Der neue Guard zitiert diese Präzedenz.

**TS-Registrierung ist hook-erzwungen, nicht nur Konvention:**
`test_every_ts_test_is_gated_or_exempt` (Z. 919) macht jeden neuen `*.test.ts` rot, der
weder im `npx tsx --test`-Step läuft noch in `_TS_TESTS_INTENTIONALLY_UNGATED` steht;
`test_gated_ts_tests_trigger_their_own_workflow` (Z. 957) verlangt **zusätzlich** den
`paths:`-Eintrag in **beiden** Trigger-Blöcken (push Z. 9, pull_request Z. 67 in
`tv-onboarding-packages.yml`). Run-Step „Test hermetic TV pins" ist Zeile 188. Ein
hermetischer (playwright-freier) TS-Analyzer-Test gehört in den Step + beide paths-Listen.

### 9.3 §3.4 präzisiert: der echte parametrize-Vektor ist 9, nicht „die frozen ledgers"

`_FROZEN_SITES` / `_FROZEN_URLOPEN_SITES` sind **literale frozensets** — die können nicht
still leer werden (Leeren ist ein sichtbarer Edit am Literal). Die §3.4-Sorge war auf die
falschen Instanzen gerichtet. Mit derselben Verschärfung wie bei den Schleifen (nur
Discovery / gefilterte Comprehension / Helper, die eines von beiden liefert) misst der
parametrize-Vektor:

| naiv (jeder Modul-Name) | verschärft (ableitbar-leer) |
|---|---|
| 148 Treffer / 68 Dateien | **9 Treffer / 8 Dateien** |

Die 9 (Probe: `docs/superpowers/plans/2026-08-03-param-probe-THROWAWAY.py`, gegen
origin/main-gleichen Baum gelaufen):

- `tests/test_requirements_lock_consistency.py:143` — `_pinned_direct_requirements()`
- `tests/test_secret_leakage_probes.py:267` — Genexpr über `_REPO_ROOT.glob(...)`
- `tests/test_smc_parity.py:266` — `_EXPECTED_PARAMS` (filtered)
- `tests/test_spec_constant_drift.py:183` — `(REPO_ROOT/'artifacts'/'experiments').glob('*.json')`
- `tests/test_sprt_llr_invariants_property.py:91` — `_NK_CASES` (filtered)
- `tests/test_workflow_auth_pattern.py:111` — `_iter_workflow_files()`
- `tests/test_workflow_no_fake_push_success.py:64` + `:78` — `_WORKFLOWS` (glob)
- `tests/test_workflow_pythonpath_for_direct_invoke.py:73` — `_iter_workflow_files()`

**Kalibrierfall für die Zeugen-Regel:** `test_spec_constant_drift.py` HAT einen Zeugen
(`test_at_least_one_spec_exists`, Z. 176, `assert self._spec_paths()`), aber an einer
**anderen Ausdrucks-Instanz** — statisch nicht als derselbe Wert beweisbar. Konsequenz für
das Design: Zeuge bindet **pro Ausdruck im selben Scope**; Cross-Test-Zeugen gehen als
datierte Exemption in die Registry, nicht als Detektor-Heuristik. (Genau 1 Datei liegt
aktuell unter dem Glob: `artifacts/experiments/f2_contextual_promotion.json` — der Fall ist
real, nicht hypothetisch.)

⇒ Task 3 aus §6 wird konkret: dieselbe Leerbarkeits-Klassifikation, zweite Syntaxposition
(`ast.Call` mit `func.attr == "parametrize"`, argvalues = deco.args[1]), 9 Baseline-Fälle.

### 9.4 §6 Task 7 korrigiert: Tri-State existiert schon, der Fund ist kleiner und schärfer

`probeVisibleChartScriptError` (`tv_shared.ts:8216`) liefert bereits
`string | CHART_ERROR_PROBE_UNREADABLE | null`; der Runtime-Smoke-Aufrufer (Z. 8720)
behandelt UNREADABLE explizit. `getVisibleChartScriptError` (Z. 8252) ist die dokumentierte
Alt-Sicht; ihr eigener Docstring sagt: *„this must NOT be used by anything that gates on a
clean compile — use the probe."*

**Der Fund:** `assertNoVisibleChartScriptError` (Z. 8257, **direkt darunter**) benutzt
genau diese flache Sicht zum Gaten. Einziger Produktiv-Aufrufer:
`scripts/tv_publish_openprep_panel.ts:198` — der openprep-Publish-Pfad meldet „kein
Chart-Fehler", auch wenn die Legende unlesbar war. Task 7 schrumpft von „Tri-State bauen"
auf „`assertNoVisibleChartScriptError` auf die Probe umstellen, UNREADABLE fail-closed".
**Bleibt vorlagepflichtig** (Verhaltensänderung am Publish-Pfad): eigener PR, User-Signal.

### 9.5 TS-Flächen-Sizing (für Task 6)

51 `*.test.ts`; 36 `for (const … of …)`-Schleifen, 32 `.every(`/`.some(`-Stellen in Tests;
~50 `null`-abflachende Stellen (`?? null`, `return null;`) in `tv_shared.ts`.
TypeScript 5.9.2 ist devDependency — der TS-Analyzer kann die Compiler-API nutzen
(`import ts from "typescript"`), kein neues Paket nötig.

### 9.6 Betriebsnotizen der Session

- Die cwd-Falle (§7) hat **wieder** zugeschnappt (Shell sprang auf `/Users/spreuss`).
  Hook-Zeile nach jedem Bash-Call lesen; absolute Pfade.
- Zwei Hooks blocken Bash-Kommandos, die bestimmte Skript-Namen **erwähnen**
  (`run_ledger_drift_guard.sh` im `cat`/`sed`-Kommando reicht). Workaround: Read-Tool
  direkt auf die Datei.
- Loop-Probe liegt tracked-nah als
  `docs/superpowers/plans/2026-08-02-vacuity-probe-THROWAWAY.py`, parametrize-Probe als
  `docs/superpowers/plans/2026-08-03-param-probe-THROWAWAY.py`. Beide THROWAWAY: Logik im
  echten Guard TDD-neu bauen, nicht kopieren.

### 9.7 Offene Punkte (unverändert + neu)

- Plan schreiben: `/superpowers:writing-plans` mit **diesem Dokument** als Spec →
  `docs/superpowers/plans/2026-08-02-vacuity-guard.md`. Task-Zuschnitt §6 gilt, mit
  §9.3 (Task 3) und §9.4 (Task 7) als Präzisierung.
- Die 25 untriagierten Loop-Treffer und 8 der 9 parametrize-Treffer sind **unbewertet** —
  True-Positive-Quote weiterhin unbekannt, gehört in den Baseline-Triage-Task, nicht in
  Behauptungen.
- Vor Branch-Start: `git fetch` + `gh pr list` (Parallelarbeit, §7).
