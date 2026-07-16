"""Keep active Pine code on TradingView's supported data-access surface.

Pine v6 does not provide arbitrary HTTP GET/POST access. The retired live-
overlay consumers used fictional ``request.raw``/``request.get`` calls and
could therefore compile neither in TradingView nor in CI. A future external
data integration must arrive through a TradingView-supported provider/symbol
surface and use supported Pine calls such as ``request.security``.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_RETIRED_HTTP_CONSUMER = _REPO_ROOT / "pine" / "smc_live_overlay_consumer.pine"
_COMPATIBILITY_TOMBSTONE = _REPO_ROOT / "SMC_Regime_and_News.pine"


def _strip_comments(src: str) -> str:
    """Drop ``//`` line comments so only executable Pine is inspected."""
    return "\n".join(line.partition("//")[0] for line in src.splitlines())


def _active_pine() -> list[Path]:
    paths = set(_REPO_ROOT.glob("*.pine"))
    paths.update((_REPO_ROOT / "pine").glob("*.pine"))
    paths.update((_REPO_ROOT / "pine" / "generated").glob("*.pine"))
    paths.update((_REPO_ROOT / "SMC++").glob("*.pine"))
    return sorted(paths)


_UNSUPPORTED_HTTP_RE = re.compile(r"\brequest\.(?:raw|get|post)\s*\(")


@pytest.mark.parametrize("pine_path", _active_pine(), ids=lambda p: p.relative_to(_REPO_ROOT).as_posix())
def test_active_pine_has_no_fictional_arbitrary_http_calls(pine_path: Path) -> None:
    live = _strip_comments(pine_path.read_text(encoding="utf-8", errors="replace"))
    hit = _UNSUPPORTED_HTTP_RE.search(live)
    assert hit is None, (
        f"{pine_path.relative_to(_REPO_ROOT)} uses unsupported arbitrary HTTP "
        f"({hit.group(0) if hit else ''}). Pine data must use a documented "
        "TradingView request.* source such as request.security; an external "
        "REST endpoint cannot be called directly from Pine."
    )


def test_uncompilable_http_consumers_stay_retired() -> None:
    assert not _RETIRED_HTTP_CONSUMER.exists(), (
        "Retired Pine HTTP consumer reappeared: "
        f"{_RETIRED_HTTP_CONSUMER.relative_to(_REPO_ROOT)}. Implement ADR-0028's provider path instead of restoring "
        "request.raw/request.get placeholders."
    )


def test_regime_and_news_is_an_explicit_network_inert_tombstone() -> None:
    text = _COMPATIBILITY_TOMBSTONE.read_text(encoding="utf-8")
    assert "RETIRED" in text
    assert "ADR-0028" in text
    assert "input." not in _strip_comments(text)
    assert "request." not in _strip_comments(text)
