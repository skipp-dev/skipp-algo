"""OPEN_PREP_OUTCOMES_DIR redirects local outcome writes off the CI-committed
canonical dir, so local run_open_prep runs stop leaving untracked
outcomes_<date>.json that collide with the incoming CI commit on git pull."""
from datetime import date

from open_prep import outcomes


def test_default_dir_is_canonical(monkeypatch):
    monkeypatch.delenv("OPEN_PREP_OUTCOMES_DIR", raising=False)
    assert outcomes._outcomes_dir() == outcomes.OUTCOMES_DIR


def test_env_override_redirects_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("OPEN_PREP_OUTCOMES_DIR", str(tmp_path / "shadow"))
    assert outcomes._outcomes_dir() == tmp_path / "shadow"


def test_blank_override_falls_back_to_canonical(monkeypatch):
    monkeypatch.setenv("OPEN_PREP_OUTCOMES_DIR", "   ")
    assert outcomes._outcomes_dir() == outcomes.OUTCOMES_DIR


def test_store_writes_to_override_not_canonical(monkeypatch, tmp_path):
    shadow = tmp_path / "shadow"
    monkeypatch.setenv("OPEN_PREP_OUTCOMES_DIR", str(shadow))
    d = date(2020, 1, 2)  # a date CI never committed → canonical must stay absent
    outcomes.store_daily_outcomes(d, [{"symbol": "NVDA", "profitable_30m": True}])
    assert (shadow / "outcomes_2020-01-02.json").is_file()
    assert not (outcomes.OUTCOMES_DIR / "outcomes_2020-01-02.json").exists()


def test_load_range_reads_from_override(monkeypatch, tmp_path):
    shadow = tmp_path / "shadow"
    monkeypatch.setenv("OPEN_PREP_OUTCOMES_DIR", str(shadow))
    outcomes.store_daily_outcomes(date(2020, 1, 2), [{"symbol": "NVDA", "profitable_30m": True}])
    # Read path honours the same override (write + read stay co-located).
    loaded = outcomes._load_outcomes_range(lookback_days=5)
    assert any(r.get("symbol") == "NVDA" for r in loaded)
