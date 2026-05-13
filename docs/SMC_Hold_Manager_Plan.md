# SMC Hold-Manager — Plan (Option C)

Status: **Plan-Dokument** — v1 (reine Visualisierung) implementiert in
`SMC_Hold_Manager.pine`. v2/v3/v4 noch ausstehend (siehe Phase-Gate-Section).

Letzte Aktualisierung: 2026-04-29

## Naming — warum kein separater „Exit-Manager"?

**Hold-Manager = Hold-Phase + Exit-Phase einer Position.** Es gibt im Repo
bewusst keinen separaten `SMC_Exit_Manager.pine`, weil ein Exit ohne
Hold-Kontext (Entry-Bar, Initial-Stop, Trail-Höchststand, Time-in-Trade,
T1-Hit-Status) keine sinnvollen dynamischen Entscheidungen treffen kann.

| Komponente | Rolle | Wann verwenden? |
|---|---|---|
| `SMC_Exit_Signal.pine`   | **Statischer Exit-Notifier** (Anfänger) | Combo 0 — nur Stop/TP1/TP2-Alerts, kein State, kein Trail |
| `SMC_Hold_Manager.pine`  | **Aktiver Trade-Manager** (inkl. Exit) | Combo 8 — ATR-Chandelier-Trail, Breakeven-nach-T1, Time-Stop |
| ~~`SMC_Exit_Manager`~~   | bewusst NICHT gebaut | nur sinnvoll, falls Exits SMC-agnostisch portabel sein müssten (kein aktueller Use-Case) |

Falls später eine SMC-agnostische Exit-Komponente gebraucht wird (z. B. für
Discord-Signal-Konsumenten), ist der Refactor trivial: Hold-Manager Sections
5+7 in eigene Datei kopieren, `mp.*`-Reads droppen — ~80 Zeilen Reduktion.

## Was ist ein „Hold-Manager"?

Eine **Position-Lifecycle-State-Machine** mit aktiver Trade-Verwaltung.
Der Unterschied zum simplen `SMC_Exit_Signal` (Option B):

| Aspekt | SMC_Exit_Signal (B) | Hold-Manager (C) |
|---|---|---|
| Stop | statisch auf BUS Invalidation | dynamisch (Trail / BE-Move / ATR-Chandelier) |
| Targets | fix TP1 (1.5R), TP2 (3R) | mehrstufig + adaptive Skalierung nach Quality |
| Position-Sizing | nicht beachtet | Skalierung basierend auf BUS QualityScore |
| Time-Stop | nicht vorhanden | „N Bars ohne Fortschritt → flach" |
| Re-Entry | nicht vorhanden | erkennt Re-Setup nach gestopptem Trade |
| Defensive Exit | bei State-Collapse (>grace bars) | + bei Volumen-Kollaps + bei CHoCH gegen |
| Telemetrie | Status-Tabelle | Voll-Lifecycle-Log + Performance-Metriken |

## Zielbild

Ein Indikator (`SMC_Hold_Manager.pine`), der dem manuellen Trader **während
einer offenen Position** kontinuierlich genau eine Anweisung pro Bar gibt:

```
Action (in trade):
  HOLD                — alles im Plan, halten
  MOVE STOP → $X.XX   — Stop nachziehen
  TAKE 1/3            — Teilgewinn
  TAKE 1/2            — Teilgewinn
  EXIT FULL           — alles raus
  TIGHTEN             — Stop verkürzt (nahe Bruch)
```

Plus passende `alertcondition()` für jeden dieser Events.

## Phased Rollout

### v1 — „Trail after TP1" (kleinster sinnvoller Schritt nach Option B)

Erweitert SMC_Exit_Signal um eine einzige Regel:

- Nach TP1-Hit: Stop wird automatisch auf **Entry-Preis** (Break-Even) bewegt.
- Neue Alert: `MOVE STOP → BREAK-EVEN`.
- Visual: Stop-Linie springt sichtbar hoch.

**Aufwand:** 1–2h. Direkt in `SMC_Exit_Signal.pine` einbaubar oder als
Fork. **Wert:** Risiko nach TP1 = 0.

### v2 — „ATR-Chandelier-Trail"

