# Live-Overlay — Betriebs-/Hosting-Notizen (Phase 1)

> **Quelle:** abgeleitet aus
> [AGENT_HANDOVER_news_overlay_2026-06-06.md](AGENT_HANDOVER_news_overlay_2026-06-06.md),
> der Strategie [live_overlay_request_get_strategy_2026-06-04.md](live_overlay_request_get_strategy_2026-06-04.md)
> und dem Umsetzungsplan [PLAN_live_overlay_phase1_2026-06-06.md](PLAN_live_overlay_phase1_2026-06-06.md).
> **Status:** Ops-Notizen (Phase-3-Seed). **Arbeitspaket:** WP-E.
> **Leitprinzip:** Der gebackene `mp.*`-Default ist **immer** der sichere
> Fallback. Das Overlay ist ein additiver Premium-Tier-Benefit; bei
> Stale/Down/Unreachable fällt Pine still auf die 2×/Tag-Baseline zurück.

---

## 1. Architektur in einem Satz

**Ein** zentral gehosteter HTTPS-JSON-Endpoint `GET /smc_live?symbol=&tf=`
liefert pro `(symbol, tf)` ein flaches „live overlay"-JSON (Contract
`smc-live-overlay/1`, siehe [spec/smc_live_overlay.schema.json](../spec/smc_live_overlay.schema.json)).
`SMC_TV_Bridge.pine` zieht es per `request.get()` (TradingView Premium+),
prüft `asof_ts`/`stale` gegen `OVERLAY_MAX_AGE_SEC` und überschreibt **feldweise**
den gebackenen `mp.*`-Wert — nur wenn frisch und vorhanden.

```
Producer (2×/Tag + ~5-Min-Snapshot)
        │   reuse der bestehenden Snapshot-/Enrichment-Artefakte
        ▼
GET /smc_live?symbol=&tf=  ──HTTPS/JSON──►  CDN (Short-TTL-Cache)
        │                                        │ identische Payload je (symbol, tf)
        │                                        ▼
        └──────────────────────────────►  Pine request.get()  ──feldweiser Merge──►  Chart
                                                  │ stale/down → Fallback auf mp.*
```

---

## 2. Serving-Layer

- **Dienst:** kleine HTTPS-JSON-API (FastAPI; vorhandenes Gerüst
  [smc_tv_bridge/smc_api.py](../smc_tv_bridge/smc_api.py), `uvicorn`-served).
  **Ein** Service, zentral von uns betrieben; Nutzer installieren **nichts** —
  sie fügen nur den Bridge-Indicator zum Chart hinzu.
- **Datenquelle:** liest den bereits vorhandenen ~5-Min-Snapshot +
  Enrichment-Artefakte (`load_raw_meta_input`-Kette,
  [smc_integration/sources/live_news_snapshot_json.py](../smc_integration/sources/live_news_snapshot_json.py)).
  **Kein** zweiter Producer — das Overlay re-serialisiert nur, was der Daily-Run
  ohnehin erzeugt.
- **Kein Streamlit:** Das Streamlit-Terminal ist ein Menschen-UI, kann von Pine
  nicht konsumiert werden und ist per Produktentscheidung **kein**
  Auslieferungspfad.
- **Payload-Form:** flach (`news_strength`, `flow_rel_vol`, `squeeze_on`, `vix_level`,
  `tone`, `flow_delta_proxy_pct`, `ats_state`, `ats_zscore`, …), damit der
  vorhandene `f_getField`-Parser ohne neuen Parser wiederverwendbar bleibt.

---

## 3. Hosting

- **Anforderung (TV-seitig):** Endpoint muss über **HTTPS** öffentlich
  erreichbar sein und valides JSON liefern. Kein HTTP, kein Self-Signed.
- **Offene Entscheidung (Operator):** Wo läuft der FastAPI-Endpoint?
  - **Option A — selbe Box wie der Producer:** teilt sich das Dateisystem mit
    dem Snapshot (Shared Volume, kein Netz-Hop). Einfachste Datenfrische,
    aber koppelt Endpoint-Uptime an die Producer-Maschine.
  - **Option B — separater Cloud-Dienst** (z. B. kleiner Container/Function):
    entkoppelt Uptime; muss den Snapshot **pullen** (geteilter Objektspeicher
    oder periodischer Sync). Bevorzugt für Phase 3 / 200-Nutzer-Last.
