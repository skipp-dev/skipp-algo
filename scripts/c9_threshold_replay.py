"""C9/T7 — Threshold-replay sensitivity tool.

Replays historical outcome streams against the C9 drift detectors at a
grid of threshold settings and reports True-Positive / False-Positive
rates per setting.  The output is written as JSON so a follow-up can
plot the sensitivity curve and lock the production thresholds.

Pure-stdlib + numpy.  Designed to be driven from a Python entry point
(``replay_thresholds(...)``) so tests can stay deterministic without
reading from disk.

The acceptance bar from
``docs/SPRINT_PLAN_C9_DRIFT_ALERT_2026-04-26.md`` §T7 is
≥ 80 % TPR at < 10 % FPR on the synthetic episode bank emitted by
:func:`build_synthetic_episodes`.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from scripts.drift_alert import (
    DriftSeverity,
    brown_forsythe_two_sample,
    ks_two_sample,
    population_stability_index,
    psi_severity,
    welch_t_two_sample,
)

__all__ = [
    "CALIBRATION_SOURCE",
    "DEFAULT_KS_GRID",
    "DEFAULT_PSI_GRID",
    "Episode",
    "ReplayResult",
    "ThresholdSetting",
    "build_synthetic_episodes",
    "evaluate_setting",
    "format_markdown_table",
    "main",
    "replay_thresholds",
    "write_report",
]


# C9/T7 (issue #298): provenance of the current detector calibration.
#
# "synthetic" — detectors 3 + 4 are p-value tests (Welch-t /
#   Brown-Forsythe) whose alpha ladder was validated against the
#   mixed-distribution synthetic episode bank only. The interim
#   effect-size literals (mean shift >= 0.3 sigma, variance ratio
#   outside [0.5, 2.0]) are gone, but the alphas still await a re-tune
#   against >= 90 days of live outcomes.
# "live" — alphas re-tuned against the locked-in live baseline windows
#   from the C8 incubation cron (flip this only in the PR that closes
#   issue #298 for good).
#
# ``tests/test_c9_threshold_finalisation_anchor.py`` fails CI the
# moment the C12 trigger is GREEN while this still reads "synthetic".
CALIBRATION_SOURCE = "synthetic"


# ── Episode bank ────────────────────────────────────────────────────


@dataclass(frozen=True)
class Episode:
    """One labelled outcome window."""

    label: str  # episode identifier
    is_drift: bool  # ground truth
    baseline: tuple[float, ...]  # backtest sample
    live: tuple[float, ...]  # live sample


def _rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


def build_synthetic_episodes(
    *,
    n_normal: int = 20,
    n_drift: int = 10,
    sample_size: int = 60,
    seed: int = 7,
    mix_distributions: bool = False,
) -> list[Episode]:
    """Build a deterministic synthetic episode bank.

    Default (``mix_distributions=False``): normals draw both baseline and
    live from N(0, 1); drifts shift the live mean by +0.5σ — large
    enough that a well-tuned K-S threshold should catch most of them
    while a poorly-tuned one rejects too many normals.

    With ``mix_distributions=True`` every third normal/drift episode is
    drawn from a heavy-tailed Student-t(df=4) or a positively-skewed
    lognormal so the tuning grid does not over-fit the Gaussian
    assumption — the C9 deep-review caveat. The mix is deterministic
    given ``seed`` so the tuner output is still reproducible.
    """
    if n_normal < 1 or n_drift < 1:
        raise ValueError("episode counts must be positive")
    if sample_size < 5:
        raise ValueError("sample_size too small")

    rng = _rng(seed)

    def _draw_pair(i: int, *, drift: bool) -> tuple[np.ndarray, np.ndarray]:
        family = i % 3 if mix_distributions else 0
        if family == 1:
            # Heavy-tailed (t with df=4 has finite variance ≈ 2).
            base = rng.standard_t(df=4, size=sample_size)
            live_raw = rng.standard_t(df=4, size=sample_size)
            shift = 0.5 if drift else 0.0
            return base, live_raw + shift
        if family == 2:
            # Skewed lognormal centred at zero.
            base = rng.lognormal(mean=0.0, sigma=0.5, size=sample_size) - 1.0
            live_raw = rng.lognormal(mean=0.0, sigma=0.5, size=sample_size) - 1.0
            shift = 0.5 if drift else 0.0
            return base, live_raw + shift
        base = rng.normal(0.0, 1.0, sample_size)
        live_raw = rng.normal(0.5 if drift else 0.0, 1.0, sample_size)
        return base, live_raw

    episodes: list[Episode] = []
    for i in range(n_normal):
        baseline, live = _draw_pair(i, drift=False)
        episodes.append(
            Episode(
                label=f"normal_{i:02d}",
                is_drift=False,
                baseline=tuple(float(x) for x in baseline),
                live=tuple(float(x) for x in live),
            )
        )
    for i in range(n_drift):
        baseline, live = _draw_pair(i, drift=True)
        episodes.append(
            Episode(
                label=f"drift_{i:02d}",
                is_drift=True,
                baseline=tuple(float(x) for x in baseline),
                live=tuple(float(x) for x in live),
            )
        )
    return episodes


# ── Detector consensus ─────────────────────────────────────────────


def _ks_severity(p_value: float | None, *, p_yellow: float, p_red: float) -> DriftSeverity:
    if p_value is None:
        return "green"
    if p_value < p_red:
        return "red"
    if p_value < p_yellow:
        return "yellow"
    return "green"


@dataclass(frozen=True)
class ThresholdSetting:
    """One point in the threshold-tuning grid."""

    ks_p_red: float
    ks_p_yellow: float
    psi_n_buckets: int = 10
    consensus_min: int = 2  # detectors firing red+ for episode-level fire

    def key(self) -> str:
        return (
            f"ks_red={self.ks_p_red:.4f}_"
            f"ks_yellow={self.ks_p_yellow:.4f}_"
            f"psi_bins={self.psi_n_buckets}_"
            f"consensus={self.consensus_min}"
        )


# Sensible production-candidate grids.  Memory hint: the production
# defaults in `compute_drift_report` (drift_alert.py) are the grid
# winner ks_p_red=0.005 / ks_p_yellow=0.025 / consensus_min=2 — see
# docs/c9_threshold_tuning.md for the 2026-06-11 grid results.
DEFAULT_KS_GRID: tuple[tuple[float, float], ...] = (
    (0.01, 0.05),
    (0.005, 0.025),
    (0.02, 0.10),
    (0.001, 0.01),
)
DEFAULT_PSI_GRID: tuple[int, ...] = (5, 10, 20)


def _is_drift_severity(severity: DriftSeverity) -> bool:
    return severity in {"yellow", "red"}


def _episode_fires(episode: Episode, setting: ThresholdSetting) -> bool:
    """Apply the 4-detector consensus from the C9 sprint plan.

    The episode "fires" iff at least ``setting.consensus_min`` (default 2)
    of the four detectors below cross their drift threshold. Two-of-four
    consensus trades single-detector sensitivity for a lower
    false-positive rate.

    Detectors (C9/T7, issue #298 — the STRUCTURAL swap of detectors
    3 + 4 to p-value tests landed 2026-06-11; the live alpha re-tune is
    still pending, see ``CALIBRATION_SOURCE`` and the anchor test):
        1. KS p-value vs ``ks_p_yellow``/``ks_p_red`` — distribution-shape
           change.
        2. PSI vs ``psi_severity`` thresholds — bucketed mass shift.
        3. Welch t-test p-value (two-sided, unequal variance) vs the
           same ``ks_p_yellow``/``ks_p_red`` ladder — first-moment shift.
           Replaces the interim ``mean_shift >= 0.3 sigma`` effect-size
           rule.
        4. Brown-Forsythe p-value (median-centered Levene) vs the same
           ladder — second-moment shift. Replaces the interim variance
           ratio outside ``[0.5, 2.0]`` rule; the median-centered
           variant is used because the plain F-ratio test is not robust
           to the heavy-tailed/skewed families in the episode bank.

    All three p-value detectors share one alpha ladder
    (``ks_p_yellow``/``ks_p_red``) — exactly mirroring production
    ``drift_alert.compute_drift_report``, which feeds a single
    ``p_value_yellow``/``p_value_red`` pair to every p-value detector.
    This keeps the replay tool and the production watchdog coupled: one
    grid axis tunes the consensus, not four detectors drifting apart.

    Zero-variance guards (pinned by
    ``tests/test_c9_episode_fires_invariants_property.py``): a
    degenerate baseline disables detectors 3 + 4; a degenerate live
    sample disables detector 4.

    See ``docs/c9_threshold_tuning.md`` for the grid results that
    validated the alpha ladder on the mixed-distribution synthetic bank
    and for the live re-tune procedure (``CALIBRATION_SOURCE`` flips to
    ``"live"`` when issue #298 closes).
    """
    baseline = np.asarray(episode.baseline, dtype=np.float64)
    live = np.asarray(episode.live, dtype=np.float64)

    fires = 0

    # Detector 1: KS p-value
    _stat, p = ks_two_sample(baseline, live)
    if _is_drift_severity(
        _ks_severity(p, p_yellow=setting.ks_p_yellow, p_red=setting.ks_p_red)
    ):
        fires += 1

    # Detector 2: PSI
    psi = population_stability_index(baseline, live, n_buckets=setting.psi_n_buckets)
    if psi is not None and _is_drift_severity(psi_severity(psi)):
        fires += 1

    # Detector 3: Welch t-test on the mean (two-sided), gated on a
    # non-degenerate baseline.
    bstd = float(baseline.std(ddof=0))
    if bstd > 0:
        _t, p_t = welch_t_two_sample(baseline, live)
        if _is_drift_severity(
            _ks_severity(p_t, p_yellow=setting.ks_p_yellow, p_red=setting.ks_p_red)
        ):
            fires += 1

    # Detector 4: Brown-Forsythe on the scale, gated on non-degenerate
    # baseline AND live samples.
    lstd = float(live.std(ddof=0))
    if bstd > 0 and lstd > 0:
        _f, p_f = brown_forsythe_two_sample(baseline, live)
        if _is_drift_severity(
            _ks_severity(p_f, p_yellow=setting.ks_p_yellow, p_red=setting.ks_p_red)
        ):
            fires += 1

    return fires >= setting.consensus_min


# ── Replay ──────────────────────────────────────────────────────────


@dataclass
class ReplayResult:
    setting: ThresholdSetting
    n_drift: int
    n_normal: int
    true_positive: int
    false_positive: int
    fired_episodes: list[str] = field(default_factory=list)

    @property
    def tpr(self) -> float:
        return self.true_positive / self.n_drift if self.n_drift else 0.0

    @property
    def fpr(self) -> float:
        return self.false_positive / self.n_normal if self.n_normal else 0.0

    @property
    def passes_acceptance(self) -> bool:
        """Sprint-plan §T7 acceptance: TPR ≥ 0.80 ∧ FPR < 0.10."""
        return self.tpr >= 0.80 and self.fpr < 0.10

    def to_dict(self) -> dict[str, Any]:
        return {
            "setting": asdict(self.setting),
            "setting_key": self.setting.key(),
            "n_drift": self.n_drift,
            "n_normal": self.n_normal,
            "true_positive": self.true_positive,
            "false_positive": self.false_positive,
            "tpr": round(self.tpr, 4),
            "fpr": round(self.fpr, 4),
            "passes_acceptance": self.passes_acceptance,
            "fired_episodes": list(self.fired_episodes),
        }


def evaluate_setting(
    episodes: Sequence[Episode],
    setting: ThresholdSetting,
) -> ReplayResult:
    n_drift = sum(1 for e in episodes if e.is_drift)
    n_normal = len(episodes) - n_drift

    tp = 0
    fp = 0
    fired: list[str] = []
    for ep in episodes:
        if _episode_fires(ep, setting):
            fired.append(ep.label)
            if ep.is_drift:
                tp += 1
            else:
                fp += 1
    return ReplayResult(
        setting=setting,
        n_drift=n_drift,
        n_normal=n_normal,
        true_positive=tp,
        false_positive=fp,
        fired_episodes=fired,
    )


def replay_thresholds(
    episodes: Sequence[Episode],
    *,
    settings: Iterable[ThresholdSetting] | None = None,
) -> list[ReplayResult]:
    if settings is None:
        settings = _default_grid()
    return [evaluate_setting(episodes, s) for s in settings]


def _default_grid() -> list[ThresholdSetting]:
    out: list[ThresholdSetting] = []
    for ks_red, ks_yellow in DEFAULT_KS_GRID:
        for psi_bins in DEFAULT_PSI_GRID:
            for consensus in (2, 3):
                out.append(
                    ThresholdSetting(
                        ks_p_red=ks_red,
                        ks_p_yellow=ks_yellow,
                        psi_n_buckets=psi_bins,
                        consensus_min=consensus,
                    )
                )
    return out


# ── Reporting ───────────────────────────────────────────────────────


def format_markdown_table(results: Sequence[ReplayResult]) -> str:
    header = (
        "| ks_p_red | ks_p_yellow | psi_bins | consensus |"
        " TPR | FPR | passes |\n"
        "|---|---|---|---|---|---|---|"
    )
    rows = [header]
    for r in results:
        s = r.setting
        rows.append(
            f"| {s.ks_p_red:.4f} | {s.ks_p_yellow:.4f} | {s.psi_n_buckets}"
            f" | {s.consensus_min} | {r.tpr:.2f} | {r.fpr:.2f}"
            f" | {'✅' if r.passes_acceptance else '❌'} |"
        )
    return "\n".join(rows)


def write_report(
    results: Sequence[ReplayResult],
    path: Path | str,
) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0.0",
        "n_settings": len(results),
        "results": [r.to_dict() for r in results],
        "passing_settings": [
            r.setting.key() for r in results if r.passes_acceptance
        ],
    }
    # C-sprint deep-review C9 MINOR fix: atomic write so a CI-run that
    # is killed mid-write never leaves a half-written sensitivity
    # artefact that downstream tooling silently consumes. Mirrors the
    # pattern used by ``run_drift_watchdog.write_report``.
    import os as _os
    import tempfile as _tempfile

    serialised = json.dumps(payload, indent=2, sort_keys=True)
    fd, tmp_str = _tempfile.mkstemp(
        dir=str(p.parent), prefix=p.name + ".", suffix=".tmp"
    )
    tmp_path = Path(tmp_str)
    try:
        with _os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(serialised)
            fh.flush()
            _os.fsync(fh.fileno())
        _os.replace(tmp_path, p)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    return p


# ── CLI ─────────────────────────────────────────────────────────────


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="C9/T7 threshold-replay sensitivity tool",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("cache/c9/threshold_replay.json"),
        help="Output JSON path",
    )
    parser.add_argument("--n-normal", type=int, default=20)
    parser.add_argument("--n-drift", type=int, default=10)
    parser.add_argument("--sample-size", type=int, default=60)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--print-table",
        action="store_true",
        help="Also print markdown table to stdout",
    )
    args = parser.parse_args(argv)

    episodes = build_synthetic_episodes(
        n_normal=args.n_normal,
        n_drift=args.n_drift,
        sample_size=args.sample_size,
        seed=args.seed,
    )
    results = replay_thresholds(episodes)
    out = write_report(results, args.out)

    print(f"Wrote {out} ({len(results)} settings)")
    passing = [r for r in results if r.passes_acceptance]
    print(f"Passing acceptance (TPR≥0.80, FPR<0.10): {len(passing)}/{len(results)}")
    if args.print_table:
        print(format_markdown_table(results))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
