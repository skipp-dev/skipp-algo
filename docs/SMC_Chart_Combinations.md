# SMC Pine Skripte — Abhängigkeiten & Chart-Kombinationen

Letzte Aktualisierung: 2026-04-29

Diese Doku beantwortet zwei wiederkehrende Fragen:

1. **Welche SMC Pine-Skripte müssen auf dem gleichen Chart laufen?**
2. **Welche Kombinationen sind für welchen Use-Case sinnvoll?**

## Kernerkenntnis

**Keines der Skripte muss „zusammen mit" einem anderen Skript auf dem Chart
laufen.** Pine-Indikatoren in TradingView sind technisch isoliert — sie
kommunizieren *nicht* untereinander auf dem Chart.

Was sie teilen, ist die **publizierte TradingView-Library**
`preuss_steffen/smc_micro_profiles_generated/1` (im Code als `mp` importiert).
Daten werden also vom TV-Server bezogen, nicht von einem Nachbar-Indikator.

→ Du musst **nicht** `SMC_Core_Engine` zusätzlich laden, damit z. B. das
`SMC_Dashboard` funktioniert. Jedes Skript ist eigenständig.

## Dependency-Map

| Skript | Library-Imports | Standalone? |
|---|---|---|
| `SMC_Core_Engine` | `smc_core_types`, `smc_utils`, `smc_draw` | ✅ ja (Quell-Engine) |
| `SMC_Dashboard` | `mp` | ✅ |
| `SMC_Mobile_Dashboard` | `mp` | ✅ |
| `SMC_Structure_Context` | `mp` | ✅ |
| `SMC_Liquidity_Context` | `mp` | ✅ |
| `SMC_Liquidity_Structure` | `mp` | ✅ |
| `SMC_Imbalance_Context` | `mp` | ✅ |
| `SMC_Profile_Context` | `mp` | ✅ |
| `SMC_Session_Context` | `mp` | ✅ |
| `SMC_HTF_Confluence` | `mp` | ✅ |
| `SMC_Orderflow_Overlay` | `mp` | ✅ |
| `SMC_Event_Overlay` | `mp` | ✅ |
| `SMC_Breakout_Overlay` | `mp` | ✅ |
| `SMC_Long_Strategy` | `mp` | ✅ |
| `SMC_Setup_Check` | keine | ✅ |
| `SMC_TV_Bridge` | keine | ✅ |
| `SMC_VRVP_Overlay` | keine | ✅ |
| `SMC_Exit_Signal` *(NEU)* | keine (nur BUS-Inputs) | ✅ |
| `SMC_Hold_Manager` *(NEU, v1)* | `mp` (read-only Snapshot) | ✅ |

→ **Alle 19 Skripte sind technisch standalone.**

## Praktische TradingView-Limits

| Plan | Indikatoren pro Chart |
|---|---|
| Free | 1 |
| Pro / Pro+ | 5 |
| Premium | 25 |

Du kannst nicht alle gleichzeitig auflegen — wähle die Kombination
passend zum Use-Case und Plan.

## Sinnvolle Kombinationen

### 0. Absolute Anfänger — „Nur BUY/SELL, kein Erklärbär" (3 Slots)

Für Nutzer, die **keine Zonen, keine FVGs, keine Strukturkonzepte** verstehen
wollen — nur klare Anweisungen per Phone-Alert.

**Empfohlene Skripte:**
- `SMC_Mobile_Dashboard` — die **Entry**-Ampel (Action-Zeile)
- `SMC_Exit_Signal` — die **Exit**-Engine (alertconditions für Stop / TP1 / TP2 / Defensive)
- `SMC_Event_Overlay` — News- / Earnings-Risiko-Filter

> ✅ **Diese Combo deckt den vollen Trade-Lifecycle per TV-Alert ab.**
> Keine Doku-Lektüre, kein Dashboard-Lesen nötig. Phone-Alerts genügen.

**Quellen-Übersicht (Stand 2026-04-29):**

| Quelle | Was es liefert | Anfänger-tauglich? |
|---|---|---|
| `SMC_Mobile_Dashboard` | Entry-Action (`ENTER`/`READY`/`WAIT`/`BLOCKED`) + Trust | ✅ |
| `SMC_Exit_Signal` *(NEU)* | `alertcondition()` für Stop, TP1 (½), TP2 (Rest), Defensive | ✅ |
| `SMC_Event_Overlay` | Visueller News-/Earnings-Risk-Filter | ✅ |
| `SMC_Dashboard` | Optionale Levels-Visualisierung (Stop, R, Quality) | ✅ (optional) |
| `SMC_Long_Strategy` | Maschinelle Backtest-Referenz (TP @ 2R) | ✅ (für Validierung) |

