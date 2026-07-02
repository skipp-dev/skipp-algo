"""Regression test for WP-B4 (pipeline/data/ops audit, HIGH).

The daemon serves token-in-path routes (``/{token}/smc_live``,
``/{token}/metrics``). uvicorn's default access log would write the full
request path — including the secret token — to stdout / Railway logs.

Pin ``access_log=False`` on the ``uvicorn.run`` call so tokens never leak.
Request counting is handled separately via ``observability.metric_counter``.
"""

from __future__ import annotations

from pathlib import Path

_MAIN = Path(__file__).resolve().parents[1] / "services" / "live_overlay_daemon" / "main.py"


def test_uvicorn_access_log_disabled() -> None:
    src = _MAIN.read_text()
    assert "access_log=False" in src, (
        "WP-B4: uvicorn.run must set access_log=False so /{token}/… paths "
        "never leak the secret token into stdout / Railway logs."
    )
