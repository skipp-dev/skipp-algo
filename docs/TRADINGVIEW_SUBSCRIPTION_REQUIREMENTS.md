# TradingView Subscription Requirements for skipp-algo SMC Suite

**Last updated:** 2026-06-16  
**Scope:** live_overlay_daemon · SMC Pine script suite · smc-library-refresh automation

---

## TL;DR / Kurzfassung

| Use case / Anwendungsfall | Basic (Free) | Essential/"Pro" | Plus | Premium | Ultimate |
|---|:---:|:---:|:---:|:---:|:---:|
| live_overlay_daemon (1–2 Skripte) | ✅ | ✅ | ✅ | ✅ | ✅ |
| SMC Core Engine (LTF aus) | ✅ | ✅ | ✅ | ✅ | ✅ |
| SMC Core Engine (LTF an) | ❌ | ✅ | ✅ | ✅ | ✅ |
| Bis zu 5 Skripte gleichzeitig | ✅¹ | ✅ | ✅ | ✅ | ✅ |
| Bis zu 10 Skripte gleichzeitig | ❌ | ❌ | ✅ | ✅ | ✅ |
| Alle 20 Skripte gleichzeitig | ❌ | ❌ | ❌ | ✅ | ✅ |
| `request.get()` HTTP aus Pine | ❌ | ❌ | ❌ | ✅ | ✅ |

¹ Basic erlaubt nur 3 Indikatoren pro Chart-Tab — reicht für Core Engine + 2 Overlays.

**Fazit / Bottom line:**  
Der live_overlay_daemon und der Kern-Handelsworkflow funktionieren vollständig mit **Essential ("Pro") oder jedem bezahlten Plan**. Premium wird nur benötigt, wenn alle 20 Skripte gleichzeitig auf einem Chart-Tab geladen werden sollen.

---

## Was ist LTF-Sampling? / What is LTF Sampling?

**Deutsch:**  
LTF = Lower TimeFrame (Niedrigerer Zeitrahmen).  
Das Skript schaut *innerhalb* jeder Kerze auf kleinere Zeitrahmen (z.B. bei einer 15min-Chart auf 1min- oder 3min-Kerzen), um zu analysieren, wie sich der Preis *während* der Kerze bewegt hat — wie viele Kerzen bullish vs. bearish waren und wie das Volumen verteilt war.

Die Pine-Funktion dafür heißt `request.security_lower_tf()`. TradingView stellt diese Funktion nur für bezahlte Abos bereit.

**English:**  
The script looks *inside* each bar at smaller timeframes (e.g. on a 15min chart it samples 1min or 3min candles) to analyze how price moved *during* the bar — how many sub-candles were bullish vs. bearish and how volume was distributed.

The Pine function is `request.security_lower_tf()`, restricted to paid subscriptions by TradingView.

---

## Vollständige Feature-Matrix / Complete Feature Matrix

