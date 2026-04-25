# Sprint-Plan C7 — Dashboard-Frontend (Track-Record-Sichtbarkeit)

**Datum:** 2026-04-26
**Owner:** Steffen Preuss
**Sprint-Größe:** 8-12 Werktage (mit Speed-Stack) / 14-18 (ohne)
**Status:** Plan, noch nicht gestartet
**Voraussetzung:** C2 + C3 + C4 + C5 + C6 fertig (zumindest Daten-Schemas stehen)

## Ziel

Operative Sichtbarkeit aller Track-Record-Metriken aus C1-C6 in einem zusammenhängenden Dashboard. Liefert:

1. **Calibration-Report-Page** — Per-Setup × Per-Symbol × Per-Regime Tabelle mit Hit-Rate, R-Multiple, Sharpe, Bootstrap-95%-CI, Permutation-p, BH-FDR-Status, PSR(SR\*=0), MinTRL.
2. **Track-Record-Gate-Page** — Ampel-Widget pro SMC-Variante: rot/gelb/grün gegen die 9 Mindestanforderungen aus dem Master-Doc.
3. **Walk-Forward-Stabilität-Page** — Fold-by-Fold Sharpe-Verlauf mit WFE>50%-Marker (aus C2).
4. **Live-vs-Backtest-Page** (Stub für C8) — Slot für spätere Live-Inkubations-Daten, Drift-Indikatoren.
5. **Methodology-Drawer** — Klickbare Doku-Links zu C2-C6-Sprints und den Bailey-Lopez-de-Prado-Quellen.

Track-Record-Gate-Sichtbarkeit ist der primäre KPI: "Habe ich etwas zu verkaufen — ja/nein/jetzt-noch-nicht-genug-Daten" muss in 3 Sekunden ablesbar sein, ohne Code zu öffnen.

## Inventur (✅ vorhanden / ❌ Greenfield)

