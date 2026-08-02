#!/usr/bin/env python3
"""Refuse a mutating TradingView run while the operator claims the account.

The operator's browser is the normal production writer on the TradingView
account and automation is the guest; TradingView autosaves from that browser.
Until now the two coordinated by convention -- ``tv-save-consumer-source``
itself says so: "No mechanism detects or excludes that session."

This is that mechanism, in the one direction it can honestly cover: CI starting
while the operator is working. It cannot detect an undeclared session, and it
does not touch the opposite direction (a tab opened mid-run), which stays with
``tv-post-mutation-verify``.

The repository variable holds an EXPIRY, not a boolean, so a forgotten claim
cannot block the pipeline past its own timestamp::

    gh variable set TV_OPERATOR_ACTIVE --body "2026-08-02T22:00:00Z"

Read-only runs are never gated: they write nothing, and gating them would let an
open window suppress exactly the verification that makes the window safe.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

VARIABLE = "TV_OPERATOR_ACTIVE"
CLEAR_COMMAND = f"gh variable delete {VARIABLE}"


def _parse(raw: str) -> datetime:
    text = raw.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("timestamp has no UTC offset")
    return parsed


def evaluate(raw: str | None, now: datetime) -> tuple[int, str]:
    """Return ``(exit_code, message)``. Exit code 1 means: do not mutate."""
    if raw is None or not raw.strip():
        return 0, ""
    try:
        until = _parse(raw)
    except ValueError as error:
        return 1, (
            f"{VARIABLE} is set to {raw!r}, which is not an ISO-8601 timestamp "
            f"with a UTC offset ({error}). Refusing to mutate TradingView while "
            f"the operator's claim cannot be read. Clear it with: {CLEAR_COMMAND}"
        )
    if until <= now:
        return 0, f"{VARIABLE} expired at {until.isoformat()} -- proceeding."
    minutes = int((until - now).total_seconds() // 60)
    return 1, (
        f"The operator claims the TradingView account until {until.isoformat()} "
        f"({minutes} min from now). Refusing to mutate: a CI write now would race "
        f"the operator's browser, whose autosave is unserialised. Wait for the "
        f"window to expire, or end it early with: {CLEAR_COMMAND}"
    )


def main() -> int:
    argparse.ArgumentParser(description="Gate mutating TradingView runs on the operator window.").parse_args()
    code, message = evaluate(os.environ.get(VARIABLE), datetime.now(timezone.utc))
    if message:
        print(f"::{'error' if code else 'notice'}::{message}")
    return code


if __name__ == "__main__":
    sys.exit(main())
