# Provider Failure Semantics

Stand: 2026-04-17 (F-04)

## Übersicht

Jede Provider-Domain hat eine formale Failure-Semantik-Matrix, die definiert,
welche Reaktion bei welchem Fehlertyp erlaubt ist.

## Failure-Action-Stufen

| Action         | Bedeutung                                             | Entry-Wirkung |
|----------------|-------------------------------------------------------|---------------|
| `FALLBACK`     | Nächster Provider in der Kette übernimmt, kein Impact  | Nein          |
| `ADVISORY`     | Warnung wird geloggt und angezeigt                     | Nein          |
| `SUPPRESS`     | Neue Entry-Signale werden unterdrückt                  | Ja            |
| `HARD_DEGRADE` | Trust-Tier auf "degraded/unavailable", Release geblockt| Ja            |

## Failure-Semantik pro Domain

### Structure

| Fehlertyp   | Action         | Max. tolerierbar | Auswirkung                            |
|-------------|----------------|------------------|---------------------------------------|
| `missing`   | `HARD_DEGRADE` | —                | Kein Snapshot möglich                  |
| `stale`     | `SUPPRESS`     | 24 h             | Entry-Signale nicht verlässlich        |
| `invalid`   | `HARD_DEGRADE` | —                | Malformed Artifact, Build geblockt     |

### Volume

| Fehlertyp   | Action      | Max. tolerierbar | Auswirkung                             |
|-------------|-------------|------------------|----------------------------------------|
| `missing`   | `ADVISORY`  | —                | Quality Scoring unvollständig          |
| `stale`     | `ADVISORY`  | 48 h             | Regime-Klassifikation kann driften     |
| `fallback`  | `FALLBACK`  | —                | Benzinga-Fallback, kein Quality-Impact |

### Technical

| Fehlertyp   | Action      | Max. tolerierbar | Auswirkung                            |
|-------------|-------------|------------------|---------------------------------------|
| `missing`   | `FALLBACK`  | —                | Optionale Enrichment entfällt          |
| `stale`     | `ADVISORY`  | 48 h             | Enrichment kann veraltet sein          |
| `fallback`  | `FALLBACK`  | —                | Anderer Provider, kein Impact          |

### News

| Fehlertyp   | Action      | Max. tolerierbar | Auswirkung                            |
|-------------|-------------|------------------|---------------------------------------|
| `missing`   | `FALLBACK`  | —                | Fallback auf Benzinga oder Skip        |
| `stale`     | `ADVISORY`  | 24 h             | Sentiment-Scores veraltet              |
| `fallback`  | `FALLBACK`  | —                | Benzinga-Fallback, reduzierte Tiefe    |

## Benzinga-Fallback

Benzinga ist der **letzte Fallback** für volume, news und structure Domains.

- **Qualitätsdifferenz**: Benzinga liefert `has_meta=True` aber `has_structure=False`.
  News-Daten aus Benzinga haben reduzierte Tiefe gegenüber live NewsAPI.
  Volume-Daten sind vorhanden, aber ohne Microstructure-Detail.
- **Wann aktiviert**: Wenn alle vorherigen Provider in der Kette nicht verfügbar sind.
- **Konsequenz**: FailureAction bleibt `FALLBACK` — kein Trust-Tier-Impact.
  Der Fallback wird als `FALLBACK_META_*_DOMAIN` Alert geloggt.

## Failure-Szenarien

### Szenario 1: Structure-Artifact fehlt (MISSING_ARTIFACT)

```
Domain:   structure
Failure:  missing
Action:   HARD_DEGRADE
Result:   Trust → "unavailable", Release geblockt, kein Snapshot
```

### Szenario 2: Volume-Domain stale (STALE_META_VOLUME_DOMAIN)

```
Domain:   volume
Failure:  stale
Action:   ADVISORY
Result:   Trust → "degraded", Warning im Report, kein Entry-Block
```

### Szenario 3: News über Benzinga-Fallback (FALLBACK_META_NEWS_DOMAIN)

```
Domain:   news
Failure:  fallback
Action:   FALLBACK
Result:   Trust unverändert, Info-Log, reduzierte News-Tiefe akzeptiert
```

## Welche Failures sind jetzt hart?

- `structure/missing` → HARD_DEGRADE (war vorher implizit)
- `structure/invalid` → HARD_DEGRADE (war vorher implizit)
- `structure/stale` → SUPPRESS (neu formalisiert)

## Was bewusst advisory bleibt

- `volume/missing`, `volume/stale` → ADVISORY (Quality-Impact, aber kein Entry-Block)
- `technical/*` → FALLBACK/ADVISORY (optionaler Enrichment)
- `news/*` → FALLBACK/ADVISORY (News ist Signal-Enrichment, nicht Gate-relevant)

---

## Status-Update 2026-04-30 — v3 Provider-Audit (PRs #1951–#1969)

Diese Failure-Semantik-Matrix wurde am 2026-04-17 (F-04) eingefroren und
deckt aktuell die Domains **structure / volume / technical / news** ab.
Der v3-Provider-Audit (Endstand 2026-04-30) hat den Provider-Stack
erweitert, ohne die existierenden Domain-Semantiken zu aendern:

- **Unusual Whales (neu)** als Options-Flow / Macro-Flow / Insider-Surface
  Provider (#1965, #1967, #1968, #1969). UW liefert Daten zu Domains,
  die bisher nicht Teil der Failure-Matrix sind (`options_flow`,
  `dark_pool`, `gex`, `market_tide`, `insider_form4`). Die Failure-
  Behandlung folgt aktuell der allgemeinen `FALLBACK` / `ADVISORY`
  Konvention der News-Domain. Eine formale Erweiterung der Matrix um
  diese Domains ist in einer separaten ADR zu klaeren (Reservierung:
  ADR-0008 "UW Failure Semantics", noch offen).

- **FMP fear-and-greed** und **FMP short-interest** Pfade wurden in
  PRs #1962 / #1964 entfernt (siehe `docs/FMP_ENDPOINT_GAP_ANALYSE.md`
  "Retired FMP Paths"). Die Failure-Matrix enthielt diese Pfade nie
  explizit — keine Aenderung noetig.

- **Monitor-Insider-Feed-Swap** (#1966): Benzinga-Insider wurde im
  Open-Prep Monitor durch FMP + UW abgeloest. Das ist semantisch
  weiterhin News-Domain (`FALLBACK` zwischen Providern); keine
  Matrix-Aenderung noetig.

- **`ib_insync` → `ib_async`** (#1955): Drop-in Importswap, kein
  Verhalten geaendert; nicht Failure-Matrix-relevant.

Der naechste freie ADR-Slot ist **0008** (siehe `docs/adr/README.md`)
— fuer eine formale UW-Failure-Semantik wuerde dieser Slot reserviert.
