#!/usr/bin/env python3
"""Prune a TradingView Playwright storage state down to TradingView's own cookies.

Why this exists
---------------
``tradingview-storage-refresh.yml`` bootstraps every capture from the previous
``TV_STORAGE_STATE`` secret, so whatever the browser collected is carried into
the next capture. Ad and tracking iframes on the TradingView chart (doubleclick,
criteo, rubiconproject, ...) set third-party cookies on every run, and the
storage state grew until the capture no longer fit through an environment
variable: from 2026-09-08 on, every refresh failed in "Validate captured storage
state" with ``/usr/bin/python: Argument list too long`` (exit 126) — Linux caps a
single environment string at 128 KiB — and the secret aged past its 72 h TTL.
A local capture measured 2026-10-05 held 3 106 cookies (903 KiB); 19 of them
(4 KiB) belonged to TradingView.

The TradingView session lives in TradingView's cookies (``sessionid``,
``sessionid_sign``, ``device_t`` on ``.tradingview.com``). Nothing in the
automation reads a third-party cookie, so they are dropped here before the
capture is validated and written back. Pruning also keeps the gzip+base64
payload far below the 48 KB limit of an Actions secret.

Refuses (exit 1, file untouched) when the pruned state carries no ``sessionid``
cookie: a domain-matching mistake here would otherwise rotate an unusable
session into the secret, and the age probe that runs next would not notice.

Prints counts and sizes only — never cookie names or values.

Usage::

    python -m scripts.tv_prune_storage_state STATE_JSON [--out OUT_JSON]   # from the repo root

Without ``--out`` the file is rewritten in place (atomically via
``scripts.smc_atomic_write``, mode preserved). Stdlib only at runtime, so it
runs on a bare CI runner without the repo's venv.
"""

from __future__ import annotations

import argparse
import base64
import gzip
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from scripts.smc_atomic_write import atomic_write_text

TRADINGVIEW_DOMAIN = "tradingview.com"
SESSION_COOKIE = "sessionid"


def is_tradingview_host(host: str) -> bool:
    """True for ``tradingview.com`` and any subdomain of it (cookie domains may lead with a dot)."""
    host = (host or "").strip().lstrip(".").lower()
    return host == TRADINGVIEW_DOMAIN or host.endswith("." + TRADINGVIEW_DOMAIN)


def prune_storage_state(state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    """Return (pruned state, stats). Keeps TradingView cookies and origins; every other key unchanged."""
    cookies = state.get("cookies") or []
    origins = state.get("origins") or []
    kept_cookies = [c for c in cookies if is_tradingview_host(str(c.get("domain", "")))]
    kept_origins = [o for o in origins if is_tradingview_host(urlparse(str(o.get("origin", ""))).hostname or "")]
    pruned = dict(state)
    pruned["cookies"] = kept_cookies
    pruned["origins"] = kept_origins
    stats = {
        "cookies_before": len(cookies),
        "cookies_after": len(kept_cookies),
        "origins_before": len(origins),
        "origins_after": len(kept_origins),
        "session_cookies": sum(1 for c in kept_cookies if c.get("name") == SESSION_COOKIE),
    }
    return pruned, stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("state", help="Playwright storage-state JSON (plain JSON, as written by the capture script)")
    parser.add_argument("--out", help="Write the pruned state here instead of rewriting STATE in place")
    args = parser.parse_args(argv)

    source = Path(args.state)
    try:
        raw = source.read_text(encoding="utf-8")
        state = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: cannot read storage state {source}: {type(exc).__name__}", file=sys.stderr)
        return 1
    if not isinstance(state, dict):
        print(f"error: {source} is not a storage-state object", file=sys.stderr)
        return 1

    pruned, stats = prune_storage_state(state)
    if stats["session_cookies"] == 0:
        print(
            f"error: no '{SESSION_COOKIE}' cookie on {TRADINGVIEW_DOMAIN} after pruning "
            f"({stats['cookies_after']} of {stats['cookies_before']} cookies kept) — refusing to write an unusable session",
            file=sys.stderr,
        )
        return 1

    text = json.dumps(pruned, indent=2)
    target = Path(args.out) if args.out else source
    atomic_write_text(text, target)
    # Same encoding the write-back step uses (gzip -9 + base64). Printed so
    # every run shows how close the secret is to GitHub's 48 KiB limit.
    secret_bytes = len(base64.b64encode(gzip.compress(text.encode("utf-8"), compresslevel=9)))
    print(
        f"Pruned storage state: cookies {stats['cookies_before']} -> {stats['cookies_after']}, "
        f"origins {stats['origins_before']} -> {stats['origins_after']}, "
        f"size {len(raw.encode('utf-8')) / 1024:.1f} KiB -> {len(text.encode('utf-8')) / 1024:.1f} KiB, "
        f"secret payload {secret_bytes} bytes (limit 48000)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
