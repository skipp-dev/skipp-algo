"""Unit tests for scripts.ib_connectivity_smoke (Copilot review #2769).

Covers:
- Argument parsing (defaults + --allow-live-port)
- Live-port refusal path (returns 1, ib_async import never attempted)
- ib_async ImportError exit code (returns 2)
- scripts.ib_client_id ImportError exit code (returns 1)
- Connected but empty accounts → returns 1
- Connected but non-DU* (live) accounts → returns 1

Fully offline: no real TWS connection is made.
"""

from __future__ import annotations

import sys
import types

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
def test_live_port_refused_without_flag(
    port: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """main() returns 1 immediately and never attempts ib_async import."""
    # Poisoning ib_async would cause rc=2 if the import were reached;
    # getting rc=1 proves the live-port guard fires first.
    monkeypatch.setitem(sys.modules, "ib_async", None)
    rc = mod.main(["--ib-port", str(port)])
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


def test_missing_ib_client_id_module_returns_1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If scripts.ib_client_id is not importable, main() must return 1."""
    # Provide an ib_async stub with IB so we pass that import and reach
    # the ib_client_id import branch.
    ib_stub = types.ModuleType("ib_async")
    ib_stub.IB = object  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ib_async", ib_stub)
    monkeypatch.setitem(sys.modules, "scripts.ib_client_id", None)
    rc = mod.main([])
    assert rc == 1


def _make_fake_ib(accounts: list[str]) -> object:
    """Return a minimal fake IB client suitable for the connected-path tests."""

    class FakeWrapper:
        pass

    class FakeClient:
        def serverVersion(self) -> int:
            return 176

    class FakeIB:
        wrapper = FakeWrapper()
        client = FakeClient()

        def connect(self, **_kw: object) -> None:
            pass

        def isConnected(self) -> bool:
            return True

        def disconnect(self) -> None:
            pass

    fw = FakeWrapper()
    fw.accounts = set(accounts)  # type: ignore[attr-defined]
    fi = FakeIB()
    fi.wrapper = fw
    return fi


def _patch_for_connected(
    monkeypatch: pytest.MonkeyPatch,
    accounts: list[str],
) -> None:
    """Wire up ib_async + ib_client_id stubs and a fake IB session."""
    fake_ib = _make_fake_ib(accounts)

    ib_stub = types.ModuleType("ib_async")
    ib_stub.IB = lambda: fake_ib  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ib_async", ib_stub)

    cid_stub = types.ModuleType("scripts.ib_client_id")
    cid_stub.allocate_ib_client_id = lambda _svc: 99  # type: ignore[attr-defined]
    cid_stub.release_ib_client_id = lambda _cid: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "scripts.ib_client_id", cid_stub)


def test_connected_empty_accounts_returns_1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Connected but no managed account → return 1."""
    _patch_for_connected(monkeypatch, accounts=[])
    rc = mod.main(["--ib-client-id", "1"])
    assert rc == 1


def test_connected_live_accounts_returns_1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Connected but non-DU* (live) accounts → return 1 (safety guard)."""
    _patch_for_connected(monkeypatch, accounts=["U1234567"])
    rc = mod.main(["--ib-client-id", "1"])
    assert rc == 1


def test_connected_paper_account_returns_0(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Connected with a valid DU* paper account → return 0 (smoke OK)."""
    _patch_for_connected(monkeypatch, accounts=["DUP862066"])
    rc = mod.main(["--ib-client-id", "1"])
    assert rc == 0



def test_auto_allocated_client_id_is_released_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No --ib-client-id: allocate_ib_client_id is called and released on success."""
    allocated: list[str] = []
    released: list[int] = []

    fake_ib = _make_fake_ib(["DUP862066"])
    ib_stub = types.ModuleType("ib_async")
    ib_stub.IB = lambda: fake_ib  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ib_async", ib_stub)

    cid_stub = types.ModuleType("scripts.ib_client_id")
    cid_stub.allocate_ib_client_id = lambda svc: (allocated.append(svc), 42)[1]  # type: ignore[attr-defined]
    cid_stub.release_ib_client_id = lambda cid: released.append(cid)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "scripts.ib_client_id", cid_stub)

    rc = mod.main([])  # omit --ib-client-id → exercises auto-allocation branch
    assert rc == 0
    assert allocated == ["c13_connectivity_smoke"]
    assert released == [42]


def test_connect_exception_releases_allocated_client_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If connect() raises, the auto-allocated client-id is still released.

    This path exercises the explicit release inside the connect ``except``
    block. The separate connected-path tests cover the release in the
    connected ``finally`` block.
    """
    released: list[int] = []

    class _ConnectRaising:
        """IB stub whose connect() always raises."""
        def connect(self, **_kw: object) -> None:
            raise ConnectionRefusedError("no gateway (test)")

    ib_stub = types.ModuleType("ib_async")
    ib_stub.IB = _ConnectRaising  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ib_async", ib_stub)

    cid_stub = types.ModuleType("scripts.ib_client_id")
    cid_stub.allocate_ib_client_id = lambda _svc: 99  # type: ignore[attr-defined]
    cid_stub.release_ib_client_id = lambda cid: released.append(cid)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "scripts.ib_client_id", cid_stub)

    rc = mod.main([])
    assert rc == 1, "connect failure must return exit-code 1"
    assert released == [99], "client-id must be released even when connect raises"
