# LOD-E2E-Audit 2026-07-23 — Triage-Vermerk (Rejections)

> **Zweck:** Verhindert, dass die unten widerlegten Folge-Vorschläge des
> E2E-Audits „live_overlay_daemon-Datenpfad" (geprüfter Ref
> `6dedaeeed`, Verdict **PASS**, keine P0/P1) erneut als Findings
> auftauchen oder als „Polish"-PR umgesetzt werden.
> Verifiziert gegen `origin/main @ 1b788235f` am 2026-07-23.

## Audit-Ergebnis (Kurzfassung)

PASS bestätigt: Audit-Ref ist Ancestor von origin/main; 407 relevante
Tests grün; für alle 16 untersuchten Masking-Vektoren existiert eine
aktive Gegenmaßnahme plus grüner Guard-Test. Kein Code-Eingriff in
Daemon/Feed erforderlich.

## Widerlegte Folge-Vorschläge

**F-1 (Ops-Hinweis `LIVE_OVERLAY_EXPECT_MARKET_TRAFFIC` in OPS.md):**
already-covered — `services/live_overlay_daemon/OPS.md:179` (Env-Tabelle,
inkl. „Keep 0 while none exists") und Rollout-Abschnitt `OPS.md:246-264`
mit Verifikations-PromQL decken die Variable vollständig.

**F-4 (`noValue`-Texte auf `or vector(0)`-Panels der dashboard.json):**
abgelehnt —

1. Wirkungslos: neben `or vector(0)` rendert `noValue` nie (die Query
   liefert immer einen Wert).
2. Bestand kleiner als berichtet: 7 Panels (nicht ~12; der Report zählte
   Queries), die 4 Stat-Panels tragen bereits `noValue: "NO DATA"`.
3. Alle Reststellen sind **contract-gepinnte Absicht**, kein Versäumnis:
   - `tests/test_live_overlay_dashboard_contract.py:1059-1065`
     (`test_latency_queries_guard_zero_observation_histogram`) verlangt
     das `or vector(0)` als NaN-Guard (leeres Histogramm; das
     `and on() (count>0)`-Konstrukt macht daraus eine ehrliche 0 bei
     „keine Requests");
   - `:870-885` (`test_dashboard_market_sessions_closed_is_not_red`)
     pinnt die 0→„CLOSED (grau)"-Semantik als Design-Entscheidung;
   - `:1021-1032` (`test_latency_alert_uses_histogram_quantile_bucket`)
     verlangt `vector(0)` im Alert-Ausdruck.

Das Masking-Restrisiko (Scrape tot → Timeline zeigt „CLOSED"/„OFF" statt
„unbekannt") ist bewusst alert-seitig gedeckt (`lo-scrape-missing`,
`lo-core-signal-missing`); die Panels sind Anzeige, nicht Wahrheitsquelle.
Eine Änderung dieser Semantik wäre eine Design-Revision samt
Test-Umschreibung und braucht eine explizite Betreiber-Entscheidung —
kein „monitoring polish".
