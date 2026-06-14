"""C13 IBKR connectivity smoke — verify TWS / IB Gateway before incubation.

A standalone preflight check for the live-incubation runbook
(:doc:`docs/c8_live_incubation_runbook.md`). It opens a single
``ib_async`` session against the paper gateway, confirms the API socket
answers, prints the negotiated server version + managed accounts, and
disconnects cleanly. It places **no orders** and reads **no market
data** — it proves the socket on the configured host/port (default
``127.0.0.1:7497``) is live and the paper account is logged in.

Run this once after launching TWS / IB Gateway and enabling the API
socket, before kicking off ``scripts.run_smc_live_incubation``.

CLI
---
::

    python -m scripts.ib_connectivity_smoke
    python -m scripts.ib_connectivity_smoke --ib-port 7497 --timeout 10

Exit codes
----------
``0`` connected, paper account present, disconnected cleanly.
``1`` connection failed, timed out, no managed account returned,
    or client-id allocation raised an exception.
``2`` ``ib_async`` is not installed.
"""

from __future__ import annotations

import argparse
import logging
import sys

LOGGER = logging.getLogger("ib_connectivity_smoke")

# IBKR convention: paper TWS = 7497, paper Gateway = 4002,
# live TWS = 7496, live Gateway = 4001. The incubation runbook pins
# paper TWS (7497); guard against accidentally smoke-testing a live port.
_LIVE_PORTS = frozenset({7496, 4001})


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ib_connectivity_smoke",
        description=(
            "Verify the IBKR paper TWS / Gateway API socket is reachable "
            "and logged in. Places no orders and requests no market data."
        ),
    )
    parser.add_argument(
        "--ib-host",
        default="127.0.0.1",
        help="TWS / IB Gateway host (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--ib-port",
        type=int,
        default=7497,
        help="TWS / IB Gateway port (default: 7497, paper TWS).",
    )
    parser.add_argument(
        "--ib-client-id",
        type=int,
        default=None,
        help=(
            "Explicit IB clientId. Default: rotating allocation via "
            "scripts.ib_client_id (service 'c13_connectivity_smoke')."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Connection timeout in seconds (default: 10).",
    )
    parser.add_argument(
        "--allow-live-port",
        action="store_true",
        help=(
            "Permit smoke-testing a live trading port (7496/4001). "
            "Off by default — the runbook is paper-only."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    args = _build_parser().parse_args(argv)

    if args.ib_port in _LIVE_PORTS and not args.allow_live_port:
        LOGGER.error(
            "Refusing to smoke-test live port %s (paper is 7497/4002). "
            "Pass --allow-live-port to override.",
            args.ib_port,
        )
        return 1

    try:
        from ib_async import IB  # local import: optional dependency
    except ImportError:
        LOGGER.error(
            "ib_async is not installed. Install it in the live-incubation "
            "environment (pip install ib_async) before running this smoke."
        )
        return 2

    allocated = False
    client_id = args.ib_client_id
    if client_id is None:
        try:
            from scripts.ib_client_id import allocate_ib_client_id
        except ImportError as exc:
            LOGGER.error("Could not import scripts.ib_client_id: %s", exc)
            return 1
        try:
            client_id = allocate_ib_client_id("c13_connectivity_smoke")
        except Exception as exc:
            LOGGER.error("Could not allocate IB client-id: %s", exc)
            return 1
        allocated = True

    ib_client = IB()
    try:
        ib_client.connect(
            host=args.ib_host,
            port=args.ib_port,
            clientId=client_id,
            timeout=args.timeout,
            readonly=True,
        )
    except Exception as exc:  # pragma: no cover — exercised live
        LOGGER.error(
            "Could not connect to %s:%s (clientId=%s): %s. "
            "Is TWS / IB Gateway running with the API socket enabled?",
            args.ib_host,
            args.ib_port,
            client_id,
            exc,
        )
        if allocated:
            _release(client_id)
        return 1

    try:
        if not ib_client.isConnected():
            LOGGER.error("connect() returned but isConnected() is False.")
            return 1

        accounts = list(getattr(getattr(ib_client, "wrapper", None), "accounts", None) or [])
        server_version = ib_client.client.serverVersion()
        LOGGER.info(
            "Connected to %s:%s (clientId=%s, serverVersion=%s).",
            args.ib_host,
            args.ib_port,
            client_id,
            server_version,
        )
        if not accounts:
            LOGGER.error(
                "Connected but no managed account returned — the gateway "
                "is up but not logged into a (paper) account."
            )
            return 1
        if not all(str(a).startswith("DU") for a in accounts):
            LOGGER.error(
                "Connected to port %s but managed accounts %r are not all "
                "DU* paper accounts — this may be a live TWS. Aborting.",
                args.ib_port,
                accounts,
            )
            return 1
        LOGGER.info("Managed accounts: %s", ", ".join(accounts))
        LOGGER.info("IBKR connectivity smoke OK.")
        return 0
    finally:
        try:
            ib_client.disconnect()
        except Exception:  # pragma: no cover — exercised live
            LOGGER.warning("ib_client.disconnect() failed", exc_info=True)
        # Release runs here unconditionally, even if disconnect() raised.
        # The connect-exception path (see `except Exception` block above)
        # also releases directly, so client-ids are freed in both paths.
        if allocated:
            _release(client_id)


def _release(client_id: int) -> None:
    try:
        from scripts.ib_client_id import release_ib_client_id

        release_ib_client_id(client_id)
    except Exception:  # pragma: no cover
        LOGGER.warning("release_ib_client_id(%s) failed", client_id, exc_info=True)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
