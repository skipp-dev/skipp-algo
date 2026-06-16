"""C8/T4 — Live-vs-Backtest drift detector.

Compares per-variant live performance (Sharpe, slippage distribution,
hit-rate) against the backtest-OOS reference produced by C2 walk-forward
and C3 bootstrap.  Emits a per-variant drift verdict plus a JSON
artifact suitable for the C7 dashboard tab and the C8/T6 monitoring.

Pure-stdlib + numpy.  No scipy.  The 2-sample KS test is implemented
in :func:`ks_two_sample` against the standard Kolmogorov asymptotic
distribution, which is the same one ``scipy.stats.ks_2samp`` falls
back to once ``min(n, m)`` exceeds the small-sample threshold.

Schema (additive only; bump the consumer when fields are removed)::

    {
      "schema_version": "1.3.0",
      "computed_at": "2026-04-26T13:30:00+00:00",
      "live_window_days": 90,
      "variants": [
        {
          "variant": "smc_breaker_btc",
          "n_live_trades": 24,
          "live_sharpe": 0.71,
          "backtest_sharpe": 0.93,
          "drift_score": 0.76,
          "trades_per_year_live": 97.3,
          "trades_per_year_backtest": 142.1,
          "slippage_ks_p": 0.32,
          "slippage_ks_reference": "backtest_samples",
          "slippage_ks_reference_type": "backtest_samples",
          "hr_in_bootstrap_ci": true,
          "overperformance_capped": false,
          "verdict": "acceptable"
        }
      ]
    }
"""

from __future__ import annotations

# F-V5-A1-2 / F-CI-O1 (2026-05-01): bootstrap root logging so the
# logger.info(...) progress messages this entry point emits actually
# surface in CI logs (default WARNING-only handler would drop them).
try:
    from scripts._logging_init import init_cli_logging
except ImportError:  # script-style invocation: `python scripts/X.py`
    import sys as _v5a12_sys
    from pathlib import Path as _v5a12_Path

    _v5a12_sys.path.insert(0, str(_v5a12_Path(__file__).resolve().parents[1]))
    from scripts._logging_init import init_cli_logging  # type: ignore[no-redef]


import argparse
import contextlib
import json
import math
import os
import sys
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

# Drift verdict bands (multiplicative live/backtest Sharpe ratio)
# W9-7 (SMR wave 9): these thresholds are HEURISTIC PLACEHOLDERS — they
# have NOT been derived from a calibration run, a power analysis, or any
# empirical measurement of acceptable performance degradation.  The values
# (0.85 / 0.65 / 0.40) were set by engineering judgment during the C8
# sprint and carry no statistical guarantee.  A properly calibrated set of
# bands requires a labelled dataset of "acceptable drift" episodes and a
# receiver-operating-characteristic (ROC) analysis to choose threshold
# cut-points at a target false-positive / false-negative operating point.
# Until that calibration is done, any automated gate that promotes/blocks
# solely on the basis of these bands has an unknown error rate.
# W9-7 carry-over / stat-review wave 10: the values are intentionally left
# unchanged here — calibration requires a multi-month live-trading dataset
# that is not yet available.  A TODO is tracked in GitHub issue #2798.
# When calibration data is available, follow the pattern in
# docs/DECISIONS.md §threshold-calibration and run
#   .venv/bin/python scripts/calibrate_drift_thresholds.py
# to derive principled values and remove this notice.
_VERDICT_BANDS: tuple[tuple[float, str], ...] = (
    (0.85, "pass"),
    (0.65, "acceptable"),
    (0.40, "concerning"),
)
# Anything below 0.40 → "fail".

