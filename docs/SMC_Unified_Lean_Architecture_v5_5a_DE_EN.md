# SMC Unified Lean Architecture v5.5a

## Deutsch

## Status

Aktive Zielarchitektur.

Version v5.5a ist keine neue breite Plattformversion, sondern eine gezielte Schärfung von v5.5.  
Sie hält am leanen Grundmodell fest und verbessert vor allem Priorisierung, Klarheit, Produktform und semantische Strenge.

Das Ziel bleibt unverändert:

**Ein schlankes, effizientes, generator-first SMC-System, das schnelle, visuell klare und möglichst zuverlässige Signale liefert, ohne sich in Kontrollmechanik, Feature-Wachstum oder Pine-Komplexität zu verlieren.**

## 1. Zweck

Diese Architektur definiert ein leichtgewichtiges Zielbild für das SMC-System und die zugehörige TradingView-Umsetzung.

Sie soll fünf Dinge gleichzeitig leisten:

1. die kanonische Marktstruktur stabil und klein halten  
2. additive Kontexte nur dort zulassen, wo sie echten Mehrwert bringen  
3. Generator, Manifest, Library und Pine-Consumer synchron halten  
4. Signale eher qualifizieren als blockieren  
5. das Pine-Skript als Produkt erhalten und nicht zu einem Forschungsterminal ausufern lassen

Die leitende Regel bleibt:

> `snapshot.structure` bleibt canonical-only.  
> Alles Weitere ist additiv und muss die Entscheidung vereinfachen, nicht verkomplizieren.

## 2. Designprinzipien

Die Architektur bevorzugt bewusst:

- Einfachheit vor Vollständigkeit
- Verdichtung vor Feldwachstum
- Signalqualität vor Confluence-Sammeln
- visuelle Klarheit vor interner Detailtiefe
- Scoring vor übermäßiger Blocklogik
- kompakte UX vor Operator-Dashboard-Denke
- Runtime-Hygiene vor Feature-Masse

## 3. Primäre Entscheidungssurface

Die Architektur definiert genau **eine** primäre, nutzerorientierte Entscheidungssurface.

Diese besteht aus:

- Lifecycle State
- Signal Quality Tier
- Event State
- Directional Bias
- bis zu 2–3 kurzen Warnings

Alle anderen Lean-Familien sind **Support-Familien**.  
Sie existieren, um diese primäre Surface zu speisen, nicht um als parallele Dashboards oder konkurrierende Interpretationssysteme aufzutreten.

## 4. Primat der Signal Quality

`Signal Quality` ist die primäre Interpretationsschicht der Lean-Architektur.

Die bevorzugte Konsum-Reihenfolge lautet:

1. Lifecycle State  
2. Signal Quality  
3. Event State  
4. Bias  
5. Warnings

## 5. Canonical Structure

Die kanonische Struktur bleibt unverändert und minimal.

Canonical `snapshot.structure` enthält nur stabile Strukturkategorien:

- `bos`
- `orderblocks`
- `fvg`
- `liquidity_sweeps`

Canonical Structure beantwortet nur eine Frage:

**Was ist strukturell passiert?**

## 6. Additive Lean-Familien

### 6.1 Event Risk Light
Pflichtfelder:
- `EVENT_WINDOW_STATE`
- `EVENT_RISK_LEVEL`
- `NEXT_EVENT_NAME`
- `NEXT_EVENT_TIME`
- `MARKET_EVENT_BLOCKED`
- `SYMBOL_EVENT_BLOCKED`
- `EVENT_PROVIDER_STATUS`

### 6.2 Session Context Light
Pflichtfelder:
- `SESSION_CONTEXT`
- `IN_KILLZONE`
- `SESSION_DIRECTION_BIAS`
- `SESSION_CONTEXT_SCORE`

Optional:
- `SESSION_VOLATILITY_STATE`

`SESSION_VOLATILITY_STATE` ist **optional**.  
Wenn dieses Feld nicht verfügbar ist, muss das System vollständig funktionsfähig bleiben.

