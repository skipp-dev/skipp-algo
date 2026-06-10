# Review-Checklist: Field-Preference `or`-Ketten

**Guard:** [tests/test_field_preference_chain_ledger.py](../tests/test_field_preference_chain_ledger.py)
(Budget in `pin_registry.toml`, Sektion `[field_preference_chain_ledger.file_counts]`)
**Herkunft:** Audit #2668 (Runde 1, PR #2669) + #2670 (Runde 2). Erfüllt die
offene #2668-Checkbox "Zukunfts-Guard".

## Das Muster

```python
size = float(row.get("size") or row.get("volume") or 0.0)   # ⛔
```

Eine `or`-Kette über **semantisch verschiedene** Felder hat zwei stille
Fehlermodi:

1. **Substitution:** Fehlt das bevorzugte Feld, wird unbemerkt ein *anderes*
   Konzept serviert (Print-Size ↔ Session-Volume, Trade-Zeit ↔ Quote-Zeit,
   gemessener Indikator ↔ Proxy). Der Konsument kann die Fälle nicht
   unterscheiden.
2. **Falsy-Schlucken:** `or` behandelt valide falsy-Werte (`0`, `0.0`, `""`,
   `[]`) als "fehlt" und fällt durch, obwohl ein Wert da war.

Real gefundene Bugs dieser Klasse: Premium aus Session-Volume statt
Trade-Size (W1), Quote-Timestamps passieren Trade-Staleness-Gates (W4),
ATR-Proxy-Regime als gemessene ADX/BB-Daten serviert (W2).

## Checkliste für Reviewer (jede neue `x.get("a") or y.get("b")`-Site)

- [ ] **Sind `a` und `b` echte Synonyme** desselben Upstream-Contracts
      (z. B. `title`/`headline` aus zwei Provider-Versionen)?
      → Benign. Budget in `pin_registry.toml` bewusst bumpen, Kommentar
      mit Begründung an die Sektion.
- [ ] **Sind `a` und `b` semantisch verschieden** (verschiedene Messgröße,
      verschiedene Uhr, verschiedene Quelle)? Dann Pflicht:
  - [ ] `is None`-Check statt `or` (falsy-Werte sind valide Daten), und
  - [ ] **Source-Disclosure-Feld** im Output (`*_source`), das festhält,
        welcher Zweig gewonnen hat.
- [ ] **Kein Default, der wie Daten aussieht:** Wenn beide fehlen, lieber
      `None`/Fehler/expliziter `"no_data"`-Marker als ein synthetischer Wert.

## Vorbild-Muster im Repo (Referenz)

| Muster | Ort | Was es richtig macht |
|---|---|---|
| `vol_regime.model_source` + `fallback_reason` | smc_core/vol_regime.py | Modell- vs. Heuristik-Pfad als Feld + Grund |
| `BiasVerdict.source` (`HTF`/`SESSION`/`MERGED`/`NONE`) | smc_core/bias_merge.py | Merge-Provenienz typisiert im DTO |
| `planned_*_source` / `actual_*_source` | smc_integration/repo_sources.py | Geplante vs. tatsächliche Provider getrennt ausgewiesen |
| `TechnicalResult.source` (`tradingview`/`fmp_fallback`/`stale_cache`) | terminal_technicals.py | Provider-Fallback-Kette im DTO (W3-Fix) |
| `regime_source` (`atr_proxy`/`no_data`) | open_prep/run_open_prep.py | Proxy-Synthese disclosed (W2-Fix) |
| `timestamp_substitutions` (`target<-source`) | databento_volatility_screener.py | Cross-Phase-Backfill maschinenlesbar (W9-Fix) |

## Trip-Verhalten des Guards

Neue Site → `test_per_file_chain_count_pinned` (oder
`test_no_new_files_with_preference_chains`) schlägt fehl und zeigt die
Live-Zeilennummern. Entweder Site nach obiger Checkliste fixen oder Budget
bewusst (mit Kommentar) bumpen. Beim Entfernen einer Site: Budget senken —
nie Headroom stehen lassen.
