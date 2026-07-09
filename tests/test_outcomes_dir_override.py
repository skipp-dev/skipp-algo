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


# --- outcome_backfill mirrors the same call-time redirect (2026-07-09) ---------

def test_backfill_default_dir_is_canonical(monkeypatch):
    from open_prep import outcome_backfill
    monkeypatch.delenv("OPEN_PREP_OUTCOMES_DIR", raising=False)
    assert outcome_backfill._outcomes_dir() == outcome_backfill.OUTCOMES_DIR


def test_backfill_env_override_redirects_dir(monkeypatch, tmp_path):
    from open_prep import outcome_backfill
    monkeypatch.setenv("OPEN_PREP_OUTCOMES_DIR", str(tmp_path / "shadow"))
    assert outcome_backfill._outcomes_dir() == tmp_path / "shadow"


def test_backfill_load_reads_from_override(monkeypatch, tmp_path):
    from open_prep import outcome_backfill, outcomes
    shadow = tmp_path / "shadow"
    monkeypatch.setenv("OPEN_PREP_OUTCOMES_DIR", str(shadow))
    # A pending record (profitable_30m=None) written to the shadow dir…
    outcomes.store_daily_outcomes(date(2021, 6, 1), [{"symbol": "NVDA", "profitable_30m": None}])
    # …must be discovered by the backfiller reading through the SAME override.
    assert outcome_backfill._load_pending_dates(lookback_days=3) == [date(2021, 6, 1)]
    _path, records = outcome_backfill._load_outcome_file(date(2021, 6, 1))
    assert records and records[0]["symbol"] == "NVDA"
    # And nothing leaked into the CI-committed canonical dir.
    assert not (outcome_backfill.OUTCOMES_DIR / "outcomes_2021-06-01.json").exists()
