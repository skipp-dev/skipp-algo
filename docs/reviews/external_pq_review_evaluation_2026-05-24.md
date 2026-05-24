# Evaluation eines externen Principal-Quant-Reviews (Stand 2026-05-24)

**Reviewer:** internes Re-Audit auf Basis von Repo-Evidenz
**Geprüftes Dokument:** „SkippALGO Repository Audit – Principal Quant Engineer Review" (extern, undatiert)
**Methodik:** Jede behauptete Schwachstelle wurde gegen den aktuellen `main`-Stand des Repos verifiziert (Pfade, Funktionsnamen, Tests, Workflows).

## TL;DR

Das externe Review ist **überwiegend falsch**. Es trifft acht „Critical"/„High"-Befunde, von denen **sieben durch existierenden Code/Tests/Workflows widerlegt** sind. Das Dokument räumt selbst ein, dass ihm der Repo-Kontext fehlt („Missing Context Requirements"), liefert aber trotzdem ein Severity-Verdikt. Das ist Regel 1 des eigenen Master-Prompts („Do not hallucinate. Separate verified facts from assumptions.") direkt verletzt.

Verwertbar bleiben **zwei** Hinweise (Survivorship-Bias-Filter, Pine-Strategy-Regressionstests). Drei Punkte sind als **non-critical** mit Substanz zu führen (Doku-Granularität, Versionierung, Audit-Logging).

## Befund-für-Befund-Evaluation

