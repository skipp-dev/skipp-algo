# Improvement Plan — Temporal-Semantic & Numerical-Hygiene Audit (2026-04-24)

**Quelle:** `TEMPORAL_NUMERICAL_AUDIT_2026-04-24.md` · 22 Findings, 3 HIGH, 6 MED, 13 LOW.
**Ziel:** P0 + P1 vor dem nächsten Tag-Release abgeschlossen, P2 als Backlog mit Owner.
**Vorgehen:** Pro Bündel ein PR + Test-Coverage. Keine blinden Umbauten — additiv wo möglich.

---

## Bundle 1 · P0 Live-Signal-Integrität (T-1) — eigener PR
- **T-1**: `emit_dynamic_alert_if_allowed(...)` bekommt `confirmed`-Parameter; Aufrufstellen reichen `barstate.isconfirmed` durch; `alert.freq_all` → `alert.freq_once_per_bar_close`.
- **Akzeptanz:** Pine kompiliert lokal grün; statische Strukturalerts bleiben unverändert; CHANGELOG-Hinweis.

## Bundle 2 · P0 Atomicity (A-1) — eigener PR
- **A-1**: `_atomic_write_parquet(df, target)` + `_atomic_write_csv(df, target)` Helper in `scripts/smc_microstructure_base_runtime.py`; alle direkten `to_parquet`/`to_csv`-Calls auf den Helper umstellen.
- **Test:** Unit-Test, der Helper-Crash zwischen `to_parquet` und `os.replace` simuliert (mock) und sicherstellt, dass `target` unverändert bleibt.
- **Akzeptanz:** Bestehende Tests grün, neuer Test grün.

## Bundle 3 · P0 Train/Test-CV (S-1) — additiv, eigener PR
- **S-1**: Neue Funktion `evaluate_walk_forward_hr(events_df, *, n_splits=5, gap=5)` in `scripts/smc_zone_priority_calibration.py`. Liefert `cv_hr_mean`, `cv_hr_std`, `cv_hr_folds` als Zusatzfeld der Kalibrierungs-JSON. Bestehender Pfad und Gates unverändert.
- **Akzeptanz:** Bestehende `test_smc_zone_priority_calibration*` Tests grün; neuer Test, dass CV-Block strukturell vorhanden + endlich ist.

## Bundle 4 · P1 Bündel (T-2, T-4, N-1, TZ-1, E-1, E-2) — eigener PR
- **T-2**: VWAP-Strategien — `process_orders_on_close=false` (konsistent intrabar) ODER Dokumentation, warum die Kombination beabsichtigt ist. Plan: `process_orders_on_close=false` setzen.
- **T-4**: `alertcondition`-Aufrufe in `USI_Strategy.pine` und `VWAP_Reclaim_Strategy.pine` mit `and barstate.isconfirmed` gaten.
- **N-1**: `abs(self.baseline_mean_pnl) < 1e-12` Epsilon-Guard in `smc_enrichment_value_analysis.py`.
- **TZ-1**: Alle `pd.to_datetime(..., errors="coerce")` mit Timestamp-Semantik um `utc=True` ergänzen (`generate_smc_micro_profiles.py`, `smc_microstructure_base_runtime.py`, `market_structure_features.py`).
- **E-1**: `except Exception: pass` im Schema-Diff durch `logger.warning(..., exc_info=True)` + `change_type = "unknown"` ersetzen.
- **E-2**: Enrichment-Loops bekommen `failed`-Liste + Failure-Rate-Gate (>10% → `RuntimeError`).
- **Akzeptanz:** Tests grün, neue Negativ-Tests für Epsilon-Guard und Failure-Rate-Gate.

## Bundle 5 · P2 Quick-Wins (S-3, D-3) — kleiner PR
- **S-3**: `random.seed(42)` + `np.random.seed(42)` als Defense-in-Depth in `smc_zone_priority_calibration.py` (Pipeline-Start).
- **D-3**: `BEST_V1_WEIGHTS` in `smc_core/fvg_quality.py` als `DEPRECATED_BEST_V1_WEIGHTS` umbenennen; Modul-Level `DeprecationWarning` beim Import des alten Namens via `__getattr__`.

