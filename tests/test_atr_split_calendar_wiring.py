"""Wiring guard for the ATR corporate-action split reset.

Background
==========

``open_prep.atr_quality.homogeneous_price_history`` protects every price-derived
feature (ATR, momentum, RSI, EMA, ADX, Bollinger, breakout) from a corporate
action by cutting the history at the split. It has two detectors, and only one
of them is general:

* the **split calendar** (``split_dates``) is authoritative and catches every
  ratio, and
* the **close-ratio fallback** only fires at ``MAX_CONTINUOUS_CLOSE_RATIO``
  (4.0), so the common 2:1 / 3:1 / 3:2 splits are invisible to it.

``tests/test_cross_source_hardening.py`` already proves the reset itself works
when ``split_dates`` is handed in. What it cannot see is the *plumbing*: it
calls ``homogeneous_price_history`` directly, so dropping ``split_dates=`` from
a production call site — or unwiring ``get_splits_calendar`` in
``_atr14_by_symbol`` — leaves that test green while every sub-4x split silently
re-enters the ATR.

Audit 2026-08-08 measured the cost of that silence on a calm 2 %/day fixture: on
the first session after an unflagged 2:1 split ``atr_pct`` reads 5.46 % instead
of 2.00 % (factor 2.7), decaying to ~2.85 % after 20 sessions. ``atr_pct``
carries the triple-barrier target/stop, the display stop and sizing, so the
error is not cosmetic.

Failure semantics
=================

A new or edited ``homogeneous_price_history`` call site must pass
``split_dates``. If a caller genuinely has no calendar available, add it to
``_CALENDARLESS_CALL_SITES`` with a rationale — that makes the degradation a
decision instead of an accident.
"""
from __future__ import annotations

import ast
import json
from collections.abc import Iterable
from datetime import date, timedelta
from pathlib import Path

import pytest

from open_prep import run_open_prep
from open_prep.atr_quality import MAX_CONTINUOUS_CLOSE_RATIO
from open_prep.run_open_prep import _calculate_atr14_from_eod
from tests._guard_corpus import iter_production_py_files, parse_module, repo_root

_REPO_ROOT = repo_root()
_GUARDED_CALL = "homogeneous_price_history"

# Call sites that deliberately run without a split calendar. Keep empty unless a
# caller provably has no way to obtain one; each entry needs a rationale.
_CALENDARLESS_CALL_SITES: dict[str, str] = {}

_DIR_EXCLUDE = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "venv",
        "node_modules",
        "artifacts",
        "docs",
        "tests",
        "SMC++",
    }
)


def _iter_prod_py() -> Iterable[Path]:
    return iter_production_py_files(_DIR_EXCLUDE)