**Action-Zeile (Mobile_Dashboard) — Entry:**

| Was sichtbar ist | Was zu tun ist |
|---|---|
| `Action: ENTER LONG` + `Trust: High` | Einstieg laut Plan |
| `Action: READY LONG` | Auf Bestätigung warten |
| `Action: WAIT` / `PREPARE LONG` | Nichts tun |
| `Action: BLOCKED` | Hände weg / Position defensiv schließen |

**Alerts (Exit_Signal) — Exit:**

| TV-Alert | Was zu tun ist |
|---|---|
| `ENTER LONG (trigger filled)` | Position OPEN — Bestätigung |
| `EXIT — TP1 (take half)` | Halbe Position raus, Stop auf Entry |
| `EXIT — TP2 (close rest)` | Rest schließen |
| `EXIT — Stop hit` | **Sofort raus** (close < Invalidation) |
| `EXIT — Defensive (setup invalidated)` | Defensiv raus (Setup-Stack zerfallen) |

**Setup auf TradingView:**

1. Beide Skripte aufs Chart legen.
2. In `SMC_Exit_Signal` die BUS-Inputs auf die SMC-Core-Outputs binden
   (Armed, Confirmed, Ready, Trigger, Invalidation) — gleiche Reihenfolge
   wie auf `SMC_Long_Strategy`.
3. Auf jede der 5 alertconditions einen TradingView-Alert mit Phone-Push
   anlegen → fertig.

**Wichtige Einschränkungen — bitte ehrlich kommunizieren:**

1. **Kein „BUY/SELL-Generator" im naiven Sinn.** System ist **Long-Dip-only**
   (US-Aktien). Keine SELL-Signale für Shorts.
2. **`Trust`-Spalte ist Pflichtlektüre.** Bei `Degraded` oder `Insufficient`
   ist das Entry-Signal **nicht handelbar**.
3. **Exit_Signal nutzt einen statischen Stop und feste TP-Level.** Kein
   Trailing, kein dynamisches Stop-Nachziehen über TP1 hinaus.
   → Für aktive Trade-Verwaltung siehe Combo 8 unten
   (`SMC_Hold_Manager` v1 — Visualisierungs-Indikator) bzw. den Plan
   [SMC_Hold_Manager_Plan.md](SMC_Hold_Manager_Plan.md) für v2/v3/v4.
4. **Backtest-Validierung:** `SMC_Long_Strategy` parallel laufen lassen — sie
   nutzt dieselben BUS-Signale und liefert die Performance-Statistik.

**Lese-Empfehlung (optional, kein Muss):**
[SMC_Dashboard_Long_Dip_Guide_DE.md](SMC_Dashboard_Long_Dip_Guide_DE.md) und
[SMC_GETTING_STARTED.md](SMC_GETTING_STARTED.md).

### 1. Daily Driver — „Standard-Trading-Layout" (5 Slots)
Best-Bang-for-Buck Combo für aktive Sessions.
- `SMC_Dashboard` — Übersicht / Score
- `SMC_Structure_Context` — BOS/CHoCH-Linien aufs Chart
- `SMC_Liquidity_Context` — Sweep / EQH / EQL als Linien
- `SMC_Imbalance_Context` — FVG-Boxen
- `SMC_Profile_Context` (Pane unten) — POCs

### 2. Breakout-Hunter (4 Slots)
Wenn du gezielt auf Range-Breaks tradest.
- `SMC_Structure_Context` — Strukturkontext
- `SMC_Breakout_Overlay` — Box + ▲▼ am Bruch + Win/Loss-Sim
- `SMC_VRVP_Overlay` — POC / VAH / VAL als Confluence-Levels
- `SMC_Liquidity_Context` — Liquidity-Pools über/unter dem Range

### 3. HTF-Confluence-Setup (3 Slots)
Multi-Timeframe-Bias-Workflow.
- `SMC_HTF_Confluence` (Pane) — HTF-Trend-Score
- `SMC_Structure_Context` — LTF-Struktur
- `SMC_Setup_Check` — Pre-Trade-Checkliste

