# C8 Phase-A Sign-off — Early NO-GO

**Date:** 2026-05-14 (Sprint-Tag 16 von 28)
**Sprint:** C13 — Live-Inkubation Phase A scharf schalten (2026-04-28 → 2026-05-25)
**Signoff-Owner:** Steffen Preuss (skipp-dev)
**Verdict:** **NO-GO — Phase-A wird nicht promoviert**
**Begründung in einem Satz:** Es existiert kein Track-Record. Daten = leer.

## Binding Contract

> "Wenn die SMC-Calibration-Track-Record nicht eindeutig profitable Setups zeigt — dann habe ich nichts zu verkaufen."
> **Beweise oder kein Verkauf.**

Diese Sign-off-Entscheidung folgt diesem Vertrag wörtlich.

## Empirische Lage am Tag 16 von 28

Quelle: [c13-daily-cron run 25831081425](https://github.com/skippALGO/skipp-algo/actions/runs/25831081425) (2026-05-13 22:53 UTC), `families_telemetry_2026-05-13.json`, `calibration_report_public.json` (schema_version 1.3.0, commit `8e4240e6`).

| Familie | live_days | n_trades | drift_verdict | kill_switch_fires |
|---|---:|---:|---|---:|
| BOS   | 0 | 0 | unknown | 0 |
| OB    | 0 | 0 | unknown | 0 |
| FVG   | 0 | 0 | unknown | 0 |
| SWEEP | 0 | 0 | unknown | 0 |

Aggregat: `metrics={}`, `n_events=null`, `weighted_hit_rate=null`, `family_weights={}`.

Phase-A-Cron-Historie (`calibration_report_public_history.jsonl`):

- 9 Einträge zwischen 2026-05-04 und 2026-05-13
- **Alle** 9 Einträge: `metrics={}, n_events=null, weighted_hit_rate=null`
- Keine einzige Zeile mit echten Daten

## Sign-off-Kriterien aus dem Runbook (§"Phase-A — Paper")

| Kriterium | SOLL | IST | Bewertung |
|---|---|---|---|
| ≥ 20 paper trades closed pro Familie | 20 / Familie | 0 / Familie | ❌ NICHT ERFÜLLT |
| \|paper-Sharpe / OOS-Sharpe − 1\| < 0.30 (drift_score ≥ 0.70) | drift_score ≥ 0.70 | nicht berechenbar (keine Trades) | ❌ NICHT BEWERTBAR |
| Slippage-K-S-p-value > 0.05 | p > 0.05 | nicht berechenbar | ❌ NICHT BEWERTBAR |
| Hit-Rate innerhalb C3-Bootstrap-CI | innerhalb CI | nicht berechenbar | ❌ NICHT BEWERTBAR |
| Killswitch nie gefeuert | 0 fires | 0 fires | ✅ trivialerweise erfüllt (keine Trades zum killen) |

**Resultat:** 4 von 5 Kriterien sind nicht erfüllt bzw. nicht bewertbar. Das einzige "✅" ist eine vakuumige Wahrheit (kein Trade → kein Killswitch).

## Was passiert ist (Reality Check)

### Cron läuft, aber leer

Die GitHub-Actions-Schedule für `c13-daily-cron.yml` läuft seit 2026-04-28 zuverlässig (zuletzt erfolgreich 2026-05-13). Aber jede Pipeline-Stufe wird soft-skipped (rc=78), weil die vorherige Stufe keine Eingabedaten findet:

- **Step 1 (backfill_live_outcomes):** kein `audit_orders_*.jsonl` → `No audit file for <DATE> — skipping backfill (rc=78)` an allen 9 Tagen
- **Step 1b (assert progress):** skipped
- **Step 2 (drift-input):** skipped
- **Step 3 (backtest-reference):** läuft, aber WFO/BCI-Inputs existieren nicht → effektiv Leerlauf
- **Step 4 (compute_live_drift):** skipped
- **Step 5a/5b:** läuft, aber emittiert das obige leere `families[]`-Array

Die Pipeline funktioniert mechanisch. Sie hat aber nichts zu verarbeiten.

### Was die Lücke verursacht hat

| Sprint-Task | Sprint-Doc-Status (SOLL) | IST per 2026-05-14 |
|---|---|---|
| T1 — IBKR Paper-Onboarding | Tag 1–3 | ❌ nicht abgeschlossen (Workstation-Side, blockiert auf Account-Konfiguration) |
| T2 — Daily-Cron operativ | Tag 3–5 | ✅ läuft (aber leer) |
| T3 — Echte Paper-Trades | Woche 1–4 | ❌ 0 Submissions (gated auf T1) |
| T4 — Backtest-Slippage-Sample | Woche 1–2 | ⚠ Code wired ([PR #2205](https://github.com/skippALGO/skipp-algo/pull/2205) open), Daten noch deterministic replay |
| T5 — `families[]`-Producer | Woche 2 | ✅ läuft (aber emittiert nur Zero-Records, weil T3 fehlt) |
| T7 — WSH Earnings-Hook | Woche 1–2 | ❌ nicht begonnen |
| T8 — Order-Imbalance-Hook | Woche 1–4 | ❌ nicht begonnen |
| T6 — Sign-off-Review | Tag 28+2 | ⏩ vorgezogen auf Tag 16 (dieses Dokument) |

Der gemeinsame Nenner aller ❌-Tasks ist **T1**. Solange IBKR Paper-Gateway nicht verbunden ist, gibt es keine Submissions, keine Fills, keine Outcomes, keine Drift-Reports. Die Calibration-Pipeline ist methodisch komplett, aber strukturell von Live-Daten getrennt.

## Was Phase-A in C13 geleistet hat (nicht null)

Auch wenn der Track-Record-Aufbau gescheitert ist, hat der Sprint strukturell ausgeliefert:

- ✅ `families[]`-Producer in `emit_public_calibration_report.py` (PR #331, gemerged)
- ✅ Atomic-write Pin-Tests auf `cache/live/*` (`tests/test_atomic_write_call_sites.py`)
- ✅ Idempotency-Guards in `backfill_live_outcomes.py`, `compute_live_drift.py`
- ✅ Daily-Cron-Schedule stabil (9/9 letzte Läufe success)
- ✅ Cron-Failure-Inventory: `test_workflow_continue_on_error_inventory.py`
- ✅ `check_c12_trigger.py` läuft (deterministisch BLOCKED mit nachvollziehbarer breakdown)
- ✅ `check_phase_b_drift_readiness.py` Gate-Logik (PR #331)
- ✅ Backtest-Slippage-Sample-Generator ([PR #2205](https://github.com/skippALGO/skipp-algo/pull/2205), open) — strukturell unblockiert Phase-B-Drift-Gate
- ✅ C10c Joint-Outcome-Modeling abgeschlossen ([PR #2202](https://github.com/skippALGO/skipp-algo/pull/2202), gemerged): Faktorisierungs-Annahme nicht zurückweisbar
- ✅ Coverage-Drift behoben ([PR #2203](https://github.com/skippALGO/skipp-algo/pull/2203), open)
- ✅ Manifest-Flake behoben ([PR #2204](https://github.com/skippALGO/skipp-algo/pull/2204), open)

**Zusammenfassung:** Die Schiene ist fertig gebaut. Es fährt kein Zug.

## Sign-off Verdict

### Pro Familie

| Familie | Verdict | Halt-Grund |
|---|---|---|
| BOS   | **NO-GO** | 0 closed trades; T1 nicht abgeschlossen |
| OB    | **NO-GO** | 0 closed trades; T1 nicht abgeschlossen |
| FVG   | **NO-GO** | 0 closed trades; T1 nicht abgeschlossen |
| SWEEP | **NO-GO** | 0 closed trades; T1 nicht abgeschlossen |

### Aggregat

**NO-GO** für Phase-B-Promotion. C14 bleibt im Backlog (siehe [`docs/sprints/backlog/c14_phase_b_promotion.md`](backlog/c14_phase_b_promotion.md)).

### Auto-Promotion-Ausschluss

Das Runbook §"Why no auto-promotion" greift nicht — es gibt nichts zu auto-promoten. Diese Entscheidung ist ein bewusster manueller Halt: **lieber ein ehrliches NO-GO am Tag 16 als ein gefälschtes GO am Tag 28+2.**

## Debug-Plan (Next-Sprint C13b)

Statt C13 mechanisch auf 28+2 zu strecken, eröffne ich einen Folge-Sprint **C13b — Daten-Aufnahme entsperren**:

### C13b — Scope

| Task | Ziel | Owner | Akzeptanz |
|---|---|---|---|
| T1.0 Pre-Flight-Account-Checkliste | Alle 4 Boxen grün (IBKR Pro, Equity ≥$500, Non-Pro, API enabled) | Workstation-Side | Screenshot/Client-Portal-Dump als Evidenz |
| T1.1 Marktdaten-Abos aktivieren | US RT Non-Cons + NYSE Imbalance + NYSE MKT Imbalance | Workstation-Side | Subscription-Status-Dump |
| T1.2 Adapter-Smoke | 1 Setup → Paper-Order → Fill → audit-log | Workstation+Cron | Erster nicht-leerer `audit_orders_*.jsonl` |
| T1.3 Audit-File-Sanity | Cron-Step-1 findet das Audit-File → backfill läuft echt | Cron | Erster nicht-leerer `incubation_*.jsonl` mit `n_trades > 0` |

### C13b — Definition of Done

**Hard:** Mindestens **1 closed paper trade in mindestens 1 Familie** mit vollständiger Pipeline:

```
audit_orders → backfill_live_outcomes → compute_live_drift → emit_public_calibration_report
→ families[0].n_trades > 0 in calibration_report_public.json
```

Erst dann öffnet C13c, der das eigentliche 28-Tage-Tracking ist. **Diese Klärung ist sauberer als ein "weitermachen wir hoffen es kommt schon".**

## Konsequenzen für C14

- C14 bleibt im Backlog. Status `BACKLOG`, nicht `ACTIVE`.
- G1 (Phase-A-signoff GO) wird durch dieses NO-GO **explizit nicht erteilt**.
- C14 öffnet erst, wenn:
  1. C13b T1.3 grün (mindestens 1 echter closed trade in mindestens 1 Familie)
  2. C13c läuft 28 Tage mit ≥20 closed trades / Familie
  3. C13c-Sign-off ist GO (4 von 5 Runbook-Kriterien erfüllt, nicht nur 1)

## Quellen & Referenzen

- Runbook Phase-A-Sign-off-Kriterien: [`docs/c8_live_incubation_runbook.md`](c8_live_incubation_runbook.md) §"Phase-A — Paper"
- Sprint-Doc: [`docs/sprints/c13_live_incubation_phase_a.md`](sprints/c13_live_incubation_phase_a.md)
- C14-Backlog-Anker: [`docs/sprints/backlog/c14_phase_b_promotion.md`](sprints/backlog/c14_phase_b_promotion.md)
- Letzter Cron-Run-Evidenz: [Actions run 25831081425](https://github.com/skippALGO/skipp-algo/actions/runs/25831081425)
- Cron-History (9 Einträge): `docs/calibration/calibration_report_public_history.jsonl`
- Cron-Step-1 soft-skip-Pattern: alle 9 Runs zeigen `No audit file for <DATE> — skipping backfill (rc=78)`
- C12-Trigger-Gate: [`scripts/check_c12_trigger.py`](../scripts/check_c12_trigger.py) (`MIN_LIVE_DAYS=90`, `MIN_LIVE_TRADES=30`) — trivialerweise BLOCKED
- Phase-B-Drift-Gate: [`scripts/check_phase_b_drift_readiness.py`](../scripts/check_phase_b_drift_readiness.py) — wartet auf Drift-Report mit `slippage_ks_reference_type=backtest_samples`

## Audit-Trail

| Wann | Wer | Was |
|---|---|---|
| 2026-04-27 | skipp-dev | C13-Sprint eröffnet (`docs/sprints/c13_live_incubation_phase_a.md`) |
| 2026-04-28 | cron | Erster Schedule-Run (rc=success, alle Steps soft-skipped) |
| 2026-05-13 | cron | Letzter Schedule-Run (rc=success, alle Steps soft-skipped) |
| 2026-05-14 | skipp-dev | **Dieses Dokument: Early-NO-GO-Sign-off, Sprint geschlossen, C13b eröffnet** |
