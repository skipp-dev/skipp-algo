"""Slim-image guard: ``streamlit_dashboard`` must import without trader deps."""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator

import pytest


class _BlockMissing:
    """meta_path finder that raises ImportError for blocked module names."""

    def __init__(self, blocked: set[str]) -> None:
        self._blocked = blocked

    def find_spec(self, name, path, target=None):  # type: ignore[no-untyped-def]
        if name.split(".")[0] in self._blocked:
            raise ImportError(f"simulated missing module: {name}")
        return None


@pytest.fixture
def block_trader_deps() -> Iterator[None]:
    blocker = _BlockMissing({"httpx", "databento"})
    sys.meta_path.insert(0, blocker)
    # Drop cached modules so re-import takes the blocker into account.
    cached = [
        m
        for m in list(sys.modules)
        if m == "streamlit_dashboard"
        or m.startswith("terminal_tabs")
        or m.startswith("scripts.build_dashboard_payload")
    ]
    for m in cached:
        sys.modules.pop(m, None)
    try:
        yield
    finally:
        sys.meta_path.remove(blocker)
        for m in cached:
            sys.modules.pop(m, None)


def test_streamlit_dashboard_imports_without_trader_deps(
    block_trader_deps: None,
) -> None:
    """Regression: the slim Docker entry must import with the slim reqs only."""

    mod = importlib.import_module("streamlit_dashboard")

    # The four C7 dashboard sub-modules must be importable.
    assert mod.tab_track_record.__name__ == "terminal_tabs.tab_track_record"
    assert mod.tab_live_incubation.__name__ == "terminal_tabs.tab_live_incubation"
    assert mod.tab_calibration_detail.__name__ == "terminal_tabs.tab_calibration_detail"
    assert mod.methodology_drawer.__name__ == "terminal_tabs.methodology_drawer"

    # Trader-tab re-exports must be either None (lazy-guarded) or a callable —
    # never raise ImportError on package access. The point is that the slim
    # surface stays usable; tabs whose deps survived the blocker are also fine.
    import terminal_tabs as tt

    for trader_attr in ("render_movers", "render_bitcoin", "render_fmp_ai"):
        val = getattr(tt, trader_attr, None)
        assert val is None or callable(val)


def test_slim_dockerfile_uses_dashboard_requirements() -> None:
    """``Dockerfile.dashboard`` must install the dashboard lock, not the full root deps."""

    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    contents = (repo_root / "Dockerfile.dashboard").read_text(encoding="utf-8")
    assert "requirements-dashboard.lock" in contents
    assert "pip install --no-cache-dir --require-hashes -r requirements-dashboard.lock" in contents
    # Must NOT pip-install the full root deps — that would defeat the slim sprint.
    assert "pip install --no-cache-dir -r requirements.txt" not in contents
    assert "pip install --no-cache-dir -r requirements.lock" not in contents
    # Entry must be the slim entry, not the full trader app.
    assert "streamlit_dashboard.py" in contents
    assert "streamlit_terminal.py" not in contents


def test_slim_dockerfile_ships_the_brand_theme() -> None:
    """The dashboard image must carry ``.streamlit/config.toml``.

    Its COPY list is an explicit allowlist, so the theme file is easy to
    forget — and when it is missing the image silently falls back to
    Streamlit's default LIGHT theme while the trader surface renders dark.
    That is a cosmetic-only failure, invisible to every other guard, so pin
    it here.
    """
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    contents = (repo_root / "Dockerfile.dashboard").read_text(encoding="utf-8")
    assert "COPY .streamlit/config.toml ./.streamlit/config.toml" in contents

    # The file it ships must actually define a theme, not just exist.
    config = (repo_root / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    assert "[theme]" in config


def test_run_dashboard_sh_native_mode_runs_streamlit_dashboard() -> None:
    """C-sprint deep-review C7 fix: native mode of ``run_dashboard.sh``
    previously launched ``streamlit_terminal.py`` (the live news /
    trading terminal) instead of the read-only Track-Record Dashboard.
    Pin the entrypoint here so the regression cannot recur silently.
    """
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    script = (repo_root / "scripts" / "run_dashboard.sh").read_text(encoding="utf-8")
    assert "streamlit run streamlit_dashboard.py" in script
    assert "streamlit run streamlit_terminal.py" not in script
