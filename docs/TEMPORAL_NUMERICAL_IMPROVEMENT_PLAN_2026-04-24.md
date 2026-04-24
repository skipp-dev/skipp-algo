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
- **T-3**: `request.security` Same-TF-Pattern entfernen (rein kosmetisch, kein Korrektheits-Bug).
- **N-2/N-3/N-4**: `math.isclose` / Sentinel-`None` migrieren — niedrige Wahrscheinlichkeit, kein P0/P1.
- **TZ-2**: Session-Fenster-Intent dokumentieren (UTC-fix vs. lokal). Issue eröffnen, kein Code-Patch.
- **SPRT-1**: Sentinel-Decision `"inconclusive"` in `smc_sprt_stop_rule.py`.
- **S-2**: Benjamini-Hochberg in `run_ab_comparison.py`.
- **S-4**: Eligibility-Policy als Doku-Block.
- **E-3**: Strategischer Refactor (`@resilient`-Decorator), eigenes Quartal.
- **A-2**: `lru_cache(maxsize=1024)` für Newsapi-Clients.
- **A-3**: Streamlit `session_state` Invalidations-Versionsschlüssel.
- **D-1**: Legacy-Pine in `pine/legacy/` verschieben (Manifest-Pfade mit ziehen).
- **D-2**: Schema-Version-Historie in `CHANGELOG.md` migrieren.

---

## Tracking
| Bundle | PR | Status |
|---|---|---|
| 1 (T-1) | — | offen |
| 2 (A-1) | — | offen |
| 3 (S-1) | — | offen |
| 4 (P1) | — | offen |
| 5 (P2 quick-wins) | — | offen |