# Stat-review S5 (#2674): these defaults are PLACEHOLDERS, not measured
# execution-quality parameters. "0.5% per the sprint plan" cites a planning
# document, not a calibration run; the std has no citation at all. The KS
# reference distribution synthesised from them (Normal(mean, std), seed
# 12345) is disclosed downstream via ``slippage_ks_reference_type ==
# "synthetic_normal"`` and MUST NOT machine-pass a promotion criterion —
# the phase evaluator treats synthetic references as not-evaluable.
# Replace with broker-fill calibration before trusting the KS p-value.
_DEFAULT_EXPECTED_SLIPPAGE_MEAN = 0.005  # 0.5% per the sprint plan (placeholder)
_DEFAULT_EXPECTED_SLIPPAGE_STD = 0.003  # uncited placeholder
_TRADING_DAYS_PER_YEAR = 252

# Drift-artifact schema version (Deep-Review C8 MAJOR finding 2026-04-27).
# The artifact schema is documented as "additive only" but previously
# emitted no version marker, leaving consumers without a machine-checkable
# guard against producer-side renames or removals. Bump policy:
#   * MAJOR: field removed or semantics changed; consumers MUST refuse
#   * MINOR: additive field; consumers may ignore it
#   * PATCH: cosmetic / docstring change with no payload diff
# When you bump this constant, update DRIFT_SCHEMA_MIN_COMPATIBLE in
# ``terminal_tabs/drift_loader.py`` and add a CHANGELOG entry.
# 1.2.0 (2026-06-10 silent-fallback audit): additive — new verdict values
# ``missing_backtest_reference`` / ``non_positive_backtest_sharpe`` /
# ``no_live_data`` and new boolean field ``overperformance_capped``.
# 1.3.0 (2026-06-10 stat-review F7): additive — cadence disclosure fields
# ``trades_per_year_live`` / ``trades_per_year_backtest``. The √252
# annualisation applied to per-trade returns makes ``drift_score`` move
# when live trades less often than backtest even at identical per-trade
# edge; the cadence fields let the operator see that confound.
DRIFT_SCHEMA_VERSION = "1.3.0"

__all__ = [
    "DRIFT_SCHEMA_VERSION",
    "DriftVerdict",
    "annualised_sharpe",
    "compute_live_drift",
    "drift_score",
    "ks_two_sample",
    "main",
    "max_drawdown_fraction",
]


@dataclass(frozen=True)
class DriftVerdict:
    """Per-variant drift assessment."""

    variant: str
    n_live_trades: int
    live_sharpe: float
    backtest_sharpe: float
    drift_score: float
    slippage_ks_p: float | None
    hr_in_bootstrap_ci: bool | None
    verdict: str
    live_max_dd: float | None = None
    backtest_max_dd: float | None = None
    slippage_ks_reference_type: str = "unavailable"
    overperformance_capped: bool = False
    trades_per_year_live: float | None = None
    trades_per_year_backtest: float | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "variant": self.variant,
            "n_live_trades": self.n_live_trades,
            "live_sharpe": round(self.live_sharpe, 6),
            "backtest_sharpe": round(self.backtest_sharpe, 6),
            "drift_score": round(self.drift_score, 6),
            "slippage_ks_p": (
                None if self.slippage_ks_p is None else round(self.slippage_ks_p, 6)
            ),
            # C8 deep-review caveat: when no real backtest-slippage
            # sample is available the K-S compares live slippage against
            # a *modelled* Normal(expected_mean, expected_std) reference.
            # ``slippage_ks_reference`` keeps the legacy field name for
            # backwards-compat consumers; both fields carry the same
            # structured marker (one of ``backtest_samples``,
            # ``synthetic_normal``, ``unavailable``). Phase-B sign-off
            # MUST require ``backtest_samples`` (see
            # docs/c8_live_incubation_runbook.md).
            "slippage_ks_reference": self.slippage_ks_reference_type,
            "slippage_ks_reference_type": self.slippage_ks_reference_type,
            "hr_in_bootstrap_ci": self.hr_in_bootstrap_ci,
            "verdict": self.verdict,
            # Silent-fallback audit (2026-06-10): live ≫ backtest hits the
            # 1.5 drift-score cap and is otherwise indistinguishable from a
            # healthy "pass". Overperformance is frequently a data defect
            # (lookahead, survivorship in the live feed) — surface it.
            "overperformance_capped": self.overperformance_capped,
            "live_max_dd": (
                None if self.live_max_dd is None else round(self.live_max_dd, 6)
            ),
            "backtest_max_dd": (
                None if self.backtest_max_dd is None else round(self.backtest_max_dd, 6)
            ),
            # Stat-review F7 (2026-06-10): Sharpe annualisation is
            # cadence-blind — both sides apply √252 to per-trade returns,
            # so a variant that trades less often live than in backtest
            # drifts even at identical per-trade edge. These fields
            # disclose the observed cadence on each side so the operator
            # can see the confound. ``trades_per_year_backtest`` is None
            # when the reference carries neither ``trades_per_year`` nor
            # ``n_trades``+``window_days``.
            "trades_per_year_live": (
                None
                if self.trades_per_year_live is None
                else round(self.trades_per_year_live, 2)
            ),
            "trades_per_year_backtest": (
                None
                if self.trades_per_year_backtest is None
                else round(self.trades_per_year_backtest, 2)
            ),
            # C8 phase tracking: the live-incubation runbook
            # (docs/c8_live_incubation_runbook.md) defines
            # phase-A (paper) / phase-B (live_small) / phase-C (live_full).
            # Promotion is manual sign-off only; this drift module does
            # *not* auto-promote — consumers must consult the runbook.
            "phase_promotion": "manual_signoff_only",
        }


