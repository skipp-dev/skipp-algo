"""Fallback-safe calibration consumer: armed-gating, sample floor, and that a
measured P genuinely overrides the ⭐ midpoint heuristic in rt_notify."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from open_prep import calibration_lookup, rt_notify


def _write_calibration(tmp_path, table):
    p = tmp_path / "calibration_latest.json"
    p.write_text(json.dumps({"table": table}), encoding="utf-8")
    return p


@pytest.fixture(autouse=True)
def _reset_cache():
    calibration_lookup._cache.update({"path": None, "mtime": None, "table": None})
    yield
    calibration_lookup._cache.update({"path": None, "mtime": None, "table": None})


def test_unarmed_returns_none_even_with_file(tmp_path, monkeypatch):
    path = _write_calibration(tmp_path, {"A1|2.0-3.0": {"n": 99, "hit_target_rate": 0.9}})
    monkeypatch.setenv("RT_CALIBRATION_PATH", str(path))
    monkeypatch.delenv("RT_CALIBRATION_ARMED", raising=False)
    assert calibration_lookup.follow_through_p("A1", 2.5) is None


def test_armed_no_file_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("RT_CALIBRATION_ARMED", "1")
    monkeypatch.setenv("RT_CALIBRATION_PATH", str(tmp_path / "missing.json"))
    assert calibration_lookup.follow_through_p("A1", 2.5) is None


def test_armed_enough_samples_returns_p(tmp_path, monkeypatch):
    path = _write_calibration(tmp_path, {"A1|2.0-3.0": {"n": 50, "hit_target_rate": 0.62}})
    monkeypatch.setenv("RT_CALIBRATION_ARMED", "1")
    monkeypatch.setenv("RT_CALIBRATION_PATH", str(path))
    # 2.5 buckets to "2.0-3.0" (same bucketing as the calibrator)
    assert calibration_lookup.follow_through_p("A1", 2.5) == pytest.approx(0.62)


def test_armed_too_few_samples_falls_back(tmp_path, monkeypatch):
    path = _write_calibration(tmp_path, {"A1|2.0-3.0": {"n": 5, "hit_target_rate": 0.9}})
    monkeypatch.setenv("RT_CALIBRATION_ARMED", "1")
    monkeypatch.setenv("RT_CALIBRATION_PATH", str(path))
    assert calibration_lookup.follow_through_p("A1", 2.5) is None  # below default 20


def test_armed_missing_bucket_returns_none(tmp_path, monkeypatch):
    path = _write_calibration(tmp_path, {"A1|2.0-3.0": {"n": 50, "hit_target_rate": 0.62}})
    monkeypatch.setenv("RT_CALIBRATION_ARMED", "1")
    monkeypatch.setenv("RT_CALIBRATION_PATH", str(path))
    assert calibration_lookup.follow_through_p("A1", 1.2) is None  # bucket 1.0-1.5 absent


def test_malformed_file_returns_none(tmp_path, monkeypatch):
    path = tmp_path / "calibration_latest.json"
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("RT_CALIBRATION_ARMED", "1")
    monkeypatch.setenv("RT_CALIBRATION_PATH", str(path))
    assert calibration_lookup.follow_through_p("A1", 2.5) is None


def _a1(vol_ratio: float, change_pct: float):
    return SimpleNamespace(level="A1", volume_ratio=vol_ratio, change_pct=change_pct, symbol="X",
                           direction="LONG", price=10.0)


def test_rt_notify_unarmed_uses_heuristic(monkeypatch):
    monkeypatch.delenv("RT_CALIBRATION_ARMED", raising=False)
    # vol 2.5 >= 2.0 and |Δ| 1.0 >= 0.9 → heuristic marks it high-conviction.
    assert rt_notify._is_high_conviction_a1(_a1(2.5, 1.0)) is True
    assert rt_notify._is_high_conviction_a1(_a1(1.2, 0.4)) is False


def test_rt_notify_calibrated_weak_p_vetoes_heuristic(tmp_path, monkeypatch):
    # A bucket the midpoint heuristic would flag (vol 2.5, |Δ| 1.0) but whose
    # MEASURED P is weak → armed calibration vetoes the ⭐ (the whole point).
    path = _write_calibration(tmp_path, {"A1|2.0-3.0": {"n": 40, "hit_target_rate": 0.10}})
    monkeypatch.setenv("RT_CALIBRATION_ARMED", "1")
    monkeypatch.setenv("RT_CALIBRATION_PATH", str(path))
    assert rt_notify._is_high_conviction_a1(_a1(2.5, 1.0)) is False


def test_rt_notify_calibrated_strong_p_promotes_and_labels(tmp_path, monkeypatch):
    # A strong measured P earns the ⭐ and surfaces the P in the tail (" ⭐P71%").
    path = _write_calibration(tmp_path, {"A1|2.0-3.0": {"n": 40, "hit_target_rate": 0.71}})
    monkeypatch.setenv("RT_CALIBRATION_ARMED", "1")
    monkeypatch.setenv("RT_CALIBRATION_PATH", str(path))
    sig = _a1(2.5, 1.0)
    assert rt_notify._is_high_conviction_a1(sig) is True
    assert rt_notify._a1_conviction_label(sig) == " ⭐P71%"
