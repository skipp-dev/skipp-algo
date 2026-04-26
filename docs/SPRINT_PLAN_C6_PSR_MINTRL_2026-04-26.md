# Sprint-Plan C6 — Probabilistic Sharpe Ratio + Minimum Track Record Length

**Datum:** 2026-04-26
**Owner:** Steffen Preuss
**Sprint-Größe:** 3-5 Werktage (klein, primär Greenfield)
**Status:** Plan, noch nicht gestartet

## Ziel

Statistische Härtung der Sharpe-Ratio gegen Skewness/Kurtosis-Bias und Multiple-Testing-Inflation. Liefert zwei Größen für das Track-Record-Gate:

1. **PSR(SR\*)** — Wahrscheinlichkeit, dass der wahre Sharpe-Ratio den Schwellenwert SR\* (z.B. 0 oder 1.0) übertrifft, korrigiert für Schiefe und Wölbung der Returns. Aus [Bailey & Lopez de Prado (2012)](http://boston.qwafafew.org/wp-content/uploads/sites/4/2017/01/Lopez_de_Prado_Sharpe.pdf).
2. **MinTRL** — Minimale Anzahl Returns-Beobachtungen, ab der ein beobachteter Sharpe-Ratio statistisch unterscheidbar von SR\* mit Konfidenz (1-α) wird. Dieselbe Quelle.

Optionaler Stretch: **Deflated Sharpe Ratio (DSR)** als Multiple-Testing-Korrektur über N Trials, [Bailey & Lopez de Prado (2014)](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf).

Track-Record-Gate-Anforderung: PSR(SR\*=0) ≥ 0.95 für mindestens eine SMC-Variante, MinTRL ≤ verfügbare OOS-Länge.

## Inventur (✅ vorhanden / ❌ Greenfield)

❌ Keine `probabilistic_sharpe`, `min_trl`, `mintrl`, `deflated` im Production-Code (nur Doku-Mentions in Reviews) — verifiziert via `grep -rni "probabilistic_sharpe|min_trl|mintrl|deflated" --include="*.py"` ohne Treffer in `open_prep/`, `smc_core/`, `scripts/`.

❌ Keine Skewness/Kurtosis-Helfer in Production-Code — `grep -rni "skew|kurtosis" --include="*.py"` zeigt nur Kontext-Strings, keine Statistik-Funktionen.

❌ Keine `def .*sharpe` Funktion im Repo — Sharpe wird in C2 (Walk-Forward) erstmals gebaut.

✅ `_normal_cdf` in [`scripts/run_ab_comparison.py:238`](https://github.com/skippALGO/skipp-algo/blob/main/scripts/run_ab_comparison.py) — pure-stdlib `math.erf`-basiert, kann für PSR-Z-Score wiederverwendet werden, vermeidet scipy-Hardabhängigkeit. Test-Pin in [`tests/test_normal_cdf_accuracy_pin.py`](https://github.com/skippALGO1/skipp-algo) sichert Genauigkeit auf 1e-9.

✅ `benjamini_hochberg()` in `scripts/run_ab_comparison.py:181` — wird von DSR-Stretch nicht direkt benötigt, aber konzeptionell verwandt (beides Multiple-Testing).

✅ `arch>=7.2.0` in `requirements.txt` — `arch` enthält stationary bootstrap (siehe C3), wird hier nicht direkt benötigt.

⚙️ Reuse aus C2: `compute_sharpe(daily_returns)` aus dem C2-Sprint liefert die rohe SR — C6 baut darauf auf.

⚙️ Reuse aus C3: Bootstrap-Verteilung der täglichen Returns liefert empirische CIs für Skew/Kurtosis als Cross-Check zu Plug-in-Schätzern.

## Methoden-Foundation

### PSR(SR\*) — Bailey-Lopez de Prado (2012)

PSR-Statistik:

```
PSR(SR*) = Φ( (SR_hat - SR*) · sqrt(n - 1) / sqrt(1 - γ₃·SR_hat + (γ₄ - 1)/4 · SR_hat²) )
```

mit:
- `SR_hat` — beobachteter (in-sample) Sharpe-Ratio (täglich oder annualisiert, konsistent verwenden)
- `SR*` — Vergleichs-Sharpe (Threshold; üblich 0 für "besser als keine Strategie", oder 1.0 für Track-Record-Gate)
- `n` — Anzahl Returns-Beobachtungen
- `γ₃` — Skewness der Returns (Plug-in-Schätzer)
- `γ₄` — Kurtosis der Returns (Plug-in-Schätzer; nicht Excess-Kurtosis)
- `Φ` — Standard-Normal-CDF

Quelle: [Lopez de Prado QWAFAFEW](http://boston.qwafafew.org/wp-content/uploads/sites/4/2017/01/Lopez_de_Prado_Sharpe.pdf), Gleichung (1).

### MinTRL — Bailey-Lopez de Prado (2012)

```
MinTRL = 1 + (1 - γ₃·SR_hat + (γ₄ - 1)/4 · SR_hat²) · (Z_α / (SR_hat - SR*))²
```

Beispiele aus [Wikipedia/Deflated Sharpe](https://en.wikipedia.org/wiki/Deflated_Sharpe_ratio): Bei SR\_hat=0.95 annualisiert, SR\*=0, α=0.05 sind ~3 Jahre tägliche Returns nötig, um H0:SR=0 mit 95% Konfidenz zu verwerfen. Bei SR\_hat=2.0, SR\*=1.0 reichen ~2.73 Jahre.

Praktisches Daily-Frequenz-Default: `Z_α = 1.645` für α=0.05 einseitig.

### Deflated Sharpe (DSR) — Stretch-Goal

```
DSR(SR_hat) = PSR(SR_0)  mit  SR_0 = E[max{SR_n}] über N Trials
```

`E[max{SR_n}]` aus Extremwert-Theorie unter H0:SR=0:
```
E[max{SR_n}] ≈ sqrt(V[SR]) · ((1-γ)·Φ⁻¹(1 - 1/N) + γ·Φ⁻¹(1 - 1/(N·e)))
```
mit γ ≈ 0.5772 (Euler-Mascheroni). Quelle: [Bailey-Lopez de Prado (2014)](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf).

Trade-off DSR: Erhöht Härte stark, braucht aber realistische Schätzung der Anzahl getesteter Strategien N — bei SMC-Hyperparameter-Sweeps schnell N=10²-10³, was SR\* substantiell verschiebt.

## Tasks

### T1 (Tag 1 vormittags) — Inventur-Pin + scipy-Verfügbarkeit ⚙️

Prüfen, ob `scipy.stats.norm.ppf` verfügbar ist (für Z\_α). Falls nicht in `requirements.txt`: pures stdlib via Inverse-Erf-Approximation (Beasley-Springer-Moro-Algorithmus) oder per `_normal_cdf` + Newton-Iteration. Default-Empfehlung: stdlib bleiben, wie bei `_normal_cdf` — vermeidet weitere Hard-Deps.

Output: 1-Pager `docs/c6_inventory.md` mit Funden + Entscheidung "stdlib vs scipy".

### T2 (Tag 1 nachmittags) — `compute_skew_kurtosis()` ⚙️🧪

Neues Modul `open_prep/stats_helpers.py` (oder Erweiterung eines bestehenden). Funktion:

```python
def compute_skew_kurtosis(returns: list[float]) -> tuple[float, float]:
    """
    Plug-in (biased) skewness und kurtosis (NICHT Excess-Kurtosis).
    Konsistent mit Bailey-Lopez de Prado PSR-Formel.
    """
```

Test-Pins in `tests/test_stats_helpers.py`:
- Normal-Verteilte Samples (n=10000): skew ≈ 0, kurtosis ≈ 3 (±0.1)
- Bekannte schiefe Verteilung (z.B. Lognormal): skew > 0
- Empty / Single-Element: handled mit Sentinel oder ValueError

### T3 (Tag 2) — `probabilistic_sharpe(returns, sr_star, sharpe_hat=None)` ⚙️🧪

Neue Funktion in `open_prep/stats_helpers.py`:

```python
def probabilistic_sharpe(
    returns: list[float],
    sr_star: float = 0.0,
    sharpe_hat: float | None = None,
    annualize: bool = False,
    periods_per_year: int = 252,
) -> dict[str, float]:
    """
    PSR(SR*) nach Bailey-Lopez de Prado (2012).
    Returns:
        {
            "psr": p in [0,1],
            "sharpe_hat": SR_hat,
            "skew": γ₃,
            "kurtosis": γ₄,
            "n": int,
            "sr_star": SR*
        }
    Halbiert Funktion für Daily-Returns-Pfad und Trade-PnL-Pfad
    (R-Multiples mit Skalierung 1/sqrt(trades_per_year)).
    """
```

Internals:
1. Sharpe-Berechnung delegiert an C2 oder lokal: `mean(r) / std(r, ddof=1)`
2. `compute_skew_kurtosis(returns)`
3. Z-Score nach PSR-Formel oben
4. `psr = _normal_cdf(z)` aus `run_ab_comparison.py` (zentralisieren oder duplizieren — Empfehlung: in `open_prep/stats_helpers.py` reimplementieren mit `math.erf`, `_normal_cdf`-Test-Pin in C6 erweitern)

Test-Pins:
- Bekannter Bailey-Beispiel-Vektor: PSR(SR\*=0) für SR\_hat=0.95, n=750, normalverteilt → ≈ 0.95
- Symmetrie: PSR(SR\*=SR\_hat) = 0.5
- Edge: SR\_hat = SR\* mit n=2 → numerisch stabil
- Negative-Skew-Penalty: PSR sinkt wenn γ₃ negativer wird (bei festem SR\_hat)

### T4 (Tag 3) — `min_trl(sr_hat, sr_star, skew, kurtosis, alpha=0.05)` ⚙️🧪

Neue Funktion in `open_prep/stats_helpers.py`:

```python
def min_trl(
    sr_hat: float,
    sr_star: float = 0.0,
    skew: float = 0.0,
    kurtosis: float = 3.0,
    alpha: float = 0.05,
) -> int:
    """
    Minimum Track Record Length nach Bailey-Lopez de Prado (2012).
    Returns: int (min Beobachtungen). ceil() angewandt.
    """
```

Test-Pins:
- Wikipedia-Replikation: SR\_hat=0.95, SR\*=0, skew=0, kurt=3, α=0.05 → ≈ 750 (3 Jahre täglich)
- SR\_hat=2.0, SR\*=1.0, skew=0, kurt=3, α=0.05 → ≈ 690 (~2.73 Jahre)
- Edge: SR\_hat ≤ SR\* → ValueError oder math.inf-Sentinel
- Skew-Sensitivität: negative skew erhöht MinTRL (intuitiv)

### T5 (Tag 4 vormittags) — Integration in Calibration-Workflow ⚙️

Anhängen an `scripts/smc_zone_priority_calibration.py`-Output (oder neuer Wrapper `scripts/smc_psr_mintrl_report.py`):

Pro SMC-Variante / Symbol-Gruppe:
1. Daily-Returns aus Outcome-Stream (C1 + C2 vorhanden)
2. PSR(SR\*=0), PSR(SR\*=1.0), PSR(SR\*=SR\_threshold)
3. MinTRL für SR\*=0 und SR\*=1.0
4. Tabelle: Symbol-Gruppe × {SR_hat, PSR, MinTRL, n, n/MinTRL-Ratio}

Output-Schema in `cache/calibration/psr_mintrl_<date>.json`:

```json
{
  "version": "v1",
  "computed_at": "2026-XX-XX",
  "method": "bailey_lopez_de_prado_2012",
  "alpha": 0.05,
  "results": [
    {
      "variant": "smc_v3_btc",
      "n": 142,
      "sr_hat": 0.93,
      "skew": -0.21,
      "kurtosis": 4.12,
      "psr_at_0": 0.91,
      "psr_at_1": 0.34,
      "min_trl_at_0": 168,
      "min_trl_at_1": 612,
      "gate_pass": false,
      "gate_reason": "psr_at_0 < 0.95"
    }
  ]
}
```

### T6 (Tag 4 nachmittags) — Track-Record-Gate-Verdrahtung ⚙️

Erweitere Gate-Schwelle in `cloud_migration_review_and_onboarding`-Doku-Tabelle (zentral):

| Metrik | Mindestwert | Liefernder Sprint |
|---|---|---|
| **PSR(SR\*=0)** | **≥ 0.95** | **C6** |
| **MinTRL(SR\*=0)** | **≤ verfügbare n** | **C6** |
| Optional PSR(SR\*=1.0) | ≥ 0.50 (Erwartungswert "wahrer SR > 1.0") | C6 |

Code-Hook: `gate_pass`-Flag im Output (T5) wird in C7 (Dashboard) angezeigt.

### T7 (Tag 5) — Stretch-Goal DSR ⚠

**Optional, nur wenn T1-T6 in 3 Tagen fertig.**

`deflated_sharpe(returns, num_trials, sr_hat=None, ...)`:
- Schätzung von `E[max{SR_n}]` mit Extremwert-Approximation
- Approximation V[SR] aus Bailey-Lopez de Prado, Gleichung (10)
- Test-Pin: bei N=1 muss DSR ≈ PSR(SR\*=0) sein
- Trade-off-Doku: bei großem N (Sweep) steigt SR\* stark → DSR sinkt; explizit dokumentieren, dass `num_trials` ehrlich anzugeben ist (Pre-Registry, siehe C4)

### T8 (Tag 5 nachmittags) — Doku + Sprint-Close 🧪

`docs/psr_mintrl_methodology.md` mit Formeln, Test-Erwartungen, Beispiel-Plot SR vs PSR. Sprint-Close-Sync in `CLOUD_MIGRATION_REVIEW_AND_ONBOARDING_2026-04-25.md` Tabelle.

## Speed-Hebel-Anwendung

- **AI-Repo-Tool:** PSR/MinTRL-Formeln sind kanonisch publiziert — ein 80%-Treffer-Tool kann initialen Skeleton in <30min liefern. Test-Pins sind kritisch.
- **pytest-xdist:** ✅ schon in `requirements.txt` — neue Tests laufen parallel.
- **Reuse `_normal_cdf`:** vermeidet scipy-Hardabhängigkeit, hält Footprint klein.
- **Reuse C2 Sharpe-Funktion:** keine Doppelung.
- **Sequentiell zu C2/C3:** C6 braucht C2-Sharpe und C3-Bootstrap-Konfidenzen — wenn C2/C3 nicht fertig, erst dort einsteigen.
- **Inventur Tag 1:** schon erledigt im Plan-Schritt — T1 nur Reverify.
- **2-Iterations-Limit pro Task:** strikt halten; bei numerischen Edge-Cases nicht in Tiefe gehen, lieber `pytest.mark.xfail` setzen.

## Risiken + Gegenmaßnahmen

| Risiko | Gegenmaßnahme |
|---|---|
| Daily-Returns nicht verfügbar weil OOS-Trades sparse | Fallback: PSR auf Per-Trade-R-Multiples mit `periods_per_year = trades_per_year` |
| Numerische Instabilität bei n<30 | T2-Edge-Case: ValueError + Warning |
| Skew/Kurt-Schätzer auf kleinem n hoch-varianten | Cross-Check mit Bootstrap-CI aus C3 |
| MinTRL > verfügbare Daten | Klar als "Track-Record nicht ausreichend" reporten, kein silentes Pass |
| DSR-num_trials-Inflation durch ehrliche Sweep-Zählung | Pre-Registry der Trials in C4 (Permutation) — selbe Disziplin |

## Akzeptanzkriterien

- [ ] `compute_skew_kurtosis` mit 4+ Test-Pins
- [ ] `probabilistic_sharpe` mit 4+ Test-Pins, inkl. Bailey-Beispiel-Replikation
- [ ] `min_trl` mit Wikipedia-Beispiel-Replikation auf ±5%
- [ ] Calibration-Workflow-Integration: PSR/MinTRL in Output-JSON pro Variante
- [ ] Track-Record-Gate aktualisiert: PSR(SR\*=0) ≥ 0.95 als blocker
- [ ] Dokumentation `docs/psr_mintrl_methodology.md` mit Formeln + Quellen
- [ ] Stretch DSR optional, nur wenn Sprint-Budget erlaubt

## Out-of-Scope

- DSR-Implementation, falls Stretch-Bedingung nicht erfüllt
- Annualization-Konvention außerhalb 252 — Daily-Default reicht
- Per-Strategy vs Per-Symbol-Aggregation — entschieden in C7 (Dashboard)

## Quellen

- Bailey & Lopez de Prado (2012), "The Sharpe Ratio Efficient Frontier" via [QWAFAFEW Boston](http://boston.qwafafew.org/wp-content/uploads/sites/4/2017/01/Lopez_de_Prado_Sharpe.pdf)
- Bailey & Lopez de Prado (2014), "The Deflated Sharpe Ratio" via [davidhbailey.com](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf)
- [Wikipedia — Deflated Sharpe ratio](https://en.wikipedia.org/wiki/Deflated_Sharpe_ratio) — kanonische Formeln + Beispiel-Werte
- [Portfolio Optimizer Blog — PSR & MinTRL](https://portfoliooptimizer.io/blog/the-probabilistic-sharpe-ratio-hypothesis-testing-and-minimum-track-record-length-for-the-difference-of-sharpe-ratios/)
- [Quantdare — Deflated Sharpe Ratio](https://quantdare.com/deflated-sharpe-ratio-how-to-avoid-been-fooled-by-randomness/)
- [Stefan Jansen ML4T — Multiple Testing](https://stefan-jansen.github.io/machine-learning-for-trading/08_ml4t_workflow/01_multiple_testing/)