### 6.3 Order Block Context Light
Pflichtfelder:
- `PRIMARY_OB_SIDE`
- `PRIMARY_OB_DISTANCE`
- `OB_FRESH`
- `OB_AGE_BARS`
- `OB_MITIGATION_STATE`

### 6.4 FVG / Imbalance Lifecycle Light
Pflichtfelder:
- `PRIMARY_FVG_SIDE`
- `PRIMARY_FVG_DISTANCE`
- `FVG_FILL_PCT`
- `FVG_MATURITY_LEVEL`
- `FVG_FRESH`
- `FVG_INVALIDATED`

### 6.5 Structure State Light
Pflichtfelder:
- `STRUCTURE_LAST_EVENT`
- `STRUCTURE_EVENT_AGE_BARS`
- `STRUCTURE_FRESH`
- `STRUCTURE_TREND_STRENGTH`

### 6.6 Signal Quality
Pflichtfelder:
- `SIGNAL_QUALITY_SCORE`
- `SIGNAL_QUALITY_TIER`
- `SIGNAL_WARNINGS`
- `SIGNAL_BIAS_ALIGNMENT`
- `SIGNAL_FRESHNESS`

## 7. Event-Risk-User-Semantik

Event Risk Light darf intern detailreicher sein, aber die Standard-User-Semantik bleibt auf **drei Zustände** reduziert:

- `blocked`
- `caution`
- `clear`

## 8. Prefer Scoring over Blocking

Hard Blocks sind nur gerechtfertigt bei:

- klar ungültigen oder irreführenden Daten
- eindeutig blockierendem Event-Risiko
- echten Runtime-/Script-Fail-Zuständen

Alles andere soll bevorzugt werden als:

- Signal Quality Penalty
- Tier Downgrade
- kurzer Warning-Text
- Best/Strict-Downgrade statt kompletter Signalvernichtung

## 9. No Shadow Logic

Der Pine-Consumer darf keine konkurrierende Interpretationslogik aufbauen, die den Lean-Generatorvertrag faktisch überschreibt.

## 10. Field Semantics Integrity

Lean-Felder dürfen keine größere Präzision suggerieren, als ihre Berechnung tatsächlich hergibt.

## 11. Pine Runtime Budget

Runtime-Effizienz ist Teil der Architektur und nicht nur ein Implementierungsdetail.

## 12. UX Modes

### Compact Mode
Standardmodus für Solo-Betrieb und später veröffentlichte / geteilte Skripte.

### Advanced Mode
Optionaler Modus für privaten, internen oder entwicklungsnahen Einsatz.

**Compact Mode ist der Referenzmodus für die Produktqualität der Lean-Architektur.**

## 13. Support-Family Admission Rule

Eine Support-Familie darf nur bleiben, wenn sie mindestens einen dieser Punkte klar verbessert:

- Signal-Timing
- Signalqualität
- visuelle Interpretation
- Nutzervertrauen
- Runtime-Effizienz
- Wartbarkeit

---

## English

## Status

Active target architecture.

Version v5.5a is not a broader platform release. It is a sharpening patch on top of v5.5.  
It preserves the lean foundation while improving prioritization, clarity, product form, and semantic discipline.

The goal remains unchanged:

**A lean, efficient, generator-first SMC system that produces fast, visually clear, and reasonably reliable signals without drifting into control overload, feature sprawl, or Pine complexity.**

## 1. Purpose

This architecture defines a lightweight target model for the SMC system and its TradingView implementation.

It must accomplish five things at once:

1. keep canonical market structure stable and small  
2. allow additive context only where it provides real value  
3. keep generator, manifest, library, and Pine consumers aligned  
4. qualify signals more often than block them  
5. keep the Pine script as a product, not a research terminal

The governing rule remains:

> `snapshot.structure` stays canonical-only.  
> Everything else is additive and must simplify the decision, not complicate it.

## 2. Design Principles

The architecture deliberately prefers:

