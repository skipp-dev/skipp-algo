# Sprint C14 — Phase-B Promotion (Live Small) [BACKLOG]

**Status:** Backlog (NICHT aktiv).
**Eröffnungs-Voraussetzung:** Sprint C13 mit `GO` signiert (`docs/c8_phase_a_signoff_*.md` mit Verdict GREEN, alle vier Familien oder explizit dokumentierte Per-Familien-Promotion).
**Geplante Dauer:** 90 Tage operativ, 100 Tage inkl. Sign-off-Doku (Phase-B Pass-Kriterium ≥ 30 closed trades je Familie nach `docs/c8_live_incubation_runbook.md` §Phase-B).
**Owner:** Steffen Preuss
**Commit-Identity:** `skipp-dev <preuss.steffen@yahoo.com>`

## Warum dieser Sprint

C13 hat — falls signiert — bewiesen, dass die produktive Schleife läuft: reale Setups → IBKR-Paper-Submissions → Outcomes → Drift-Berechnung → Calibration-Report. Phase-B flippt diese Schleife auf `paper_mode=False` mit `PHASE_B_RECOMMENDED_SIZE_SCALE` (10–25 % vom Vollziel) und liefert den ersten extern verkaufbaren Track-Record-Datenpunkt.

> Hauptziel-Anker: **„Wenn die SMC-Calibration-Track-Record nicht eindeutig profitable Setups zeigt — dann habe ich nichts zu verkaufen."**
> Phase-B ist die Phase, in der der Track-Record entsteht. Phase-A war Plumbing-Validierung.

Strukturelle Vorbereitung in C13 erledigt:

