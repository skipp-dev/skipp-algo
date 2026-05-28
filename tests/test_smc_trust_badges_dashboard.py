"""ENG-WS2-03 — Trust/Freshness badges in dashboards.

These tests pin the contract that both the desktop dashboard
(``SMC_Dashboard.pine``) and the mobile dashboard
(``SMC_Mobile_Dashboard.pine``) consume the canonical product-trust state
emitted by the generated library (``mp.TRUST_STATE`` /
``mp.TRUST_DEGRADATION_REASON`` / ``mp.TRUST_ACTION_IMPACT``) and surface a
visible degradation cue without requiring Audit View.

The assertions are deliberately string-pinned (substring contracts) in the
same style as ``tests/test_tradingview_decision_first_ui.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DESKTOP = REPO_ROOT / "SMC_Dashboard.pine"
MOBILE = REPO_ROOT / "SMC_Mobile_Dashboard.pine"


def _read(path: Path) -> str:
    if not path.exists():
        pytest.skip(f"{path.name} is not present in the workspace")
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# SMC_Dashboard.pine
# ---------------------------------------------------------------------------


def test_desktop_dashboard_defines_product_trust_badge_helpers() -> None:
    source = _read(DESKTOP)
    assert "product_trust_badge_text(string trust_state, string degradation_reason)" in source
    assert "product_trust_badge_state(string trust_state)" in source
    # Contract: badge text must cover every TrustState the Python helper
    # produces (HEALTHY / DEGRADED / STALE / WATCH_ONLY / UNAVAILABLE).
    for token in ('"healthy"', '"degraded"', '"stale"', '"watch_only"', '"unavailable"'):
        assert token in source, f"product trust badge missing branch for {token}"


def test_desktop_dashboard_default_surfaces_consume_product_trust_state() -> None:
    source = _read(DESKTOP)
    # Decision Brief (default) and the Compact view must both attach the
    # canonical product trust badge to their Trust / Data row, so degraded
    # state is visible without entering Audit View.
    assert source.count("product_trust_badge_text(mp.TRUST_STATE, mp.TRUST_DEGRADATION_REASON)") >= 3
    assert source.count("product_trust_badge_state(mp.TRUST_STATE)") >= 3
    # The badge prefix the Trust / Data rows use.
    assert ' | data: " + product_trust_badge_text(mp.TRUST_STATE' in source


def test_desktop_dashboard_hero_surface_includes_product_trust_badge() -> None:
    source = _read(DESKTOP)
    # The Hero surface must compose its trust line from the hero state plus
    # the new product trust badge ("· data: …" suffix).
    assert "h_trust + ((h_trust == \"degraded\" or h_trust == \"stale\" or h_trust == \"unavailable\") ? \" ⚠\" : \"\") + \" · data: \" + product_trust_badge_text(mp.TRUST_STATE, mp.TRUST_DEGRADATION_REASON)" in source
    # Hero row state must clamp to the worse of legacy hero trust state and
    # product trust state, so a stale/watch-only/unavailable product trust
    # state always paints the row warning/bad.
    assert "h_trust_state_legacy < h_trust_state_product ? h_trust_state_legacy : h_trust_state_product" in source


# ---------------------------------------------------------------------------
# SMC_Mobile_Dashboard.pine
# ---------------------------------------------------------------------------


def test_mobile_dashboard_consumes_product_trust_state() -> None:
    source = _read(MOBILE)
    assert "string product_trust_m = mp.TRUST_STATE" in source
    # Mobile uses the same emoji vocabulary as the desktop badge so the
    # surfaces stay visually coherent.
    for token in ('"healthy"', '"degraded"', '"stale"', '"watch_only"', '"unavailable"'):
        assert token in source, f"mobile trust badge missing branch for {token}"
    # Context cell paints bear when the product trust state is degraded
    # even if the legacy hero trust state still reports healthy.
    assert "product_trust_bad_m or hero_trust_m == \"degraded\"" in source


def test_mobile_context_text_uses_product_trust_emoji() -> None:
    source = _read(MOBILE)
    # #55: mobile context surfaces the awaiting-data sentinel via
    # hero_market_display ("⚪ awaiting data" when HERO_MARKET_MODE == "UNKNOWN").
    assert 'string context_text = hero_market_display + " · " + product_trust_emoji_m' in source
