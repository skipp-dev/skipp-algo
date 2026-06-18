"""Tests for Databento corporate-actions reference cache helpers."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

import databento_reference
import databento_utils
import databento_volatility_screener as screener_mod


def test_refresh_builds_symbol_alias_and_identifier_maps(tmp_path: Path) -> None:
    class FakeCorporateActions:
        def get_range(self, **kwargs):
            return pd.DataFrame(
                [
                    {
                        "event": "LCC",
                        "effective_date": "2022-06-09",
                        "old_localcode": "FB",
                        "new_localcode": "META",
                    },
                    {
                        "event": "ICC",
                        "effective_date": "2022-06-09",
                        "symbol": "META",
                        "old_i_s_i_n": "OLDISIN",
                        "new_i_s_i_n": "NEWISIN",
                    },
                ]
            )

    class FakeReferenceClient:
        corporate_actions = FakeCorporateActions()

    databento_reference._invalidate_state_cache()
    state = databento_reference.maybe_refresh_symbol_reference_cache(
        ["FB", "META"],
        api_key="db-test-key",
        cache_dir=tmp_path,
        force_refresh=True,
        client=FakeReferenceClient(),
    )

    assert state["provider_status"] == "ok"
    assert state["symbol_aliases"] == {"FB": "META"}
    assert state["identifier_map"]["META"]["aliases"] == ["FB"]
    assert state["identifier_map"]["META"]["identifiers"]["isin"] == {
        "previous": "OLDISIN",
        "current": "NEWISIN",
        "effective_date": "2022-06-09",
        "event": "ICC",
    }


def test_refresh_caches_not_subscribed_status(tmp_path: Path) -> None:
    calls = {"count": 0}

    class FailingCorporateActions:
        def get_range(self, **kwargs):
            calls["count"] += 1
            raise RuntimeError("403 license_reference_dataset_no_subscription")

    class FailingReferenceClient:
        corporate_actions = FailingCorporateActions()

    databento_reference._invalidate_state_cache()
    first = databento_reference.maybe_refresh_symbol_reference_cache(
        ["FB"],
        api_key="db-test-key",
        cache_dir=tmp_path,
        force_refresh=True,
        client=FailingReferenceClient(),
    )

    assert first["provider_status"] == "not_subscribed"
    assert calls["count"] == 1

    class UnexpectedCorporateActions:
        def get_range(self, **kwargs):
            raise AssertionError("cached not_subscribed state should suppress refetch")

    class UnexpectedReferenceClient:
        corporate_actions = UnexpectedCorporateActions()

    second = databento_reference.maybe_refresh_symbol_reference_cache(
        ["FB"],
        api_key="db-test-key",
        cache_dir=tmp_path,
        client=UnexpectedReferenceClient(),
    )

    assert second["provider_status"] == "not_subscribed"


def test_normalizers_apply_cached_reference_aliases(tmp_path: Path, monkeypatch) -> None:
    cache_file = tmp_path / "corporate_actions_reference_state.json"
    cache_file.write_text(
        json.dumps(
            {
                "version": 1,
                "provider_status": "ok",
                "fetched_at": "2026-04-08T10:00:00+00:00",
                "last_attempted_at": "2026-04-08T10:00:00+00:00",
                "last_error": "",
                "coverage_symbols": ["FB"],
                "events": [],
                "symbol_aliases": {"FB": "META"},
                "identifier_map": {},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DATABENTO_REFERENCE_CACHE_DIR", str(tmp_path))
    databento_reference._invalidate_state_cache()

    assert databento_utils.normalize_symbol_for_databento("FB") == "META"
    assert screener_mod.normalize_symbol_for_databento("FB") == "META"


def test_reference_event_risk_snapshot_filters_recent_events(tmp_path: Path) -> None:
    cache_file = tmp_path / "corporate_actions_reference_state.json"
    cache_file.write_text(
        json.dumps(
            {
                "version": 1,
                "provider_status": "ok",
                "fetched_at": "2026-04-08T10:00:00+00:00",
                "last_attempted_at": "2026-04-08T10:00:00+00:00",
                "last_error": "",
                "coverage_symbols": ["META"],
                "events": [],
                "symbol_aliases": {},
                "identifier_map": {
                    "META": {
                        "aliases": ["FB"],
                        "events": [
                            {"event": "LCC", "effective_date": "2026-04-06"},
                            {"event": "ICC", "effective_date": "2025-12-01"},
                        ],
                        "latest_effective_date": "2026-04-06",
                        "identifiers": {},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    databento_reference._invalidate_state_cache()

    snapshot = databento_reference.get_reference_event_risk_snapshot(
        ["META"],
        as_of=date(2026, 4, 8),
        lookback_days=7,
        cache_dir=tmp_path,
    )

    assert snapshot["provider_status"] == "ok"
    assert snapshot["reference_change_tickers"] == ["META"]
    assert snapshot["by_symbol"]["META"]["event_types"] == ["LCC"]
    assert snapshot["by_symbol"]["META"]["aliases"] == ["FB"]


def test_build_identifier_map_mixed_date_formats() -> None:
    # Test that dates with different string lengths/formats (YYYY-MM-DD vs ISO timestamps)
    # are correctly parsed and compared chronologically, and not lexically as strings.
    records = [
        {
            "event": "LCC",
            "effective_date": "2024-01-02T12:00:00Z",
            "old_symbol": "AAA",
            "new_symbol": "BBB",
            "new_localcode": "BBB",
            "old_isin": "ISIN1",
            "new_isin": "ISIN2",
        },
        {
            "event": "ICC",
            "effective_date": "2024-01-03",
            "old_symbol": "BBB",
            "new_symbol": "BBB",
            "old_isin": "ISIN2",
            "new_isin": "ISIN3",
        },
    ]

    aliases = {"AAA": "BBB"}
    identifier_map = databento_reference._build_identifier_map(records, aliases)

    # "latest_effective_date" should be the chronologically latest one: "2024-01-03"
    assert identifier_map["BBB"]["latest_effective_date"] == "2024-01-03"
    assert identifier_map["BBB"]["identifiers"]["isin"]["current"] == "ISIN3"


def test_interprocess_lock_is_called(tmp_path: Path, monkeypatch) -> None:
    lock_called = []

    original_lock = databento_reference._interprocess_lock

    def mock_lock(cache_dir=None):
        lock_called.append(True)
        return original_lock(cache_dir)

    monkeypatch.setattr(databento_reference, "_interprocess_lock", mock_lock)

    class FakeCorporateActions:
        def get_range(self, **kwargs):
            return pd.DataFrame([])

    class FakeReferenceClient:
        corporate_actions = FakeCorporateActions()

    databento_reference._invalidate_state_cache()
    databento_reference.maybe_refresh_symbol_reference_cache(
        ["AAPL"],
        api_key="db-test-key",
        cache_dir=tmp_path,
        force_refresh=True,
        client=FakeReferenceClient(),
    )

    assert len(lock_called) > 0
