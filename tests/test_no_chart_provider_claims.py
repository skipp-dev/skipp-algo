"""Guard the supported boundary between Pine and server-side data services."""
from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_TEXT_SUFFIXES = {".md", ".py", ".json", ".yaml", ".yml"}


def _active_boundary_files() -> list[Path]:
    paths = [
        _ROOT / "README.md",
        _ROOT / "CHANGELOG.md",
        *(_ROOT / "docs").rglob("*"),
        *(_ROOT / "services" / "live_overlay_daemon").rglob("*"),
    ]
    return sorted(
        path
        for path in paths
        if path.is_file()
        and path.suffix in _TEXT_SUFFIXES
        and "archive" not in path.parts
    )


def test_active_docs_do_not_restore_fictional_pine_network_delivery() -> None:
    api_names = tuple(
        "request." + suffix for suffix in ("ra" + "w", "g" + "et", "po" + "st")
    )
    provider_claims = (
        "tradingview" + " provider",
        "pine" + " http consumer",
        "pine/overlay requests",
    )
    forbidden = api_names + provider_claims

    hits: list[str] = []
    for path in _active_boundary_files():
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        for phrase in forbidden:
            if phrase in text:
                hits.append(f"{path.relative_to(_ROOT)}: {phrase}")

    assert not hits, (
        "Active documentation restored an unsupported chart-provider data path:\n"
        + "\n".join(hits)
    )