| Feature (DE/EN) | Basic (Free) | Essential/"Pro" | Plus | Premium | Hinweis / Note |
|---|:---:|:---:|:---:|:---:|---|
| **Order Block Erkennung** / OB detection | ✅ | ✅ | ✅ | ✅ | Keine LTF-Abhängigkeit |
| **FVG / Imbalance Erkennung** | ✅ | ✅ | ✅ | ✅ | Keine LTF-Abhängigkeit |
| **HTF Trend-Stack** (4H/1D/1W) | ✅ | ✅ | ✅ | ✅ | `request.security()` — alle Pläne |
| **Setup armed / confirmed / ready** | ✅ | ✅ | ✅ | ✅ | Nur Barschlusskurs-Logik |
| **Alerts (ready/confirmed/clean/early)** | ✅ | ✅ | ✅ | ✅ | Alle Alert-Typen feuern |
| **`ltf_bull_share` im Alert-Text** | `n/a` | ✅ | ✅ | ✅ | Zeigt "n/a" wenn LTF aus |
| **`ltf_volume_delta` im Alert-Text** | `n/a` | ✅ | ✅ | ✅ | Zeigt "n/a" wenn LTF aus |
| **Intrabar-Druckanalyse** / intrabar pressure | ❌ | ✅ | ✅ | ✅ | Kernfeature von LTF-Sampling |
| **LTF-gestützter "Strict Entry" Gate** | ❌ | ✅ | ✅ | ✅ | `strict_entry_ltf_ok` Gate |
| **"Strict Entry" mit Fallback** | ⚠️toggle¹ | ✅ | ✅ | ✅ | Toggle: `allow_strict_entry_without_ltf` |
| **live_overlay_daemon (Databento-Feed)** | ✅ | ✅ | ✅ | ✅ | Unabhängig vom TV-Abo |
| **`request.get()` TV Bridge HTTP** | ❌ | ❌ | ❌ | ✅ | Aktuell **auskommentiert** — inaktiv |
| **Bis zu 3 Skripte gleichzeitig** | ✅ | ✅ | ✅ | ✅ | Basic-Limit |
| **Bis zu 5 Skripte gleichzeitig** | ❌ | ✅ | ✅ | ✅ | Essential-Limit |
| **Bis zu 10 Skripte gleichzeitig** | ❌ | ❌ | ✅ | ✅ | Plus-Limit |
| **Alle 20 Skripte gleichzeitig** | ❌ | ❌ | ❌ | ✅ | Premium: 25 Indikatoren/Tab |

¹ Toggle `allow_strict_entry_without_ltf = true` in den Script-Einstellungen setzen → Strict Entry feuert auch ohne LTF-Volumenbestätigung, aber ohne Volumen-Gate (weniger präzise Filterung).

---

## Wie "Strict Entry" mit / ohne LTF funktioniert

### Mit LTF-Sampling (Essential/"Pro" und höher)

```
Strict Entry = OK wenn:
  ✔ Setup ready
  ✔ Signal quality gate OK
  ✔ HTF alignment OK
  ✔ ltf_volume_delta >= 0  ← intrabar: Käufer überwiegen
  ✔ Acceleration gate OK
  ✔ SD entry gate OK
  ✔ weitere Gates ...
```

Alert-Text enthält: `ltf_bull_share=68% | ltf_volume_delta=12%`

### Ohne LTF-Sampling (Basic/Free, toggle=false)

```
Strict Entry = OK wenn:
  ✔ Setup ready
  ✔ Signal quality gate OK
  ✔ HTF alignment OK
  ✔ strict_entry_ltf_ok = true (Gate wird übersprungen / bypassed)
  ✔ Acceleration gate OK
  ✔ weitere Gates ...
```

Alert-Text enthält: `ltf_bull_share=n/a | ltf_volume_delta=n/a`

**Praktische Auswirkung:** Das Signal feuert, aber ohne Volumen-Bestätigung auf Intrabar-Ebene. Der Filter ist etwas großzügiger — alle anderen Bedingungen (HTF-Ausrichtung, OB-Qualität, Session-Gate etc.) bleiben aktiv.

---

## Detailanalyse: Pine API Calls

### `request.security()` — HTF-Daten, FVG-Erkennung
- **Dateien:** `SMC_Core_Engine.pine` (Zeilen 2367, 4696, 4697)
- **Abo-Anforderung:** Alle Pläne inklusive Basic (kostenlos)
- **Nutzung:** Higher-Timeframe Trend-Erkennung, FVG-Scanning über Zeitrahmen hinweg

### `request.security_lower_tf()` — Intrabar LTF-Sampling
- **Datei:** `SMC_Core_Engine.pine` Zeile 3469
- **Abo-Anforderung:** Jedes **bezahlte** Abo (Essential/"Pro" und höher)
- **Toggle:** Geschützt durch `enable_ltf_sampling` Input (Standard: `true`).  
  Auf `false` setzen → Skript läuft auch auf Basic/Free-Tier.
