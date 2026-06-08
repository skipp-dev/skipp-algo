# WP-0 — Feld-Quellen-Audit (Live-Overlay Phase 1)

> **Zweck:** Für jedes Phase-1-Overlay-Feld die produzierende Python-Funktion, das Artefakt
> und die **Frische-Klasse** festhalten. Entscheidet die Aufteilung von WP-B in **B1**
> (heute frisch servierbar) und **B2** (braucht On-Demand-Hook oder bleibt baked-frisch).
> **Erstellt:** 2026-06-06 · Teil von [PLAN_live_overlay_phase1_2026-06-06.md](PLAN_live_overlay_phase1_2026-06-06.md)

---

## 1. Methodik

- Enrichment-Block-Namen stammen aus dem maschinenlesbaren Sidecar
  `pine/generated/smc_micro_profiles_generated.json` → Schlüssel `enrichment_blocks`
  (autoritativ, 42 Blöcke).
- Producer wurden per Code-Suche in `smc_integration/sources/**`, `scripts/` und
  `smc_integration/measurement_evidence.py` verifiziert.
- **Frische-Klassen:**
  - **`on-demand`** — pro Symbol bei Request frisch beschaffbar (echter Overlay-Mehrwert).
  - **`baked`** — nur so frisch wie der 2×/Tag-Generatorlauf (kein Overlay-Mehrwert; feldweise
    fällt Pine ohnehin auf `mp.*` zurück, daher zurückstellbar).

---

## 2. Feld-Mapping

| Overlay-Feld (flach) | Enrichment-Block | Producer (verifiziert) | Artefakt | Frische | Bucket |
|---|---|---|---|---|---|
| `news_strength`, `news_bias` | `news` | `smc_integration/sources/live_news_snapshot_json.py::load_raw_meta_input` → `scripts/smc_news_scorer.compute_news_sentiment` | `artifacts/smc_microstructure_exports/smc_live_news_snapshot.json` | **on-demand** (~5 min; `asof_strategy="now"`-Opt-in stempelt frischen `asof_ts`) | **B1** |
| `flow_rel_vol` | `flow_qualifier` (Feld `REL_VOL`) | `scripts/smc_flow_qualifier.py::build_flow_qualifier` (eingehängt in `scripts/generate_smc_micro_base_from_databento.py`; Ratio `volume_today/volume_avg_20d`; Rohspalte `rel_vol` aus `databento_watchlist_csv.py` als Upstream-Input) | `smc_micro_profiles_generated.json` | **baked** (Generator-Kadenz) | **B1\*** |
| `squeeze_on` (0/1) | `compression_regime` (Feld `SQUEEZE_ON`) | `scripts/smc_compression_regime.py::build_compression_regime` (eingehängt in `scripts/generate_smc_micro_base_from_databento.py`) | `smc_micro_profiles_generated.json` | **baked** | **B2** |
| `vix_level` | `volatility_regime` / `regime` | Generator-Enrichment (`scripts/generate_smc_micro_base_from_databento.py`) | `smc_micro_profiles_generated.json` | **baked** | **B2** |
| `flow_delta_proxy_pct` | `flow_qualifier` | Generator-Enrichment | `smc_micro_profiles_generated.json` | **baked** | **B2** |
| `ats_state`, `ats_zscore` | `flow_qualifier` | Generator-Enrichment | `smc_micro_profiles_generated.json` | **baked** | **B2** |
| `tone` / `global_heat` | `regime` / `news` | gemischt (`news_heat_global` on-demand; Regime baked) | gemischt | **gemischt** | **B2** |

\* `flow_rel_vol` ist *verfügbar*, aber nur baked-frisch. Es kann in **B1** mit ausgeliefert
werden (kein zusätzlicher Hook nötig), liefert aber erst echten Mehrwert, wenn die Quelle
on-demand aktualisiert wird. Konservativ: in B1 mitnehmen, als „baked" markiert (`stale`-Logik greift).

---

## 3. Schlussfolgerung für WP-B

- **B1 (sofort, echter Mehrwert):** `news_strength`, `news_bias` — on-demand frisch über die
  5-Minuten-Snapshot-Quelle. Plus optional `flow_rel_vol` (verfügbar, baked-markiert).