# ── statistics ──────────────────────────────────────────────────────


def annualised_sharpe(
    returns: Sequence[float],
    *,
    trades_per_year: float = _TRADING_DAYS_PER_YEAR,
) -> float:
    """Bailey-Lopez-de-Prado-style annualised Sharpe.

    Returns 0.0 for fewer than 2 samples or zero std.

    W9-4 (SMR wave 9): the ``trades_per_year`` parameter MUST reflect the
    actual observation cadence of ``returns``.  If ``returns`` are per-trade
    (not daily-bar aggregates), pass the observed annual trade count — e.g.
    ``compute_live_drift()`` derives it from the live trade log and the
    lookback window.  The default of ``_TRADING_DAYS_PER_YEAR=252`` is kept
    for backward-compatibility only and is intentionally wrong for per-trade
    returns; callers that rely on the default should pass the true cadence.
    """
    arr = np.asarray(list(returns), dtype=float)
    if arr.size < 2:
        return 0.0
    sd = float(arr.std(ddof=1))
    if sd <= 0.0 or not math.isfinite(sd):
        return 0.0
    return float(arr.mean() / sd * math.sqrt(trades_per_year))


def max_drawdown_fraction(returns: Sequence[float]) -> float | None:
    """Peak-to-trough drawdown as a positive fraction of the peak equity.

    Treats ``returns`` as additive equity-curve increments (R-multiples
    or fractional). Returns ``None`` when fewer than 2 samples are
    available so callers can render a "no data" placeholder rather than
    a misleading 0.0.
    """
    arr = np.asarray(list(returns), dtype=float)
    if arr.size < 2:
        return None
    equity = 1.0 + np.cumsum(arr)
    peaks = np.maximum.accumulate(equity)
    # Guard against zero/negative peaks to keep the ratio bounded.
    safe_peaks = np.where(peaks <= 0, 1.0, peaks)
    drawdowns = (peaks - equity) / safe_peaks
    dd = float(np.max(drawdowns))
    return max(0.0, dd) if math.isfinite(dd) else None


def drift_score(live_sharpe: float, backtest_sharpe: float) -> float:
    """Drift = live / max(backtest, 0.001), capped to [0.0, 1.5]."""
    denom = max(float(backtest_sharpe), 0.001)
    raw = float(live_sharpe) / denom
    if not math.isfinite(raw):
        return 0.0
    return float(max(0.0, min(1.5, raw)))