def _call_sites() -> list[tuple[str, int, ast.Call]]:
    sites: list[tuple[str, int, ast.Call]] = []
    for path in _iter_prod_py():
        tree = parse_module(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name == _GUARDED_CALL:
                sites.append((path.relative_to(_REPO_ROOT).as_posix(), node.lineno, node))
    return sites


def test_every_production_call_site_hands_in_a_split_calendar() -> None:
    sites = _call_sites()
    assert sites, "no homogeneous_price_history call sites found — scan is broken"

    unguarded = [
        f"{rel}:{lineno}"
        for rel, lineno, node in sites
        if not any(kw.arg == "split_dates" for kw in node.keywords)
        and rel not in _CALENDARLESS_CALL_SITES
    ]
    assert not unguarded, (
        "these call sites drop the authoritative split calendar and fall back to "
        f"the >={MAX_CONTINUOUS_CLOSE_RATIO}x close-ratio detector, which is blind "
        f"to 2:1/3:1/3:2 splits: {unguarded}"
    )


def test_split_calendar_is_consulted_before_the_atr_cache() -> None:
    source = (_REPO_ROOT / "open_prep" / "run_open_prep.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    func = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_atr14_by_symbol"
    )
    # Exact constant, not a substring: a renamed-away `get_splits_calendar_OFF`
    # still contains the old name and would keep a `in body` check green.
    looks_up_calendar = any(
        isinstance(node, ast.Constant) and node.value == "get_splits_calendar"
        for node in ast.walk(func)
    )
    assert looks_up_calendar, (
        "_atr14_by_symbol no longer looks up the split calendar — every sub-4x "
        "split now enters the ATR unnoticed"
    )


def test_a_split_symbol_is_never_served_from_the_pre_split_atr_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Behavioural counterpart to the wiring guard above.

    The cache holds a pre-split ATR. If the split map stops gating the cache
    reuse, that stale number is returned verbatim and the reset in
    ``homogeneous_price_history`` never runs for the symbol.
    """
    as_of = date(2026, 5, 20)
    split_day = date(2026, 5, 15)
    stale_pre_split_atr = 2.0  # 2 % of a 100.0 pre-split close

    monkeypatch.setattr(run_open_prep, "ATR_CACHE_DIR", tmp_path)
    # BOTH caches warm — the production steady state. With only the ATR half
    # seeded, the technical-cache miss re-fetches the symbol anyway and would
    # mask a broken cache gate.
    (tmp_path / f"{as_of.isoformat()}_p14.json").write_text(
        json.dumps({
            "as_of": as_of.isoformat(),
            "atr_period": 14,
            "algorithm_version": run_open_prep.ATR_CACHE_ALGORITHM_VERSION,
            "atr14_by_symbol": {"SPLT": stale_pre_split_atr},
            "momentum_z_by_symbol": {"SPLT": 0.0},
            "prev_close_by_symbol": {"SPLT": 100.0},
            "technical_features_by_symbol": {
                "SPLT": run_open_prep._technical_features_from_eod([]),
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        run_open_prep, "_incremental_atr_from_eod_bulk",
        lambda **_kwargs: ({}, {}, {}),
    )

    post_split_close = 50.0

    class _Client:
        def get_splits_calendar(self, _from: date, _to: date) -> list[dict[str, object]]:
            return [{"symbol": "SPLT", "date": split_day.isoformat()}]

        def get_historical_price_eod_full(
            self, _symbol: str, _from: date, _to: date,
        ) -> list[dict[str, object]]:
            rows = [
                {
                    "date": (date(2026, 3, 1) + timedelta(days=index)).isoformat(),
                    "high": 101.0, "low": 99.0, "close": 100.0,
                }
                for index in range(60)
            ]
            rows.extend(
                {
                    "date": (split_day + timedelta(days=index)).isoformat(),
                    "high": post_split_close * 1.01,
                    "low": post_split_close * 0.99,
                    "close": post_split_close,
                }
                for index in range(20)
            )
            return rows

    atr_map = run_open_prep._atr14_by_symbol(_Client(), ["SPLT"], as_of)[0]

    assert atr_map.get("SPLT") != stale_pre_split_atr, (
        "the pre-split cached ATR was served for a symbol with a known split — "
        "the split map no longer gates the cache reuse"
    )
    assert atr_map.get("SPLT") == pytest.approx(post_split_close * 0.02, abs=1e-3)


@pytest.mark.parametrize(
    ("ratio", "min_inflation"),
    [(2.0, 1.20), (3.0, 1.20), (1.5, 1.05)],
)
def test_without_a_calendar_a_sub_threshold_split_stays_undetected(
    ratio: float, min_inflation: float,
) -> None:
    """Gegenprobe: quantifies what the wiring above is actually buying.

    If this ever stops failing to detect the split, the close-ratio fallback got
    stricter and the two tests above may be relaxed — deliberately, not silently.
    """
    assert ratio < MAX_CONTINUOUS_CLOSE_RATIO
    start = date(2026, 5, 1)
    rows: list[dict[str, object]] = [
        {
            "date": (start + timedelta(days=index)).isoformat(),
            "high": 101.0, "low": 99.0, "close": 100.0,
        }
        for index in range(40)
    ]
    split_day = start + timedelta(days=40)
    post = 100.0 / ratio
    rows.extend(
        {
            "date": (split_day + timedelta(days=index)).isoformat(),
            "high": post * 1.01, "low": post * 0.99, "close": post,
        }
        for index in range(20)
    )

    with_calendar = _calculate_atr14_from_eod(rows, period=14, split_dates={split_day})
    without_calendar = _calculate_atr14_from_eod(rows, period=14)

    assert with_calendar == pytest.approx(post * 0.02, abs=1e-4)
    assert without_calendar >= with_calendar * min_inflation, (
        f"a {ratio}:1 split is below the {MAX_CONTINUOUS_CLOSE_RATIO}x fallback, so "
        "only the calendar can catch it"
    )
