"""Repository guardrails against fixed-offset market-time regressions."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRODUCTION_SUFFIXES = {".py", ".ts", ".js", ".mjs"}
SKIP_PARTS = {".git", ".venv", "node_modules", "tests", "artifacts", "docs"}


def _production_sources() -> list[Path]:
    return [
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and path.suffix in PRODUCTION_SUFFIXES
        and not SKIP_PARTS.intersection(path.relative_to(ROOT).parts)
    ]


def test_market_time_code_has_no_fixed_offset_timezone_objects() -> None:
    """Fixed-offset tzinfo objects cannot model regional DST calendars."""
    pattern = re.compile(
        r"(?:datetime\.)?timezone\s*\(\s*(?:datetime\.)?timedelta\s*\(\s*hours\s*=",
    )
    offenders = []
    for path in _production_sources():
        text = path.read_text(encoding="utf-8", errors="ignore")
        if pattern.search(text):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], f"fixed-offset timezone objects found: {offenders}"


def test_market_session_sources_use_regional_iana_zones() -> None:
    market_hours = (ROOT / "services/live_overlay_daemon/market_hours.py").read_text()
    session_context = (ROOT / "scripts/smc_session_context_block.py").read_text()
    fx_sessions = (ROOT / "scripts/fx_probe_universe.py").read_text()

    for source in (market_hours, session_context, fx_sessions):
        assert '"America/New_York"' in source
        assert '"Europe/London"' in source
    assert '"Asia/Tokyo"' in session_context
    assert '"Asia/Tokyo"' in fx_sessions
    assert "fallback_start_utc" not in market_hours
    assert "FIXED UTC offsets" not in session_context


def test_known_dst_blind_markers_are_not_reintroduced() -> None:
    offenders = []
    for path in _production_sources():
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "KNOWN DST-BLIND" in text or "13:30–20:00 UTC Mon–Fri" in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], f"DST-blind market-time markers found: {offenders}"