### 4. Orderflow-Deep-Dive (4 Slots)
- `SMC_Structure_Context`
- `SMC_Liquidity_Structure` (Pane) — Sweep-Quantifizierung
- `SMC_Orderflow_Overlay` (Pane) — Volumen / Delta
- `SMC_VRVP_Overlay` — Visible-Range-Profile

### 5. News-Aware Day-Trading (3 Slots)
- `SMC_Dashboard`
- `SMC_Event_Overlay` — News-Marker
- `SMC_Session_Context` (Pane) — Session-Status

### 6. Mobile (1 Slot)
- `SMC_Mobile_Dashboard` — alleine, große Schrift, alle Stati in einer Tabelle.

### 7. Backtest / Live-Strategy (1–2 Slots)
- `SMC_Long_Strategy` — die ausführbare Strategy
- optional `SMC_Dashboard` daneben für Operator-Visibility

### 8. Aktive Trade-Verwaltung — Hold-Manager (3 Slots, Phase-A-safe)

> **Naming-Klarstellung:** Es gibt bewusst keinen separaten
> `SMC_Exit_Manager`. Hold-Manager subsumiert die Exit-Phase, weil ein
> dynamischer Exit ohne Hold-Kontext (Entry-Bar, Trail-Höchststand,
> T1-Hit-Status) keine sinnvollen Entscheidungen treffen kann. Statischer
> Exit-Notifier für Anfänger ist `SMC_Exit_Signal` (Combo 0).

Für Nutzer, die **bereits in einer Position sind** und während des Trades
laufende Steuerung wollen (Stop-Trail, T1/T2-Visualisierung, Time-Stop in
Minuten, Earnings-Pre-Defensive-Hinweis).

- `SMC_Mobile_Dashboard` — Entry-Ampel (wie in Combo 0)
- `SMC_Exit_Signal` — statische Exit-Engine (Backup-Alerts)
- `SMC_Hold_Manager` — **aktive** Trade-Verwaltung mit ATR-Chandelier-Trail,
  Breakeven-nach-T1, Time-Stop in Minuten, edge-detected Alerts (`HM_*`)

**Wichtige Hinweise zu `SMC_Hold_Manager` v1:**

- Reine **Visualisierung** (`indicator()`, kein `strategy.*` — keine
  Auto-Orders).
- Plan-Inputs (Entry, Initial-Stop, T1/T2-R) werden **manuell** gefüllt
  oder per Webhook-Toggle aus dem Setup-Alert. BUS Target1/2/StopLevel
  sind aktuell nicht publiziert (→ Phase B).
- Alle 6 Alerts (`HM_ENTRY`, `HM_T1`, `HM_T2`, `HM_STOP`, `HM_TIMESTOP`,
  `HM_EXIT_ANY`) sind **edge-detected** — feuern genau einmal pro Event,
  kein Bar-Spam.
- v1 ist **Long-only**. Short-Pfad, family-aware ATR-Mult, Quality-Sizing
  und Webhook-State-Persistence kommen in v2/v3/v4 (siehe Plan-Doku,
  Phase-Gates an Sprint-C13 Phase-A/B-Sign-off gebunden).

> ⚠️ **Nicht parallel zu `SMC_Long_Strategy` mit Live-Orders laufen lassen**,
> solange v1 reine Visualisierung ist — sonst zwei konkurrierende Exit-
> Logiken im selben Track-Record.

## Kombinationen, die du vermeiden solltest

- **Mehrere Pane-Skripte gleichzeitig** (`Liquidity_Structure` +
  `Orderflow` + `Profile` + `Session` + `HTF_Confluence`) → frisst Platz
  unter dem Chart, wird unleserlich.
- **`Dashboard` + `Mobile_Dashboard` parallel** → redundant; einer reicht.
- **`SMC_TV_Bridge` parallel zu `Dashboard` / `Structure_Context`** →
  der Bridge ist „alles in einem", überlappt mit den Einzel-Contexts.

## TL;DR

- Alle Skripte laufen **einzeln**.
- Empfohlene Default-Kombi für aktives Trading:
  **Dashboard + Structure_Context + Liquidity_Context + Imbalance_Context + Profile_Context**
  (5er-Slot-Premium-Plan).
- Für gezielte Setups (Breakouts / HTF / News) tausche selektiv die Overlays.