- ✅ Phase-B Drift-Gate `scripts/check_phase_b_drift_readiness.py` läuft seit C13/T4 mit `slippage_ks_reference_type=backtest_samples` (PR #2205, cron Step 3b)
- ✅ `families[]`-Producer + `check_c12_trigger.py` etabliert (PR #331)
- ✅ Atomic-Audit-Log mit Idempotency-Schutz (`_atomic_append_audit`)
- ⚠ `MIN_LIVE_DAYS = 90` und `MIN_LIVE_TRADES = 30` Schwellen aus C12-Trigger gelten weiter

## Voraussetzungen (HARD GATE — ohne diese 8 Punkte wird Sprint nicht eröffnet)

- [ ] **G1:** C13 Sign-off-Dokument `docs/c8_phase_a_signoff_<YYYY-MM-DD>.md` mit Verdict `GO` (mind. 1 Familie, dokumentierter Halt-Grund pro NO-GO-Familie)
- [ ] **G2:** Phase-A Drift-Verdict `pass` oder `acceptable` in den letzten 7 zusammenhängenden Cron-Runs vor Sign-off
- [ ] **G3:** Backtest-Slippage-Sample-Source mind. `mixed` (nicht reines `replay`), d. h. ≥ 1 real_fills-Record je geplanter Phase-B-Familie im `cache/calibration/backtest_slippage_samples_<DATE>.json` ([T4-Akzeptanzkriterium](https://github.com/skippALGO/skipp-algo/blob/main/scripts/build_backtest_slippage_samples.py))
- [ ] **G4:** US Securities Snapshot and Futures Value Bundle aktiviert ($10/Mo) — non-konsolidierte Quotes verfälschen Phase-B-Slippage-Drift (siehe [`scripts/compute_live_drift.py`](https://github.com/skippALGO/skipp-algo/blob/main/scripts/compute_live_drift.py); C13 §Abos-für-Phase-B-aufgeschoben)
- [ ] **G5:** IBKR-Account-Flip von Paper-Mode auf Live-Small — Master-Account-Konfiguration in Client Portal, Risiko-Limits in `cache/live/risk_limits.json` neu gezogen (Phase-A-Limits × 0.10 als Startgröße)
- [ ] **G6:** Killswitch-Test gegen Live-Small-Konfiguration grün (synthetic kill-fire → Halt, debug, post-mortem, Reset-Pfad dokumentiert)
- [ ] **G7:** Incident-Review-Playbook geschrieben (`docs/c14_incident_playbook.md`) — jeder Kill-Switch-Breach in Phase-B MUSS einen Eintrag triggern, sonst Vorgang gesperrt
- [ ] **G8:** Sicherheits-Doku-Anker für `phase=live_small`-Flagge — wer/was/wie kann die Flagge umlegen, was passiert bei Disconnect mid-trade, Recovery-Steps (Pull aus `docs/c8_live_incubation_runbook.md` §Phase-C-Fail-Modes adaptiert)

**Erst wenn G1–G8 abgehakt sind, wird dieser Sprint auf "aktiv" gestellt** und aus `docs/sprints/backlog/` nach `docs/sprints/c14_phase_b_promotion.md` verschoben.

## Sprint-Scope (90 Tage operativ, T1–T8 parallel)

### T1 — Phase-B Konfiguration scharf schalten (Tag 1–2)

**Ziel:** `phase=live_small` produktiv, `paper_mode=False`, Size-Scaling `PHASE_B_RECOMMENDED_SIZE_SCALE` aktiv.

- [ ] `scripts/run_smc_live_incubation.py --phase live_small` Erstausführung gegen Tagessetups; verifizieren dass `paper_mode=False` im Audit-JSONL emittiert wird
- [ ] Validate-Pfad: erste reale Order in IBKR Live-Account, Mini-Position (1 Aktie oder Subzent-Notional je nach Symbol), Killswitch im Hot-Reload-Test
- [ ] Risk-Limits-Update: `cache/live/risk_limits.json` → `max_position_size_pct = 0.10 * Phase-C-Target`, `max_daily_loss_pct = 0.005`, `max_consecutive_losses = 3`
- [ ] Cron-Workflow `c13-daily-cron.yml` (oder Fork `c14-daily-cron.yml` falls Phase-A-Cron parallel weiterlaufen soll) auf Live-Small-Glob-Pattern zeigen

**Akzeptanzkriterium:** Erster Live-Small-Audit-Eintrag im Repo (`cache/live/audit_<DATE>.jsonl` mit `phase=live_small`, `fill_price` gesetzt, `kill_switch_fired=False`).

### T2 — Phase-B Pass-Kriterien-Tracker (Tag 1, kontinuierlich)

**Ziel:** Pro-Familie Live-Tracker, der jeden Tag pro Familie evaluiert wo wir stehen.

Pass-Kriterien aus `docs/c8_live_incubation_runbook.md`:

| Kriterium | Schwelle | Hard/Soft |
|---|---|---|
| `n_trades_closed` | ≥ 30 | HARD |
| `live_sharpe / backtest_sharpe` | ≥ 0.50 | SOFT-Watch (drift_score-basiert) |
| `drift_score` | ≥ 0.65 (verdict `pass` oder `acceptable`) | HARD |
| `kill_switch_fires` | 0 | HARD |
| `max_drawdown_live / max_drawdown_backtest` | < 2.0 | HARD |
| `slippage_ks_reference_type` | `backtest_samples` | HARD (C13/T4 ✓) |
| `window_complete` | `true` | HARD |

- [ ] Erweiterung `scripts/build_families_telemetry.py` (oder neuer Schwester-Script `scripts/build_phase_b_progress.py`) mit oberen 7 Kolumnen pro Familie
- [ ] Output: `cache/calibration/phase_b_progress_<DATE>.json` mit `families: {BOS|OB|FVG|SWEEP: {…, days_remaining, eta_signoff}}`
- [ ] Streamlit-Tab `streamlit_terminal/tab_phase_b_progress.py`: pro Familie Progress-Bar 0–30 Trades, Drift-Verdict-Ampel, Kill-Switch-Counter, ETA-bis-Sign-off

**Akzeptanzkriterium:** Tagesausgabe deterministisch reproducible aus Audit + Drift-JSONL; ETA-Berechnung berücksichtigt Trade-Rate der letzten 14 Tage.

### T3 — Acuity Sentiment-Hook produktiv (Tag 5–35, parallel zu T1/T2)

**Ziel:** Falls C13 die Imbalance-Aligned-vs-Opposed-Korrelations-Studie als „lohnt sich" markiert hat (`|hit_rate_aligned - hit_rate_opposed| > 0.10`), wird in Phase-B auch der Sentiment-Hook produktiv.

- [ ] Acuity-API-Lizenz-Klärung: Browser-Widget aus IBKR-Client-Portal liefert NUR iFrame; echte Acuity Sentiment API ist separater Vertrag ([Acuity Sentiment API Docs](https://knowledgebase.acuitytrading.com/en/acuity-client-knowledge-base/acuity-sentiment-api-documentation)). Pricing-Diskussion mit Acuity direkt
- [ ] Hook-Stelle existiert bereits: [`smc_core/layering.py:34-180`](https://github.com/skippALGO/skipp-algo/blob/main/smc_core/layering.py) (`signed_news`, `enriched_news_heat`)
- [ ] Wrapper-Modul `open_prep/acuity_sentiment.py` mit REST-Client, Daily-Cache `cache/live/acuity_sentiment_<DATE>.json`, Pre-Trade-Filter wie WSH-Earnings in C13/T7
- [ ] Decision-Anker: Falls C13 T8.4-Korrelations-Report Imbalance-Hook deaktiviert hat → Acuity bleibt deferred (kein Phase-B-Mandate). Falls C13 T8.4 GREEN war → T3 wird scharf

**Akzeptanzkriterium:** Sentiment-Score je Symbol vor Submission gelesen; Audit-Log enthält `acuity_sentiment_id` und `acuity_skip_reason` falls Skip-Pfad gefeuert.

### T4 — C10-ML-Trainer Live-Daten-Hot-Swap (Tag 28–80)

**Ziel:** Sobald ≥ 4 Wochen Live-Daten gesammelt sind, XGBoost-Trainer mit produktivem Outcome-Stream nachtrainieren.

- [ ] Erst nach Tag 28: Recalibration-Re-Run mit `cache/live/audit_*.jsonl` als zusätzlichem Trainingsset
- [ ] Hot-Swap-Pfad: neues Modell-Artefakt schreibt nach `artifacts/models/xgb_smc_<DATE>.json`; `scripts/run_smc_live_incubation.py` lädt das neueste passende
- [ ] Champion-Challenger: altes Modell 1 Woche parallel als „shadow", Audit-Log markiert beide Verdicts
- [ ] Promotion-Kriterium: shadow-Hitrate ≥ champion-Hitrate − 0.02 UND shadow-Drift-Score ≥ champion-Drift-Score

**Akzeptanzkriterium:** Min. 1 erfolgreicher Hot-Swap-Zyklus mit dokumentierter Champion-Promotion ODER Decision „shadow blieb champion, kein Swap"; beides im Sprint-Anker dokumentiert.

### T5 — Earnings-Calendar + Imbalance-Hook produktiv (sofort, falls C13/T7+T8 GREEN)

**Ziel:** WSH-Earnings-Pre-Trade-Filter und NYSE/NYSE-MKT-Imbalance-Hook übernehmen den Phase-A-Schalter-Stand und werden ohne Modifikation weitergeführt.

- [ ] Verifizieren dass WSH-Daily-Cache und Imbalance-Snapshot-Cron in Phase-B unverändert laufen
- [ ] Falls C13/T8.4-Verdict „lohnt sich" war: Imbalance-Hook wird vom passiven Sammel- auf aktiven Pre-Trade-Filter-Modus geflippt (siehe C13/T8.4 Decision)
- [ ] Sentiment-Hook (T3) liest dieselben Pre-Trade-Hooks; gleiche Skip-Reason-Semantik

**Akzeptanzkriterium:** Pre-Trade-Skip-Reasons (`skipped_due_to_earnings_window`, `skipped_due_to_imbalance_opposed`, `skipped_due_to_sentiment_extreme`) im Audit-Log dokumentiert; mindestens 5 Skips je aktiver Hook über die 90 Tage.

### T6 — Backtest-Slippage-Sample auf „real_fills"-Dominanz heben (Tag 14–90, kontinuierlich)

**Ziel:** Der Phase-B Drift-Gate-Pfad aus C13/T4 läuft mit `mixed`-Mode. Phase-B muss zeigen dass der Sample-Source primär `real_fills` ist (`mixed` mit n_real ≥ 100 je Familie).

- [ ] Tagesaudit: `cache/calibration/backtest_slippage_samples_<DATE>.json` muss bis Tag 30 mindestens 1 Familie mit `source: "real_fills"` (nicht „mixed") enthalten
- [ ] Bis Tag 60: 2 Familien `real_fills`-dominant
- [ ] Bis Tag 90: 3 Familien `real_fills`-dominant (SWEEP ist optional weil naturgemäß selten)

**Akzeptanzkriterium:** Sample-Source-Progression im Sign-off-Dokument als Tabelle pro Familie pro 30-Tage-Bucket.

### T7 — Track-Record-Externalisierung (Tag 60–90)

**Ziel:** Bei Pass aller Hard-Kriterien wird der Track-Record für externe Präsentation aufbereitet.

- [ ] PSR (Probabilistic Sharpe Ratio) ≥ MinTRL (Minimum Track Record Length) als hartes Gate aus C-Cross-Cutting-Standards
- [ ] Pro-Familie Equity-Curve, Drawdown-Curve, Hit-Rate-Distribution
- [ ] Methodik-Doku-Anker auf „extern verkaufbar" flippen (zurzeit explizit privat per C13 §"Was Phase-A NICHT leistet")
- [ ] Marketing-Material-Lückencheck: Pitch-Deck-Outline, FAQ, Disclaimer-Sektion, Audit-Trail-Erklärung

**Akzeptanzkriterium:** `docs/c14_track_record_external.md` mit allen Familien, PSR-Werten, Caveat-Liste; Methodik-Doku-Anker geflippt.

### T8 — Sign-off + C15-Anker (Tag 90–100)

**Ziel:** GO/NO-GO-Entscheid pro Familie, Sign-off-Dokument, ggf. C15 (Phase-C Live Full) als Folgesprint öffnen.

- [ ] `docs/c14_phase_b_signoff_<YYYY-MM-DD>.md` mit Tabellen pro Familie + Per-Familien-Verdict
- [ ] Bei GREEN: Sprint-Plan C15 (Phase-C Promotion, `phase=live_full`, Size-Scaling weg) eröffnen
- [ ] Bei NO-GO einzelner Familien: dokumentierte Halt-Gründe, Debug-Plan, evtl. C14-Verlängerung für betroffene Familien (analog zu Phase-A-Verlängerungs-Mechanismus)

**Akzeptanzkriterium:** Klares GO/NO-GO pro Familie; bei NO-GO Halt-Grund + Debug-Plan; bei GO → C15-Anker eröffnet.

## Pass-Kriterien für Sprint-Abschluss (must, alle hard)

- ≥ 30 closed trades je geplanter Promotion-Familie
- Drift-Verdict `pass` oder `acceptable` in den letzten 14 zusammenhängenden Cron-Runs
- Kill-Switch nie gefeuert
- `max_drawdown_live < 2.0 × max_drawdown_backtest`
- `slippage_ks_reference_type = backtest_samples` UND mind. 1 Familie mit real_fills-dominantem Sample
- `window_complete = true` über die 30-Tage-Sign-off-Periode

## Was C14 NICHT leistet (klar abgegrenzt)

- **Kein Phase-C-Sign-off** — `phase=live_full` (volle Position-Größe, Kelly-Sizing) ist explizit C15
- **Kein RL-Execution-Layer-Schalten** — `MIN_LIVE_DAYS=90` aus `scripts/check_c12_trigger.py` wird in C14 erreicht; das Schalten ist aber separater C15.x-Sprint mit eigenem Sign-off
- **Kein Marketing-Release ohne Disclaimer** — C14 Track-Record ist 90 Tage × 30 Trades; externes Marketing braucht zusätzliche regulatorische Compliance-Review (separater Track ausserhalb der Tech-Sprints)
- **Kein Live-Full vor Phase-B-Sign-off** — Position-Sizing-Per-Kelly bleibt explizit out of scope

## Risiken & Gegenmaßnahmen (Phase-B-spezifisch)

| Risiko | Wahrscheinlichkeit | Auswirkung | Gegenmaßnahme |
|---|---|---|---|
| Kill-Switch feuert mid-trade in Phase-B | mittel (Live-Daten anders verhalten als Paper) | Incident-Review + 7-Tage-Pause je Familie | Playbook G7; Halt-Mechanismus per Cron pre-flight gepinnt |
| Drift `concerning` 2× in Folge | hoch (Phase-Übergang Paper→Live ist klassischer Drift-Trigger) | Phase-B verlängern um 14 Tage, 1 NO-GO pro Familie möglich | Per-Familien-Phase-B-Verlängerung dokumentiert (analog Phase-A); Cross-Familien-Halt nicht erzwungen |
| `MIN_LIVE_DAYS=90` aus C12-Trigger nicht erreicht | niedrig (90 Tage operativ geplant) | C12-Trigger bleibt BLOCKED | Tracking-Cron evaluiert täglich, Verzögerung dokumentiert nicht halt |
| Real-Slippage signifikant > Backtest-Slippage | hoch (Paper unterschätzt Slippage systematisch) | T6 erreicht real_fills-Dominanz, drift_score sinkt | Phase-B verlängert sich automatisch über Slippage-K-S-Pfad; Akzeptanzkriterium ist drift_score ≥ 0.65, nicht absolute Slippage |
| US Securities Snapshot Bundle nicht aktiviert (G4 nicht erfüllt) | niedrig (operativer Check vor Sprint-Eröffnung) | Phase-B-Slippage-Berechnung verfälscht | G4 ist HARD GATE; Sprint kann nicht starten |
| Acuity-API-Lizenz blockiert | mittel (Lizenz nicht öffentlich verfügbar) | T3 deferred zu C15 | T3 ist NICHT in Pass-Kriterien; deferred ohne Sprint-Halt |
| ML-Trainer-Hot-Swap regrediert Hit-Rate | mittel (klassischer ML-Recalibration-Fail) | T4 Champion bleibt, kein Swap | Champion-Challenger-Pattern HARD; Promotion-Kriterium dokumentiert |

## Definition of Done (Sprint C14)

✅ **MUSS** (für Sprint-Abschluss):
- Daily-Cron läuft 90 Tage ohne manuelle Intervention auf `phase=live_small`
- Phase-B-Progress-Tracker (T2) emittiert täglich
- Backtest-Slippage-Sample (T6) erreicht real_fills-Dominanz in mind. 1 Familie
- Sign-off-Dokument geschrieben + Per-Familien-GO/NO-GO entschieden
- Kill-Switch nie gefeuert (oder explizit dokumentierter Incident-Review-Pfad bei 1 Vorkommnis als „akzeptabel")

🧪 **SOLL** (Phase-C-Promotion-Voraussetzung):
- 3+ Familien real_fills-dominant
- 3+ Familien GO-Verdict
- T7 Track-Record-Externalisierung abgeschlossen
- C15-Anker eröffnet

⚠ **NICE-TO-HAVE**:
- ML-Trainer-Hot-Swap mind. 1× erfolgreich durchgespielt (T4)
- Acuity-Sentiment-Hook produktiv (T3)
- Pitch-Deck-Outline und Marketing-Disclaimer-Sektion

## Skip-Anker (gemäß repo discipline)

C14 wird **erst eröffnet, wenn G1–G8 grün sind**. Bei vorzeitiger Eröffnungs-Anfrage:

- Reject-Begründung: „Phase-A Sign-off fehlt" → zurück zu C13/T8 oder Phase-A-Verlängerung
- Skip-Anker (`SkipReason.PHASE_A_NOT_SIGNED_OFF`) im Repo-Memory dokumentieren

## Querverweise

- `docs/sprints/c13_live_incubation_phase_a.md` — Phase-A-Anker
- `docs/c8_live_incubation_runbook.md` §Phase-B — Operatives Runbook
- `scripts/check_phase_b_drift_readiness.py` — Drift-Gate (C13/T4 wired)
- `scripts/check_c12_trigger.py` — `MIN_LIVE_DAYS=90`, `MIN_LIVE_TRADES=30`
- `scripts/build_backtest_slippage_samples.py` — Slippage-Sample-Builder
- `scripts/run_smc_live_incubation.py --phase live_small` — Operativer Schalter
- PR #2205 — C13/T4 Cron-Bootstrap, Phase-B Drift-Gate strukturell entsperrt
