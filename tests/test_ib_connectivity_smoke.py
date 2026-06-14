"""Unit tests for scripts.ib_connectivity_smoke (Copilot review #2769).

Covers:
- Argument parsing (defaults + --allow-live-port)
- Live-port refusal path (returns 1, ib_async import never attempted)
- ib_async ImportError exit code (returns 2)

Fully offline: no real TWS connection is made.
"""

from __future__ import annotations

import sys

import pytest

import scripts.ib_connectivity_smoke as mod


def test_build_parser_defaults() -> None:
    """Argument defaults match the documented CLI."""
    args = mod._build_parser().parse_args([])
    assert args.ib_host == "127.0.0.1"
    assert args.ib_port == 7497
    assert args.ib_client_id is None
    assert args.timeout == 10.0
    assert args.allow_live_port is False


def test_allow_live_port_flag_sets_true() -> None:
    """--allow-live-port stores True."""
    args = mod._build_parser().parse_args(["--allow-live-port"])
    assert args.allow_live_port is True


@pytest.mark.parametrize("port", sorted(mod._LIVE_PORTS))
def test_live_port_refused_without_flag(port: int) -> None:
    """main() returns 1 immediately and never attempts ib_async import."""
    # We can verify "no import attempted" by ensuring ib_async is absent and
    # confirming we get 1 (not 2, which would mean we reached the import path).
    saved = sys.modules.pop("ib_async", None)
    sys.modules["ib_async"] = None  # would cause rc=2 if import were tried
    try:
        rc = mod.main(["--ib-port", str(port)])
    finally:
        sys.modules.pop("ib_async", None)
        if saved is not None:
            sys.modules["ib_async"] = saved
    assert rc == 1


@pytest.mark.parametrize("port", sorted(mod._LIVE_PORTS))
def test_live_port_allowed_with_flag_proceeds_to_import(
    port: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With --allow-live-port the guard is bypassed; ib_async import is attempted."""
    # Block ib_async so the test stays offline; expect rc=2 (import failed),
    # not rc=1 (guard triggered) — proving the guard was skipped.
    monkeypatch.setitem(sys.modules, "ib_async", None)
    rc = mod.main(["--ib-port", str(port), "--allow-live-port"])
    assert rc == 2


def test_missing_ib_async_returns_2(monkeypatch: pytest.MonkeyPatch) -> None:
    """If ib_async is not installed, main() must return exit code 2."""
    monkeypatch.setitem(sys.modules, "ib_async", None)
    rc = mod.main([])
    assert rc == 2
