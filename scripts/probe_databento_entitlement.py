"""Read-only Databento catalog, historical-access, and optional live probe.

The filename is retained for operator compatibility. The report deliberately
separates three facts: global catalog membership, historical range access, and
live access. Catalog membership never proves an account entitlement.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence

from databento_access import (
    DatasetAccessStatus,
    inspect_historical_access,
    list_catalog_datasets_from_client,
    probe_live_access,
)

_FOCUS_DATASETS: tuple[str, ...] = (
    "EQUS.MINI",
    "EQUS.SUMMARY",
    "XNAS.ITCH",
    "XNYS.PILLAR",
    "XASE.PILLAR",
    "ARCX.PILLAR",
    "XNAS.BASIC",
    "DBEQ.BASIC",
    "OPRA.PILLAR",
    "GLBX.MDP3",
)


def _get_api_key() -> str:
    key = os.environ.get("DATABENTO_API_KEY", "").strip()
    if not key:
        raise RuntimeError("DATABENTO_API_KEY is not set")
    return key


def _tri(value: bool | None, *, checked: bool = True) -> str:
    if not checked or value is None:
        return "UNKNOWN"
    return "YES" if value else "NO"


def format_status(status: DatasetAccessStatus) -> str:
    """Format one status without collapsing unknown into false."""
    historical = _tri(status.historical_range_available)
    live = _tri(status.live_entitled, checked=status.live_checked)
    history_range = ""
    if status.historical_start or status.historical_end:
        history_range = f" [{status.historical_start or '?'} -> {status.historical_end or '?'}]"
    return (
        f"{status.dataset:<16} catalog={_tri(status.catalog_present):<7} "
        f"historical={historical:<7}{history_range} "
        f"live={live:<7} reason={status.reason}"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", action="append", dest="datasets")
    parser.add_argument(
        "--probe-live",
        action="store_true",
        help="perform a bounded live subscription probe (off by default)",
    )
    parser.add_argument("--live-schema", default="trades")
    parser.add_argument("--live-symbol", default="AAPL")
    parser.add_argument("--live-timeout-seconds", type=float, default=5.0)
    return parser


def run_probe(
    client: object,
    *,
    api_key: str,
    datasets: Sequence[str],
    probe_live: bool,
    live_schema: str,
    live_symbol: str,
    live_timeout_seconds: float,
    catalog_datasets: list[str] | None = None,
) -> list[DatasetAccessStatus]:
    """Collect independent access facts for each requested dataset."""
    catalog = (
        catalog_datasets
        if catalog_datasets is not None
        else list_catalog_datasets_from_client(client)
    )
    statuses: list[DatasetAccessStatus] = []
    for dataset in datasets:
        status = inspect_historical_access(
            client,
            dataset,
            catalog_datasets=catalog,
        )
        if probe_live:
            status = probe_live_access(
                status,
                api_key=api_key,
                schema=live_schema,
                symbol=live_symbol,
                timeout_seconds=live_timeout_seconds,
            )
        statuses.append(status)
    return statuses


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        api_key = _get_api_key()
        from databento_client import _make_databento_client

        client = _make_databento_client(api_key)
        catalog = list_catalog_datasets_from_client(client)
    except Exception as exc:
        from databento_utils import _redact_sensitive_error_text

        message = _redact_sensitive_error_text(f"{type(exc).__name__}: {exc}")
        print(f"ERROR: {message}", file=sys.stderr)
        return 2

    datasets = tuple(dict.fromkeys(str(item).strip().upper() for item in (args.datasets or _FOCUS_DATASETS)))
    if args.probe_live and len(datasets) != 1:
        print("ERROR: --probe-live requires exactly one --dataset", file=sys.stderr)
        return 2
    print("Databento access probe")
    print(f"catalog_count={len(catalog)} (global catalog; not an entitlement list)")
    print("live_probe=" + ("ENABLED" if args.probe_live else "NOT_CHECKED"))

    statuses = run_probe(
        client,
        api_key=api_key,
        datasets=datasets,
        probe_live=args.probe_live,
        live_schema=args.live_schema,
        live_symbol=args.live_symbol,
        live_timeout_seconds=args.live_timeout_seconds,
        catalog_datasets=catalog,
    )
    for status in statuses:
        print(format_status(status))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