- simplicity over completeness
- condensation over field growth
- signal quality over confluence accumulation
- visual clarity over internal detail
- scoring over excessive blocking
- compact UX over operator-dashboard thinking
- runtime hygiene over feature mass

## 3. Primary Decision Surface

The architecture defines exactly **one** primary user-facing decision surface.

That surface consists of:

- lifecycle state
- signal quality tier
- event state
- directional bias
- up to 2–3 concise warnings

All other lean families are **support families**.  
They exist to feed this surface, not to act as parallel dashboards or competing interpretation systems.

## 4. Signal Quality Primacy

`Signal Quality` is the primary interpretation layer of the lean architecture.

Preferred consumption order:

1. lifecycle state  
2. signal quality  
3. event state  
4. bias  
5. warnings

## 5. Canonical Structure

Canonical structure remains unchanged and minimal.

Canonical `snapshot.structure` contains only stable structure categories:

- `bos`
- `orderblocks`
- `fvg`
- `liquidity_sweeps`

Canonical structure answers one question only:

**What happened structurally?**

## 6. Additive Lean Families

### 6.1 Event Risk Light
Required fields:
- `EVENT_WINDOW_STATE`
- `EVENT_RISK_LEVEL`
- `NEXT_EVENT_NAME`
- `NEXT_EVENT_TIME`
- `MARKET_EVENT_BLOCKED`
- `SYMBOL_EVENT_BLOCKED`
- `EVENT_PROVIDER_STATUS`

### 6.2 Session Context Light
Required fields:
- `SESSION_CONTEXT`
- `IN_KILLZONE`
- `SESSION_DIRECTION_BIAS`
- `SESSION_CONTEXT_SCORE`

Optional:
- `SESSION_VOLATILITY_STATE`

`SESSION_VOLATILITY_STATE` is **optional**.  
If unavailable, the system must remain fully functional.

### 6.3 Order Block Context Light
Required fields:
- `PRIMARY_OB_SIDE`
- `PRIMARY_OB_DISTANCE`
- `OB_FRESH`
- `OB_AGE_BARS`
- `OB_MITIGATION_STATE`

### 6.4 FVG / Imbalance Lifecycle Light
Required fields:
- `PRIMARY_FVG_SIDE`
- `PRIMARY_FVG_DISTANCE`
- `FVG_FILL_PCT`
- `FVG_MATURITY_LEVEL`
- `FVG_FRESH`
- `FVG_INVALIDATED`

### 6.5 Structure State Light
Required fields:
- `STRUCTURE_LAST_EVENT`
- `STRUCTURE_EVENT_AGE_BARS`
- `STRUCTURE_FRESH`
- `STRUCTURE_TREND_STRENGTH`

### 6.6 Signal Quality
Required fields:
- `SIGNAL_QUALITY_SCORE`
- `SIGNAL_QUALITY_TIER`
- `SIGNAL_WARNINGS`
- `SIGNAL_BIAS_ALIGNMENT`
- `SIGNAL_FRESHNESS`

## 7. Event Risk User Semantics

Event Risk Light should map to three user-facing states only:
- `blocked`
- `caution`
- `clear`

## 8. Prefer Scoring over Blocking

Hard blocks are justified only for:

- clearly invalid or misleading data
- clearly blocking event risk
- real runtime or script failure states

## 9. No Shadow Logic

The Pine consumer must not build a competing interpretation layer that effectively overrides the lean generator contract.

## 10. Field Semantics Integrity

Lean fields must not imply more precision than their underlying computation supports.

## 11. Pine Runtime Budget

Runtime efficiency is part of the architecture, not merely an implementation concern.

## 12. UX Modes

### Compact Mode
Default mode for solo operation and later shared/published scripts.

### Advanced Mode
Optional mode for private, internal, or development-oriented use.

**Compact Mode is the reference mode for lean product quality.**

## 13. Support Family Admission Rule

A support family should remain only if it clearly improves at least one of the following:

- signal timing
- signal quality
- visual interpretation
- user trust
- runtime efficiency
- maintainability
