"""Library-context bridge (SC-LIB-001, issue #3872 aftermath).

#3790 declared universe/trust "runtime-sidecar data" while nothing served
them. These tests pin the bridge that closes the gap: generator-controlled
``export const`` parsing, honest None semantics for static libraries, and
the additive ``smc_live`` field contract the sidecar validates.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from services.live_overlay_daemon import library_context_bridge as bridge

ENRICHED_PINE = """\
//@version=6
library("smc_micro_profiles_generated", overlay = false)
export const string ASOF_DATE = "2026-07-22"
export const string ASOF_TIME = "2026-07-22T16:40:00Z"
export const int UNIVERSE_SIZE = 4
export const int PROVIDER_COUNT = 3
export const string STALE_PROVIDERS = ""
export const string UNIVERSE_TICKERS_PART_1 = "AAPL,MSFT"
export const string UNIVERSE_TICKERS_PART_2 = "NVDA,ONDS"
"""

STATIC_PINE = """\
//@version=6
library("smc_micro_profiles_generated", overlay = false)
export const string ASOF_DATE = "2026-07-21"
export const string ASOF_TIME = ""
export const int UNIVERSE_SIZE = 6929
export const string UNIVERSE_TICKERS = ""
"""


@pytest.fixture(autouse=True)
def _reset_cache():
    bridge._cache.update({"data": None, "mtime_ns": None, "path": None})
    yield


def _point_at(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, text: str) -> None:
    pine = tmp_path / "lib.pine"
    pine.write_text(text, encoding="utf-8")
    monkeypatch.setenv("LIBRARY_CONTEXT_PINE_PATH", str(pine))


def test_enriched_library_yields_membership_and_trust(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _point_at(monkeypatch, tmp_path, ENRICHED_PINE)
    ctx = bridge.context_for_symbol("NASDAQ:ONDS")
    assert ctx == {
        "universe_member": True,
        "universe_size": 4,
        "library_asof_date": "2026-07-22",
        "library_asof_time": "2026-07-22T16:40:00Z",
        "provider_trust_status": "ok",
        "provider_stale_list": None,
    }
    assert bridge.context_for_symbol("TSLA")["universe_member"] is False


def test_static_library_yields_unknown_not_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty universe means "not scanned at all" — membership must be
    None (unknown), never False ("scanned and absent"), and the misleading
    UNIVERSE_SIZE of a static library must not leak."""
    _point_at(monkeypatch, tmp_path, STATIC_PINE)
    ctx = bridge.context_for_symbol("AAPL")
    assert ctx["universe_member"] is None
    assert ctx["universe_size"] is None
    assert ctx["library_asof_date"] == "2026-07-21"
    assert ctx["library_asof_time"] is None
    assert ctx["provider_trust_status"] is None
    assert ctx["provider_stale_list"] is None


def test_degraded_and_unavailable_provider_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    degraded = ENRICHED_PINE.replace(
        'export const string STALE_PROVIDERS = ""',
        'export const string STALE_PROVIDERS = "benzinga,newsapi"',
    )
    _point_at(monkeypatch, tmp_path, degraded)
    ctx = bridge.context_for_symbol("AAPL")
    assert ctx["provider_trust_status"] == "degraded"
    assert ctx["provider_stale_list"] == "benzinga,newsapi"

    dead = ENRICHED_PINE.replace(
        "export const int PROVIDER_COUNT = 3", "export const int PROVIDER_COUNT = 0"
    )
    _point_at(monkeypatch, tmp_path, dead)
    bridge._cache.update({"data": None, "mtime_ns": None, "path": None})
    assert bridge.context_for_symbol("AAPL")["provider_trust_status"] == "unavailable"


def test_missing_file_fails_soft(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIBRARY_CONTEXT_PINE_PATH", str(tmp_path / "absent.pine"))
    ctx = bridge.context_for_symbol("AAPL")
    assert all(value is None for value in ctx.values())


def test_cache_refreshes_on_mtime_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pine = tmp_path / "lib.pine"
    pine.write_text(ENRICHED_PINE, encoding="utf-8")
    monkeypatch.setenv("LIBRARY_CONTEXT_PINE_PATH", str(pine))
    assert bridge.context_for_symbol("ONDS")["universe_member"] is True
    updated = ENRICHED_PINE.replace('"NVDA,ONDS"', '"NVDA"')
    pine.write_text(updated, encoding="utf-8")
    import os

    os.utime(pine, ns=(pine.stat().st_atime_ns, pine.stat().st_mtime_ns + 1_000_000))
    assert bridge.context_for_symbol("ONDS")["universe_member"] is False
