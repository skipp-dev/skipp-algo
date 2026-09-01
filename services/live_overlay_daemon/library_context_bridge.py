"""Library-context bridge — serves what the static-library flip removed.

Issue #3872 aftermath / sidecar SC-LIB-001: #3790 declared universe, VIX,
event-risk and trust data "runtime-sidecar data" but nothing served them.
VIX and the event-risk gate already ride the ``smc_live`` payload; this
bridge supplies the remaining two — universe membership and provider
trust — parsed from the generated Pine library
(``pine/generated/smc_micro_profiles_generated.pine``), fetched at runtime
from :func:`config.library_context_pine_url` with the copy baked into the
image as fallback.

The runtime fetch replaced an image-only read on 2026-09-01. The old docstring
justified the image read with "the daemon [...] redeploys on every main push".
That is false *by design*: the daemon deploys only via
``deploy-live-overlay-daemon.yml``, path-filtered to
``services/live_overlay_daemon/**``, and this library lives outside that path —
so a library refresh could never redeploy it. Measured: between the 08-21 and
08-30 deploys main moved the file 87 times while the daemon served
``UNIVERSE_SIZE=6960`` and a universe from 08-20 against main's 6952, i.e. nine
days of ``universe_member`` decided on a stale list, with nothing alerting.
Every sibling bridge (evidence_freshness, pine_library_versions, sweep_trap,
tradingview_bindings, provider_usage) already had a runtime source; this was
the only one that did not.

Parsing scope is deliberately tiny: only generator-controlled
``export const`` lines (ASOF_DATE/ASOF_TIME/UNIVERSE_SIZE/PROVIDER_COUNT/
STALE_PROVIDERS + the UNIVERSE_TICKERS part concatenation). Fail-soft:
a missing/unreadable/static (empty-universe) source yields ``None`` fields —
the sidecar renders "—" instead of invented values.
"""
from __future__ import annotations

import base64
import json
import re
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from . import config

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
    return config.library_context_pine_path()


def _is_github_contents_api_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    return parsed.netloc.lower() == "api.github.com" and "/contents/" in parsed.path


def _fetch_url(url: str, token: str, timeout: float = 10.0) -> str | None:
    """Fetch the library source over HTTPS; ``None`` on any failure."""
    if not url.lower().startswith("https://"):
        return None
    headers = {"Accept": "text/plain", "User-Agent": "skipp-library-context/1.0"}
    # The Contents API answers with a base64 metadata envelope unless asked for
    # raw. Without this the body would parse as Pine source, match zero
    # ``export const`` lines and yield an EMPTY context that looks exactly like
    # a legitimate static library — the same trap the pine-library-version
    # bridge documents. ``_looks_like_library`` below is the second net.
    if _is_github_contents_api_url(url):
        headers["Accept"] = "application/vnd.github.raw+json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8")
    except Exception:
        return None


def _decode_github_envelope(body: str) -> str | None:
    """Decode a ``{content, encoding: "base64"}`` envelope to the inner text."""
    try:
        parsed = json.loads(body)
    except ValueError:
        return None
    if not isinstance(parsed, dict):
        return None
    if str(parsed.get("encoding", "")).lower() != "base64" or "content" not in parsed:
        return None
    try:
        return base64.b64decode(str(parsed["content"])).decode("utf-8")
    except (ValueError, TypeError):
        return None


def _looks_like_library(text: str) -> bool:
    """Is *text* actually the generated library, not an error page or envelope?

    Guards the fetch against succeeding with a body that parses to nothing. A
    truncated/wrong response must fall back to the baked file, NOT quietly
    serve empty fields — an empty context is indistinguishable from a static
    library and would read as "scanned, nothing to report".
    """
    return "ASOF_TIME" in text and "export const" in text


def _read_source() -> tuple[str | None, str]:
    """Return ``(library text, source)``; URL first, baked file as fallback.

    The source travels with the text because the two age differently and
    :func:`_load` invalidates them differently — collapsing them to a bare
    string made the file fallback expire on the URL's clock instead of on its
    own mtime.
    """
    url = config.library_context_pine_url()
    if url:
        body = _fetch_url(url, config.library_context_pine_url_token())
        if body is not None:
            text = body if _looks_like_library(body) else (_decode_github_envelope(body) or "")
            if _looks_like_library(text):
                return text, "url"
    try:
        return _pine_path().read_text(encoding="utf-8"), "file"
    except (OSError, UnicodeDecodeError):
        return None, ""


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
        # No baked file is fine now — the URL may still answer. Only a failing
        # URL *and* a missing file yield the empty context, below.
        mtime_ns = None
    # Two invalidation rules, because the two sources age differently: a fetched
    # library expires on a clock (it changes under us with every library
    # refresh), a baked file only when it is rewritten. Using mtime alone —
    # as this bridge did until 2026-09-01 — pins the answer to the image build.
    now_mono = time.monotonic()
    ttl = config.library_context_cache_ttl_secs()
    with _cache_lock:
        if _cache["data"] is not None and _cache["path"] == str(path):
            fetched_at = _cache.get("fetched_at")
            if fetched_at is not None:
                if (now_mono - fetched_at) < ttl:
                    return _cache["data"]
            elif _cache["mtime_ns"] == mtime_ns:
                return _cache["data"]
    text, source = _read_source()
    if text is None:
        return _empty()
    parsed = _parse(text)
    with _cache_lock:
        _cache["fetched_at"] = now_mono if source == "url" else None
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
