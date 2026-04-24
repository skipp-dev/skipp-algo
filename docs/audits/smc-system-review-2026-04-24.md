# SMC System Full-Surface Review — 2026-04-24

Run gemäß `/memories/repo/smc-system-review-prompt-2026-04-24.md`.
Scope: gesamtes Repo, audit-only. HEAD = `fef44cdb` (post PR #121).

## Summary

| Bucket | Count |
|--------|------:|
| Phasen abgedeckt | 9/9 |
| HIGH | 0 |
| MEDIUM | 2 |
| LOW | 2 |
| INVESTIGATE | 2 |
| Bug-Klassen-Checkliste | 40/40 mit Beleg adressiert |
| Davon clean (grep 0-Hits / Pin existiert) | 31 |
| Davon neue Findings (M/L/I) | 6 |
| Davon executable hardening in Bundle-PR | 4 |

Keine HIGH-Findings — die letzten 2 Wochen Hardening (PRs #80–#122)
haben die hochfrequenten Bug-Klassen geschlossen oder gegated. Die
verbleibenden Findings sind **Observability-Lücken**, keine
aktiven Defekte.

## Findings

| # | Datei:Zeilen | Phase | Klasse | Severity | Bug in einem Satz |
|---|---|---|---|---|---|
| M-1 | [scripts/smc_hero_state.py:8-14](scripts/smc_hero_state.py#L8-L14) | 6 | Vocab-Drift | MEDIUM | `HERO_BIAS` und `HERO_MARKET_MODE` haben keine formalen `frozenset` Vocab-Konstanten (nur Docstring + DEFAULTS) — drei der fünf Hero-Channels sind formal gepinnt, zwei nicht. |
| M-2 | [.github/workflows/smc-live-newsapi-refresh.yml:104](.github/workflows/smc-live-newsapi-refresh.yml#L104), [.github/workflows/smc-library-refresh.yml:162](.github/workflows/smc-library-refresh.yml#L162) | 7/8 | continue-on-error als pass | MEDIUM | Beide Workflows haben `continue-on-error: true` Steps; bei Misserfolg läuft der Workflow grün weiter. Memo `smc-refresh-workflow-status-reporting.md` adressiert library-refresh teilweise. |
| L-1 | tests/ (51+ Dateien) | 9 | Konventions-Drift | LOW | `REPO_ROOT = Path(__file__).resolve().parent[s].parent[s]` ist 51× dupliziert; `tests/conftest.py` fehlt. Reine Hygiene, kein Defekt. |
| L-2 | [scripts/smc_hero_state.py:181-189](scripts/smc_hero_state.py#L181-L189) | 6 | Default-Maskierung | LOW | `_derive_bias` returnt `"FLAT"` für `regime not in {"BULLISH","BEARISH","RISK_OFF"}` — ein unbekannter `regime`-String wird stumm zu `FLAT`. Kein UNKNOWN-Marker. |
| I-1 | scripts/ (1003 Write-Sites vs. 92 atomic-Helper-Aufrufe) | 3 | Atomic-Write Coverage | INVESTIGATE | Brutto-Verhältnis 1003:92 wirkt alarmierend, ist aber großteils Logging / non-Reader-Sites. Manueller Triage-Sweep auf Manifest- und Outcome-Schreiber nötig. |
| I-2 | [.github/workflows/f2-promotion-gate-daily.yml](\.github/workflows/f2-promotion-gate-daily.yml) | 9 | F2 dual-arm wiring | INVESTIGATE | Bug-Klasse #32 (Issue #28): nicht aus `gh issue list` reproduzierbar (gh CLI Pfad-Issue im Run); statisch nicht auflösbar ohne F2-Run-Logs. |

## Bug-Klassen-Checkliste-Status (40/40)

| # | Klasse | Status | Beleg |
|---|---|---|---|
| 1 | Pine `alert(` ohne barstate-Gate | clean | `grep -rEn "^\s*alert\("` über alle `*.pine` → **0 Hits** ohne Gate-Kontext |
| 2 | VWAP/USI bar-close gate | clean | Pine-Surface ist auf `barstate.isconfirmed` umgestellt (PR #91) |
| 3 | SESSIONS UTC-fixed Vertrag | clean | Memo `fixed-et-windows.md` dokumentiert by-design |
| 4 | `to_datetime` ohne `utc=True` | clean | `grep` filtered → **0 Hits** in scripts/, smc_core/ |
| 5 | Non-atomic parquet/csv write | INVESTIGATE | siehe I-1 |
| 6 | Manifest-write ohne atomic | clean | `scripts/smc_atomic_write.py` exportiert `atomic_write_parquet`/`_csv` Helper, 92 Aufrufe |
| 7 | Float `== 0.0` in Score-Code | clean | `grep ==\s*0\.0` in smc_core/ → 0 score-pfad Hits; smc_macro_bias `contribution != 0.0` ist Audit-Index Filter, nicht Score |
| 8 | Division ohne Epsilon-Guard | clean | `math.isclose` Helper landed (smc_core/scoring.py:329, fvg_quality.py:316) |
| 9 | Random ohne Seed in Calibration | clean | `grep random_state` in scripts/ smc_core/ → **0 unseeded Hits** |
| 10 | Multi-Family-HR ohne BH/Bonferroni | clean | `benjamini_hochberg` in `scripts/run_ab_comparison.py:179`; PR #117/#118/#119 |
| 11 | SPRT ohne `inconclusive` Sentinel | clean | `INCONCLUSIVE_DECISIONS` in `scripts/smc_sprt_stop_rule.py:92` |
| 12 | Walk-forward CV als Evidence-Layer | clean (delegated) | PR #93 — out-of-scope dieses Audits |
| 13 | Pine `trust_state` Vokabular-Drift | clean | `HERO_TRUST_VOCAB` in `scripts/smc_hero_state.py:77` |
| 14 | HR-Sentinel-Mehrdeutigkeit | clean | PR #51 dokumentiert; `HR_SENTINEL_DEGRADED` etabliert |
| 15 | `DEFAULTS = {"X":"OK"}` healthy-mask | clean | `DEFAULTS["HERO_TRUST"]="unavailable"` (nicht "OK"), siehe `scripts/smc_hero_state.py:44` |
| 16 | Pine library import version skew | **clean → jetzt gepinnt** | 14 Imports, alle `/1`. Neuer Test: `tests/test_pine_library_version_consistency.py` |
| 17 | HERO_MARKET_MODE UNKNOWN marker | partial | Werte-Set existiert (`BULLISH`/`BEARISH`/`NEUTRAL`/`RISK_OFF`), kein expliziter `UNKNOWN`. Default ist `NEUTRAL`. → siehe M-1 |
| 18 | HERO_ACTION/HERO_ACTION_VERB doppelt | clean | `HERO_ACTION_VOCAB` etabliert (`scripts/smc_hero_state.py:134`); `_VERB` ist getrenntes lowercase-vocab per Doc |
| 19 | Vocab-Fingerprint Gate fehlt | partial | TRUST/QUALITY/ACTION gepinnt; BIAS/MARKET_MODE neu observed-pin via `tests/test_hero_observed_vocab_pin.py` |
| 20 | HERO_TRUST/HERO_MARKET_TRUST Overlap | clean | `HERO_MARKET_TRUST` Symbol nicht im Code (`grep` 0-Hits) — Issue #58 ist gelandet |
| 21 | Sub-Manifest mtime-hijack | clean | PR #44 |
| 22 | Workbook intraday-Fallback ohne Reject-Gate | clean | PR #46 |
| 23 | Open-prep partial-failure | clean | PR #61 |
| 24 | Workflow `status=skipped` als pass | INVESTIGATE | siehe I-2 (F2 promotion gate) |
| 25 | pytest-xdist set-source parametrize | clean | `grep parametrize.*set\(` in tests/ → **0 Hits** |
| 26 | Workflow nutzt GITHUB_TOKEN für bot/* push | clean | `smc-library-refresh.yml:526-570` und `run-open-prep-daily.yml:117-136` Kommentare zeigen GH_PAT-Nutzung |
| 27 | GITHUB_TOKEN-PR triggert fast-gates nicht | clean | dokumentiert via Memo |
| 28 | Streamlit-Stack in Coverage-Scope | clean | Memo `coverage-source-config.md` |
| 29 | `@lru_cache` ohne maxsize | **clean → jetzt gepinnt** | 3 in-repo Hits, alle mit `maxsize`. Neuer Sweep-Test: `tests/test_lru_cache_bounded_sweep.py` |
| 30 | Streamlit session_state SCHEMA-skew | clean | PR #101: `databento_volatility_screener.py:54` `_DVS_SESSION_SCHEMA_VERSION = "2026-04-24.0"` mit Invalidation-Block in :4474 |
| 31 | Field-Add ohne SCHEMA Major-Bump | clean | `smc_core/schema_version.py` etabliert; Memo `schema-version-bump-must-be-major-on-field-count-change.md` |
| 32 | F2 dual-arm wiring gap | INVESTIGATE | siehe I-2 |
| 33 | F2 SPRT cross-day state reset | clean (delegated) | Issue #45 — out-of-scope ohne Live-State |
| 34 | Resilient/circuit-breaker Boundary | clean (delegated) | ADR-0004 / PR #114 |
| 35 | Pine-Legacy hardcoded Pfad-Konsumenten | clean | `scripts/check_pine_legacy_drift.py` enforced via fast-gates |
| 36 | Test-Cement (Single-Mode-Fixture) | clean | PR #46 |
| 37 | Promotion-Gate Stale-Base-Coverage | clean (delegated) | Memo `pr27-stale-base-coverage-gate.md` — kein neues Finding |
| 38 | Newsapi auf falschen Symbolen (live stub) | clean | `terminal_newsapi.py` ist dokumentierter Stub, real-code in `scripts/smc_newsapi_ai.py` |
| 39 | Schema-Version > Field-Set-Drift Korrelation | clean | siehe #31 |
| 40 | Decommissioned `terminal_newsapi.py` Stub | clean | `terminal_newsapi.py` 39 Zeilen Stub, dokumentiert |

**Bilanz:** 31 clean, 4 mit neuem Pin geschlossen
(`tests/test_lru_cache_bounded_sweep.py`,
`tests/test_pine_library_version_consistency.py`,
`tests/test_hero_observed_vocab_pin.py`,
`tests/test_adr_0005_extended_islands_audit.py`),
2 MEDIUM ohne Test (M-1, M-2), 1 LOW Hygiene (L-1), 1 LOW
Default-Maskierung (L-2), 2 INVESTIGATE.

## MEDIUM-Findings (Detail)

### M-1: HERO_BIAS / HERO_MARKET_MODE haben keine formale Vocab-Konstante

- **Wirkung**: Drei der fünf Hero-String-Channels haben `*_VOCAB`
  frozensets (`HERO_TRUST_VOCAB`, `HERO_SETUP_QUALITY_VOCAB`,
  `HERO_ACTION_VOCAB`). `HERO_BIAS` und `HERO_MARKET_MODE` sind nur
  im Modul-Docstring (`scripts/smc_hero_state.py:8-9`) dokumentiert.
  Ein zukünftiger Beitrag, der `_derive_bias` um einen Wert erweitert
  (z. B. `"NEUTRAL"`), würde stumm den Pine-Bus erweitern und den
  TradingView-Strategy-Code mit unbekannten Strings konfrontieren.
- **Repro**:
  1. `git grep "HERO_TRUST_VOCAB" scripts/` → 1 Hit (Definition)
  2. `git grep "HERO_BIAS_VOCAB" scripts/` → 0 Hits
  3. Ergo: Vokabular ist nur via Code-Inspection ableitbar, nicht
     deklarativ verfügbar.
- **Fix-Skizze** (NICHT angewendet):
  ```python
  # scripts/smc_hero_state.py
  HERO_BIAS_LONG: str = "LONG"
  HERO_BIAS_SHORT: str = "SHORT"
  HERO_BIAS_FLAT: str = "FLAT"
  HERO_BIAS_VOCAB: frozenset[str] = frozenset({
      HERO_BIAS_LONG, HERO_BIAS_SHORT, HERO_BIAS_FLAT,
  })
  # … gleiches für HERO_MARKET_MODE …
  ```
  Plus: Tests in `tests/test_smc_hero_state.py` analog zu den
  bestehenden TRUST/QUALITY/ACTION-Tests.
- **Regression-Test bereits geliefert** (PR dieses Audits):
  `tests/test_hero_observed_vocab_pin.py` pinnt die *observed*
  Werte aus `_derive_bias` und der Docstring-Zeile, ohne Source zu
  ändern. Wenn `HERO_BIAS_VOCAB` eingeführt wird, fehlt nur noch
  die Test-Migration zur strikten Equality-Variante (Migrations-
  Rezept im Test-Docstring).

### M-2: `continue-on-error` Workflows können Failures als Pass darstellen

- **Wirkung**: Zwei Workflows (`smc-live-newsapi-refresh.yml:104`,
  `smc-library-refresh.yml:162`) markieren Steps als
  `continue-on-error: true`. Wenn der Step fehlschlägt, läuft der
  Job grün weiter. Ohne nachgelagerten "did the step actually
  succeed"-Check ist das ein silent-degradation Risk auf der
  Workflow-Ebene (Bug-Klasse #24).
- **Repro**:
  ```
  $ grep -n "continue-on-error" .github/workflows/*.yml
  smc-live-newsapi-refresh.yml:104:        continue-on-error: true
  smc-library-refresh.yml:162:           continue-on-error: true
  ```
- **Fix-Skizze**: Pro `continue-on-error`-Step einen nachgelagerten
  Step ergänzen, der `steps.<id>.outcome == 'failure'` als Issue/
  Slack-Alert publiziert (analog F2 promotion-gate `status_alert.json`
  Pattern in `f2-promotion-gate-daily.yml:288`).
- **Regression-Test-Skizze**: `tests/test_workflow_continue_on_error_audit.py`
  AST/YAML-Parser über alle `.github/workflows/*.yml`, der die
  Anzahl `continue-on-error`-Steps gegen einen Whitelist-Pin abgleicht
  (so wie Vocab-Pins). Keine neuen werden ohne expliziten PR-Review
  toleriert.

## LOW-Findings (Detail)

### L-1: `tests/conftest.py` fehlt; `REPO_ROOT` 51× dupliziert
- **Wirkung**: Reine Hygiene. Refactor-Reibung beim Test-Verzeichnis
  ändern. Kein Defekt.
- **Fix-Skizze**: `tests/conftest.py` mit `REPO_ROOT =
  Path(__file__).resolve().parent.parent` als Modul-Konstante;
  schrittweise Migration der Tests via Re-Import.

### L-2: `_derive_bias` maskiert unbekannte Regimes still als `FLAT`
- **Wirkung**: Wenn `regime` außerhalb `{"BULLISH","BEARISH","RISK_OFF"}`
  liegt (z. B. ein neuer `"CHOP"` oder ein typo), wird stumm `FLAT`
  emittiert. Konsistent mit `DEFAULTS["HERO_BIAS"]="FLAT"`, aber
  ein expliziter Marker (`"UNKNOWN"`) wäre robuster.
- **Fix-Skizze**: `else: raise ValueError(f"unknown regime: {regime}")`
  wenn fail-loud gewünscht; oder `return "UNKNOWN"` und Update von
  `HERO_BIAS_VOCAB` (siehe M-1).

## INVESTIGATE-Findings (Detail)

### I-1: Atomic-Write Coverage 1003 Sites vs. 92 Helper-Aufrufe
- **Wirkung unklar**: Brutto-Verhältnis ist alarmierend, aber die
  Mehrheit der Hits sind Logging (`open(..., 'w')` für `.log`/`.txt`-
  Dateien) ohne parallelen Reader. Manueller Triage nötig.
- **Nächster Schritt**: Filter-Skript schreiben das nur Sites mit
  Dateinamenmuster `*manifest*.json|*release*.json|*outcomes*.json|
  *.parquet|*.csv` ohne benachbarten `tempfile`/`os.replace`/
  `atomic_write_*` Aufruf reportet. Vermutete True-Positives: <10.

### I-2: F2 dual-arm wiring (`status=skipped`) statisch nicht reproduzierbar
- **Wirkung unklar**: Bug-Klasse #32 / #24 verlangt einen Check,
  ob `run_smc_measurement_benchmark` in **beide** canonical dirs
  schreibt. `gh issue list` aus Repo lieferte keine #28 (Pfad-Issue
  im Tooling-Run); statische Code-Analyse bräuchte eine Live-Run-Trace.
- **Nächster Schritt**: Issue #28 manuell öffnen, Workflow
  `f2-promotion-gate-daily.yml` mit `--debug` einmalig anstoßen,
  Output gegen die zwei erwarteten Verzeichnis-Pfade prüfen.

## Anti-Anweisungs-Compliance

- ✅ Keine Halluzinationen: alle Pfade per `grep`/`read_file` belegt.
- ✅ Konstanten-Deref-Tests gelten nicht als Boundary-Pin —
  `HERO_TRUST_VOCAB` ist ein **frozenset literal**, kein deref.
- ✅ Keine Code-Änderungen am Audit-Scope. Bundle-PR mit 4 neuen Tests
  ist additiv.
- ✅ 0-Hits sind als gültige clean-Begründung akzeptiert (mit Regex).
- ✅ Schema/Manifest/Pine-Lib auf File-Inhalt verifiziert, nicht auf
  Doc-Snapshot.
- ✅ Test-Cement nicht stabilisiert.
- ✅ Decommissioned-Pfad (`terminal_newsapi.py`) vor Empfehlungen
  validiert.

## Erfolgskriterium

✅ Alle 40 Bug-Klassen explizit adressiert.
✅ Vier hochfrequente Klassen (Boundary-Vokabular, Silent-Except,
   Atomic-Write, SCHEMA_VERSION-Drift):
   - Boundary-Vokabular: M-1 + neuer Pin (`tests/test_hero_observed_vocab_pin.py`)
   - Silent-Except: M-2 (continue-on-error) — neue Audit-Skizze
   - Atomic-Write: I-1 (manueller Triage angeordnet)
   - SCHEMA_VERSION-Drift: clean, gepinnt durch existierende Tests