### Streamlit-Stack vorhanden
- ✅ `streamlit>=1.54.0` in `requirements.txt` ([Streamlit Caching-Doku](https://docs.kanaries.net/topics/Streamlit/streamlit-caching))
- ✅ `plotly>=5.18.0` in `requirements.txt`
- ✅ Hauptapp `streamlit_terminal.py` mit 5200 Zeilen (Top-Level News-Dashboard)
- ✅ Modulare Sub-Apps:
  - `streamlit_terminal_pure.py`
  - `streamlit_terminal_runtime.py`
  - `streamlit_terminal_alerts.py`
  - `streamlit_terminal_config.py`
  - `streamlit_databento_volatility_screener.py`
  - `streamlit_smc_micro_base_generator.py`
- ✅ Tab-Architektur in `terminal_tabs/`: 18 Tabs (`tab_alerts.py`, `tab_movers.py`, `tab_heatmap.py`, ...) mit klarem Pattern (`__init__.py`, `_shared.py`)
- ✅ Plotly-Verwendung in `streamlit_terminal.py`, `terminal_tabs/tab_heatmap.py`, `scripts/run_smc_measurement_benchmark.py`

### FastAPI-Stack vorhanden
- ✅ `fastapi>=0.115.0` in `requirements.txt`
- ✅ `smc_tv_bridge/smc_api.py` mit 371 Zeilen, 3 Endpoints: `/smc_snapshot`, `/smc_tv`, `/health`
- ✅ Mock-API `smc_tv_bridge/smc_mock_api.py` für Entwicklung

### SMC-Tab fehlt
- ❌ Keine `tab_smc.py` / `tab_calibration.py` / `tab_track_record.py` im Verzeichnis `terminal_tabs/` — `grep -l "smc\|setup\|outcome\|sharpe\|hit_rate" terminal_tabs/` liefert keine Treffer
- ❌ Keine `streamlit_track_record.py` als eigenständige Seite

### Daten-Quellen für Dashboard (aus Sprint-Reihe)
- ✅ `cache/calibration/*.json` — Format kommt aus C1/C2/C3 (zone_priority_calibration und walk-forward Outputs)
- ⚙️ `cache/calibration/psr_mintrl_<date>.json` — wird von C6 erzeugt
- ⚙️ `cache/calibration/regime_stratified_<date>.json` — wird von C5 erzeugt
- ⚙️ `cache/calibration/walk_forward_<date>.json` — wird von C2 erzeugt

### Public-Report-Pipeline (Reuse)
- ✅ `scripts/emit_public_calibration_report.py:174` mit `build_public_report()` und `:341` mit `report = build_public_report(...)` — bestehender Pfad für aufbereitete Calibration-Daten
- ✅ `scripts/run_smc_measurement_benchmark.py` mit Plotly-Charts als Referenz-Pattern

## Architektur-Entscheidung

**Empfehlung: Single-Page Streamlit-Multi-Tab innerhalb `streamlit_terminal.py`**, parallel zu bestehenden News-Tabs.

Begründung:
- Reuse Login/Layout/Caching-Stack (`@st.cache_data`, `@st.cache_resource` — siehe [Streamlit Caching Docs](https://docs.kanaries.net/topics/Streamlit/streamlit-caching))
- Keine zweite Domain/Port-Konfiguration nötig
- Tab-Pattern in `terminal_tabs/` etabliert — neue Tabs kosten ~150-300 Zeilen pro Stück
- Streamlit-Stateless-Rerun-Modell ist akzeptabel, weil Dashboard-Daten aus statischen JSON-Files kommen (keine Live-Order-Routing)

**Alternativ erwogen**: separate Streamlit-App + FastAPI-Backend ([Towards Data Science Pattern](https://towardsdatascience.com/fastapi-and-streamlit-the-python-duo-you-must-know-about-72825def1243/)). Verworfen für C7, weil Daten-Volumen klein (<10MB JSON), keine Multi-User-Concurrency-Anforderung im aktuellen Stadium. Einlass-Hook für Future: smc_api kann später Live-Daten servieren (siehe C8).

## Tasks

### T1 (Tag 1) — Inventur-Pin + Daten-Schema-Lock ⚙️🧪

Reverify:
- C1/C2/C3/C5/C6 Output-JSON-Schemas (aus Sprint-Plänen sammeln)
- Reuse `scripts/emit_public_calibration_report.build_public_report()` als zentraler Aggregator? Entscheidung: **ja** — eine `build_dashboard_payload()`-Funktion, die alle Sprint-Outputs zusammenführt
- Dependencies-Check: `streamlit>=1.54.0`, `plotly>=5.18.0`, ggf. `pydantic` für Schema-Validation

Output: `docs/c7_dashboard_data_contract.md` mit 1-Pager über JSON-Schema-Verträge zwischen Sprints und Dashboard. Als Pull-Request nur Doku.

### T2 (Tag 2-3) — Aggregator-Service `build_dashboard_payload()` ⚙️🧪

Neues Modul `scripts/build_dashboard_payload.py` (oder als Funktion in `emit_public_calibration_report.py`):

```python
def build_dashboard_payload(
    cache_dir: Path = Path("cache/calibration"),
    date: str | None = None,  # None = latest
) -> dict[str, Any]:
    """
    Sammelt:
      - walk_forward_<date>.json     (aus C2)
      - bootstrap_ci_<date>.json     (aus C3)
      - permutation_<date>.json      (aus C4)
      - regime_stratified_<date>.json(aus C5)
      - psr_mintrl_<date>.json       (aus C6)
      - outcomes_<date>.jsonl        (aus C1)
    Joined per (setup_type, symbol_group) + Track-Record-Gate-Status.
    """
```

Output-Schema in `cache/dashboard/payload_<date>.json`:

```json
{
  "version": "v1",
  "computed_at": "2026-XX-XX",
  "variants": [
    {
      "setup_type": "smc_breaker",
      "symbol_group": "btc",
      "regime": "RISK_ON",
      "n_trades": 142,
      "hit_rate": 0.58,
      "sharpe": 0.93,
      "bootstrap_ci_low": 0.42,
      "bootstrap_ci_high": 1.31,
      "perm_p": 0.018,
      "bh_fdr_pass": true,
      "psr_at_0": 0.91,
      "min_trl_at_0": 168,
      "wfe": 0.62,
      "max_dd": 0.094,
      "gate_status": "amber",
      "gate_failures": ["psr_at_0_below_0.95"]
    }
  ],
  "global": {
    "total_variants": 24,
    "gate_green": 3,
    "gate_amber": 8,
    "gate_red": 13
  }
}
```

Test-Pins in `tests/test_build_dashboard_payload.py`:
- Mock JSON-Dateien einlesen, korrektes Joining
- Edge: fehlendes File → Fallback `null` mit Warning
- Edge: Schema-Mismatch zwischen Sprint-Outputs → klarer Fehler

### T3 (Tag 3-5) — Tab `tab_track_record.py` ⚙️🧪

Neues Modul `terminal_tabs/tab_track_record.py` parallel zu bestehenden Tabs.

Sektionen:
1. **Globale Ampel** (oben, prominent): Anzahl Variants × Gate-Status (rot/gelb/grün) als `st.metric` + Plotly-Donut.
2. **Variant-Tabelle** (`st.dataframe`): Columns Setup × Symbol × Regime × n × HR × Sharpe × Bootstrap-CI × Perm-p × FDR × PSR × MinTRL × WFE × DD × Gate. Sortierbar, filterbar (Streamlit native).
3. **Detail-Drawer** beim Klick: Single-Variant Plotly-Charts:
   - Bootstrap-Verteilung des Sharpe (Histogramm + 95%-CI-Linie)
   - Walk-Forward Fold-by-Fold Sharpe (Bar-Chart)
   - PSR-Sensitivität: SR\* vs PSR-Kurve
4. **Gate-Failure-Liste**: pro roter Variant, welche Mindestanforderungen verletzt sind, mit Link zu Sprint-Doku.

Reuse aus Bestand:
- ⚙️ `terminal_tabs/_shared.py` für common UI-Helpers
- ⚙️ Plotly-Pattern aus `terminal_tabs/tab_heatmap.py`
- ⚙️ `@st.cache_data(ttl=300)` für `build_dashboard_payload()`-Output (siehe [Streamlit Caching](https://docs.kanaries.net/topics/Streamlit/streamlit-caching) — TTL=5min weil JSON-Files nightly geupdated)

Test-Pins (Streamlit AppTest):
- Smoke: Tab rendert ohne Exception bei leerem Payload
- Smoke: Tab rendert mit Mock-Payload (3 Variants)
- Gate-Status-Badge zeigt korrekte Farbe basierend auf `gate_status`-Feld

### T4 (Tag 5-6) — Tab `tab_calibration_detail.py` ⚙️🧪

Tieferer Drill-Down pro Variant. Sektionen:
1. **Walk-Forward-Stabilität-Tab**: Fold-Verlauf, WFE-Marker, Anchored vs Rolling-CV-Modus.
2. **Bootstrap-Tab**: Studentized stationary block bootstrap-Verteilungen für HR, R-Multiple, Sharpe.
3. **Permutation-Tab**: Empirische Null-Verteilung mit observed-Statistik markiert.
4. **Regime-Tab**: Regime-stratifizierte Tabelle mit Cross-Regime-Konsistenz-Plot.
5. **PSR/MinTRL-Tab**: PSR-Kurve über SR\*, MinTRL-Bedarf-Display.

Reuse: Charts aus `scripts/run_smc_measurement_benchmark.py` (Plotly-Pattern bereits etabliert).

### T5 (Tag 6-7) — Methodology-Drawer + Source-Links ⚙️

Sticky-Sidebar `with st.sidebar:` mit:
- Links zu Sprint-Plänen `docs/SPRINT_PLAN_C2-C6_*.md` (im Repo)
- Quellen: [Bailey-Lopez de Prado (2012)](http://boston.qwafafew.org/wp-content/uploads/sites/4/2017/01/Lopez_de_Prado_Sharpe.pdf), [Bailey-Lopez de Prado (2014)](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf), [Politis-Romano stationary bootstrap](https://en.wikipedia.org/wiki/Bootstrapping_(statistics))
- Threshold-Werte: alle Track-Record-Gate-Mindestanforderungen aus Master-Doc
- Last-Computed-Timestamp + Daten-Frische-Indikator

Test: Smoke-Render, Link-Validität-Check.

### T6 (Tag 7-8) — Live-vs-Backtest-Stub für C8 ⚙️

Tab `tab_live_incubation.py` als Stub mit:
- Placeholder-Tabelle "Variant × Backtest-Sharpe × Live-Sharpe × Drift-pp × Live-Trades"
- Hinweis-Box: "Live-Inkubation startet in Sprint C8. Aktuell keine Live-Daten."
- Schema-Vorbereitung für C8-Output (`cache/live/incubation_<date>.json`)

Sinn: API stabilisiert, C8-Sprint kann später nur Daten füllen, kein UI-Refactoring.

### T7 (Tag 8-9) — Performance-Härtung ⚙️🧪

[Streamlit Caching-Best-Practices](https://docs.kanaries.net/topics/Streamlit/streamlit-caching) anwenden:
- `@st.cache_data(ttl="5m")` auf `build_dashboard_payload()` und alle JSON-File-Reads
- `@st.cache_resource` für ggf. ML-Models (nicht im Scope, aber Pattern bereit)
- Lazy-Tab-Loading: nur sichtbare Tabs rendern (Streamlit nativ via `st.tabs`)
- Parquet statt JSON für große Outcome-Streams (>10MB) — siehe [SO-Antwort](https://stackoverflow.com/questions/79586550/how-can-i-optimize-a-streamlit-dashboard-for-large-csv-files-to-improve-load-tim)

Smoke-Performance-Test in `tests/test_dashboard_smoke.py`:
- Initial-Render <3s mit Mock-Payload (24 Variants)
- Tab-Switch <500ms

### T8 (Tag 9-10) — Auth + Deploy-Stub ⚙️

Reuse vorhandener Auth-Pattern aus `streamlit_terminal.py` (falls vorhanden — sonst nur internes Hosting).

Deploy-Optionen (Entscheidung später, nicht in C7):
- **Option A**: Lokal über `streamlit run` — einfachster Pfad
- **Option B**: Container Apps (siehe Cloud-Migration-Doku) — für späteren Multi-User-Zugang
- **Option C**: Streamlit Cloud Free — schnellster Public-Demo-Pfad

C7 liefert nur Lokal-Run + Container-Compatibility. Multi-User-Auth ist Out-of-Scope.

### T9 (Tag 10-12) — Doku + Sprint-Close 🧪

`docs/c7_dashboard_user_guide.md` mit:
- Screenshots aller Tabs
- Lese-Anleitung "Wie interpretiere ich rote vs gelbe Variants"
- Daten-Refresh-Workflow (manuell vs nightly Cron)
- Bekannte Limitationen + Out-of-Scope für C8/C9

Sprint-Close-Sync in Master-Doc.

## Speed-Hebel-Anwendung

- **AI-Repo-Tool**: Streamlit-Tab-Pattern hochrepetitiv — Cursor/Claude Code 80%-Treffer realistisch. T3+T4 sind die größten Beschleunigungs-Kandidaten.
- **pytest-xdist**: ✅ schon in `requirements.txt`. Streamlit AppTest-Suites parallelisierbar.
- **Reuse `terminal_tabs/_shared.py`**: kein Doppeln von UI-Helpers.
- **Reuse `tab_heatmap.py`-Plotly-Pattern**: Charts in T3/T4 starten von etabliertem Code.
- **Reuse `emit_public_calibration_report.build_public_report()`**: Aggregator nicht greenfield.
- **`@st.cache_data` mit TTL**: pflicht ab Tag 1, nicht erst in T7 nachholen — siehe [Caching-Doku](https://docs.kanaries.net/topics/Streamlit/streamlit-caching).
- **2-Iterations-Limit pro Tab**: strikt halten; UX-Politur wird auf Bedarfsbasis nach Sprint-Close gemacht.

## Risiken + Gegenmaßnahmen

| Risiko | Gegenmaßnahme |
|---|---|
| Sprint-Output-Schemas in C2-C6 ändern sich nach Plan | T1 macht Schema-Lock + Pydantic-Validation |
| Streamlit-Rerun macht Dashboard träge bei großen Payloads | `@st.cache_data` Pflicht, Parquet statt JSON ab >10MB |
| Multi-User-Anforderung kommt später | Tab-Architektur entkoppelt Daten-Aggregator von UI — späterer FastAPI-Übergang machbar |
| Auth muss kommen | Out-of-Scope für C7, in C8 oder Cloud-Migration |
| Plotly-Charts-Vielfalt explodiert | Konsolidieren in `terminal_tabs/_shared_charts.py` ab Task 2 |

## Akzeptanzkriterien

- [ ] `build_dashboard_payload()` mit 4+ Test-Pins
- [ ] `tab_track_record.py` rendert mit Mock-Payload, Ampel zeigt korrekte Status
- [ ] `tab_calibration_detail.py` mit allen 5 Sub-Tabs (Walk-Forward, Bootstrap, Permutation, Regime, PSR)
- [ ] `tab_live_incubation.py` Stub vorhanden für C8
- [ ] Methodology-Drawer mit allen Sprint-Plan-Links und Bailey-Lopez-de-Prado-Quellen
- [ ] Smoke-Performance-Test: Initial-Render <3s, Tab-Switch <500ms
- [ ] Doku `docs/c7_dashboard_user_guide.md` mit Screenshots
- [ ] Track-Record-Gate-Status in 3 Sekunden ohne Code-Öffnen ablesbar

## Out-of-Scope

- Multi-User-Auth + Login (kommt mit Cloud-Migration oder C8)
- Public-Demo-Deploy
- Mobile-Layout (Desktop-First)
- WebSocket-Live-Updates (in C8 oder C9)
- Customer-Facing Marketing-Page

## Quellen

- [Streamlit Caching `st.cache_data` vs `st.cache_resource`](https://docs.kanaries.net/topics/Streamlit/streamlit-caching)
- [Streamlit-Multipage-Pattern](https://docs.streamlit.io/get-started/tutorials/create-a-multipage-app)
- [Reflex Streamlit-vs-Dash-Vergleich (April 2026)](https://reflex.dev/blog/streamlit-vs-dash-python-dashboards/) — Background zu Rerun-Modell
- [FastAPI+Streamlit-Pattern, Towards Data Science](https://towardsdatascience.com/fastapi-and-streamlit-the-python-duo-you-must-know-about-72825def1243/) — falls Stack später entkoppelt wird
- [Stack Overflow Streamlit-Performance-Optimization](https://stackoverflow.com/questions/79586550/how-can-i-optimize-a-streamlit-dashboard-for-large-csv-files-to-improve-load-tim) — Parquet/Caching-Tipps