- **B2 (späterer Hook):** `squeeze_on`, `vix_level`, `flow_delta_proxy_pct`, `ats_*`, `tone`/
  `global_heat`. Diese entstehen im 2×/Tag-Generator. Bis ein On-Demand-Enrichment-Hook
  existiert, werden sie im Endpoint **weggelassen** → Pine löst feldweise auf `mp.*` (baked) auf.
- **Event-Risk** (`event_risk`, `event_risk_light`) bleibt **Phase 2** (Escalation-only), hier
  bewusst nicht aufgenommen.

---

## 4. Offene Punkte (nach WP-A/WP-B zu klären)

1. Ob `flow_rel_vol` in B1 wirklich mitgeliefert wird, oder erst in B2 (Entscheidung beim
   Contract-Freeze in WP-A).
2. Ob für B2 ein dedizierter On-Demand-Enrichment-Hook gebaut wird oder die Felder bewusst
   baked-frisch bleiben (Strategie-Entscheidung; kein Code in dieser Phase).
3. Exakte flache Schlüsselnamen + Typen werden in WP-A (`spec/smc_live_overlay.schema.json`)
   eingefroren.

---

## 5. Nachtrag — B2 jetzt live serviert **und** Pine-konsumiert (Stand 2026-06-08)

> Aktualisiert §§3/4. Die offenen Punkte §4.2 und §4.3 sind entschieden.

**§4.2 (On-Demand-Hook):** Es wurde **kein** dedizierter zweiter Producer gebaut.
Der `/smc_live`-Endpoint baut den Snapshot und leitet tone/VIX/Flow/ATS on-demand
über dieselbe Provider-/Qualifier-Kette wie B1 ab (**kein** Re-Serialisieren
vorberechneter Artefakte) und stempelt `asof_ts`/`stale`; die B2-Felder werden so
on-demand frisch ausgeliefert. VIX stammt dabei aus einem dedizierten
market-weiten `^VIX`-Quote-Pfad (TTL 300s), nicht aus dem Per-Symbol-Snapshot.

**§4.3 (Schlüssel/Typen):** In `spec/smc_live_overlay.schema.json`
(`smc-live-overlay/1`) eingefroren.

Die folgenden **B2-Felder** werden inzwischen serverseitig ausgeliefert **und**
feldweise von `SMC_TV_Bridge.pine` konsumiert:

| B2-Feld | Typ | Serviert | Pine-Konsum |
|---|---|---|---|
| `tone` | string | WP-G (#2609) | WP-L (#2616) |
| `vix_level` | number | WP-H (#2612) | WP-L (#2616) |
| `flow_delta_proxy_pct` | number | WP-K (#2614) | WP-L (#2616) |
| `ats_state` | string | WP-K (#2614) | WP-L (#2616) |
| `ats_zscore` | number | WP-K (#2614) | WP-L (#2616) |

- **ATS = average trade size:** Der Z-Score (`ats_zscore`) wird gegen den
  20-Tage-Mittelwert/-Std aus `reports/ats_baseline_20d.json` (WP-J #2613)
  gebildet. Fehlt ein Symbol dort, wird `ats_*` weggelassen → `mp.*`-Fallback.
- **Fail-closed (#2615):** Liefert das Mikrostruktur-Fenster keine Trades
  (`n_trades == 0`, z. B. außerhalb der Handelszeiten), gibt der Endpoint
  **kein** fabriziertes Flow/ATS-Overlay aus – die neutralen Defaults
  (`avg_trade_size=0.0`, `buy_volume_pct=50.0`) würden sonst die gebackene
  `mp.*`-Baseline überschreiben –, sondern lässt die Felder weg.
- **Invariante unverändert:** Das Overlay **augmentiert nur**. Stale, absent
  oder leeres Fenster ⇒ feldweiser Fallback auf `mp.*` (Pine: Zahlen → `na`,
  Strings → `""`). `squeeze_on`/`flow_rel_vol` bleiben **baked-only** (Endpoint
  lässt sie weg; die Bridge liest sie scaffolded und erhält `na`).
- **Offen:** `global_heat` (in §3 unter „gemischt“) bleibt unverdrahtet; aktuell
  wird aus dieser Gruppe nur `tone` ausgeliefert/konsumiert.
