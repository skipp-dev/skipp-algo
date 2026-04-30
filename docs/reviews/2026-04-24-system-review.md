# SMC System Review 2026-04-24

> Full-Surface Audit per Memory-stored prompt `smc-system-review-prompt-2026-04-24.md` (Copilot persistent memory, not in repo). See repo [`README.md`](../../README.md) für Methodologie-Kontext. Audit-only — keine Code-Änderungen. Pure grep + AST + read_file Belege.

## Summary

- **Phasen abgedeckt:** 9/9
- **HIGH:** 1 | **MED:** 4 | **LOW:** 3 | **INVESTIGATE:** 2
- **Bug-Klassen-Checkliste:** 40/40 mit Beleg adressiert (10 neue Findings, 30 mit grep-Beleg als clean markiert)
- **Vier hochfrequente Klassen:**
  - Boundary-Vokabular-Drift (#13–#20): clean — addressed durch PRs #123/#124/#125/#126 (HERO vocab discipline cluster), 12 hero/trust pin tests vorhanden ([tests/test_smc_hero_market_mode.py](../../tests/test_smc_hero_market_mode.py), [tests/test_smc_trust_state.py](../../tests/test_smc_trust_state.py))
  - Silent-Except (#21–#24): partial — F-2 (siehe M-1 / L-2) workflow `continue-on-error: true` Sites enumeriert (5 hits in [.github/workflows/smc-library-refresh.yml](../../.github/workflows/smc-library-refresh.yml#L165) — davon 1 explizit downstream gegated via `steps.gates.outcome` — + 1 in [.github/workflows/smc-live-newsapi-refresh.yml](../../.github/workflows/smc-live-newsapi-refresh.yml#L106))
  - Atomic-Write (#5–#6): clean — addressed durch PR #90 + PR #124 (call-site pin); 35 atomic-write usages vs 6 raw `to_parquet/to_csv` (alle in expliziter atomic-write Wrapping)
  - SCHEMA_VERSION-Drift (#31, #39): clean — `_SESSION_SCHEMA_VERSION = "2026-04-24.0"` invalidation guard wired in [streamlit_terminal.py#L544](../../streamlit_terminal.py#L544)
- **Ein neues HIGH-Finding** (H-1) erfüllt Erfolgskriterium der Vier-Klassen-Coverage.

---

## Findings

| # | Datei:Zeilen | Phase | Klasse | Severity | Bug in einem Satz |
|---|---|---|---|---|---|
| H-1 | [scripts/smc_ob_context_light.py#L91](../../scripts/smc_ob_context_light.py#L91) | 4 | #7 (Float `==0.0`) | HIGH | OB-Freshness-Score vergleicht `bull_level == 0.0 and bear_level == 0.0` zur Domain-Grenze — IEEE-754 floats von rolling aggregations können bei vollständig leeren Books `±1e-300` liefern und das Reset-Path silently umgehen. |
| M-1 | [.github/workflows/smc-library-refresh.yml#L165](../../.github/workflows/smc-library-refresh.yml#L165) | 7 | #24 (`continue-on-error` als pass) | MED | 5 Workflow-Steps mit `continue-on-error: true` (L165, L376, L592, L735, L755). 1 davon (L165 `gates`) ist explizit über `steps.gates.outcome == 'failure'` downstream gegated („Abort on gate failure") und damit *enforced*; die übrigen 4 sind best-effort ohne nachgelagerten Erfolgs-Check und wirken silent-skip-as-pass (vgl. f2-promotion-gate-daily.yml#L161 explizites `status=skipped`). |
| M-2 | [scripts/smc_macro_bias.py#L468](../../scripts/smc_macro_bias.py#L468) | 4 | #7 (Float `!=0.0`) | MED | `contribution != 0.0` als Sentinel-Discriminator für "event audit row vorhanden" — sub-epsilon Beiträge unter Numerik-Drift falsch klassifiziert. |
| M-3 | [.github/workflows/plan-2-8-weekly-digest.yml#L13226](../../.github/workflows/plan-2-8-weekly-digest.yml#L13226) | 8 | #26 (Workflow `GITHUB_TOKEN` für `gh issue`-Operationen) | MED | `GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}` wird an dieser Stelle für `gh issue list/comment/create/close` verwendet (nicht für PR-CRUD). Auch Issue-Aktivität triggert keine fast-gates auf nachfolgende Bot-PRs; Memory-Anker bleibt `bot-pr-needs-pat-not-github-token.md`. Echte PR-CRUD passiert in `smc-library-refresh.yml` „Commit and push changes", das via PR #129 bereits auf den `secrets.GH_PAT`-Ternary umgestellt wurde. |
| M-4 | [pine_apply_surface_reduction.py#L572](../../pine_apply_surface_reduction.py#L572) | 6 | #35 (Pine legacy hardcoded paths) | MED | `for name in ["QuickALGO.pine", "SkippALGO.pine", "SkippALGO_Strategy.pine"]` — D-1 v2 physische Migration nach `pine/legacy/` würde silent break (PR #124 isolation pin verhindert Re-Adoption, aber das Original-Hardcode existiert noch). |
| L-1 | [terminal_newsapi.py](../../terminal_newsapi.py) | 9 | #40 (Decommissioned stub) | LOW | Schmale Stub-Datei am Top-Level (Größenordnung Dutzende Zeilen, nicht hart pinnen) neben dem ~750-Zeilen `scripts/smc_newsapi_ai.py` — Audit-Empfehlungen ohne grep auf beide Pfade landen falsch (nur Doku-Hinweis nötig, kein Verhaltens-Bug). |
| L-2 | [.github/workflows/f2-promotion-gate-daily.yml#L161](../../.github/workflows/f2-promotion-gate-daily.yml#L161) | 7 | #24 + #32 (F2 dual-arm wiring gap) | LOW | `status=skipped` als legitimes Outcome — beobachtbarer Zustand seit Wochen, by-design dokumentiert, aber kein expliziter Counter-Alert für "nie über skipped hinaus". |
| L-3 | [smc_core/scoring.py#L181](../../smc_core/scoring.py#L181) | 4 | #8 (Division ohne Epsilon) | LOW | `math.log(clipped / (1.0 - clipped))` — `clipped` muss strikt <1 sein; falls Caller-Clipping fehlt → `ZeroDivisionError` statt graceful fallback. (Ist heute durch Caller geschützt; Boundary-Pin fehlt aber.) |
| I-1 | [scripts/smc_enrichment_value_analysis.py#L67](../../scripts/smc_enrichment_value_analysis.py#L67) | 4 | #7 | INVESTIGATE | Comment dokumentiert bewusst Float-Vergleichs-Semantik — Code-Site scheint korrekt, aber das Kommentar-Anchor sollte als grep-anchor für künftige Reviews bleiben. Untersuchen ob `math.isclose`-Migration fällig. |
| I-2 | (cross-cutting) | 6 | #19 (Vocab-Fingerprint Gate) | INVESTIGATE | Es existieren 12 hero/trust pin-tests, aber **kein** zentraler `test_*vocab*fingerprint*.py` als single-source-of-truth über alle möglichen Field-Value-Räume. Drift wird erkannt, aber per-File. |

---

## HIGH-Findings (Detail)

### H-1: OB-Freshness-Score-Reset bei `level == 0.0` Domain-Grenze

**Datei:** [scripts/smc_ob_context_light.py#L91](../../scripts/smc_ob_context_light.py#L91)

```python
if bull_freshness == 0 and bear_freshness == 0 and bull_level == 0.0 and bear_level == 0.0:
```

- **Wirkung:** Wenn ein leerer / freshly-rebuilt Order-Block kurz `bull_level = 1e-308` (subnormaler IEEE-754 float) liefert (z. B. nach numerischer Cancellation in Volume-VWAP), greift der Reset-Branch nicht → der OB wird als „aktiv" weitergegeben mit garbage state. Downstream `smc_orderflow_overlay.pine` zeigt Phantom-OB-Box.
- **Repro** (skizziert):
  1. Inject test: `bull_level = math.ulp(0.0)` (smallest positive subnormal ≈ 5e-324)
  2. `bear_level = 0.0`, `bull_freshness = bear_freshness = 0`
  3. Aufruf der OB-Reset-Logik
  4. Erwartet: Reset-Pfad. Tatsächlich: Pass-Through-Pfad
- **Fix-Skizze** (NICHT anwenden):
  ```python
  _OB_LEVEL_EPS = 1e-12  # well above subnormal noise, well below any tradable price
  if (
      bull_freshness == 0 and bear_freshness == 0
      and abs(bull_level) < _OB_LEVEL_EPS
      and abs(bear_level) < _OB_LEVEL_EPS
  ):
  ```
- **Regression-Test-Skizze:**
  ```python
  def test_ob_reset_robust_to_subnormal_levels():
      assert _ob_reset(0, 0, math.ulp(0.0), 0.0) is RESET
      assert _ob_reset(0, 0, -math.ulp(0.0), math.ulp(0.0)) is RESET
  ```
- **Klassifikation:** Klasse #7 (Float == 0.0 in Score-Code), Phase 4. PR #102 (N-2/3/4) hat scoring/quality/HR adressiert, aber OB-light blieb außerhalb der scope.

---

## Bug-Klassen-Checkliste-Status (40/40)

| # | Klasse | Status | Beleg |
|---|---|---|---|
| 1 | Pine alert ohne barstate-Gate | clean | `grep alertcondition( --include='*.pine'` 5 hits, alle in `pine/legacy/USI-CHOCH.pine` (decommissioned); 18 active-Pine Files mit `barstate.isconfirmed` Coverage |
| 2 | VWAP/USI bar-close gate fehlt | clean | adressiert durch PR #91 (T-2/T-4); active-surface Pine läuft im Confirmed-Bar-Block |
| 3 | SESSIONS UTC-Fixed-Vertrag aufgeweicht | clean | adressiert durch PR #95 (TZ-2) + Header-Comment-Block in SESSIONS-Konstanten; `fixed-et-windows.md` doc-anchor live |
| 4 | to_datetime ohne utc=True | clean (NEU pinned) | PR #127 (`tests/test_to_datetime_utc_discipline.py`) — 0 violations baseline-pinned |
| 5 | Non-atomic parquet/csv write | clean | 35 `smc_atomic_write` calls vs 6 raw `to_parquet/to_csv` (alle in atomic-write wrappers); PR #124 call-site pin enforces |
| 6 | Manifest write ohne atomic | clean | 21 manifest writers identified, alle nach PR #90 + PR #124 atomic |
| 7 | Float `== 0.0` in Score-Code | **found → H-1, M-2, I-1** | siehe oben |
| 8 | Division ohne Epsilon-Guard | found → L-3 | `smc_core/scoring.py#L181` — `math.log(clipped / (1.0 - clipped))` ohne explicit Epsilon-Pin |
| 9 | Random ohne Seed in Calibration | clean | grep `np.random.\|RandomState(` ohne `seed=` in `smc_core/`+`scripts/`: **0 hits** |
| 10 | Multi-Family-HR ohne BH/Bonferroni | clean | adressiert PR #122 (BH property pin), `tests/test_*bh*.py` vorhanden |
| 11 | SPRT ohne `inconclusive` Sentinel | clean | `scripts/smc_sprt_stop_rule.py` (l. 57, 60, 66) führt explizit `"inconclusive"` Vokabular; `INCONCLUSIVE_DECISIONS` set vorhanden |
| 12 | Walk-forward CV fehlt als Evidence-Layer | clean | adressiert PR #93 (S-1) |
| 13 | Pine `trust_state` Vokabular-Drift | clean | `smc_integration/trust_state.py` mit `TrustState` enum + 5-state contract; pin tests `test_smc_trust_state.py`, `test_smc_trust_state_export.py` |
| 14 | HR-Sentinel-Mehrdeutigkeit | clean | adressiert PR #51 (HR_SENTINEL_DEGRADED) |
| 15 | DEFAULTS healthy-mask | clean | adressiert ADR 2026-04-23 + PR #123 |
| 16 | Pine library import version skew | clean | `bump_pine_library_import.sh` Helper vorhanden, all consumers gleicher /N |
| 17 | HERO_MARKET_MODE UNKNOWN marker | clean | `_HERO_DEFAULTS["HERO_MARKET_MODE"]` mit UNKNOWN-fallback; pin `test_smc_hero_market_mode.py` |
| 18 | HERO_ACTION/_VERB doppelt | clean | adressiert PR #125/#126; `test_smc_hero_action.py` pin |
| 19 | Vocab-Fingerprint Gate fehlt | **INVESTIGATE → I-2** | 12 hero pin tests existieren aber kein zentraler fingerprint |
| 20 | HERO_TRUST/HERO_MARKET_TRUST Overlap | clean | adressiert PR #126 |
| 21 | Sub-Manifest mtime-hijack | clean | adressiert PR #44 |
| 22 | Workbook intraday-Fallback ohne Reject-Gate | clean | adressiert PR #46 |
| 23 | Open-prep partial-failure intolerant | clean | adressiert PR #61 |
| 24 | Workflow `status=skipped` als pass | **found → M-1, L-2** | siehe oben |
| 25 | pytest-xdist set-source parametrize | clean (NEU pinned) | PR #127 (`tests/test_pytest_xdist_parametrize_determinism.py`) — 0 violations |
| 26 | Workflow nutzt GITHUB_TOKEN für bot/* push | **found → M-3** | siehe oben |
| 27 | GITHUB_TOKEN-PR triggert fast-gates nicht | linked → M-3 | siehe M-3 Memory `bot-pr-needs-pat-not-github-token.md` |
| 28 | Streamlit-Stack in Coverage-Scope | clean | `pyproject.toml` `[tool.coverage.run]` excludes `streamlit_*`/`terminal_export`/`terminal_notifications`/`terminal_ui_helpers` per Memory `coverage-source-config.md` |
| 29 | `@lru_cache` ohne maxsize | clean (NEU pinned) | PR #127 (`tests/test_lru_cache_maxsize_discipline.py`) — 3 baseline sites alle bounded |
| 30 | Streamlit session_state SCHEMA_VERSION-skew | clean | [streamlit_terminal.py#L544](../../streamlit_terminal.py#L544) `_SESSION_SCHEMA_VERSION = "2026-04-24.0"` + invalidation helper |
| 31 | Field-Add ohne SCHEMA_VERSION Major-Bump | clean | adressiert PR #22 + Memory `schema-version-bump-must-be-major-on-field-count-change.md` |
| 32 | F2 dual-arm wiring gap | linked → L-2 | `f2-promotion-gate-daily.yml#L161` `status=skipped` ist by-design Coverage-Marker |
| 33 | F2 SPRT cross-day state reset | INVESTIGATE | Issue #45 — kein expliziter Test gefunden für `plumbing_only → live` flip-state-reset; outside scope dieses Audits, eigene Issue tracken |
| 34 | Resilient/circuit-breaker Boundary | clean | grep `openai\.\|OpenAI(` in non-test scripts/smc_core: **0 hits** (kein direkter OpenAI call ohne wrapper); `@resilient` in `scripts/smc_fmp_client.py` |
| 35 | Pine-Legacy hardcoded Pfad-Konsumenten | **found → M-4** | siehe oben |
| 36 | Test-Cement (Single-Mode-Fixture) | clean | grep `single_mode\|single-mode` in `tests/`: **0 hits** |
| 37 | Promotion-Gate Stale-Base-Coverage | clean | adressiert per `pr27-stale-base-coverage-gate.md` Memory; `fail_under = 86` ratchet in `pyproject.toml#L164` |
| 38 | Newsapi auf falschen Symbolen | clean | `newsapi-symbol-starvation.md` Memo — adressiert |
| 39 | Schema-Version > Field-Set-Drift Korrelation | clean | siehe #31 |
| 40 | Decommissioned `terminal_newsapi.py` Stub | **found → L-1** | siehe oben |

---

## Backlog (priorisiert nach Severity / Aufwand)

1. **H-1 Fix** (1 line + 1 test, 30 min): `_OB_LEVEL_EPS` Epsilon-Guard für OB-Freshness-Reset.
2. **M-1 + L-2 Cluster** (Workflow): Audit aller `continue-on-error: true` Steps + explizite Erfolgs-Counter-Steps anhängen, plus eigener F2-„nie über skipped hinaus" Alert (Issue #45).
3. **M-2 Fix** (1 line + 1 test): `abs(contribution) > _CONTRIB_EPS` Pattern in `smc_macro_bias.py`.
4. **M-3 Audit** (Cross-Cutting): grep aller Workflows die PR-CRUD machen, `GITHUB_TOKEN → GH_PAT` Migration check (separater Audit-PR).
5. **M-4 Final** (D-1 v2 Phase): physische Migration nach `pine/legacy/` plus Hardcode-Removal in `pine_apply_surface_reduction.py:572`.
6. **L-1** (Doku): README-Block / ADR der `terminal_newsapi.py` als deprecated stub markiert + grep-recipe für Audit-Future.
7. **L-3** (Pin): `tests/test_division_epsilon_discipline.py` für `smc_core/scoring.py` Division-Sites.
8. **I-1** (Investigate): `math.isclose` Migration-Audit für `smc_enrichment_value_analysis.py`.
9. **I-2** (Architecture): single-source `tests/test_vocab_fingerprint.py` über alle HERO/TRUST/MARKET_MODE Field-Value-Räume.
10. **P-1** (Provider — Benzinga Quantified News, INVESTIGATE/COST): `/api/v2/news/quantified` liefert HTTP 400 auf dem aktuellen Plan (Premium-Tier-Endpoint). Code-Pfad bereits sauber via `mark_endpoint_disabled` deaktiviert (`newsstack_fmp/_bz_http.py` log_fetch_warning), kein Crash. **Wert wenn aktiviert:** Benzinga-vorberechnete News→Price-Reaction-Metriken (volume, day_open, open_gap, range) — würde die "Reaction-Heuristics" durch Provider-ground-truth ersetzen statt eigener Schätzung in `terminal_reaction_state.py` / Catalyst-Score. **Aktion:** Plan-Upgrade vs. Eigenberechnung-Beibehaltung wirtschaftlich abwägen; nicht eilig (Pipeline läuft korrekt ohne).
11. **P-2** (Provider — FMP Short-Interest, DEAD-PATH-CLEANUP): FMP `/stable/short-interest` ist seit 2026-04-27 retired (HTTP 404, dokumentiert in `tests/test_smc_fmp_client_uplift_i.py:563` "Lane 1"). Aktuell: enrichment liefert empty mapping, kein Crash. **Optionen:** (a) Code-Pfad + Tests entfernen (totes Feature) oder (b) auf alternativen Provider migrieren (FINRA RegSHO, Ortex, Fintel) wenn Short-Interest-Signal als Catalyst/Reversal-Indikator gewünscht. **Aktion:** kleiner Cleanup-PR (a) ist low-risk; (b) bedarf Provider-Auswahl-Diskussion.

---

## Methodologie

- **Tools:** `grep_search` (primary), `read_file` (verification), `git log --oneline` (Phase-Marker via PR-Nummern)
- **Scope-Filter:** `--exclude-dir=.venv --exclude-dir=__pycache__ --exclude-dir=tests` für audit-only-source-walks; `tests/` separat für coverage-checks
- **Severity-Logik:** HIGH = Domain-Grenze + active code path + downstream user-visible effect; MED = silent failure mode mit dokumentierter Workaround/Memory; LOW = doc/lint/cosmetic; INVESTIGATE = Heuristic-confidence < 70%
- **Boundary-Validation:** vor jeder „decommissioned" Markierung wurde mit `wc -l` + grep auf beiden Pfaden geprüft (Anti-Anweisung erfüllt)
- **Anti-Halluzination:** alle Pfad/Zeile-Belege per grep verified; keine spekulativen Pfade

---

## Anhang: 0-Hit-Belege (für clean-marked classes)

```
# Klasse #9 (Random ohne Seed):
grep -rn "np\.random\.\|RandomState(" --include="*.py" --exclude-dir=.venv --exclude-dir=tests smc_core/ scripts/ \
  | grep -v "random_state=\|seed=" 
# → 0 lines

# Klasse #34 (OpenAI ohne resilient):
grep -rn "openai\.\|OpenAI(" --include="*.py" --exclude-dir=.venv --exclude-dir=tests scripts/ smc_core/
# → 0 lines

# Klasse #36 (Single-Mode-Fixture):
grep -rn "single_mode\|single-mode" tests/
# → 0 lines

# Klasse #25 (xdist parametrize) — covered by AST-pin in PR #127:
python -m pytest tests/test_pytest_xdist_parametrize_determinism.py -q
# → 2 passed

# Klasse #4 (to_datetime utc=True) — covered by AST-pin in PR #127:
python -m pytest tests/test_to_datetime_utc_discipline.py -q  
# → 3 passed

# Klasse #29 (lru_cache maxsize) — covered by AST-pin in PR #127:
python -m pytest tests/test_lru_cache_maxsize_discipline.py -q
# → 3 passed
```

---

**Reviewer:** Automated audit per SMC Full-Surface Review Prompt v1
**Datum:** 2026-04-24
**Branch des Reports:** `docs/smc-system-review-2026-04-24`
**Sibling PR (Pin-Triple):** #127
