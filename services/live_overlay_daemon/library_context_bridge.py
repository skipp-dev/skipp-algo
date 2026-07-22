"""Library-context bridge — serves what the static-library flip removed.

Issue #3872 aftermath / sidecar SC-LIB-001: #3790 declared universe, VIX,
event-risk and trust data "runtime-sidecar data" but nothing served them.
VIX and the event-risk gate already ride the ``smc_live`` payload; this
bridge supplies the remaining two — universe membership and provider
trust — parsed from the generated Pine library committed in this repo
(``pine/generated/smc_micro_profiles_generated.pine``). The daemon deploys
from the repo image and redeploys on every main push, so the file tracks
each library refresh without any new fetch surface.

Parsing scope is deliberately tiny: only generator-controlled
``export const`` lines (ASOF_DATE/ASOF_TIME/UNIVERSE_SIZE/PROVIDER_COUNT/
STALE_PROVIDERS + the UNIVERSE_TICKERS part concatenation). Fail-soft:
a missing/unreadable/static (empty-universe) file yields ``None`` fields —
the sidecar renders "—" instead of invented values.
"""
from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from typing import Any

DEFAULT_PINE_PATH = "pine/generated/smc_micro_profiles_generated.pine"

_STRING_EXPORT_RE = re.compile(
    r'^export const string (?P<name>[A-Z0-9_]+) = "(?P<value>[^"]*)"', re.MULTILINE
)
_INT_EXPORT_RE = re.compile(
    r"^export const int (?P<name>[A-Z0-9_]+) = (?P<value>-?\d+)", re.MULTILINE
)

_cache_lock = threading.Lock()
# Mutated in place under the lock — no ``global`` statement (statement-budget
# guard) and trivially resettable in tests.
_cache: dict[str, Any] = {"data": None, "mtime_ns": None, "path": None}


def _pine_path() -> Path:
    raw = os.environ.get("LIBRARY_CONTEXT_PINE_PATH", "").strip() or DEFAULT_PINE_PATH
    return Path(raw)


def _empty() -> dict[str, Any]:
    return {
        "universe": frozenset(),
        "universe_size": None,
        "library_asof_date": None,
        "library_asof_time": None,
        "provider_count": None,
        "stale_providers": None,
    }


def _parse(text: str) -> dict[str, Any]:
    strings = {m.group("name"): m.group("value") for m in _STRING_EXPORT_RE.finditer(text)}
    ints = {m.group("name"): int(m.group("value")) for m in _INT_EXPORT_RE.finditer(text)}

    tickers: set[str] = set()
    # Enriched libraries ship the universe as UNIVERSE_TICKERS_PART_1..N
    # (Pine string-literal length cap); a static library exports a single
    # empty UNIVERSE_TICKERS instead.
    for name, value in strings.items():
        if name.startswith("UNIVERSE_TICKERS_PART_") or name == "UNIVERSE_TICKERS":
            tickers.update(t for t in value.split(",") if t.strip())

    return {
        "universe": frozenset(t.strip().upper() for t in tickers),
        "universe_size": ints.get("UNIVERSE_SIZE"),
        "library_asof_date": strings.get("ASOF_DATE") or None,
        "library_asof_time": strings.get("ASOF_TIME") or None,
        "provider_count": ints.get("PROVIDER_COUNT"),
        "stale_providers": strings.get("STALE_PROVIDERS"),
    }


def _load() -> dict[str, Any]:
    path = _pine_path()
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        return _empty()
    with _cache_lock:
        if (
            _cache["data"] is not None
            and _cache["mtime_ns"] == mtime_ns
            and _cache["path"] == str(path)
        ):
            return _cache["data"]
    try:
        parsed = _parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return _empty()
    with _cache_lock:
        _cache["data"] = parsed
        _cache["mtime_ns"] = mtime_ns
        _cache["path"] = str(path)
    return parsed


def context_for_symbol(symbol: str) -> dict[str, Any]:
    """Additive ``smc_live`` payload fields for *symbol*; every value nullable.

    ``universe_member`` is ``None`` (unknown) when the library carries no
    universe (static generation) — never ``False``, which would wrongly
    claim "scanned and absent".
    """
    data = _load()
    ticker = symbol.strip().upper().rsplit(":", 1)[-1]
    universe: frozenset[str] = data["universe"]
    member: bool | None = (ticker in universe) if universe else None

    provider_count = data["provider_count"]
    stale = data["stale_providers"]
    if provider_count is None:
        trust_status: str | None = None
    elif provider_count > 0 and not stale:
        trust_status = "ok"
    elif provider_count > 0:
        trust_status = "degraded"
    else:
        trust_status = "unavailable"

    return {
        "universe_member": member,
        "universe_size": data["universe_size"] if universe else None,
        "library_asof_date": data["library_asof_date"],
        "library_asof_time": data["library_asof_time"],
        "provider_trust_status": trust_status,
        "provider_stale_list": (stale or None) if provider_count is not None else None,
    }
