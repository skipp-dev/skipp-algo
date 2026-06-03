"""Ad-hoc EV-20 diagnostic: resolution (discrimination) + PSR cost-parity audit.

Reads archived promotion-decision JSONs and, from the aggregate metrics alone
(brier, ece, sharpe_hat, skew, kurtosis, n_returns), derives:

  Step 1 - Resolution audit via the Murphy/Brier two-component decomposition:
      Brier = Uncertainty - Resolution + Reliability
    With a sign-return target the base rate p is ~0.5, so Uncertainty = p*(1-p).
    Reliability (mean SQUARED calibration gap) is bounded above by the reported
    ECE (mean ABSOLUTE gap), since squared gaps <= absolute gaps for gaps in
    [0, 1]; the resolution band therefore brackets reliability in [0, ECE].
    Resolution = Uncertainty - Brier + Reliability. Near-zero resolution means
    the probability score does NOT separate winners from losers.

  Step 2 - PSR benchmark reconstruction:
    PSR (Bailey/Lopez de Prado 2012) z-score:
      z = (SR_hat - SR_bench) * sqrt(n-1) /
          sqrt(1 - skew*SR_hat + (kurt-1)/4 * SR_hat^2)
    The archived PSR uses SR_bench = 0. The pre-registered H1 benchmark is
    "regime-matched SPY buy-and-hold". We recompute PSR against a non-zero SPY
    per-period Sharpe - de-annualised onto each family's own event cadence so
    the strategy SR and the benchmark SR share one time basis - to show how
    much of the 0.99 PSR is "beats zero" vs "beats buy-and-hold".

  Time-basis (EV-20 ppy fix, PR #2513): the per-event Sharpe is annualised two
    ways - the legacy daily-bar basis (sr*sqrt(252)) and the TRUE event-cadence
    basis (sr*sqrt(evt/yr)). The cadence is read from the measured
    extra.observed_periods_per_year when present (src=obs), else approximated as
    n/1.62 (src=~n). SRtrue is the investor-grade number; SR252 is shown only to
    expose how far the legacy headline sat from the real basis.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import mean

DEC_DIR = Path("artifacts/ev20_audit")  # populated by the caller (git show)
SPY_ANNUAL_SHARPE = 0.55  # conservative regime-neutral SPY buy-and-hold proxy
MINTRL_WINDOW_YEARS = 1.62  # legacy n/window fallback when no observed cadence


def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def psr_z(sr_hat: float, sr_bench: float, n: float, skew: float, kurt: float) -> float:
    denom = math.sqrt(max(1e-12, 1.0 - skew * sr_hat + (kurt - 1.0) / 4.0 * sr_hat**2))
    return (sr_hat - sr_bench) * math.sqrt(max(1.0, n - 1.0)) / denom


def audit(files: list[Path]) -> None:
    per_family: dict[str, list[dict]] = {}
    for fp in files:
        d = json.loads(fp.read_text(encoding="utf-8"))
        for dec in d["decisions"]:
            m = dec["metrics"]
            fam = dec["family"]
            sr = m.get("extra.sharpe_hat")
            n = m.get("extra.n_returns")
            skew = m.get("extra.skew")
            kurt = m.get("extra.kurtosis")
            # EV-20 ppy fix: measured realised events/year, present only on
            # runs produced after PR #2513. None/absent on legacy archives.
            obs_ppy = m.get("extra.observed_periods_per_year")
            row = {
                "brier": m.get("brier"),
                "ece": m.get("ece"),
                "psr": m.get("psr"),
                "sr": sr,
                "n": n,
                "skew": skew,
                "kurt": kurt,
                "obs_ppy": obs_ppy,
            }
            per_family.setdefault(fam, []).append(row)

    print(f"{'FAM':5} {'brier':>7} {'ece':>6} {'Resol_lo':>9} {'Resol_hi':>9} "
          f"{'evt/yr':>7} {'src':>4} {'SR252':>6} {'SRtrue':>7} "
          f"{'PSR0':>6} {'PSR_spy':>8} {'n':>5}")
    print("-" * 96)
    for fam, rows in per_family.items():
        brier = mean(r["brier"] for r in rows)
        ece = mean(r["ece"] for r in rows)
        sr = mean(r["sr"] for r in rows)
        n = mean(r["n"] for r in rows)
        skew = mean(r["skew"] for r in rows)
        kurt = mean(r["kurt"] for r in rows)

        # Brier = Uncertainty - Resolution + Reliability, base rate ~0.5 ->
        # Uncertainty = 0.25. Reliability (squared gaps) is much smaller than
        # ECE (absolute gaps): reliability in [0, ece]. So resolution is bounded:
        #   lo (reliability=0, best-calibrated assumption) = Uncertainty - Brier
        #   hi (reliability=ece, pessimistic)             = Uncertainty - Brier + ece
        uncertainty = 0.25
        resol_lo = uncertainty - brier
        resol_hi = uncertainty - brier + ece

        # EV-20 time-basis: prefer the measured realised cadence when every
        # decision in the family carries it (mean of the observed values);
        # otherwise fall back to the legacy n/window approximation and flag it.
        observed = [r["obs_ppy"] for r in rows if r["obs_ppy"] is not None]
        if observed:
            evt_per_year = mean(observed)
            src = "obs"
        else:
            evt_per_year = n / MINTRL_WINDOW_YEARS
            src = "~n"

        sr_252 = sr * math.sqrt(252.0)  # legacy daily-bar headline basis
        sr_true = sr * math.sqrt(evt_per_year)  # true event-cadence basis
        # De-annualise the SPY hurdle onto THIS family's event cadence so the
        # strategy SR (per event) and the benchmark SR share one time basis.
        spy_per_period = SPY_ANNUAL_SHARPE / math.sqrt(evt_per_year)
        psr0 = _phi(psr_z(sr, 0.0, n, skew, kurt))
        psr_spy = _phi(psr_z(sr, spy_per_period, n, skew, kurt))

        print(f"{fam:5} {brier:7.4f} {ece:6.4f} {resol_lo:9.4f} {resol_hi:9.4f} "
              f"{evt_per_year:7.0f} {src:>4} {sr_252:6.2f} {sr_true:7.2f} "
              f"{psr0:6.3f} {psr_spy:8.3f} {int(n):5d}")

    print()
    print(f"SPY benchmark assumed: annual Sharpe {SPY_ANNUAL_SHARPE}, "
          f"de-annualised to each family's event cadence (evt/yr) for PSR_spy.")
    print("Uncertainty=0.25 (base rate ~0.5). Resol_lo/hi = resolution band; <=0 means")
    print("no better than a coin flip. Brier<=0.22 gate needs resolution-reliability>=0.03.")
    print("evt/yr src=obs -> measured extra.observed_periods_per_year (PR #2513);")
    print("src=~n -> legacy n/1.62 approximation (no measured cadence in archive).")
    print("SR252 = sr*sqrt(252) legacy headline; SRtrue = sr*sqrt(evt/yr) true basis.")
    print("PSR0 = archived benchmark (SR>0). PSR_spy = recomputed vs SPY buy-and-hold.")


if __name__ == "__main__":
    files = sorted(DEC_DIR.glob("*.json"))
    if not files:
        raise SystemExit(f"no decision JSONs in {DEC_DIR}")
    audit(files)