- Nach Entry: Trailing-Stop = `highest(high, N) − ATR(14) × mult` (default mult=2.5).
- Aktiv erst nachdem `close > trigger + 1R`.
- Stop nie nach unten — nur nach oben.
- Neue Alert: `MOVE STOP → $X.XX (chandelier)`.

**Aufwand:** 3–4h. **Wert:** Größere Bewegungen werden mitgenommen, ohne
den Stop zu früh zu verkürzen.

### v3 — „Time-Stop + Defensive-Layer"

- Wenn nach `N` Bars (default 10–20) kein Fortschritt (`high − entry < 0.5R`):
  Alert `TIME STOP — flat machen`.
- Volumen-Kollaps-Detektor: rolling Volume MA fällt unter X%.
- CHoCH-gegen-Detektor: BUS StateCode wechselt auf bearish CHoCH.

**Aufwand:** 4–6h. **Wert:** Schützt vor „Range-Tod" und vor Reversal.

### v4 — „Quality-skaliertes Sizing + Re-Entry"

- Position-Size-Empfehlung als Output: `1.0 × base` bei QualityScore ≥ 0.8,
  `0.5 × base` bei 0.5–0.8, `0.0` bei < 0.5.
- Re-Entry-Detektion nach Stop: erkennt erneute ARMED-Phase und unterscheidet
  „Same-Setup-Reentry" (sofort) von „New-Setup-Reentry" (warten auf Confirm).

**Aufwand:** 6–8h. **Wert:** macht aus dem manuellen Trader einen
„semi-automatischen" mit konsistentem Money-Management.

## Quellen-Validierung (welche BUS-Outputs / Library-Symbole brauchen wir?)

### Bestätigt verfügbar (validated 2026-04-29)
- `BUS Armed`, `BUS Confirmed`, `BUS Ready` (input.source) ✅
- `BUS Trigger`, `BUS Invalidation` ✅
- `BUS QualityScore`, `BUS StateCode`, `BUS SourceKind`, `BUS TrendPack` ✅
- `BUS ZoneActive`, `BUS SchemaVersion` ✅

### **NICHT verfügbar** — wichtige Korrektur
- ❌ `BUS Target1`, `BUS Target2`, `BUS StopLevel` existieren **nicht** als
  separate BUS-Outputs. Nur `BUS Invalidation` ist publiziert.
- → Targets müssen **intern berechnet** werden als R-Multiple von
  `(Trigger − Invalidation)`. Genau dieses Pattern nutzt
  `SMC_Long_Strategy.pine` (Zeile 75–76, `take_profit_r` default 2.0).

### Library `mp.*` — Lifecycle-Flags (KORREKTUR 2026-04-29)

**Vorherige Fehlangabe in dieser Doku:** `mp.LONG_INVALIDATED_NOW`,
`mp.LONG_BROKEN_DOWN`, `mp.LONG_CONFIRM_EXPIRED` — **diese Symbole
existieren NICHT** als `mp.*` Library-Exports. Sie wurden in einer früheren
Fassung dieser Doku fälschlich als verfügbar gelistet.

**Was tatsächlich existiert (validiert via grep im Workspace):**

Der **vollständige 4-Tupel-Return** von `resolve_long_invalidation_state()`
(in `SMC++/smc_lifecycle_private.pine:110`):

```
[long_setup_expired, long_confirm_expired, long_broken_down, long_invalidated_now]
```

| Flag | Quelle | Bedeutung |
|---|---|---|
| `long_setup_expired`   | `armed && !confirmed && setup_age > setup_expiry_bars` | ARMED→CONFIRMED Time-out |
| `long_confirm_expired` | `confirmed && confirm_age > confirm_expiry_bars`       | CONFIRMED→READY Time-out |
| `long_broken_down`     | `invalidation_break_src < invalidation_level − buffer` | Preis durchbricht Invalidation |
| `long_invalidated_now` | Aggregate-Master-Pulse aus den drei oberen + intra-bar source-broken/lost | Master-Edge |

**Semantik-Unterscheidung _now vs _this_bar (kritisch für Alerts):**

