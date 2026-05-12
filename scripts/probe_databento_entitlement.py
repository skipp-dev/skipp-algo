"""Live probe for Databento dataset entitlement (provider audit 2026-05-12).

Provider-utilization audit row "Verify Databento dataset entitlement via
``client.metadata.list_datasets()``; document tier" — the OPRA UOA migration
landed on the assumption that ``DATABENTO_API_KEY`` is entitled to
``OPRA.PILLAR``, but the audit also flagged a broader dormancy delta:
``mbo`` / ``mbp-1`` / ``mbp-10`` / ``definition`` / ``statistics`` /
``imbalance`` / ``cmbp-1`` / ``cbbo-1s`` schemas are all currently
NOT consumed by any cron and could materially improve SMC liquidity
context, pre-market briefing, and FMP load if wired.

This script enumerates the authoritative entitlement by:

1. Calling ``client.metadata.list_datasets()`` to enumerate ALL datasets
   the configured API key can access.
2. For each accessible dataset, calling ``client.metadata.get_dataset_range``
   and ``client.metadata.list_schemas`` (when available) to print the
   per-schema coverage window.
3. Probing the existing project-preferred dataset list
   (``PREFERRED_DATABENTO_DATASETS``) so the operator can see which item
   the auto-selector would pick.
4. Flagging the high-value schemas from the audit (``imbalance``,
   ``definition``, ``mbo``, ``statistics``, ``cmbp-1``, ``cbbo-1s``,
   and any ``OPRA.PILLAR`` membership) with ENTITLED / NOT-ENTITLED.

Usage::

    DATABENTO_API_KEY=... python -m scripts.probe_databento_entitlement

The output is intended to be pasted into the audit follow-up doc so the
tier-upgrade decision (extend to OPRA.PILLAR? add imbalance schema?) has
ground truth attached.

This is a READ-ONLY probe. It does not write artifacts, send any data,
or mutate state. No retries — a single failed metadata call exits non-
zero so the failure is visible.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

# High-value schemas the provider-audit (2026-05-12) called out as
# dormant-but-strategic. We probe each of these per dataset so the
# operator can decide whether the current tier already includes them
# or a tier upgrade is needed.
_AUDIT_FOCUS_SCHEMAS: tuple[str, ...] = (
    # SMC microstructure (mbp/mbo)
    "mbo", "mbp-1", "mbp-10",
    # Reference / corp actions
    "definition",
    # Daily OHLC + bid/ask stats (cheaper than trades re-aggregation)
    "statistics",
    # Pre-market signal currently absent
    "imbalance",
    # Consolidated NBBO 1s (spread/liquidity granularity)
    "cmbp-1", "cbbo-1s",
    # Options flow (drives OPRA UOA migration)
    "trades",
)

# Datasets we strategically care about per the audit. The probe annotates
# whether the key is entitled to each.
_AUDIT_FOCUS_DATASETS: tuple[str, ...] = (
    "OPRA.PILLAR",        # Options \u2014 retires Unusual Whales
    "DBEQ.BASIC",         # Default equity feed
    "XNAS.ITCH",          # NASDAQ depth (mbo / mbp-10)
    "GLBX.MDP3",          # CME (futures, not currently used)
    "XNYS.PILLAR",        # NYSE PILLAR (mbp depth)
    "OPRA.AUCTION",       # Options auction
    "DBEQ.MAX",           # Premium equity bundle
)


def _get_api_key() -> str:
    """Return the configured Databento API key, or exit if missing."""
    key = os.environ.get("DATABENTO_API_KEY", "").strip()
    if not key:
        sys.stderr.write(
            "ERROR: DATABENTO_API_KEY is not set. Cannot probe entitlement.\n"
        )
        sys.exit(2)
    return key


def _try_call(label: str, fn, *args, **kwargs) -> Any:
    """Call ``fn`` and return its result, or a ``{'error': ...}`` sentinel.

    We never raise out of this helper because the probe is meant to be
    informational: a 4xx on one schema should not abort the rest of the
    report.
    """
    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 \u2014 probe wants the message
        return {"_error": f"{label} failed: {type(exc).__name__}: {exc}"}


def _format_section(title: str) -> str:
    bar = "=" * len(title)
    return f"\n{title}\n{bar}\n"


def main() -> int:
    api_key = _get_api_key()
    try:
        from databento_client import _make_databento_client
    except Exception as exc:
        sys.stderr.write(f"ERROR: cannot import databento_client: {exc}\n")
        return 2
    try:
        client = _make_databento_client(api_key)
    except Exception as exc:
        sys.stderr.write(f"ERROR: cannot construct Databento client: {exc}\n")
        return 2

    print(_format_section("Databento entitlement probe \u2014 2026-05-12"))
    print(f"Key fingerprint: ...{api_key[-4:]}  (last 4 chars only)")

    # ------------------------------------------------------------------
    # 1. Enumerate all accessible datasets
    # ------------------------------------------------------------------
    print(_format_section("1. Accessible datasets (client.metadata.list_datasets)"))
    datasets_raw = _try_call("list_datasets", client.metadata.list_datasets)
    if isinstance(datasets_raw, dict) and "_error" in datasets_raw:
        print(f"  ERROR: {datasets_raw['_error']}")
        return 1
    if not datasets_raw:
        print("  (no datasets returned)")
        return 1
    datasets = sorted(str(d) for d in datasets_raw)
    print(f"  Total: {len(datasets)} datasets")
    for ds in datasets:
        print(f"    - {ds}")

    accessible = set(datasets)

    # ------------------------------------------------------------------
    # 2. Audit-focus dataset entitlement table
    # ------------------------------------------------------------------
    print(_format_section("2. Audit-focus dataset entitlement"))
    print("  Dataset                Entitled?")
    print("  ---------------------- ---------")
    for ds in _AUDIT_FOCUS_DATASETS:
        flag = "YES" if ds in accessible else "NO"
        print(f"  {ds:<22} {flag}")

    opra_entitled = "OPRA.PILLAR" in accessible
    print()
    print(
        f"  OPRA.PILLAR entitled: {opra_entitled}  \u2014 "
        + (
            "OK, ENABLE_OPRA_UOA can be flipped to 1."
            if opra_entitled
            else "NOT entitled. OPRA UOA migration blocked until tier upgrade."
        )
    )

    # ------------------------------------------------------------------
    # 3. Per-dataset schema coverage (for the focus datasets only \u2014 we
    #    don't want a 10x explosion of metadata calls in the report).
    # ------------------------------------------------------------------
    print(_format_section("3. Schema coverage (focus datasets)"))
    for ds in _AUDIT_FOCUS_DATASETS:
        if ds not in accessible:
            continue
        ds_range = _try_call(
            f"get_dataset_range({ds})",
            client.metadata.get_dataset_range,
            dataset=ds,
        )
        print(f"\n  -- {ds} --")
        if isinstance(ds_range, dict) and "_error" in ds_range:
            print(f"    range: {ds_range['_error']}")
            continue
        start = ""
        end = ""
        schemas: list[str] = []
        if isinstance(ds_range, dict):
            start = str(ds_range.get("start", ""))
            end = str(ds_range.get("end", ""))
            schema_field = ds_range.get("schema") or ds_range.get("schemas")
            if isinstance(schema_field, dict):
                schemas = sorted(schema_field.keys())
            elif isinstance(schema_field, (list, tuple)):
                schemas = sorted(str(s) for s in schema_field)
        print(f"    range:   {start}  ->  {end}")
        if schemas:
            print(f"    schemas: {', '.join(schemas)}")
        else:
            print("    schemas: (none reported by get_dataset_range)")

        # Cross-tab with the audit-focus schema list
        if schemas:
            schema_set = set(schemas)
            for s in _AUDIT_FOCUS_SCHEMAS:
                flag = "YES" if s in schema_set else "no"
                print(f"      [{flag}] {s}")

    # ------------------------------------------------------------------
    # 4. PREFERRED_DATABENTO_DATASETS check
    # ------------------------------------------------------------------
    print(_format_section("4. PREFERRED_DATABENTO_DATASETS selection"))
    try:
        from databento_client import PREFERRED_DATABENTO_DATASETS as _PREF
    except Exception as exc:
        print(f"  (could not import PREFERRED_DATABENTO_DATASETS: {exc})")
    else:
        picked = None
        for ds in _PREF:
            if ds in accessible:
                picked = ds
                break
        print(f"  Preferred order: {list(_PREF)}")
        print(f"  Auto-selector would pick: {picked or '(fallback: DBEQ.BASIC)'}")

    print(_format_section("Done"))
    return 0 if opra_entitled or accessible else 1


if __name__ == "__main__":
    sys.exit(main())