def _verdict_for(score: float) -> str:
    for threshold, label in _VERDICT_BANDS:
        if score >= threshold:
            return label
    return "fail"


def _kolmogorov_sf(d: float, n_eff: float) -> float:
    """Two-sided Kolmogorov asymptotic survival function.

    Thin wrapper around :func:`scripts._kolmogorov.kolmogorov_sf_two_sample`
    so this module and ``scripts.drift_alert`` emit identical p-values
    (single source of truth for the C9 K-S detector).
    """
    from scripts._kolmogorov import kolmogorov_sf_two_sample

    return kolmogorov_sf_two_sample(d, n_eff)


def ks_two_sample(
    a: Sequence[float], b: Sequence[float],
) -> tuple[float, float | None]:
    """Two-sample Kolmogorov-Smirnov test (statistic, asymptotic p).

    Returns ``(0.0, None)`` if either sample is empty — "not evaluable",
    matching :func:`scripts.drift_alert.ks_two_sample` (stat-review F12:
    the twins previously forked here, with this side returning ``(0.0,
    1.0)`` = "perfectly compatible", a latent p=1.0 laundering one
    refactor away from reachability).
    """
    x = np.sort(np.asarray(list(a), dtype=float))
    y = np.sort(np.asarray(list(b), dtype=float))
    n, m = x.size, y.size
    if n == 0 or m == 0:
        return 0.0, None
    data = np.concatenate([x, y])
    cdf_x = np.searchsorted(x, data, side="right") / n
    cdf_y = np.searchsorted(y, data, side="right") / m
    d = float(np.max(np.abs(cdf_x - cdf_y)))
    n_eff = (n * m) / (n + m)
    p = _kolmogorov_sf(d, n_eff)
    return d, p


