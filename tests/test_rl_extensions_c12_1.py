"""Sprint C12.1 tests for rl.extensions (CVaR, adversarial, WF, audit log)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from rl.extensions import (
    ConstraintHit,
    ConstraintHitLog,
    RLWalkForwardConfig,
    adversarial_bar_replay,
    cvar,
    cvar_reward,
    walk_forward_episodes,
)

# ---------------------------------------------------------------------------
# CVaR
# ---------------------------------------------------------------------------


def test_cvar_picks_worst_alpha_tail() -> None:
    returns = [0.10, 0.05, 0.0, -0.05, -0.20]  # 5 obs, alpha=0.2 -> 1 obs
    assert cvar(returns, alpha=0.20) == pytest.approx(-0.20)


def test_cvar_alpha_one_is_full_mean() -> None:
    returns = [1.0, 2.0, 3.0, 4.0]
    assert cvar(returns, alpha=1.0) == pytest.approx(2.5)


def test_cvar_empty_zero() -> None:
    assert cvar([], alpha=0.05) == 0.0


def test_cvar_validates_alpha() -> None:
    with pytest.raises(ValueError, match="alpha"):
        cvar([1.0], alpha=0.0)
    with pytest.raises(ValueError, match="alpha"):
        cvar([1.0], alpha=1.5)


def test_cvar_reward_penalises_tail_loss() -> None:
    """Same mean, fatter left tail => smaller cvar_reward."""
    a = [0.01, 0.01, 0.01, 0.01]                    # mean 0.01, no tail loss
    b = [0.04, 0.04, 0.04, -0.08]                   # mean 0.01, tail -0.08
    assert sum(a) / len(a) == pytest.approx(sum(b) / len(b))
    r_a = cvar_reward(a, alpha=0.25)
    r_b = cvar_reward(b, alpha=0.25)
    assert r_b < r_a


def test_cvar_reward_no_tail_no_penalty() -> None:
    """All-positive series: tail mean is positive => penalty is 0."""
    pos = [0.01, 0.02, 0.03, 0.04]
    assert cvar_reward(pos, alpha=0.25) == pytest.approx(sum(pos) / len(pos))


def test_cvar_reward_risk_aversion_scales_penalty() -> None:
    series = [0.01, 0.01, 0.01, -0.10]
    r1 = cvar_reward(series, alpha=0.25, risk_aversion=1.0)
    r5 = cvar_reward(series, alpha=0.25, risk_aversion=5.0)
    # r5 should be MORE negative (larger penalty) than r1.
    assert r5 < r1


# ---------------------------------------------------------------------------
# Adversarial replay
# ---------------------------------------------------------------------------


def test_adversarial_replay_doubles_worst_bars() -> None:
    bars = [{"return_pct": v} for v in [0.01, 0.02, -0.05, 0.03, -0.10]]
    out = adversarial_bar_replay(bars, n_worst=2)
    assert len(out) == len(bars) + 2
    # The two worst bars (-0.10, -0.05) appear at least twice in the stream.
    out_returns = [b["return_pct"] for b in out]
    assert out_returns.count(-0.10) >= 2
    assert out_returns.count(-0.05) >= 2


def test_adversarial_replay_n_worst_zero_is_noop() -> None:
    bars = [{"return_pct": v} for v in [0.01, -0.02, 0.03]]
    out = adversarial_bar_replay(bars, n_worst=0)
    assert out == bars


def test_adversarial_replay_caps_at_population() -> None:
    bars = [{"return_pct": -0.01}] * 4
    out = adversarial_bar_replay(bars, n_worst=100)
    assert len(out) == 8


def test_adversarial_replay_custom_statistic() -> None:
    bars = [{"slip_bps": v} for v in [1, 5, 50, 2]]  # 50 is the worst slippage
    out = adversarial_bar_replay(
        bars, n_worst=1, statistic=lambda b: -b["slip_bps"]
    )
    # Highest slippage bar (50) should be duplicated.
    assert sum(1 for b in out if b["slip_bps"] == 50) == 2


def test_adversarial_replay_requires_default_field_or_statistic() -> None:
    with pytest.raises(ValueError, match="return_pct"):
        adversarial_bar_replay([{"foo": 1}], n_worst=1)


def test_adversarial_replay_validates_n_worst() -> None:
    with pytest.raises(ValueError, match="n_worst"):
        adversarial_bar_replay([{"return_pct": 0.0}], n_worst=-1)


# ---------------------------------------------------------------------------
# Walk-forward over episodes
# ---------------------------------------------------------------------------


def test_wf_episodes_expanding_train_grows() -> None:
    cfg = RLWalkForwardConfig(n_episodes=60, n_folds=5, embargo_episodes=1)
    folds = walk_forward_episodes(cfg)
    assert len(folds) == 5
    sizes = [len(f.train_episodes) for f in folds]
    assert sizes == sorted(sizes), sizes


def test_wf_episodes_rolling_constant_train() -> None:
    cfg = RLWalkForwardConfig(
        n_episodes=120, n_folds=4, embargo_episodes=1,
        scheme="rolling", train_episodes=20,
    )
    folds = walk_forward_episodes(cfg)
    assert all(len(f.train_episodes) == 20 for f in folds)


def test_wf_episodes_disjoint_val() -> None:
    cfg = RLWalkForwardConfig(n_episodes=50, n_folds=4, embargo_episodes=0)
    folds = walk_forward_episodes(cfg)
    val_seen: set[int] = set()
    for f in folds:
        s = set(f.val_episodes)
        assert s.isdisjoint(val_seen)
        val_seen |= s


def test_wf_episodes_train_val_purged_by_embargo() -> None:
    cfg = RLWalkForwardConfig(n_episodes=40, n_folds=3, embargo_episodes=2)
    folds = walk_forward_episodes(cfg)
    for f in folds:
        if not f.train_episodes:
            continue
        gap = min(f.val_episodes) - max(f.train_episodes)
        assert gap >= 2 + 1, gap


def test_wf_episodes_validation() -> None:
    with pytest.raises(ValueError, match="n_episodes"):
        RLWalkForwardConfig(n_episodes=2, n_folds=5)
    with pytest.raises(ValueError, match="embargo_episodes"):
        RLWalkForwardConfig(n_episodes=20, n_folds=3, embargo_episodes=-1)
    with pytest.raises(ValueError, match="rolling"):
        RLWalkForwardConfig(n_episodes=20, n_folds=3, scheme="rolling")


def test_wf_episodes_n_folds_must_be_positive() -> None:
    with pytest.raises(ValueError, match="n_folds"):
        RLWalkForwardConfig(n_episodes=20, n_folds=0)
    with pytest.raises(ValueError, match="n_folds"):
        RLWalkForwardConfig(n_episodes=20, n_folds=-1)


# ---------------------------------------------------------------------------
# ConstraintHitLog
# ---------------------------------------------------------------------------


def test_audit_log_round_trip(tmp_path: Path) -> None:
    log = ConstraintHitLog(tmp_path / "constraint_hits.ndjson")
    log.record_clamp(
        constraint="max_size_fraction",
        requested=0.05,
        enforced=0.01,
        reason="size_cap",
    )
    log.record_clamp(
        constraint="max_drawdown_pct",
        requested=0.15,
        enforced=0.0,
        reason="dd_cap",
        extras={"session": "rth"},
    )
    rows = log.read_all()
    assert len(rows) == 2
    assert rows[0]["constraint"] == "max_size_fraction"
    assert rows[1]["extras"] == {"session": "rth"}


def test_audit_log_append_monotonic(tmp_path: Path) -> None:
    log = ConstraintHitLog(tmp_path / "hits.ndjson")
    for i in range(5):
        log.record(
            ConstraintHit(
                timestamp=float(i),
                constraint="x",
                requested=float(i),
                enforced=0.0,
                reason="",
            )
        )
    rows = log.read_all()
    timestamps = [r["timestamp"] for r in rows]
    assert timestamps == sorted(timestamps)


def test_audit_log_empty_file_is_empty(tmp_path: Path) -> None:
    log = ConstraintHitLog(tmp_path / "missing.ndjson")
    assert log.read_all() == []
    assert len(log) == 0


def test_audit_log_truncated_last_line_is_tolerated(tmp_path: Path) -> None:
    log = ConstraintHitLog(tmp_path / "trunc.ndjson")
    log.record_clamp(constraint="a", requested=1.0, enforced=0.5)
    log.record_clamp(constraint="b", requested=2.0, enforced=1.0)
    # Simulate a crash that left a partial last line
    with log.path.open("a", encoding="utf-8") as fh:
        fh.write('{"constraint": "c", "requ')  # truncated, no newline
    rows = log.read_all()
    assert len(rows) == 2
    assert [r["constraint"] for r in rows] == ["a", "b"]


def test_audit_log_one_json_object_per_line(tmp_path: Path) -> None:
    log = ConstraintHitLog(tmp_path / "lines.ndjson")
    log.record_clamp(constraint="a", requested=1.0, enforced=0.5)
    log.record_clamp(constraint="b", requested=2.0, enforced=1.0)
    raw = log.path.read_text(encoding="utf-8")
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    assert len(lines) == 2
    for ln in lines:
        json.loads(ln)  # parse must succeed


def test_audit_log_creates_parent_dir(tmp_path: Path) -> None:
    nested = tmp_path / "deep" / "nest" / "hits.ndjson"
    log = ConstraintHitLog(nested)
    log.record_clamp(constraint="x", requested=1.0, enforced=0.0)
    assert nested.exists()