| # | Externer Befund | Severity (extern) | Verifizierter Status | Evidenz |
|---|---|---|---|---|
| 1 | Pine Script Signal Repainting – kein Non-Repainting-Validation | Critical | **FALSCH** | [SMC_Core_Engine.pine](SMC_Core_Engine.pine#L160) verwendet `barstate.isconfirmed` an 8+ Stellen (Order-Block-Promotion, FVG-Confirmation, Retracement-Logik). [SMC_Breakout_Overlay.pine](SMC_Breakout_Overlay.pine#L132-L199) gated Alerts explizit auf `barstate.isconfirmed`. [SkippALGO_Confluence.pine](SkippALGO_Confluence.pine#L231) hat `barCloseOnly`-Schalter. |
| 2 | Data Leakage in Databento Cache – kein Timestamp-Validation | Critical | **FALSCH** | [databento_client.py](databento_client.py#L103-L137) implementiert `_get_schema_available_end` + `_clamp_request_end` (verhindert Requests jenseits der vom Vendor freigegebenen Daten). [databento_provider.py](databento_provider.py#L57-L134) exponiert `get_schema_available_end` über das Provider-Interface. Cache-Versionierung in `CACHE_VERSION_BY_CATEGORY` (PR #2338). |
| 3 | ML Walkforward Lookahead Bias – keine temporale Boundary | Critical | **FALSCH** | [ml/walkforward.py](ml/walkforward.py#L1-L153) ist eine López-de-Prado-Implementierung mit `embargo_bars`, Purging (`event_horizon`), expliziter Assertion `embargo >= 0`. [ml/training/base.py](ml/training/base.py#L68-L86) injiziert sie in alle Family-Trainings. |
| 4 | Missing Brier / ECE Calibration | High | **FALSCH** | [ml/metrics.py](ml/metrics.py#L25-L85) exportiert `brier_score` und `expected_calibration_error`. [ml/calibration/conformal.py](ml/calibration/conformal.py) liefert Marginal/Mondrian-Konformität. Test in [tests/test_conformal_coverage.py](tests/test_conformal_coverage.py). Promotion-Gate konsumiert beide ([governance/promotion_gate.py](governance/promotion_gate.py#L78-L104)). |
| 5 | Survivorship Bias – kein Delisting-Filter | High | **TEILWEISE KORREKT** | `grep -ri "delisted\|survivorship\|listing_status"` liefert keinen Treffer. Die Universe-Logik in `databento_universe.py` filtert über Vendor-Aktivität (CMBP-Verfügbarkeit), nicht über Delisting-Events. Für ein reines Live-/Forward-Setting akzeptabel; für künftige Backtests auf historischen Universen ist ein expliziter Delisting-Filter sinnvoll. |
| 6 | Backtest Realism Gap – kein Slippage / Latency | High | **FALSCH** | [rl/slippage/](rl/slippage) implementiert `AlmgrenChrissCalibrator` (Bayesian linear regression, BPS-Output mit 95%-CI). [rl/simulator/execution_env.py](rl/simulator/execution_env.py#L62-L237) trackt `implementation_shortfall_bps` pro Slice. [scripts/build_backtest_slippage_samples.py](scripts/build_backtest_slippage_samples.py) erzeugt Kalibrierungs-Samples; getestet in [tests/test_build_backtest_slippage_samples.py](tests/test_build_backtest_slippage_samples.py). TWAP/VWAP-Baselines in [rl/baselines/](rl/baselines). |
| 7 | Alpha Budget Controls – kein Multiple-Testing | Medium | **FALSCH** | [governance/alpha_ledger.py](governance/alpha_ledger.py) + [governance/alpha_ledger.json](governance/alpha_ledger.json). Promotion-Gate enforced FDR (q=0.05 default) und PSR (>=0.95) – siehe `DEFAULT_FDR_Q`, `DEFAULT_PSR_MIN` in [governance/promotion_gate.py](governance/promotion_gate.py#L78-L79). |
| 8 | CI/CD Gate Quality – unzureichende Coverage | Medium | **FALSCH (im behaupteten Umfang)** | 34 Workflows in `.github/workflows/`, davon mehrere als Release-Blocker (`ci.yml` mit `fast-gates`, `validate`, `select-runner`, `Analyze (python)`, `Analyze (javascript-typescript)`, `lint inline backticks (strict)` – via Branch-Protection erzwungen). Promotion-Gate-Workflows: `f2-promotion-gate-daily.yml`, `phase-b-promotion-readiness.yml`, `fvg-quality-quartile-gate.yml`, `drift-watchdog.yml`. Coverage-Gate via `pyproject.toml`. |

## Was an dem Review *strukturell* schiefläuft

1. **Severity-Inflation ohne Evidenz.** Sechs der acht Befunde haben in der „Open Questions / Missing Evidence"-Sektion das Eingeständnis „No evidence of …", werden in der Findings-Table aber als Critical/High klassifiziert. Korrekt wäre: Severity = `UNKNOWN – evidence missing`, nicht `CRITICAL`.
2. **Erfundene Test-Pfade.** Die Regression-Test-Spalte referenziert Dateien (`tests/test_pine_signals.py`, `tests/test_databento_cache.py`, `tests/test_no_lookahead.py`, `tests/test_model_calibration.py`, `tests/test_survivorship_bias.py`, `tests/test_backtest_realism.py`, `tests/test_multiple_testing.py`, `tests/test_ci_gates.py`), die im Repo **nicht existieren**. Das ist nicht „suggested" – das ist als Befund-Evidenz formatiert.
3. **Pfad-Hallucination.** „Pine Script Files: Complete `terminal_technicals.py`" – `terminal_technicals.py` ist eine News-/Terminal-Komponente, kein Pine-Integrationsfile. Die Pine-Quellen liegen als `.pine` im Repo-Root und unter `pine/legacy/`.
4. **Verletzt den eigenen Master-Prompt.** Rule 1 lautet wörtlich „Do not hallucinate. Cite file paths, artifact names, …" – das Review zitiert keine einzige existierende Datei oder Funktion.

## Eigene, evidenz-basierte Findings

Diese ersetzen die externe Findings-Table. Severity = realistische Capital/Reputation/Engineering-Wirkung.

| Severity | Finding | Evidenz | Why it matters | Recommended action | Regression test |
|---|---|---|---|---|---|
| Medium | Cache-Content vs Cache-Key Universe-Drift (PR #2338, akzeptierter Trade-off) | [databento_volatility_screener.py](databento_volatility_screener.py#L382) – `build_cache_path` enthält keine Universe-Fingerprint mehr; Inhalt ist universe-abhängig. Mitigation: Pre-merge `isin(day_universe_symbols)`-Filter (~L2432/L2871/L2980), `CACHE_VERSION_BY_CATEGORY`-Bump, daily TTL. Out-of-scope laut PR-Body: Universe-Version in Parquet-Metadata. | Symbol, das nach Cache-Write neu im Universe ist, wird auf HIT stillschweigend ausgelassen, bis TTL/Version-Bump greift. | Follow-up Issue: `captured_universe_hash` + `captured_at` in Parquet-Payload schreiben; bei Lese-Zeit gegen aktuelles Universe checken und bei Drift gezielt nachladen. | Neuer Test: `tests/test_databento_cache_universe_drift.py` – simuliert Cache-Hit mit fehlendem Symbol, erwartet Refetch. |
| Medium | Survivorship-Bias-Schutz nicht explizit | Keine `delisted`/`listing_status`-Filter in `databento_universe.py`; impliziter Schutz nur durch Vendor-Aktivität. | Künftige historische Backtests auf rotierenden Universen produzieren optimistische Ergebnisse. | Explizites `active_only=True`-Argument im Universe-Builder + Persistierung des Universe-Snapshots pro Trade-Day. | Test: Universe-Snapshot für T-180 darf keine Symbole enthalten, die zwischen T-180 und heute delisted sind. |
| Low | Keine dedizierte `test_walkforward.py` | `ml/walkforward.py` wird transitiv über `ml/training/base.py` getestet, hat aber keinen direkten Boundary-/Embargo-Unit-Test. | Regression in `embargo`-Logik würde nur über Family-Smoke auffallen. | Minimaler Property-Test: zufällige `(n_samples, n_folds, embargo, event_horizon)`-Tuples, Assert `max(train_idx) + embargo < min(val_idx)` und `min(val_idx) > max(purged_idx)`. | `tests/test_walkforward_boundary.py`. |
| Low | Pine-Strategy hat keine offline reproducible Regressionsfixtures | Pine läuft nur in TradingView; SMC_Long_Strategy/SMC_Short_Strategy haben keine numerische Snapshot-Suite in `tests/`. | Strategie-Logik-Drift fällt erst bei TV-Preflight auf. | Bestehende Python-Mirror-Tests (`tests/test_smc_*`) um Snapshot-JSON gegen referenz-CSV erweitern, falls noch nicht vorhanden. | Bestehendes Pattern aus `tests/test_smc_dashboard_contract.py` übernehmen. |
| Info | Audit-Logging in Operator-Surfaces | Streamlit-Terminal-Module loggen Polling-Events, aber kein strukturierter Operator-Audit-Trail. | Nur relevant, falls SkippALGO jemals als Decision-Support für regulierte Workflows positioniert wird. | Aktuell nicht notwendig – Disclaimer „Research & Monitoring Terminal" deckt es. | – |

## 7-Tage-Plan (realistisch, basierend auf realem Repo-Stand)

1. PR #2338 mergen, sobald `fast-gates` für den rebasten Head durch ist (laufender Vorgang).
2. Follow-up-Issue „Universe-Version in Databento-Cache-Payload" anlegen (Out-of-scope aus #2338).
3. `tests/test_walkforward_boundary.py` als Property-Test ergänzen.
4. Issue „Explicit survivorship filter in `databento_universe.py`" – mit `active_only`-API und Snapshot-Persistierung.

## 30-Tage-Plan

1. Universe-Version-Metadata in Parquet-Payload schreiben + Drift-Detector beim Lese-Pfad.
2. Backtest-Suite mit historischem Universe-Snapshot statt aktuellem Universe.
3. Promotion-Gate-Dashboard: Brier/ECE/FDR/PSR/PSI-Verläufe pro Family als wöchentlicher Artifact.

## Compliance-Hinweis

SkippALGO bleibt ausschließlich Research & Monitoring Terminal. Keine Investment-Empfehlungen, kein Auto-Trading per Default. Alle Promotion-Gate-Verdikte sind Decision Support, kein Trade-Signal.
