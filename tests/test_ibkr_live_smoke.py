"""Live IBKR Paper-TWS smoke test for the ib_async client wrapper.

The actual ib_insync → ib_async migration landed in PR #1955 and was
hand-verified against a developer's local Paper TWS that day. This test
bakes that round-trip into the suite as a *recurring* guard so future
regressions of the SDK swap (e.g. import paths, API drift, asyncio
loop handling) get caught automatically when a contributor happens to
have Paper TWS open.

Skip behaviour
==============
The test is **always skipped on CI and on machines without TWS**:

1. ``pytest.importorskip("ib_async")`` — skip if the SDK is not
   installed (it lives in ``requirements.txt``, but we do not want a
   hard import error if a downstream consumer trims requirements).
2. ``socket.create_connection(("127.0.0.1", 7497), timeout=0.3)`` —
   skip if the IBKR Paper-TWS API socket is closed. CI hosts and most
   contributor machines will hit ``ConnectionRefusedError`` here and
   the test bails out without contacting any external service.

Only when both are true does the test actually open a TWS session.

Why ``clientId=99``
===================
The producer / live-trading paths in this repo use clientIds in the
1..16 range (see ``terminal_*`` IBKR wiring). Picking 99 keeps the
smoke test from clobbering a locally-running production session that
happens to share the TWS instance.
"""

from __future__ import annotations

import socket

import pytest

# Soft import: skip the whole module if ib_async is not installed.
ib_async = pytest.importorskip("ib_async")  # noqa: F841 -- kept for the side effect


_PAPER_TWS_HOST = "127.0.0.1"
_PAPER_TWS_PORT = 7497
_CLIENT_ID = 99
_CONNECT_TIMEOUT_S = 10
_PROBE_TIMEOUT_S = 0.3


def _paper_tws_reachable() -> bool:
    """Return True iff the Paper-TWS API port accepts a TCP connection.

    Uses a very short timeout so this probe is essentially free on hosts
    where TWS is not running (the kernel returns ECONNREFUSED
    immediately on loopback).
    """

    try:
        with socket.create_connection(
            (_PAPER_TWS_HOST, _PAPER_TWS_PORT),
            timeout=_PROBE_TIMEOUT_S,
        ):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _paper_tws_reachable(),
    reason=(
        f"IBKR Paper TWS not reachable on "
        f"{_PAPER_TWS_HOST}:{_PAPER_TWS_PORT} "
        "(start TWS in Paper mode with API enabled to run this test)."
    ),
)


def test_ib_async_paper_tws_roundtrip() -> None:
    """Connect to Paper TWS via ib_async and exercise the read-only API.

    Steps:
      1. Connect (asserts ``serverVersion > 0``).
      2. ``qualifyContracts`` for AAPL on SMART (asserts ``conId > 0``).
      3. ``reqContractDetails`` (asserts the round-tripped conId).

    No orders, no market-data subscriptions that incur fees, no writes —
    purely a SDK-level handshake that proves the ib_async swap is
    end-to-end functional.
    """

    from ib_async import IB, Stock

    ib = IB()
    try:
        ib.connect(
            _PAPER_TWS_HOST,
            _PAPER_TWS_PORT,
            clientId=_CLIENT_ID,
            timeout=_CONNECT_TIMEOUT_S,
        )
        assert ib.isConnected(), "ib_async failed to establish a TWS session"
        assert ib.client.serverVersion() > 0, "TWS reported no server version"

        qualified = ib.qualifyContracts(Stock("AAPL", "SMART", "USD"))
        assert len(qualified) == 1, f"expected exactly 1 qualified contract, got {len(qualified)}"
        aapl = qualified[0]
        assert aapl.conId > 0, "qualifyContracts returned a contract with no conId"

        details = ib.reqContractDetails(aapl)
        assert details, "reqContractDetails returned an empty list for AAPL"
        assert details[0].contract.conId == aapl.conId, (
            "reqContractDetails returned a contract whose conId does not match the qualified one"
        )
    finally:
        if ib.isConnected():
            ib.disconnect()
