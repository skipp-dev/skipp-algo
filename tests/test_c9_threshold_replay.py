"""Tests for scripts.c9_threshold_replay (C9/T7)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.c9_threshold_replay import (
    DEFAULT_KS_GRID,
    DEFAULT_PSI_GRID,
    Episode,
    ThresholdSetting,
    build_synthetic_episodes,
    evaluate_setting,
    format_markdown_table,
    main,
    replay_thresholds,
    write_report,
)

# ── episode bank ────────────────────────────────────────────────────


def test_build_synthetic_episodes_counts_match() -> None:
    eps = build_synthetic_episodes(n_normal=20, n_drift=10)
    assert len(eps) == 30
    assert sum(1 for e in eps if e.is_drift) == 10
    assert sum(1 for e in eps if not e.is_drift) == 20


def test_build_synthetic_episodes_deterministic() -> None:
    a = build_synthetic_episodes(seed=42)
    b = build_synthetic_episodes(seed=42)
    assert [e.live for e in a] == [e.live for e in b]


def test_build_synthetic_episodes_seeds_differ() -> None:
    a = build_synthetic_episodes(seed=1)
    b = build_synthetic_episodes(seed=2)
    assert [e.live for e in a] != [e.live for e in b]


def test_build_synthetic_episodes_rejects_zero_counts() -> None:
    with pytest.raises(ValueError, match="positive"):
        build_synthetic_episodes(n_normal=0, n_drift=10)


def test_build_synthetic_episodes_rejects_tiny_sample() -> None:
    with pytest.raises(ValueError, match="sample_size"):
        build_synthetic_episodes(sample_size=2)


# ── threshold setting ─────────────────────────────────────────────


def test_threshold_setting_key_includes_all_axes() -> None:
    s = ThresholdSetting(ks_p_red=0.01, ks_p_yellow=0.05)
    k = s.key()
    assert "ks_red=0.0100" in k
    assert "ks_yellow=0.0500" in k
    assert "psi_bins=10" in k
    assert "consensus=2" in k


def test_default_grids_non_empty() -> None:
    assert len(DEFAULT_KS_GRID) >= 3
    assert len(DEFAULT_PSI_GRID) >= 2


# ── single-setting evaluation ─────────────────────────────────────


def _episode(label: str, *, drift: bool, baseline: list[float], live: list[float]) -> Episode:
    return Episode(
        label=label,
        is_drift=drift,
        baseline=tuple(baseline),
        live=tuple(live),
    )


def test_evaluate_setting_no_episodes_fires() -> None:
    eps = [
        _episode("a", drift=False, baseline=[0.0] * 10, live=[0.0] * 10),
        _episode("b", drift=True, baseline=[0.0] * 10, live=[0.0] * 10),
    ]
    setting = ThresholdSetting(
        ks_p_red=0.01, ks_p_yellow=0.05, consensus_min=2
    )
    r = evaluate_setting(eps, setting)
    assert r.true_positive == 0
    assert r.false_positive == 0
    assert r.tpr == 0.0
    assert r.fpr == 0.0
    assert r.fired_episodes == []


def test_evaluate_setting_strong_drift_episode_fires() -> None:
    baseline = [float(i) * 0.01 for i in range(60)]
    live = [float(i) * 0.01 + 5.0 for i in range(60)]
    eps = [_episode("loud_drift", drift=True, baseline=baseline, live=live)]
    setting = ThresholdSetting(
        ks_p_red=0.01, ks_p_yellow=0.05, consensus_min=2
    )
    r = evaluate_setting(eps, setting)
    assert r.true_positive == 1
    assert "loud_drift" in r.fired_episodes


def test_replay_results_are_one_per_setting() -> None:
    eps = build_synthetic_episodes()
    settings = [
        ThresholdSetting(0.01, 0.05),
        ThresholdSetting(0.001, 0.01),
    ]
    out = replay_thresholds(eps, settings=settings)
    assert len(out) == 2
    keys = {r.setting.key() for r in out}
    assert len(keys) == 2


# ── full grid acceptance ──────────────────────────────────────────


def test_default_grid_has_at_least_one_passing_setting() -> None:
    """Sprint-plan §T7 acceptance: ≥1 grid point hits TPR≥0.80, FPR<0.10.

    Uses ``mix_distributions=True`` so the bar is *not* Gaussian-only; the
    synthetic bank covers t(df=4) and lognormal episodes too. This is the
    tighter gate identified by the C-sprint deep review; with the Gaussian-
    only bank every grid point trivially passes and the test would not
    detect a regression.
    """
    eps = build_synthetic_episodes(
        n_normal=40, n_drift=20, sample_size=80, seed=11, mix_distributions=True
    )
    results = replay_thresholds(eps)
    passing = [r for r in results if r.passes_acceptance]
    assert passing, (
        "No threshold setting met the C9/T7 acceptance bar "
        "(TPR≥0.80, FPR<0.10) on the mixed-distribution synthetic bank — "
        "investigate (see docs/c9_threshold_tuning.md for re-tuning protocol)."
    )


def test_replay_result_to_dict_round_trippable() -> None:
    eps = build_synthetic_episodes(n_normal=5, n_drift=5, sample_size=30)
    setting = ThresholdSetting(0.01, 0.05)
    r = evaluate_setting(eps, setting)
    d = r.to_dict()
    assert d["setting_key"] == setting.key()
    assert "tpr" in d and "fpr" in d
    assert d["passes_acceptance"] in (True, False)


# ── markdown + JSON output ────────────────────────────────────────


def test_format_markdown_table_has_header_and_rows() -> None:
    eps = build_synthetic_episodes(n_normal=5, n_drift=5, sample_size=30)
    results = replay_thresholds(
        eps,
        settings=[
            ThresholdSetting(0.01, 0.05),
            ThresholdSetting(0.005, 0.025, consensus_min=3),
        ],
    )
    md = format_markdown_table(results)
    assert "| TPR | FPR |" in md
    lines = md.splitlines()
    # header + separator + 2 data rows
    assert len(lines) == 4


def test_write_report_emits_schema_versioned_json(tmp_path: Path) -> None:
    eps = build_synthetic_episodes(n_normal=5, n_drift=5, sample_size=30)
    results = replay_thresholds(
        eps, settings=[ThresholdSetting(0.01, 0.05)]
    )
    out = write_report(results, tmp_path / "out.json")
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.0.0"
    assert payload["n_settings"] == 1
    assert isinstance(payload["passing_settings"], list)


# ── CLI smoke ─────────────────────────────────────────────────────


def test_cli_main_writes_report(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    import logging

    out = tmp_path / "replay.json"
    with caplog.at_level(logging.INFO, logger="scripts.c9_threshold_replay"):
        rc = main(
            [
                "--out",
                str(out),
                "--n-normal",
                "5",
                "--n-drift",
                "5",
                "--sample-size",
                "30",
            ]
        )
    assert rc == 0
    assert out.exists()
    assert "Wrote" in caplog.text
    assert "Passing acceptance" in caplog.text


def test_cli_main_print_table_flag(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    import logging

    out = tmp_path / "replay.json"
    with caplog.at_level(logging.INFO, logger="scripts.c9_threshold_replay"):
        rc = main(
            [
                "--out",
                str(out),
                "--n-normal",
                "3",
                "--n-drift",
                "3",
                "--sample-size",
                "30",
                "--print-table",
            ]
        )
    assert rc == 0
    assert "| TPR | FPR |" in caplog.text