- `long_invalidated_now` ist ein **Level-Signal** („gerade invalidiert", bleibt true).
- `long_invalidated_this_bar` ist ein **Edge-Signal** in `compute_long_arm_should_trigger`
  (`smc_lifecycle_private.pine:37`) — Re-Arm-Sperre auf derselben Bar, nur
  rising-edge.
- Für Hold-Manager-Alerts **immer** Edge konsumieren (`ta.change(state) != 0`
  oder `var bool fired = false`-Latch), sonst feuert jede Bar 20× — siehe
  Schwäche E unten und das v1-Skeleton (`SMC_Hold_Manager.pine`).

**Sichtbarkeit:**

- Diese Flags sind **lokale Pine-Variablen** in `SMC_Core_Engine.pine`
  (Zeile 1505 / 1729) — **nicht** als separate BUS-Outputs publiziert.
- Sie sind aber **implizit in `BUS StateCode`** enthalten: die Funktion
  `resolve_long_state_code()` (Zeile 1729–1730) setzt ein `invalid_state`
  Bit basierend auf `long_invalidated_now or long_invalidated_this_bar`.
  Wenn `BUS StateCode` in den „INVALID"-Range fällt, ist Lifecycle-
  Invalidation passiert.

**Konsequenz für den Hold-Manager:**

- Für v3 „Defensive-Layer" reicht **das Beobachten von `BUS StateCode`**.
  Kein Library-Symbol nötig.
- Falls man explizite Lifecycle-Flags als eigene BUS-Series wünscht
  (sauberer Trigger, weniger StateCode-Mapping im Konsumenten), wäre das
  ein separates Mini-PR im SMC Core: `plot(long_invalidated_now ? 1 : 0, "BUS LongInvalidatedNow")` etc. Drei zusätzliche `plot()`-Lines, kein Lifecycle-Refactor.

### Bekannt verfügbar in `mp.*` (validiert in `SMC_Long_Strategy.pine`)
- `mp.TRADE_STATE` (z. B. "BLOCKED")
- `mp.HIGH_IMPACT_MACRO_TODAY` (bool)
- `mp.MARKET_REGIME` (z. B. "RISK_OFF")
- `mp.EARNINGS_TODAY_TICKERS` (string)

→ Diese kann der Hold-Manager als **zusätzlichen Defensive-Layer** nutzen:
„Wenn Trade offen und mp.TRADE_STATE → BLOCKED": defensiver Exit.

## Anti-Pattern: was der Hold-Manager NICHT machen soll

- ❌ Eigene neue Setups detektieren (das ist Sache von Mobile_Dashboard).
- ❌ Library-Lifecycle nachimplementieren (das macht SMC Core).
- ❌ Auto-Trading-Hooks (das macht SMC_Long_Strategy + TradersPost).
- ❌ Mehrere Positionen gleichzeitig managen (Pine-Indikator ≠ Portfolio-Engine).

## Bekannte Schwächen & Mitigation (Review 2026-04-29)

| ID | Schwäche | Phase | Mitigation |
|---|---|---|---|
| A | `long_setup_expired` initial im Flag-Inventar gefehlt | Doku | **gefixt** — siehe 4-Tupel oben |
| B | `_now` vs `_this_bar` Semantik unklar | Doku | **gefixt** — siehe Tabelle oben |
| C | Pine `var`-State-Loss bei Recompile | v3+ | Reset-Hook + `barstate.isconfirmed`-Gate; v3: Webhook-gestützte State-Rekonstruktion |
| D | Time-Stop in Bars ist TF-abhängig | v3 | Time-Stop in **Minuten**, nicht Bars (TF-agnostisch) |
| E | `alertcondition()` feuert auf Level → Alert-Spam | v1 | **Alert-Edge-Framework von Tag 1**: alle Alerts auf rising-edge (`x and not x[1]`) |
| F | Quality-Sizing-Schwellen (0.5/0.8) sind arbiträr | v4 | Aus `mp.ZONE_CAL_*` / neuen `mp.HOLD_SIZING_*` Konstanten ziehen |
| G | ATR-Chandelier `mult=2.5` nicht family-aware | v2 | `mult_by_family` aus T4-Backtest-Slippage-Sample (Sprint C13) |

**Zusatz-Punkte:**

- **Gap-Open / Earnings:** Pre-Defensive-Layer — bei `mp.EARNINGS_TODAY_TICKERS`
  oder `_TOMORROW` am **Vortag-Close** `EXIT_BEFORE_EARNINGS` feuern, nicht am
  Earnings-Tag selbst (Stop wird sonst gegappt). v3.
- **Multi-Position-Verbot:** Wenn zweites Entry-Signal vor Close des ersten
  kommt → `OVERRIDE_BLOCKED` anzeigen, nicht silently überschreiben. v1.
- **Observability:** Pine kann nicht auf Disk schreiben. Empfohlen:
  Alert-Webhook-JSON-Payload pro State-Transition + Chart-Table mit den
  letzten 20 Events.

## Phase-Gate-Bedingungen (Track-Record-Konsistenz)

- **v1** (reine Visualisierung): darf **ab sofort** gebaut werden — kein
  Eingriff in Live-Path, keine Drift-Gefahr für die laufende Sprint-C13
  Phase-A Paper-Inkubation unter `SMC_Long_Strategy.pine`.
- **v2/v3** (aktives Management): **erst nach Phase-A-Sign-off** (~26.05.2026),
  sonst wechselst du mitten im Track-Record das Exit-Regime und Backtest-
  vs.-Paper-Drift wird unauswertbar.
- **v4** (Quality-Sizing): **erst nach Phase-B-Sign-off** (~Ende Juli),
  sonst kalibrierst du gegen ein nicht-konfidenz-gepinntes Score.

## Test-Plan

1. **Compile-Check** via `test_compile.py` (existiert bereits im Repo).
2. **Visual-Check**: Backtest-Replay über 50 historische ARMED→Trade-Zyklen,
   prüfen dass Lifecycle-State sich korrekt fortbewegt.
3. **Side-by-Side**: `SMC_Long_Strategy` vs. `SMC_Hold_Manager`-Empfehlungen —
   sollten in v1 (Trail-after-TP1) bei TP-Hits ähnliche Equity-Kurven
   produzieren.
4. **Property-Test (Monotonie)**: Stop-Level sinkt nie (long), Target-
   Reihenfolge wird eingehalten (T1 vor T2), Position-Size dekrementiert
   monoton nach jedem TP.
5. **Edge-Detection-Pin**: jeder Alert (`HM_ENTRY`, `HM_T1`, `HM_T2`,
   `HM_STOP`, `HM_TIMESTOP`, `HM_EXIT_ANY`) feuert **genau einmal** pro
   Event über simulierten Multi-Bar-Hold. Pinned Test gegen
   Pine↔Python-Parity-Risiko aus Bug-Hunt v2 Phase 7.4.
6. **State-Persistence-Test**: Nach simuliertem Recompile ist der Zustand
   entweder wiederhergestellt oder explizit als `UNKNOWN` markiert (kein
   silentes State=NONE).
7. **Outcomes-Schema-Integration**: Hold-Manager-Outputs landen im
   `cache/live/outcomes_*.jsonl` im **selben Schema** wie
   `SMC_Long_Strategy`-Outcomes. Notwendig für die Phase-A
   Backtest-vs-Live-Drift-Berechnung.
8. **Golden-File** über 50 ARMED→Trade-Zyklen aus Sprint-C13-Paper-Trading-
   Daten (sobald verfügbar) — deterministisch byteweise gepinnt, nicht nur
   „ähnliche Equity-Kurven".

## Offene Fragen

1. Sollte v1 als Erweiterung in `SMC_Exit_Signal.pine` einfließen oder als
   separates `SMC_Hold_Manager.pine` (eigener Slot)? — Empfehlung:
   **separat**, damit Anfänger weiter Option B nutzen können ohne
   Komplexität. Profis schalten dann den Hold-Manager dazu.
2. Brauchen wir eine TV-Strategy-Variante (`SMC_Hold_Strategy.pine`) für
   Backtests? — Ja, in Phase v2/v3 sinnvoll.
3. Sollten wir den State im Indikator persistent speichern (var) oder per
   `request.security` aus einer höheren TF? — Var reicht; aber Watch-out:
   wenn Pine-Skript neu kompiliert wird, geht der State verloren. Akzeptabel
   für manuellen Trader (er sieht es im Chart sofort).
