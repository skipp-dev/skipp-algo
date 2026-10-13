{% raw %}
# Sprint-Plan C9 — Drift-Alert + Anomalie-Monitoring

**Datum:** 2026-04-26
**Owner:** Steffen Preuss
**Sprint-Größe:** 3-5 Werktage (klein, hoher Reuse-Anteil)
**Status:** Plan, noch nicht gestartet
**Voraussetzung:** C1+C8 fertig (Outcome-Stream + Live-Drift-Detector)

## Ziel

Automatisches Frühwarnsystem für Setup-Decay, Regime-Drift und Live-Anomalien. Liefert:

1. **Statistische Drift-Detection** auf Live-Outcome-Stream (Page-Hinkley, CUSUM, KS gegen Backtest-Referenz, PSI auf Feature-Verteilung)
2. **Cron-getriebene tägliche Auswertung** mit GitHub Actions (vorhandenes Pattern)
3. **Multi-Channel-Alerts** (Webhook/Slack/Discord) mit Throttling
4. **Action-Plan-Mapping**: jeder Alert-Level hat vor-definierte Response (Halt/Recalibrate/Investigate/Wait)

Ohne C9 wird Decay erst zu spät bemerkt — typische Erfahrung: "AI-Modell-Akkuratheit kann innerhalb von Tagen nach Deployment degradieren" ([Agility at Scale, März 2026](https://agility-at-scale.com/ai/generative/continuous-evaluation-and-drift-monitoring/)). C9 macht den Track-Record-Gate-Schutz nachhaltig.

## Inventur (✅ vorhanden / ❌ Greenfield)

### Cron-Infrastruktur Production-erprobt
- ✅ 23 GitHub-Actions-Workflows vorhanden in `.github/workflows/`, davon viele tägliche/rollende:
  - `g23-ab-watchdog.yml` — täglich, SPRT-basiertes A/B-Watchdog
  - `feature-importance-daily.yml`
  - `f2-promotion-gate-daily.yml`
  - `open-prep-outcome-backfill.yml`
  - `public-calibration-dashboard.yml`
  - `smc-measurement-benchmark-rolling.yml`
  - `plan-2-8-status-daily.yml`
  - `run-open-prep-daily.yml`
- ⚙️ Neue Workflow `smc-drift-monitor.yml` folgt etabliertem Cron-Pattern, kein Greenfield-Design

### Alert-Pipeline Production-erprobt
- ✅ `open_prep/alerts.py` (466 Zeilen) mit:
  - `dispatch_alerts()` `:251`
  - `_format_traderspost_payload()` `:140`, `_format_slack_payload()` `:151`, `_format_discord_payload()` `:175`, `_format_generic_payload()` `:188`
  - `_send_webhook()` `:348` mit `_NoRedirect` Handler `:384` (Security)
  - `_is_safe_webhook_url()` `:210` (SSRF-Protection)
  - `_throttle_key()` `:98`, `_is_throttled()` `:104`, `_mark_sent()` `:112`, `_prune_stale_entries()` `:118`
  - `alert_regime_change()` `:437` als bestehender Alert-Typ
- ✅ `scripts/smc_alert_notifier.py` (636 Zeilen) mit:
  - `evaluate_alerts()` `:127`
  - `_state_fingerprint()` `:367`, `load_previous_fingerprint()` `:371`, `save_fingerprint()` `:386`
  - `suppress_duplicates()` `:392`
- ✅ `scripts/smc_sprt_stop_rule.py` (334 Zeilen) — SPRT-Stoprule-Pattern für sequentielle Detection
- ✅ `scripts/g23_ab_watchdog.py` (437 Zeilen) — Watchdog-Pattern als Referenz

### Drift-Detection ❌ Greenfield
- ❌ Kein `page_hinkley`, `cusum`, `adwin`, `psi`, `kl_divergence` im Production-Code (verifiziert via grep)
- ✅ Aber: `_normal_cdf` aus `run_ab_comparison.py` und Skewness/Kurtosis aus C6 wiederverwendbar
- ✅ KS-Test infrastruktur indirekt durch C8-`compute_live_drift` (T4 in C8) — wird hier formalisiert

### Live-Outcome-Stream als Input
- ✅ Aus C8: `cache/live/incubation_<date>.jsonl` mit per-Trade-Outcome-Stream
- ✅ Aus C1: `cache/calibration/outcomes_<date>.jsonl`
- ✅ Aus C5: `cache/calibration/regime_stratified_<date>.json` (Backtest-Referenz pro Regime)

## Methoden-Foundation (4 komplementäre Detektoren)

Quelle: [Agility at Scale Drift-Monitoring (März 2026)](https://agility-at-scale.com/ai/generative/continuous-evaluation-and-drift-monitoring/) und [MetricGate Concept-Drift](https://metricgate.com/blogs/concept-drift-model-monitoring/).

| Methode | Drift-Typ | Entscheidung | Quelle |
|---|---|---|---|
| **Page-Hinkley** | Gradueller Drift, Streaming | PH(t) > 3σ·sqrt(w) | Page (1954), [OneUptime](https://oneuptime.com/blog/post/2026-01-30-concept-drift-detection/view) |
| **CUSUM** | Abrupter Drift | C⁺(t) > 5σ mit k=0.5σ | [MetricGate](https://metricgate.com/docs/concept-drift-detection/) |
| **KS-Test (windowed)** | Verteilungs-Shift | p < 0.05 + Effect-Size | [Daily Dose of DS](https://www.dailydoseofds.com/mlops-crash-course-part-16/) |
| **PSI** | Feature-Stability | <0.10 stabil, 0.10-0.25 minor, >0.25 major | [Agility at Scale](https://agility-at-scale.com/ai/generative/continuous-evaluation-and-drift-monitoring/) |

**Konsens-Logik**: Wenn ≥2 von 4 Methoden Drift signalisieren → "concerning". Wenn ≥3 → "fail" + Auto-Halt. Eine isolierte Detection allein ist nicht ausreichend (Reduktion Falsch-Alarme).

## Tasks

### T1 (Tag 1 vormittags) — Inventur-Pin + Schema-Lock ⚙️

Reverify:
- C8-Output `cache/live/incubation_<date>.jsonl` Schema (aus C8-Plan)
- C1-Output `cache/calibration/outcomes_<date>.jsonl` Schema
- C5-Output `cache/calibration/regime_stratified_<date>.json` Schema
- Bestehende Alert-Pipeline-Schema in `dispatch_alerts()` `:251`

Output: `docs/c9_drift_data_contract.md` mit Schema-Verträgen.

### T2 (Tag 1 nachmittags + Tag 2) — `open_prep/drift_detectors.py` ⚙️🧪

Greenfield-Modul mit den 4 Detektoren als Klassen mit gemeinsamem Interface:

```python
@dataclass(frozen=True)
class DriftResult:
    method: str            # "page_hinkley" | "cusum" | "ks_test" | "psi"
    is_drift: bool
    score: float           # Method-spezifisch normalisiert auf [0, ∞)
    severity: str          # "stable" | "minor" | "major" | "critical"
    reference_window: int
    detection_window: int
    p_value: float | None  # Nur für KS-Test
    extra: dict[str, Any]  # Method-spezifische Felder

class PageHinkleyDetector:
    """Page-Hinkley nach Page (1954). Gradueller Drift, Streaming."""
    def __init__(self, delta: float = 0.005, lambda_threshold_sigma_factor: float = 3.0): ...
    def update(self, value: float) -> DriftResult: ...
    def reset(self) -> None: ...

class CUSUMDetector:
    """Two-sided CUSUM. Abrupter Drift."""
    def __init__(self, k_sigma_factor: float = 0.5, h_sigma_factor: float = 5.0): ...
    def update(self, value: float, mean_ref: float, std_ref: float) -> DriftResult: ...

class KSWindowDetector:
    """Sliding-Window KS-Test gegen Reference-Distribution."""
    def __init__(self, ref_size: int = 500, window_size: int = 100, alpha: float = 0.05): ...
    def add_sample(self, value: float) -> None: ...
    def detect(self) -> DriftResult: ...

class PSIDetector:
    """Population Stability Index, quantile-binned, 10 bins default."""
    def __init__(self, n_bins: int = 10): ...
    def compute(self, ref: list[float], cur: list[float]) -> DriftResult: ...
```

Test-Pins in `tests/test_drift_detectors.py`:

**Page-Hinkley**:
- Stable Stream (200 samples normal(0.1, 0.02)) → keine Detection
- Gradueller Drift ab Sample 200 (linear+0.15 über 200 Samples) → Detection vor Sample 400
- Reset nach Detection startet sauber

**CUSUM**:
- Identische Streams → C⁺ ≈ 0
- Abrupter Shift +1σ → Detection innerhalb 10 Samples
- Negative Shifts via C⁻

**KS-Test**:
- Identische Distributionen → p > 0.5
- Mean-Shift +0.5σ → p < 0.05
- Wasserstein-Distance als Effect-Size konsistent mit KS-Statistic

**PSI**:
- Identische Distributionen → PSI ≈ 0
- Mean-Shift +0.4 + sd 1.0→1.2 (Standard-Beispiel aus [MetricGate](https://metricgate.com/blogs/concept-drift-model-monitoring/)) → PSI > 0.25
- Edge: leere Bins → eps=1e-4 Floor

### T3 (Tag 2-3) — `scripts/run_smc_drift_check.py` ⚙️🧪

Cron-Entry-Point:

```bash
python scripts/run_smc_drift_check.py \
  --live-dir cache/live/ \
  --reference cache/calibration/regime_stratified_<date>.json \
  --backtest-window-days 90 \
  --live-window-days 14 \
  --output cache/drift/drift_<date>.json
```

Workflow:
1. Lade letzten Live-Outcome-Stream
2. Lade Backtest-Referenz (Sharpe, Hit-Rate, R-Multiple-Verteilung pro Variant × Regime)
3. Pro Variant: alle 4 Detektoren auf Outcome-Stream-Metric (R-Multiple, signed PnL, Slippage)
4. Konsens-Aggregation:
   - 0 Drifts → "stable"
   - 1 Drift → "minor"
   - 2 Drifts → "concerning"
   - 3+ Drifts → "critical"
5. Output `cache/drift/drift_<date>.json`

Schema-Beispiel:

```json
{
  "version": "v1",
  "computed_at": "2026-XX-XX",
  "live_window_days": 14,
  "backtest_window_days": 90,
  "variants": [
    {
      "variant": "smc_breaker_btc",
      "regime": "RISK_ON",
      "n_live": 18,
      "metrics": {
        "r_multiple": {
          "page_hinkley": {"is_drift": false, "score": 0.31},
          "cusum": {"is_drift": false, "score": 1.4},
          "ks_test": {"is_drift": true, "score": 0.18, "p_value": 0.024},
          "psi": {"is_drift": false, "score": 0.12, "verdict": "minor"}
        }
      },
      "consensus": "minor",
      "consensus_count": 1,
      "verdict": "monitor",
      "recommended_action": "wait_more_data"
    }
  ],
  "global": {
    "total_variants": 24,
    "stable": 18,
    "minor": 4,
    "concerning": 2,
    "critical": 0
  }
}
```

### T4 (Tag 3) — Action-Plan + Alert-Routing ⚙️🧪

Action-Plan-Mapping nach [MetricGate-Empfehlung](https://metricgate.com/blogs/concept-drift-model-monitoring/) — "Drift detection without an action plan is just an expensive dashboard":

| Verdict | Action | Owner | Channel |
|---|---|---|---|
| stable | Log only | — | — |
| minor | Log + Slack-Notification | Steffen | Slack |
| concerning | Slack + Manual-Review-Flag in Dashboard | Steffen | Slack + Dashboard |
| critical | Slack + Discord + Auto-Pause-Live (über C8 Kill-Switch) | Steffen + System | Multi-Channel + System |

`scripts/dispatch_drift_alerts.py`:

```python
def route_drift_alert(result: dict[str, Any], channels: dict[str, str]) -> None:
    """
    Routet Drift-Result an passende Channels mit Throttling
    (Reuse open_prep/alerts.py Throttle-Logik).
    """
```

Reuse:
- `dispatch_alerts()` `:251` aus `open_prep/alerts.py`
- `_format_slack_payload()` `:151`, `_format_discord_payload()` `:175`
- `_throttle_key()` `:98` (vermeidet Spam bei 24h-wiederholten Alerts)
- `_is_safe_webhook_url()` `:210` (SSRF-Schutz)

Test-Pins:
- "stable"-Verdict triggert keinen Alert
- "critical" feuert auf alle 3 Channels
- Throttle: zweite Critical innerhalb 1h triggert nur 1× Discord, nicht 2×
- Auto-Pause-Hook ruft C8-Kill-Switch korrekt auf

### T5 (Tag 4 vormittags) — GitHub Actions Workflow ⚙️

`.github/workflows/smc-drift-monitor.yml` analog zu `g23-ab-watchdog.yml`:

```yaml
name: smc-drift-monitor

on:
  schedule:
    - cron: '15 6 * * *'  # täglich 06:15 UTC = 08:15 Berlin (vor Markt-Open USA)
  workflow_dispatch:

jobs:
  drift-monitor:
    runs-on: ubuntu-latest
    concurrency:
      group: smc-drift-monitor
    steps:
      - uses: actions/checkout@v4
      - name: Setup Python
        uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - name: Install
        run: pip install -r requirements.txt
      - name: Run drift check
        env:
          DRIFT_SLACK_WEBHOOK: ${{ secrets.DRIFT_SLACK_WEBHOOK }}
          DRIFT_DISCORD_WEBHOOK: ${{ secrets.DRIFT_DISCORD_WEBHOOK }}
        run: |
          python scripts/run_smc_drift_check.py \
            --live-dir cache/live/ \
            --reference cache/calibration/regime_stratified_latest.json \
            --output cache/drift/drift_$(date +%Y-%m-%d).json
          python scripts/dispatch_drift_alerts.py \
            --input cache/drift/drift_$(date +%Y-%m-%d).json
      - name: Upload drift report
        uses: actions/upload-artifact@v4
        with:
          name: smc-drift-monitor
          path: cache/drift/drift_*.json
          retention-days: 60
```

Reuse-Pattern aus `g23-ab-watchdog.yml`:
- `concurrency: group:` zum Vermeiden von Doppel-Runs
- `actions/upload-artifact@v4` für Audit-Trail
- `workflow_dispatch` für manuelle Reruns

### T6 (Tag 4 nachmittags) — Dashboard-Integration ⚙️

Erweiterung des `tab_live_incubation.py` aus C7 um Drift-Panel:

- Globale Drift-Übersicht (stable/minor/concerning/critical Counts)
- Per-Variant Drift-Score-Heatmap (4 Methoden × Variant)
- Alert-Event-Log mit Filterung nach Severity
- Action-Plan-Anzeige pro Variant

Reuse aus C7:
- `terminal_tabs/_shared.py` UI-Helpers
- Plotly-Pattern aus `tab_heatmap.py`
- `@st.cache_data(ttl="5m")`

Test-Pin: Tab rendert mit Mock-`drift_<date>.json` (24 Variants).

### T7 (Tag 4-5) — Historical-Backfill + Threshold-Tuning ⚙️🧪

Vor Live-Schaltung der Cron auf Historischen Outcome-Streams (C1-Output) replay-en, um:
- False-Positive-Rate zu kalibrieren (Ziel: <1 False-Critical/Monat)
- Threshold-Werte (`delta`, `lambda_threshold_sigma_factor`, `n_bins`) feinjustieren
- Doku in `docs/c9_threshold_tuning.md` mit Sensitivität-Plots

Akzeptanz: bei 90-Tage-Historical-Backfill mindestens 80% True-Positives bei <10% False-Positives auf bekannten Drift-Episoden.

### T8 (Tag 5) — Doku + Sprint-Close 🧪

`docs/c9_drift_monitoring_runbook.md`:
- Was ist Drift? Sudden vs Gradual nach [OneUptime](https://oneuptime.com/blog/post/2026-01-30-concept-drift-detection/view)
- Wie lese ich den Drift-Output?
- Was tun bei jedem Verdict?
- Threshold-Anpassung
- Reset-Workflow nach Recalibration (C2-Reload)

Sprint-Close-Sync in Master-Doc.

## Speed-Hebel-Anwendung

- **AI-Repo-Tool**: Detektoren-Code-Skeleton aus [OneUptime-Beispiel](https://oneuptime.com/blog/post/2026-01-30-concept-drift-detection/view) und [MetricGate-Beispiel](https://metricgate.com/blogs/concept-drift-model-monitoring/) ist kanonisch — ein 80%-Treffer-Tool kann initialen Detector-Code in <30min liefern. Test-Pins kritisch.
- **pytest-xdist**: ✅ in `requirements.txt`. 4 Detector-Klassen × ~5 Tests = 20 Tests parallel.
- **Reuse `open_prep/alerts.py`**: Throttle, Webhook-Security, Multi-Channel — alles bereits vorhanden.
- **Reuse Cron-Pattern aus `g23-ab-watchdog.yml`**: keine GitHub-Actions-Recherche nötig.
- **Reuse `_normal_cdf` aus `run_ab_comparison.py:238`**: für KS-p-Value falls scipy-frei.
- **Sequentiell zu C8**: braucht Live-Outcome-Stream — falls C8 noch nicht live, läuft C9 zunächst auf C1-Backtest-Stream zur Validation.
- **2-Iterations-Limit pro Detector**: strikt halten; jede Methode hat klare Stopkriterien.

## Risiken + Gegenmaßnahmen

| Risiko | Gegenmaßnahme |
|---|---|
| Zu viele False-Positives → Alert-Müdigkeit | T7 Historical-Backfill kalibriert Thresholds, Konsens-Logik (2-of-4) reduziert False-Alarms |
| KS-Test wird hypersensitiv bei großen Samples ([MetricGate-Hinweis](https://metricgate.com/blogs/concept-drift-model-monitoring/)) | Effect-Size-Threshold zusätzlich zu p-Value, oder adaptive Window-Size |
| Drift bei Regime-Wechsel ist erwartet (nicht echter Decay) | Pro-Regime-Stratifikation (aus C5) gibt Kontext-Layer |
| Alert-Spam bei wiederholten Critical | `_throttle_key` `:98` aus `open_prep/alerts.py`, Default 24h-Cooldown |
| Auto-Pause bei False-Critical → Geld-Verlust durch Stillstand | Critical-Verdict pausiert nur bei 3-of-4-Konsens, nicht 2-of-4 |
| Schema-Mismatch C8 vs C9 | T1 Schema-Lock + Pydantic-Validation |
| Cron-Workflow-Fail durch Secrets-Missing | Pre-Flight-Check in T5 GitHub-Actions-YAML |

## Akzeptanzkriterien

- [ ] `drift_detectors.py` mit 4 Detektor-Klassen + 5+ Test-Pins pro Klasse
- [ ] `run_smc_drift_check.py` läuft end-to-end mit Mock-Live-Stream
- [ ] `dispatch_drift_alerts.py` mit Action-Plan-Routing + Throttle-Test
- [ ] GitHub-Actions-Workflow `smc-drift-monitor.yml` täglich erfolgreich
- [ ] Dashboard-Drift-Panel rendert mit Mock-Daten
- [ ] Historical-Backfill: ≥80% True-Positive bei <10% False-Positive
- [ ] Runbook `docs/c9_drift_monitoring_runbook.md`
- [ ] Auto-Pause-Hook für critical-Verdict mit C8-Kill-Switch verbunden

## Out-of-Scope

- Per-Trade Echtzeit-Drift (Streaming WebSocket) — Daily-Cron reicht für 30-Trade/Monat-Volumen
- ADWIN als zusätzlicher Detektor (Stretch, nicht in C9 Scope — kann später)
- ML-basierte Anomalie-Detection (Isolation Forest, Autoencoder) — späterer Sprint
- Multi-Strategie-Korrelations-Drift — Out-of-Scope, kommt mit Portfolio-Phase

## Quellen

- [OneUptime — Concept-Drift-Detection (Januar 2026)](https://oneuptime.com/blog/post/2026-01-30-concept-drift-detection/view) — Page-Hinkley + KS-Test Code-Skelette
- [MetricGate — Concept-Drift-Monitoring (April 2026)](https://metricgate.com/blogs/concept-drift-model-monitoring/) — PSI-Thresholds 0.10/0.25, Page-Hinkley-Streaming
- [MetricGate — Concept-Drift-Detection-Calculator](https://metricgate.com/docs/concept-drift-detection/) — Konsens-Logik mit 4 Methoden
- [Daily Dose of DS — Drift-Monitoring (November 2025)](https://www.dailydoseofds.com/mlops-crash-course-part-16/) — Statistik-Übersicht
- [Agility at Scale — AI-Drift-Monitoring (März 2026)](https://agility-at-scale.com/ai/generative/continuous-evaluation-and-drift-monitoring/) — Method-Comparison-Tabelle
- [AI Infrastructure Alliance — 8 Drift-Methoden](https://ai-infrastructure.org/8-concept-drift-detection-methods/) — Background CUSUM/PH
- Page (1954) — Original Page-Hinkley-Test (referenziert in allen Quellen)
- Bifet & Gavalda (2007) — ADWIN (Stretch, not in scope)
{% endraw %}