- **Impact bei Deaktivierung:** Intrabar-Partizipations-/Druckbalken werden nicht angezeigt. Der `ltf_bull_share`- und `ltf_volume_delta`-Wert im Alert erscheint als `n/a`. Alle anderen SMC-Logiken (Order Blocks, FVGs, Struktur, Alerts) sind unberührt.

### `request.get()` / `request.post()` — HTTP-Calls aus Pine
- **Datei:** `SMC_TV_Bridge.pine` Zeile 33
- **Abo-Anforderung:** **Premium oder höher** (TV-seitig erzwungen)
- **Aktueller Status:** ⚠️ **AUSKOMMENTIERT** — durch `na`-Platzhalter ersetzt.  
  Der live_overlay_daemon nutzt diesen Code-Pfad **nicht** — Daten fließen über Databento.  
  Wenn dieser Block in einer zukünftigen Iteration aktiviert wird, wird Premium Pflicht.

---

## Indikatoren pro Chart-Tab / Indicators per Chart Tab

TradingView begrenzt, wie viele Indikatoren gleichzeitig auf einem Chart-Tab laufen können:

| Plan | Indikatoren / Tab | Passende Skripte aus diesem Repo |
|---|---|---|
| Basic (Free) | 3 | Core Engine + 2 Overlays |
| Essential ("Pro") | 5 | Core + Dashboard + 3 Overlays |
| Plus | 10 | Core + Dashboard + 6 Overlays |
| Premium | 25 | Alle 20 Skripte + 5 Reserve |
| Ultimate | 50 | Alle Skripte + breite Reserve |

Das Repo enthält **20 Produktions-Pine-Skripte** (+ 1 Test-Datei):

```
SMC_Core_Engine.pine        ← primäre Signalquelle
SMC_Dashboard.pine
SMC_TV_Bridge.pine          ← Live-Daten-Bridge (request.get aktuell inaktiv)
SMC_Long_Strategy.pine
SMC_Breakout_Overlay.pine
SMC_Event_Overlay.pine
SMC_Exit_Signal.pine
SMC_HTF_Confluence.pine
SMC_Hold_Manager.pine
SMC_Imbalance_Context.pine
SMC_Liquidity_Context.pine
SMC_Liquidity_Structure.pine
SMC_Mobile_Dashboard.pine
SMC_Orderflow_Overlay.pine
SMC_Profile_Context.pine
SMC_Session_Context.pine
SMC_Setup_Check.pine
SMC_Structure_Context.pine
SMC_VRVP_Overlay.pine
SkippALGO_Confluence.pine
```

---

## live_overlay_daemon — Mindestanforderung

Der Automatisierungs-Layer (Playwright + Databento) benötigt nur:

- **Lite-Modus:** `SMC_Core_Engine.pine` allein (1 Skript)
- **Internal/Bridge-Modus:** `SMC_TV_Bridge.pine` allein (1 Skript, `request.get` inaktiv)
- **Mainline-Modus:** `SMC_Core_Engine.pine` + `SMC_Dashboard.pine` + `SMC_Long_Strategy.pine` (3 Skripte)

Alle drei Modi laufen auf **jedem Plan inklusive Basic (Free)**, sofern LTF-Sampling auf Basic deaktiviert ist.

---

## Warum die Aussage "nur Premium" falsch war — ehrliche Einschätzung

**Die kurze Antwort:** Die Aussage war nie vollständig begründet. Sie entstand wahrscheinlich durch eine oberflächliche Überprüfung, bei der `request.get()` im TV Bridge gesehen wurde — und da diese Funktion Premium erfordert, wurde das auf das gesamte System verallgemeinert. Das war ein Fehler.

**Was der Code tatsächlich zeigt:**

`request.get()` in `SMC_TV_Bridge.pine` (Zeile 28) ist **auskommentiert** und wird durch einen `na`-Platzhalter ersetzt:

```pine
// [status, headers, body] = request.get(url)
// if status == 200
//     ...
na  // placeholder – remove when uncommenting above
```

Das heißt: Diese Funktion wurde absichtlich deaktiviert und ist in keinem Live-Betrieb aktiv. Dennoch war sie offenbar der Ausgangspunkt der "nur Premium"-Behauptung — entweder weil der Code-Review nicht tief genug ging, oder weil ursprünglich eine aktive Nutzung geplant war und die Deaktivierung nicht kommuniziert wurde.

`request.security_lower_tf()` (Zeile 3469) ist **aktiv**, aber:
- Durch einen Toggle (`enable_ltf_sampling`) abschaltbar
- Erfordert nur *irgendein* bezahltes Abo — nicht Premium
- Beeinflusst ausschließlich den intrabar Volumen-Gate im Strict Entry

**Fazit:** Die "nur Premium"-Aussage war eine Vereinfachung, die auf einer aktiv inaktiven Funktion basierte. Eine präzise Analyse hätte zwischen den Plänen unterschieden und den Toggle-Mechanismus berücksichtigt. Diese Dokumentation korrigiert das nachträglich auf Basis des tatsächlichen Quellcodes.

---

## Empfohlene Konfiguration pro Plan

| Plan | Empfohlene Skripte | LTF-Toggle | Strict-Fallback |
|---|---|:---:|:---:|
| **Basic (Free)** | Core Engine + Dashboard + TV Bridge | `false` | `true` (optional) |
| **Essential ("Pro")** | + Structure Context, HTF Confluence | `true` | nicht nötig |
| **Plus** | + Liquidity Context, Orderflow Overlay, VRVP | `true` | nicht nötig |
| **Premium** | alle 20 | `true` | nicht nötig |

---

## Empfehlung / Recommendation

**Deutsch:**  
Ein **Essential- ("Pro"-) Account** reicht für den live_overlay_daemon und die Kern-Handelsfunktionalität vollständig aus. `request.security_lower_tf()` (LTF-Sampling) funktioniert mit jedem bezahlten Abo. Premium wird nur benötigt, wenn alle 20 Skripte gleichzeitig auf einem Chart-Tab geladen werden sollen. Der `request.get()`-Block im TV Bridge ist auskommentiert und hat keinen Einfluss auf den Live-Betrieb.

**English:**  
An **Essential ("Pro") account** is fully sufficient for the live_overlay_daemon and core trading functionality. `request.security_lower_tf()` (LTF sampling) works on any paid subscription. Premium is only needed if all 20 scripts must run simultaneously on one chart tab. The `request.get()` block in TV Bridge is commented out and has no effect on live operation.

---

## Standard Plan — Essential ohne "Pro"-Bezeichnung

"Standard" in der aktuellen TradingView-Benennung entspricht **Essential** (der ersten bezahlten Stufe, ca. €14.95/Mo.).  
Dies ist der Plan, der früher "Pro" hieß.

- **live_overlay_daemon:** ✅ voll funktionsfähig  
- **SMC Core Engine (LTF aus):** ✅ voll funktionsfähig  
- **SMC Core Engine (LTF an):** ✅ voll funktionsfähig (Essential ist ein bezahlter Plan)  
- **Gleichzeitige Skripte:** bis zu 5 pro Chart-Tab  
- **Empfohlenes Script-Set für Essential:**  
  `SMC_Core_Engine` + `SMC_Dashboard` + `SMC_Structure_Context` + `SMC_HTF_Confluence` + `SMC_TV_Bridge`

**Basic/Free** (kein bezahltes Abo):
- `request.security_lower_tf()` funktioniert nicht → `enable_ltf_sampling = false` setzen  
- Maximal 3 Indikatoren pro Chart-Tab  
- live_overlay_daemon bleibt voll funktionsfähig  
- Strict Entry feuert weiterhin, aber ohne intrabar Volumen-Gate (`n/a` in Alert-Feldern)