# ── data loading ────────────────────────────────────────────────────


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _group_by_variant(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        v = row.get("variant")
        if not isinstance(v, str) or not v:
            continue
        out.setdefault(v, []).append(dict(row))
    return out


def _coerce_float(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


# ── public entry point ──────────────────────────────────────────────


def compute_live_drift(
    *,
    live_rows: Sequence[Mapping[str, Any]] | None = None,
    backtest_reference: Mapping[str, Mapping[str, Any]] | None = None,
    live_jsonl: Path | None = None,
    backtest_calibration: Path | None = None,
    slippage_reference: Path | None = None,
    min_trades: int = 15,
    expected_slippage_mean: float = _DEFAULT_EXPECTED_SLIPPAGE_MEAN,
    expected_slippage_std: float = _DEFAULT_EXPECTED_SLIPPAGE_STD,
    live_window_days: int = 90,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Compute per-variant drift verdicts.

    Either pass already-loaded ``live_rows`` and ``backtest_reference``
    (preferred for tests) or point at JSONL/JSON files on disk.

    Each live row must carry at least ``variant`` and ``return`` (the
    realised per-trade return as a fraction, e.g. R-multiple / position
    size).  Optional keys: ``slippage`` (per-trade slippage as a
    fraction), ``hit`` (bool, 1 = trade was a winner).

    ``backtest_reference`` is a ``{variant: {sharpe, hit_rate_ci_low,
    hit_rate_ci_high}}`` dict, typically the C2 walk-forward + C3
    bootstrap output.

    Variants below ``min_trades`` live trades are returned with
    verdict ``insufficient_sample``; a warning marker but never an
    error so cron callers can still emit the artifact safely.

    Reference-integrity verdicts (2026-06-10 silent-fallback audit):
    ``missing_backtest_reference`` (variant absent from / non-numeric in
    the reference), ``non_positive_backtest_sharpe`` (ratio would be
    meaningless) and ``no_live_data`` (reference-only variant with zero
    live rows — "stopped trading"). All three fail closed against the
    ``run_smc_live_incubation`` pass/acceptable allowlist.
    """
    if live_rows is None:
        if live_jsonl is None:
            raise ValueError("either live_rows or live_jsonl must be provided")
        live_rows = _read_jsonl(Path(live_jsonl))
    if backtest_reference is None:
        if backtest_calibration is None:
            raise ValueError(
                "either backtest_reference or backtest_calibration must be provided",
            )
        with Path(backtest_calibration).open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        backtest_reference = payload.get("backtest_reference") or {}

    grouped = _group_by_variant(live_rows)

    # ── C13/T4: per-family slippage-sample injection ──────────────
    # When ``--slippage-reference`` points at a file produced by
    # :mod:`scripts.build_backtest_slippage_samples`, broadcast each
    # family’s samples to every variant key whose family prefix
    # matches (e.g. ``BOS_megacap`` consumes the ``BOS`` family
    # samples). This flips ``slippage_ks_reference_type`` from
    # ``synthetic_normal`` to ``backtest_samples`` and unblocks the
    # Phase-B promotion gate.
    if slippage_reference is not None:
        with Path(slippage_reference).open("r", encoding="utf-8") as fh:
            slip_payload = json.load(fh)
        # Imported lazily to keep the module import-light for tests
        # that never touch the slippage path.
        from scripts.build_backtest_slippage_samples import (
            expand_to_variant_samples,
        )

        per_variant = expand_to_variant_samples(slip_payload, grouped.keys())
        if per_variant:
            merged: dict[str, dict[str, Any]] = {
                k: dict(v) for k, v in (backtest_reference or {}).items()
            }
            for variant, samples in per_variant.items():
                slot = merged.setdefault(variant, {})
                slot["slippage_samples"] = samples
            backtest_reference = merged
    when = (now or datetime.now(UTC)).isoformat()
    verdicts: list[dict[str, Any]] = []

    # Silent-fallback audit (2026-06-10): iterate the UNION of live
    # variants and backtest-reference variants. A variant that has a
    # reference but zero live trades in the window ("stopped trading")
    # is the strongest drift signal of all and must not vanish from
    # the artifact silently.
    for variant in sorted(set(grouped) | set(backtest_reference or {})):
        rows = grouped.get(variant, [])
        ref = backtest_reference.get(variant) or {}
        # H1: keep the raw coercion result — ``None`` means "reference
        # missing or non-numeric", which must NOT collapse to 0.0 (the
        # 0.001 denominator clamp would turn any live Sharpe ≥ 0.00085
        # into drift_score 1.5 → verdict "pass" for a variant that has
        # no reference at all).
        backtest_sharpe_raw = _coerce_float(ref.get("sharpe"))
        backtest_sharpe = backtest_sharpe_raw or 0.0
        ci_low = _coerce_float(ref.get("hit_rate_ci_low"))
        ci_high = _coerce_float(ref.get("hit_rate_ci_high"))
        backtest_max_dd = _coerce_float(ref.get("max_dd"))
        ref_slippage_raw = ref.get("slippage_samples")

        returns: list[float] = []
        slippage: list[float] = []
        hits: list[int] = []
        for r in rows:
            ret = _coerce_float(r.get("return"))
            if ret is not None:
                returns.append(ret)
            slip = _coerce_float(r.get("slippage"))
            if slip is not None:
                slippage.append(slip)
            h = r.get("hit")
            if isinstance(h, (bool, int, float)):
                hits.append(1 if h else 0)

        n_live = len(returns)
        # W9-4 (SMR wave 9): compute the live cadence (trades/year) here
        # so both annualised_sharpe call sites below receive the true
        # per-trade scaling factor instead of the wrong √252 daily default.
        _tpy_live = (
            n_live * 365.25 / live_window_days if live_window_days > 0 else None
        )
        if n_live == 0 and variant not in grouped:
            # M1: reference-only variant — no live rows at all in the
            # window. Emit an explicit row instead of dropping it.
            verdicts.append(
                DriftVerdict(
                    variant=variant,
                    n_live_trades=0,
                    live_sharpe=0.0,
                    backtest_sharpe=backtest_sharpe,
                    drift_score=0.0,
                    slippage_ks_p=None,
                    hr_in_bootstrap_ci=None,
                    verdict="no_live_data",
                    live_max_dd=None,
                    backtest_max_dd=backtest_max_dd,
                ).to_json(),
            )
            continue
        if n_live < min_trades:
            verdicts.append(
                DriftVerdict(
                    variant=variant,
                    n_live_trades=n_live,
                    live_sharpe=annualised_sharpe(
                        returns,
                        trades_per_year=_tpy_live or _TRADING_DAYS_PER_YEAR,
                    ),
                    backtest_sharpe=backtest_sharpe,
                    drift_score=0.0,
                    slippage_ks_p=None,
                    hr_in_bootstrap_ci=None,
                    verdict="insufficient_sample",
                    live_max_dd=max_drawdown_fraction(returns),
                    backtest_max_dd=backtest_max_dd,
                ).to_json(),
            )
            continue

        live_sharpe = annualised_sharpe(
            returns,
            trades_per_year=_tpy_live or _TRADING_DAYS_PER_YEAR,
        )

        # H1: a missing / non-numeric backtest reference must yield an
        # explicit non-pass verdict, not a ratio against the 0.001
        # denominator clamp. Same epistemics class as comparing an arm
        # against itself (PR #2664 / #2666): no reference arm ⇒ no
        # measurement. ``run_smc_live_incubation`` gates on an
        # allowlist (pass/acceptable), so these verdicts fail closed.
        if backtest_sharpe_raw is None:
            verdicts.append(
                DriftVerdict(
                    variant=variant,
                    n_live_trades=n_live,
                    live_sharpe=live_sharpe,
                    backtest_sharpe=0.0,
                    drift_score=0.0,
                    slippage_ks_p=None,
                    hr_in_bootstrap_ci=None,
                    verdict="missing_backtest_reference",
                    live_max_dd=max_drawdown_fraction(returns),
                    backtest_max_dd=backtest_max_dd,
                ).to_json(),
            )
            continue
        if backtest_sharpe_raw <= 0.0:
            # A non-positive backtest Sharpe makes the live/backtest
            # ratio semantically meaningless (the clamp would report
            # drift_score 1.5 → "pass" regardless of live quality).
            verdicts.append(
                DriftVerdict(
                    variant=variant,
                    n_live_trades=n_live,
                    live_sharpe=live_sharpe,
                    backtest_sharpe=backtest_sharpe_raw,
                    drift_score=0.0,
                    slippage_ks_p=None,
                    hr_in_bootstrap_ci=None,
                    verdict="non_positive_backtest_sharpe",
                    live_max_dd=max_drawdown_fraction(returns),
                    backtest_max_dd=backtest_max_dd,
                ).to_json(),
            )
            continue

        # Stat-review F7 (2026-06-10): observed-cadence disclosure.
        # Live cadence already computed above as _tpy_live (W9-4);
        # backtest cadence from the reference if it carries either an
        # explicit ``trades_per_year`` or ``n_trades`` + ``window_days``.
        trades_per_year_live = _tpy_live
        trades_per_year_backtest = _coerce_float(ref.get("trades_per_year"))
        if trades_per_year_backtest is None:
            bt_n = _coerce_float(ref.get("n_trades"))
            bt_days = _coerce_float(ref.get("window_days"))
            if bt_n is not None and bt_days is not None and bt_days > 0:
                trades_per_year_backtest = bt_n * 365.25 / bt_days

        score = drift_score(live_sharpe, backtest_sharpe)
        verdict = _verdict_for(score)
        # L2: live ≫ backtest saturates the 1.5 cap and would otherwise
        # be indistinguishable from a healthy "pass".
        raw_ratio = live_sharpe / max(backtest_sharpe, 0.001)
        overperformance_capped = math.isfinite(raw_ratio) and raw_ratio > 1.5

        ks_p: float | None = None
        slippage_ref_type = "unavailable"
        if slippage:
            # Prefer a real backtest-slippage sample if the reference
            # carries one; otherwise fall back to a deterministic
            # Normal(expected_mean, expected_std) reference. The
            # synthetic fallback is statistically weak vs fat-tailed
            # real slippage — see C8 review notes.
            ref_sample: list[float] = []
            if isinstance(ref_slippage_raw, list) and ref_slippage_raw:
                ref_sample = [
                    s for s in (
                        _coerce_float(x) for x in ref_slippage_raw
                    ) if s is not None
                ]
                if ref_sample:
                    slippage_ref_type = "backtest_samples"
            if not ref_sample:
                ref_n = max(len(slippage), 100)
                rng = np.random.default_rng(seed=12345)
                ref_sample = rng.normal(
                    loc=expected_slippage_mean,
                    scale=max(expected_slippage_std, 1e-9),
                    size=ref_n,
                ).tolist()
                slippage_ref_type = "synthetic_normal"
            if ref_sample:
                _, ks_p = ks_two_sample(slippage, ref_sample)

        hr_in_ci: bool | None = None
        if hits and ci_low is not None and ci_high is not None:
            hr = sum(hits) / len(hits)
            hr_in_ci = bool(ci_low <= hr <= ci_high)

        verdicts.append(
            DriftVerdict(
                variant=variant,
                n_live_trades=n_live,
                live_sharpe=live_sharpe,
                backtest_sharpe=backtest_sharpe,
                drift_score=score,
                slippage_ks_p=ks_p,
                hr_in_bootstrap_ci=hr_in_ci,
                verdict=verdict,
                live_max_dd=max_drawdown_fraction(returns),
                backtest_max_dd=backtest_max_dd,
                slippage_ks_reference_type=slippage_ref_type,
                overperformance_capped=overperformance_capped,
                trades_per_year_live=trades_per_year_live,
                trades_per_year_backtest=trades_per_year_backtest,
            ).to_json(),
        )

    return {
        "schema_version": DRIFT_SCHEMA_VERSION,
        "computed_at": when,
        "live_window_days": live_window_days,
        "variants": verdicts,
    }


# ── atomic JSON write ───────────────────────────────────────────────


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".drift_", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            # ATOMIC-WRITE-EXEMPT: hand-rolled mkstemp+fsync+os.replace pattern above.
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.write("\n")
            # C-sprint deep-review: flush+fsync before os.replace so a
            # crash between buffer-write and disk-sync does not leave
            # a truncated/empty drift verdict (consumed by the
            # watchdog and the dashboard). Mirrors the pattern in
            # ``scripts/run_drift_watchdog.py`` and ``open_prep/outcomes.py``.
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


# ── CLI ────────────────────────────────────────────────────────────


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Compute live-vs-backtest drift metrics")
    p.add_argument("--live-jsonl", type=Path, required=True)
    p.add_argument("--backtest-calibration", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument(
        "--slippage-reference",
        type=Path,
        default=None,
        help=(
            "Optional path to a per-family backtest-slippage sample file "
            "produced by scripts/build_backtest_slippage_samples.py. "
            "When supplied, the K-S reference flips from synthetic_normal "
            "to backtest_samples and unblocks Phase-B promotion (C13/T4)."
        ),
    )
    p.add_argument("--min-trades", type=int, default=15)
    p.add_argument("--live-window-days", type=int, default=90)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    init_cli_logging()  # F-V5-A1-2 (2026-05-01)
    args = _build_arg_parser().parse_args(argv)
    report = compute_live_drift(
        live_jsonl=args.live_jsonl,
        backtest_calibration=args.backtest_calibration,
        slippage_reference=args.slippage_reference,
        min_trades=args.min_trades,
        live_window_days=args.live_window_days,
    )
    _atomic_write_json(args.output, report)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
