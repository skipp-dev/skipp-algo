"""Payload-volume measurement for the generated Pine library (ADR-0029).

Every pre-existing check around the generated microstructure library reads
metadata *about* the payload — ``ASOF_DATE``, ``UNIVERSE_SIZE``, manifest/path
consistency. None reads the payload itself, which is why five library versions
shipped empty and the defect surfaced on a chart rather than in the pipeline.

This module supplies the missing quantity. It is deliberately dependency-free
(stdlib only): the publish-contract verifier and the generator both import it,
and the verifier must stay importable without pandas.

Two properties are load-bearing:

*   **Sharding.** ``render_csv_export`` emits a single literal only while the
    payload fits in ``max_chars``; ``UNIVERSE_TICKERS`` renders at 3900, so a
    healthy 6929-symbol universe becomes ``NAME_PART_1 + "," + NAME_PART_2 …``.
    A parser shaped like the existing ``ASOF_DATE`` regex finds no literal
    there and would score a healthy payload as 0 — inverting every rule built
    on top of it.
*   **Unknown is not empty.** A parse failure yields ``known=False`` rather
    than a count of 0, so an unreadable artifact reads neither as empty nor as
    green. This mirrors the ``data_age_known`` gauge convention.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

#: Membership-list exports, mirroring ``generate_smc_micro_profiles.LIST_EXPORTS``.
#: Duplicated rather than imported to keep this module free of pandas; the two
#: are pinned together by ``test_list_exports_match_the_generator``.
MEMBERSHIP_LIST_EXPORTS = (
    "CLEAN_RECLAIM_TICKERS",
    "STOP_HUNT_PRONE_TICKERS",
    "MIDDAY_DEAD_TICKERS",
    "RTH_ONLY_TICKERS",
    "WEAK_PREMARKET_TICKERS",
    "WEAK_AFTERHOURS_TICKERS",
    "FAST_DECAY_TICKERS",
)

UNIVERSE_TICKERS_EXPORT = "UNIVERSE_TICKERS"

_UNIVERSE_SIZE_RE = re.compile(r"export\s+const\s+int\s+UNIVERSE_SIZE\s*=\s*(\d+)")


def _boundary(name: str) -> str:
    return rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])"


def _split_csv(value: str) -> list[str]:
    return [part for part in value.split(",") if part]


def parse_pine_csv_export(text: str, export_name: str) -> list[str] | None:
    """Return the symbols of a rendered CSV export, or ``None`` if absent.

    Handles both forms ``render_csv_export`` can emit: a single string literal,
    and the sharded ``NAME_PART_n`` concatenation used once the payload exceeds
    ``max_chars``. ``None`` means "not found" and is distinct from ``[]``,
    which means "found and genuinely empty".
    """
    literal = re.search(
        rf"export\s+const\s+string\s+{_boundary(export_name)}\s*=\s*\"([^\"]*)\"",
        text,
    )
    if literal is not None:
        return _split_csv(literal.group(1))

    shards = re.findall(
        rf"const\s+string\s+{re.escape(export_name)}_PART_(\d+)\s*=\s*\"([^\"]*)\"",
        text,
    )
    if not shards:
        return None

    ordered = [chunk for _, chunk in sorted(shards, key=lambda pair: int(pair[0]))]
    return _split_csv(",".join(ordered))


@dataclass(frozen=True)
class PayloadVolume:
    """How much payload the generated library actually carries."""

    universe_size: int | None
    universe_tickers_count: int
    list_total: int
    known: bool


def measure_payload_volume(text: str) -> PayloadVolume:
    """Measure the payload of a rendered Pine library source."""
    size_match = _UNIVERSE_SIZE_RE.search(text)
    universe_size = int(size_match.group(1)) if size_match else None
    universe_tickers = parse_pine_csv_export(text, UNIVERSE_TICKERS_EXPORT)

    list_total = 0
    for export_name in MEMBERSHIP_LIST_EXPORTS:
        symbols = parse_pine_csv_export(text, export_name)
        if symbols is not None:
            list_total += len(symbols)

    return PayloadVolume(
        universe_size=universe_size,
        universe_tickers_count=len(universe_tickers) if universe_tickers is not None else 0,
        list_total=list_total,
        known=universe_size is not None and universe_tickers is not None,
    )


def payload_blocking_reasons(volume: PayloadVolume) -> list[str]:
    """Blocking reasons for the productivity gate.

    Each reason is a *contradiction between two fields*, never a bare emptiness
    check — the incident this guards against was a field (``universe_size``,
    sourced from the base scan) trusted in isolation while the list the
    consumers actually read (sourced from the enrichment sidecar) was empty.
    A contradiction cannot be legitimate, so neither reason needs a threshold
    or an exemption list.

    The reasons apply unconditionally. The static control plane — the one mode
    in which an absent ``UNIVERSE_TICKERS`` was by construction — was retired
    and removed (ADR-0029 decision 3, operator decision 2026-07-22), so no
    mode-dependent suppression exists here.

    An unmeasurable payload blocks nothing; ``known=False`` is surfaced
    separately rather than being read as empty.
    """
    if not volume.known or volume.universe_size is None:
        return []

    if volume.universe_size > 0 and volume.universe_tickers_count == 0:
        return ["empty_universe_tickers"]
    if volume.universe_tickers_count > 0 and volume.list_total == 0:
        return ["empty_membership_lists"]
    return []