- **Empfehlung Phase 1:** mit der einfachsten Variante starten (Snapshot lokal
  lesbar), CDN davorschalten, Hosting-Ort vor Phase-3-Lasttest finalisieren.

---

## 4. Cache / CDN

- Die Antwort ist **pro `(symbol, tf)` identisch** und idempotent → ideal für
  einen **Short-TTL-Cache** hinter einem CDN. 200 Nutzer = triviale Last bei
  brauchbarer Cache-Hit-Rate.
- **TTL-Wahl:** kleiner als die Snapshot-Kadenz, damit frische Daten zeitnah
  sichtbar werden, aber groß genug für hohe Hit-Rate. Richtwert **30–60 s**
  TTL (Snapshot ist ~5 Min frisch; TV throttelt `request.get()` ohnehin auf
  bar-/recalc-Takt — „realtime Sekunden" ist nicht das Ziel).
- **Header:**
  - `Cache-Control: public, max-age=<TTL>` setzen.
  - `ETag` + `Last-Modified` aus `asof_ts` ableiten, damit das CDN revalidieren
    kann.
  - CORS bleibt GET-only/öffentlich (vgl. bestehende `/smc_tv`-Route).
- **Wichtig:** Der CDN-Cache ist eine **Performance-Schicht**, **kein**
  Korrektheits-Mechanismus. Die Frische-Entscheidung trifft Pine selbst über
  `asof_ts`/`stale` — ein zu alter Cache-Eintrag wird vom Overlay-Frischecheck
  ohnehin verworfen und führt zum sicheren `mp.*`-Fallback.

---

## 5. Frische & Stale-Semantik

- Jede Payload trägt `asof_ts` (Unix-Sekunden) und `stale` (bool). Pine
  entscheidet **unabhängig** vom TV-Recalc-Timing:
  `overlayFresh = i_enabled and asof>0 and (timenow/1000 - asof_ts) <= i_overlayMaxAge and stale != "true"`.
- `i_overlayMaxAge` (Pine-Input, Default **600 s**) ist die obere
  Frische-Grenze; serverseitig sollte `stale` gesetzt werden, sobald der
  zugrunde liegende Snapshot älter als sein Erwartungsfenster ist.
- **Bestehender Stale-Gate:** Der News-Snapshot kennt bereits
  `_META_DOMAIN_STALE_HOURS = 48.0`
  ([smc_integration/repo_sources.py](../smc_integration/repo_sources.py)).
  Der `/smc_live`-Endpoint sollte konsistent dazu `stale=true` markieren,
  statt veraltete Werte als frisch auszuliefern.
- **Off-Universe-Symbole:** liefern ein **leeres, aber Contract-valides** JSON
  (Envelope vorhanden, Datenfelder weggelassen) → Pine fällt feldweise auf
  `mp.*` zurück. Kein 500er, kein Teil-Payload.

---

## 6. Auth / Missbrauch

- **Premium-Gate:** `request.get()` ist TradingView **Premium+ only**. Die
  „Premium-only"-Durchsetzung erfolgt **primär über den Skript-Zugriff**
  (invite-only/Premium-publizierte Library), **nicht** API-seitig — der
  Endpoint kann den TV-Nutzer nicht zuverlässig authentifizieren.
- **Payload effektiv öffentlich:** Pine `request.get()` kann einen
  Query-Parameter mitgeben, aber **keine Secrets halten**. Daher gilt: die
  Antwort als öffentlich behandeln — **nichts Sensibles** einbetten (keine
  Keys, keine proprietären Schwellen, keine Roh-Positionsdaten).
- **Abuse-Schutz:** optionales Rate-Limiting/Token als Query-Param möglich,
  aber als reiner Missbrauchs-Dämpfer, nicht als Vertraulichkeitsgrenze. Der
  CDN-Cache absorbiert legitime Last ohnehin.

---

## 7. Monitoring

- **Uptime/Latenz:** Health-Probe gegen den bestehenden `/health`-Endpoint;
  Alarm bei 5xx-Rate oder Latenz-Anstieg.
- **Frische-Drift:** `asof_ts` der Antworten beobachten — wenn das Maximum
  über `i_overlayMaxAge` hinausläuft, liefert der Producer keine frischen
  Snapshots mehr (Pine fällt dann korrekt zurück, aber der Mehrwert ist weg).
- **Cache-Hit-Rate:** vor dem 200-Nutzer-Lasttest (Phase 3) als KPI
  etablieren; niedrige Hit-Rate ⇒ TTL/Key-Design prüfen.
- **Fail-Safe-Beleg:** WP-D
  ([tests/test_smc_live_overlay_fallback.py](../tests/)) weist nach, dass
  Down/Stale ⇒ `mp.*`-Fallback (kein Clear durch Datenlücke).

---

## 8. Sicherheits-Invariante (nicht verhandelbar)

- **Overlay augmentiert, ersetzt nie.** Frisch → überschreibt den gebackenen
  Default zur Laufzeit; stale/absent/unreachable → Fallback auf `mp.*`.
  Backtests bleiben deterministisch (Overlay nur realtime).
- **Event-Risk = escalation-only:** `MARKET_EVENT_BLOCKED` /
  `SYMBOL_EVENT_BLOCKED` sind sicherheitskritisch. Das Overlay darf einen Block
  **hinzufügen**, nie entfernen. Bei Ausfall gilt „caution", nie „clear"
  (`effective_blocked = baked_blocked OR overlay_blocked`).
  **Stand 2026-06-08 (#2618):** Die 7 Event-Felder werden jetzt **serviert**
  (WP-B2, Quelle: gecachter Databento-Reference-Snapshot — **kein**
  Live-Earnings-/Kalender-/News-Feed) und in `SMC_TV_Bridge.pine` **diagnostisch
  angezeigt** (WP-B3, `tighten-only`: Block-Flags nur bei `"true"` + frischem
  Overlay; stale/absent ⇒ `–`). Das **consumer-seitige Trade-Gating**
  (`effective_blocked` tatsächlich in Entry-Entscheidungen umsetzen) ist **noch
  offen** und bleibt ein separater Folge-Schritt.

---

## 9. Bekannter Workflow-Gap (separater Operator-PR — NICHT in diesem Parallel-Plan)

> ⚠️ **Nicht parallel-safe:** berührt den Daily-Workflow und erfordert
> Operator-Freigabe. Hier nur **dokumentiert**, **nicht** umgesetzt.

Die `*-error.png`-Diagnose-Screenshots des TradingView-Preflights
(`automation/tradingview/reports/screenshots/`) werden heute **nicht** als
CI-Artefakt hochgeladen. Dadurch ist eine Live-Diagnose fehlgeschlagener
Publish-Läufe erschwert.

- **Fix (klein, aber im Daily-Workflow):** den Upload-Pfad in
  [.github/workflows/smc-library-refresh.yml](../.github/workflows/smc-library-refresh.yml)
  um einen `actions/upload-artifact`-Schritt für
  `automation/tradingview/reports/screenshots/**` (inkl. `*-error.png`,
  `if: always()`) ergänzen.
- **Warum separat:** Der Workflow ist der Live-Publish-Pfad (Cron 2×/Tag
  16:00/20:00 UTC, Pin `test_workflow_databento_handoff_timeouts`). Jede
  Änderung daran gehört in einen **eigenen, vom Operator freigegebenen PR**
  außerhalb des additiven Live-Overlay-Plans.

---

## 10. Phasen-Übergang

| Phase | Ops-Inhalt | Exit |
|---|---|---|
| **1 (jetzt)** | Endpoint aus 5-Min-Snapshot, einfaches Hosting, CDN davor | ein Symbol live im Test-Chart; Fallback bei Down verifiziert (WP-D) |
| **2** | Event-Risk (escalation-only) + 🟡-Gruppe | Fail-Safe verifiziert (Endpoint-Kill → caution, nicht clear) |
| **3** | CDN/Cache-Tuning, Monitoring-Dashboards, per-Symbol-Fan-out, Nutzer-Doku zum Aktivieren der Bridge | 200-Nutzer-Lasttest; Cache-Hit-Rate akzeptabel |
