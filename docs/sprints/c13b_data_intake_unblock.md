# Sprint C13b — Daten-Aufnahme entsperren

**Datum:** 2026-05-14
**Owner:** Steffen Preuss
**Voraussetzung:** C13 als NO-GO geschlossen ([`docs/c8_phase_a_signoff_2026-05-14.md`](../c8_phase_a_signoff_2026-05-14.md))
**Status:** **ACTIVE**
**Sprint-Fenster:** offen-ended (kein Zeitlimit, weil 1-Ziel-Sprint)

## Warum dieser Sprint

C13 ist am Tag 16 als NO-GO geschlossen worden. Sign-off-Dokument zeigt: 9 Cron-Runs, **0 closed trades, 0 audit-files**. Die methodische Pipeline läuft, aber sie sieht keine Daten.

Der einzige Engpass ist **T1 (IBKR Paper-Onboarding)** aus C13. Solange das nicht steht, ist jeder Folge-Sprint umsonst.

**Binding Contract:** "Beweise oder kein Verkauf." → erst echte Daten, dann Sprints.

## Sprint-Scope (1 Ziel, 4 Hürden)

### T1 — Pre-Flight-Account-Checkliste (Workstation-Side)

Aus C13 T1.0 (IBKR API Market Data Subscriptions, [Reference](https://www.interactivebrokers.com/campus/ibkr-api-page/market-data-subscriptions/)):

- [ ] **Account-Typ = IBKR Pro** verifiziert (Client Portal → Settings → Account Configuration). Screenshot/Evidenz in `cache/c13b/account_type_check.png`.
- [ ] **Mindest-Equity ≥ $500 USD** im Master-Live-Account. Evidenz in `cache/c13b/equity_check.txt` (Cash-Balance-Dump).
- [ ] **Subscriber-Status = Non-Professional** (Client Portal → Settings → Market Data Subscriptions). Evidenz in `cache/c13b/subscriber_status.png`.
- [ ] **Market Data API Access aktiviert** (Client Portal → Market Data Subscriptions → API enable). Evidenz in `cache/c13b/api_enable.png`.

**Akzeptanz:** alle 4 Boxen grün, alle 4 Evidenz-Files gecheckt-in (oder Hash + externer Pfad in `docs/c13b_evidence_manifest.md` falls Bilder zu groß).

### T2 — Marktdaten-Abos aktivieren (Workstation-Side)

Aus C13 T1.1:

- [ ] **US Real-Time Non Consolidated Streaming Quotes** (Gebühr erlassen) aktiviert
- [ ] **NYSE Order Imbalances (NP)** ($1.00/Mo) aktiviert
- [ ] **NYSE MKT Order Imbalances (NP)** ($1.00/Mo) aktiviert
- [ ] **US-Investmentfonds (NP, L1)** (Gebühr erlassen) aktiviert (schadlos, brach)

**Akzeptanz:** Subscription-Status-Dump aus Client Portal als `cache/c13b/subscriptions.json` (oder gleichwertig dokumentiert).

### T3 — Adapter-Smoke (Workstation-Side + CI-verifizierbar)

Aus C13 T1.2:

- [ ] `scripts/smc_to_ibkr_adapter.py` gegen Paper-Gateway gefahren
- [ ] 1 Setup → IBKROrderIntent → erfolgreiche `placeOrder`-Antwort
- [ ] Risk-Limits aus `scripts/live_risk_limits.py` lösen Killswitch NICHT aus
- [ ] `cache/live/risk_limits.json` mit realistischen Caps gepinnt

**Akzeptanz:** 1 erfolgreicher Round-Trip Setup → Paper-Order → ausgeführt → audit-log-Eintrag in `cache/live/audit_orders_YYYY-MM-DD.jsonl`.

### T4 — End-to-End-Datenfluss (CI-verifizierbar)

Der entscheidende Test: **Cron-Step-1 findet das Audit-File und backfilled echte Outcomes.**

- [ ] Nach T3 läuft der nächste tägliche `c13-daily-cron.yml`-Run und Step 1 **soft-skipped NICHT** (rc != 78)
- [ ] `cache/live/incubation_<DATE>.jsonl` enthält mindestens 1 Eintrag mit `closed=true, n_trades > 0`
- [ ] `docs/calibration/calibration_report_public.json` enthält mindestens eine Familie mit `n_trades > 0`
- [ ] `calibration_report_public_history.jsonl` neue Zeile hat `n_events != null` und `weighted_hit_rate != null`

**Akzeptanz (DoD C13b):**

```
families[X].n_trades > 0 in calibration_report_public.json
∧ metrics != {} in calibration_report_public_history.jsonl (newest line)
∧ Cron-Step-1 rc == 0 (NOT 78)
```

Sobald das einmal grün ist, **schließt C13b** und **C13c (28-Tage-Tracking)** öffnet automatisch.

## Was C13b NICHT leistet

- **Kein 28-Tage-Window** — das ist C13c
- **Kein WSH-Hook** (T7 aus C13) — schiebt sich nach C13c
- **Kein Imbalance-Hook** (T8 aus C13) — schiebt sich nach C13c
- **Kein Sign-off-Review** — C13b hat nur 1 Akzeptanz-Kriterium

## Risiken & Gegenmaßnahmen

| Risiko | Wahrscheinlichkeit | Auswirkung | Gegenmaßnahme |
|---|---|---|---|
| IBKR Pro Konvertierung schlägt fehl | niedrig | T1 blockiert | Support-Ticket; alternative Broker prüfen (extreme Eskalation) |
| Subscription-Activation hängt > 24h | mittel | T2 verzögert | parallel T1.1 starten, asynchron warten |
| Paper-Gateway Auth-Probleme | mittel | T3 blockiert | TWS-Logs aktivieren, IBKR-API-Forum-Pattern |
| Cron-Step-1 findet Audit-File nicht (Pfad-Mismatch) | niedrig | T4 blockiert | Pfad-Convention in `c13-daily-cron.yml` Step 1 dokumentieren |

## Definition of Done (Sprint C13b)

✅ **MUSS:**
- T1: alle 4 Account-Checks grün + Evidenz
- T2: alle 3 Abos aktiviert + Subscriptions-Dump
- T3: 1 Setup → Paper-Order → audit-log-Eintrag
- T4: `n_trades > 0` in calibration_report_public.json an einem regulären Cron-Run

🧪 **SOLL:**
- T4-Resultat mind. 3 aufeinanderfolgende Tage stabil (kein Regress auf Zero-Records)

⚠ **NICE-TO-HAVE:**
- Audit-File-Sanity-Test in `tests/` (z.B. `test_cron_step1_finds_audit_file.py`)

## Sobald C13b grün ist

C13c-Sprint-Anker öffnet automatisch mit:
- 28-Tage-Window neu starten
- Alle 4 Familien tracken
- Sign-off-Kriterien aus dem Runbook gegen echte Daten testen

## Quellen

- C13-Sprint (closed): [`docs/sprints/c13_live_incubation_phase_a.md`](c13_live_incubation_phase_a.md)
- C13 Sign-off NO-GO: [`docs/c8_phase_a_signoff_2026-05-14.md`](../c8_phase_a_signoff_2026-05-14.md)
- Runbook: [`docs/c8_live_incubation_runbook.md`](../c8_live_incubation_runbook.md)
- IBKR API Market Data Subscriptions: [IBKR Campus Reference](https://www.interactivebrokers.com/campus/ibkr-api-page/market-data-subscriptions/)
- C14-Backlog: [`docs/sprints/backlog/c14_phase_b_promotion.md`](backlog/c14_phase_b_promotion.md)