## Backlog (P2 ohne PR — Owner zu vergeben)
- ~~**T-3**: `request.security` Same-TF-Pattern entfernen (rein kosmetisch, kein Korrektheits-Bug).~~
  → erledigt: Audit-Hypothese war
  `request.security(syminfo.tickerid, timeframe.period, …)` (redundant —
  selbes Symbol, selbe TF). Re-Grep über alle `*.pine` ergibt **null
  Vorkommen**. Die vier verbleibenden `… , timeframe.period, …`-Treffer
  in [`SMC++/smc_utils.pine`](../SMC++/smc_utils.pine) (`external_trend_gate`,
  `external_breadth_gate`) sind **externe Symbole** auf gleicher TF —
  legitime Cross-Symbol-Fetches, kein Refactor-Kandidat. Re-introduction
  wird durch eine Same-TF-Guard-Zeile in der Pine-Lint-Stufe abgesichert
  (Folge-PR auf #105).
- ~~**N-2/N-3/N-4**: `math.isclose` / Sentinel-`None` migrieren — niedrige Wahrscheinlichkeit, kein P0/P1.~~
  → erledigt in [`smc_core/scoring.py`](../smc_core/scoring.py) und
  [`smc_core/fvg_quality.py`](../smc_core/fvg_quality.py): explizite
  `math.isclose`-Form mit dokumentierter `abs_tol`. Vollständige
  Migration der übrigen Hit-Points bleibt als Konvention dokumentiert.
- ~~**SPRT-1**: Sentinel-Decision `"inconclusive"` in `smc_sprt_stop_rule.py`.~~
  → erledigt: neue Decision-Literal-Variante `"inconclusive"` plus
  `INCONCLUSIVE_DECISIONS`-Tuple. `terminal_decision()` gibt jetzt
  `"inconclusive"` statt `"max_n_reached"` zurück, wenn die LLR an einem
  fixen n innerhalb der Wald-Bounds liegt.
- ~~**S-2**: Benjamini-Hochberg in `run_ab_comparison.py`.~~
  → erledigt: `benjamini_hochberg(pvals, q)` Helper +
  `_family_fdr_layer(...)` advisor-Layer (Two-Proportion-Z-Test
  pro Family, BH-FDR mit `q=0.05`). Surfaced als `digest["fdr"]` und
  in der Markdown-Rendering-Section. **Advisory-only**:
  beeinflusst Promote/Hold/Rollback nicht.
  - **S-2 follow-up (Bootstrap-Calibration-FDR)**: erledigt.
    Permutation-basierter BH-FDR-Layer über `family×{brier,ece}` Cells in
    `_calibration_fdr_layer(...)` (Phipson-Smyth `(r+1)/(B+1)`-Korrektur,
    `MIN_EVENTS_PER_ARM_FOR_BOOTSTRAP=30`, `B=2000`, `seed=42`,
    joint BH über alle 8 Cells). CLI-Flag `--enable-calibration-fdr`
    (opt-in, default off) + Ledger-Loader via
    `smc_core.event_ledger.read_event_ledger`. Surfaced als
    `digest["fdr_calibration"]` und Markdown-Section.
    **Advisory-only** — Recommendation/SPRT/Hit-Rate-FDR byte-identisch
    (Regression-Test in `test_run_ab_comparison_calibration_fdr.py`).
    Test bewertet **Post-Calibration-Probabilities** im Ledger ohne
    Platt-Refit pro Permutation (Design-Memo §3.2 Option A).
    Block-Bootstrap (serielle Korrelation) als Backlog-Item.
- ~~**S-4**: Eligibility-Policy als Doku-Block.~~ → erledigt durch
  [`docs/adr/0002-promotion-eligibility-policy.md`](adr/0002-promotion-eligibility-policy.md)
  (PR #99).
- **E-3**: Strategischer Refactor (`@resilient`-Decorator), eigenes Quartal.
  - **Pilot/Foundation gelandet**: `smc_core/resilient.py` +
    17 Contract-Tests (`tests/test_smc_core_resilient.py`).
    Decorator + API stehen; per-Adapter-Migration (Finnhub, FMP,
    Newsapi, Databento) bleibt eigene PR-Serie.
  - **Erste Migration (FMP) gelandet** auf
    `feat/e3-fmp-client-resilient-migration`:
    `scripts/smc_fmp_client.py:_get` ersetzt die hand-rolled Retry-Schleife
    durch `@resilient(retries=…, base_delay=0.5, max_delay=4.0, exceptions=(URLError,), on_failure=_wrap_fatal)`. Semantik identisch (gleiche retriable HTTP-Codes, gleiche Fail-Fast für
    404/401/403, gleiche Anzahl Versuche), Backoff jetzt exponentiell
    mit Full-Jitter statt linear. Regression-Test bestätigt das Wiring.
  - **Zweite Migration (OpenAI in `terminal_fmp_insights._call_openai_chat`)**:
    `@resilient(retries=2, base_delay=2.0, max_delay=2.0, exceptions=(httpx.ReadTimeout,), on_retry=…)`. Retry nur auf Read-Timeouts, fail-fast auf `HTTPStatusError`. Neue Sentinel-
    Exception `_OpenAIEmptyChoices` für 200-mit-leeren-Choices.
    4 neue Tests in `tests/test_terminal_fmp_insights_resilient.py`.
  - **Reality-Check (`terminal_finnhub.py:_get`)**: bewusst **nicht**
    migriert. Modul läuft auf der Streamlit-UI-Thread; `@resilient`
    blockiert per Design die aufrufende Thread für `base_delay·2^retries`
    Sekunden — UI-incompatibel. Außerdem ist das 403-`/social-sentiment`-
    Permanent-Disable und das globale 429-Skip-Window ein
    *Circuit-Breaker*-Muster, das die heutige `exceptions=`-Filter-API
    nicht ausdrücken kann. Inline-NOTE im Modul dokumentiert die
    Abgrenzung; folgende E-3-Iteration könnte ein
    `@circuit_breaker`-Companion ergänzen.
  - **Reality-Check (`databento_client.py:_databento_get_range_with_retry`)**:
    bewusst **nicht** in dieser Iteration migriert. Drei Shape-Mismatches:
    (a) Retryability-Predicate ist Message-Substring-Filter über
    beliebige `Exception`-Typen (`"read timed out"`, `"429"`, `"502"`,
    `"connection reset"`, …), nicht Exception-Class-Filter — die
    `@resilient`-API `exceptions=(...)` passt strukturell nicht;
    (b) Funktion ist dupliziert in `databento_volatility_screener.py`
    mit fünf Test-Fixtures, die direkt
    `databento_volatility_screener.time_module.sleep` monkey-patchen —
    saubere Migration verlangt vorher Dedup; (c)
    `_normalize_tls_certificate_env()`-Side-Effect pro Attempt gehört
    semantisch nicht in den generischen Decorator. Eigene PR mit
    Predicate-Adapter (z.B. `RetriablePredicate`) und
    Volatility-Screener-Dedup vorgesehen.
- ~~**A-2**: `lru_cache(maxsize=1024)` für Newsapi-Clients.~~ → erledigt
  in `scripts/smc_newsapi_ai.py` (PR #98). Audit-Text war stale —
  `terminal_newsapi.py` ist Decommissioned-Stub.
- ~~**A-3**: Streamlit `session_state` Invalidations-Versionsschlüssel.~~
  → erledigt in `streamlit_terminal.py` und
  `databento_volatility_screener.py` (PR #101): Schema-Version-Konstante
  + Invalidations-Helper, der bei Bump nur **derived** State-Keys verwirft
  und User-Inputs (API-Keys, Sidebar-Toggles) erhält.
- ~~**D-1**: Legacy-Pine in `pine/legacy/` verschieben (Manifest-Pfade mit ziehen).~~
  → Phase 1 erledigt durch [`PINE_LEGACY.md`](../PINE_LEGACY.md):
  Index-Datei klassifiziert die 24 Root-Pine-Files als `LEGACY` / aktiv.
  Drift-Lint
  ([`scripts/check_pine_legacy_drift.py`](../scripts/check_pine_legacy_drift.py))
  in `smc-fast-pr-gates` verhindert stille Drift (PR #105).
  ~~**D-1 v2** (physischer Move) jetzt entscheidungsreif:
  [`docs/adr/0003-pine-legacy-physical-move-resolver.md`](adr/0003-pine-legacy-physical-move-resolver.md)
  empfiehlt Resolver-Shim statt Sweep-Refactor.~~ → **D-1 v2 erledigt:**
  23 LEGACY-`*.pine` nach `pine/legacy/` verschoben (`SkippALGO_Confluence.pine`
  bleibt aktiv im Root, `test_div.pine` bleibt Test-Fixture). Resolver-Shim
  [`scripts/pine_path_resolver.py`](../scripts/pine_path_resolver.py)
  liefert `resolve_pine_file(basename)` mit Such-Reihenfolge Root → `pine/legacy/`
  und Kollisions-Detect. File-Opener
  [`pine_apply_surface_reduction.py`](../pine_apply_surface_reduction.py) und
  [`test_usi_lint.py`](../test_usi_lint.py) auf Resolver gewired; Klassifikatoren
  ([`scripts/smc_bus_manifest.py`](../scripts/smc_bus_manifest.py),
  [`scripts/smc_file_lifecycle.py`](../scripts/smc_file_lifecycle.py)) behalten
  bare-basename-Lookups (reine Tag-Maps, kein I/O). Drift-Lint scannt jetzt
  beide Verzeichnisse und failt auf Basename-Kollisionen.
- ~~**D-2**: Schema-Version-Historie in `CHANGELOG.md` migrieren.~~
  → erledigt: neue Top-Level-Sektion **"Schema Versions"** in
  [`CHANGELOG.md`](../CHANGELOG.md) konsolidiert die volle Bump-Historie
  (1.0.0 → 1.1.0 → 1.2.0 → 2.0.0 → 2.1.0 [superseded] → 3.0.0) inkl.
  Commit-SHAs, Daten und Begründungen. Inline-Kommentar in
  [`smc_core/schema_version.py`](../smc_core/schema_version.py) auf den
  aktuellen Pin reduziert mit Pointer auf den Changelog.

---

## Tracking
| Bundle | PR | Status |
|---|---|---|
| 1 (T-1) | #89 | gemerged |
| 2 (A-1) | #90 | gemerged |
| 3 (S-1) | #93 | gemerged |
| 4 (P1: T-2/T-4/N-1/E-1/E-2) | #91 | gemerged |
| 5 (P2 quick-wins: S-3) | #92 | gemerged |
| Follow-up TZ-2 Lock-Down | #95 | gemerged |
| Follow-up Tracking-Update | #94 | gemerged |

### Aus Scope ausgenommen (begründet)
- **TZ-1** (`utc=True` everywhere): die einzigen `pd.to_datetime`-Call-Sites auf
  echten Timestamp-Spalten (`smc_microstructure_base_runtime.py:1419`,
  `market_structure_features.py:213`) verwenden bereits `utc=True`. Restliche
  Call-Sites sind auf Date-Only-Spalten — `utc=True` würde bei
  Local-Timezones um Mitternacht 1-Tages-Shifts riskieren.
- **TZ-2** (Session-Fenster DST-Drift): Intent als **UTC-fixiert by design**
  geklärt (Sommer-Local-Anchor BST/EDT in festem UTC). Header-Kommentar über
  `SESSIONS` in `scripts/smc_session_context_block.py` und vier Lock-Down-Tests
  (`test_tz2_*` in `tests/test_smc_session_context_block.py`) nageln den
  Kontrakt fest. Geliefert in PR #95.
- **D-3** (`BEST_V1_WEIGHTS` parallel): Symbol existiert nicht; gemeinte
  `LENIENT_WEIGHTS` ist aktiver Test-Baseline-Import. Kein Dead-Code.
- **D-1, D-2** (Legacy-Pine verschieben, Schema-History): reine
  Aufräum-Arbeiten ohne Sicherheits-/Korrektheits-Impact, separates Backlog.

### Lessons Learned (Konvention für nächsten Audit-Zyklus)
- **MED-Bündel ≤ 3 Findings pro PR.** Bundle 4 (PR #91) hat fünf P1-Findings
  (T-2/T-4/N-1/E-1/E-2) zusammengefasst. Hier ohne Folgekosten gemerged, aber
  bei späterer Test-Flakiness wäre die Root-Cause-Isolation pro Finding
  teurer gewesen. Künftig MED/P1 nur in Drei-Findings-Häppchen.
- **Audit-Symbole vor Implementierung verifizieren.** D-3 zeigte auf
  `BEST_V1_WEIGHTS`, das es nicht gibt (gemeint war `LENIENT_WEIGHTS`).
  Schnelle `grep`-Verifikation hat ~30 Min Implementierungszeit gespart.
- **TZ-Findings nicht als reine Doku-Aufgabe parken.** TZ-2 wurde initial
  als „Issue eröffnen, kein Code-Patch" gelistet. Erst der Lock-Down-Test
  garantiert, dass Intent (UTC-fixiert) nicht durch ein späteres
  „DST-Bugfix"-Refactor verloren geht. Regel: jeder TZ-Intent-Befund braucht
  mindestens einen DST-invarianten Test.

