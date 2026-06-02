"""Ad-hoc EV-20 diagnostic: resolution (discrimination) + PSR cost-parity audit.

Reads archived promotion-decision JSONs and, from the aggregate metrics alone
(brier, ece, sharpe_hat, skew, kurtosis, n_returns), derives:

  Step 1 - Resolution audit via the Murphy/Brier two-component decomposition:
      Brier = Uncertainty - Resolution + Reliability
    With a sign-return target the base rate p is ~0.5, so Uncertainty = p*(1-p).
    Reliability is bounded by the reported ECE (reliability ~ mean squared gap,
    ECE = mean abs gap, so reliability <= ECE * max_gap; we bound it two ways).
    Resolution = Uncertainty - Brier + Reliability. Near-zero resolution means
    the probability score does NOT separate winners from losers.

  Step 2 - PSR benchmark reconstruction:
    PSR (Bailey/Lopez de Prado 2012) z-score:
      z = (SR_hat - SR_bench) * sqrt(n-1) /
          sqrt(1 - skew*SR_hat + (kurt-1)/4 * SR_hat^2)
    The archived PSR uses SR_bench = 0. The pre-registered H1 benchmark is
    "regime-matched SPY buy-and-hold". We recompute PSR against a non-zero SPY
    per-period Sharpe to show how much of the 0.99 PSR is "beats zero" vs
    "beats buy-and-hold".
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import mean

DEC_DIR = Path("artifacts/ev20_audit")  # populated by the caller (git show)
SPY_ANNUAL_SHARPE = 0.55  # conservative regime-neutral SPY buy-and-hold proxy


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
            ppy = m.get("extra.periods_per_year", 252.0)
            row = {
                "brier": m.get("brier"),
                "ece": m.get("ece"),
                "psr": m.get("psr"),
                "sr": sr,
                "n": n,
                "skew": skew,
                "kurt": kurt,
                "ppy": ppy,
            }
            per_family.setdefault(fam, []).append(row)

    spy_per_period = SPY_ANNUAL_SHARPE / math.sqrt(252.0)

    print(f"{'FAM':5} {'brier':>7} {'ece':>6} {'Resol_lo':>9} {'Resol_hi':>9} "
          f"{'SR/yr':>6} {'evt/yr':>7} {'PSR0':>6} {'PSR_spy':>8} {'n':>5}")
    print("-" * 86)
    for fam, rows in per_family.items():
        brier = mean(r["brier"] for r in rows)
        ece = mean(r["ece"] for r in rows)
        sr = mean(r["sr"] for r in rows)
        n = mean(r["n"] for r in rows)
        skew = mean(r["skew"] for r in rows)
        kurt = mean(r["kurt"] for r in rows)
        ppy = rows[0]["ppy"]

        # Brier = Uncertainty - Resolution + Reliability, base rate ~0.5 ->
        # Uncertainty = 0.25. Reliability (squared gaps) is much smaller than
        # ECE (absolute gaps): reliability in [0, ece]. So resolution is bounded:
        #   lo (reliability=0, best-calibrated assumption) = Uncertainty - Brier
        #   hi (reliability=ece, pessimistic)             = Uncertainty - Brier + ece
        uncertainty = 0.25
        resol_lo = uncertainty - brier
        resol_hi = uncertainty - brier + ece

        sr_annual = sr * math.sqrt(ppy)
        evt_per_year = n / 1.62  # mintrl window ~1.62y; reveals ppy=252 mismatch
        psr0 = _phi(psr_z(sr, 0.0, n, skew, kurt))
        psr_spy = _phi(psr_z(sr, spy_per_period, n, skew, kurt))

        print(f"{fam:5} {brier:7.4f} {ece:6.4f} {resol_lo:9.4f} {resol_hi:9.4f} "
              f"{sr_annual:6.2f} {evt_per_year:7.0f} {psr0:6.3f} {psr_spy:8.3f} {int(n):5d}")

    print()
    print(f"SPY benchmark assumed: annual Sharpe {SPY_ANNUAL_SHARPE} "
          f"(per-period {spy_per_period:.4f}).")
    print("Uncertainty=0.25 (base rate ~0.5). Resol_lo/hi = resolution band; <=0 means")
    print("no better than a coin flip. Brier<=0.22 gate needs resolution-reliability>=0.03.")
    print("evt/yr vs ppy=252: if evt/yr != 252 the annualised SR time-basis is suspect.")
    print("PSR0 = archived benchmark (SR>0). PSR_spy = recomputed vs SPY buy-and-hold.")


if __name__ == "__main__":
    files = sorted(DEC_DIR.glob("*.json"))
    if not files:
        raise SystemExit(f"no decision JSONs in {DEC_DIR}")
    audit(files)
