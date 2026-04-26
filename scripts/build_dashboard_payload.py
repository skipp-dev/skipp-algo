"""C7/T2 — Aggregator: build a self-contained dashboard payload.

Joins the per-sprint JSON outputs (C2 walk-forward, C3 bootstrap CIs,
C4 permutation, C5 regime stratification, C6 PSR / minTRL) into a
single dict that the streamlit Track-Record-Tabs in C7 can consume
without re-implementing the I/O layer.

Design rules
------------

* **Pure stdlib + numpy.** No new dependencies — the dashboard surface
  must stay deployable on the same minimal slim image as the rest of
  the inference layer.
* **Missing inputs are fallbacks, not errors.** Each loader returns
  ``None`` on a missing or malformed file and records a `warnings`
  entry on the payload. The dashboard then renders an explicit
  "no data" state instead of crashing the tab.
* **Deterministic.** Given the same input directory and ``as_of_date``
  the function returns byte-identical JSON (sorted keys, no clocks).

The output schema is pinned by ``DASHBOARD_PAYLOAD_VERSION`` and the
shape is mirrored by ``tests/test_build_dashboard_payload.py`` so a
breaking change forces a coordinated update of the schema + tests.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DASHBOARD_PAYLOAD_VERSION = "v1"

# Sprint-output filename patterns. Each loader gracefully degrades to
# ``None`` if the file is missing or fails to parse.
_FILE_PATTERNS: dict[str, str] = {
    "walk_forward": "walk_forward_{date}.json",
    "bootstrap_ci": "bootstrap_ci_{date}.json",
    "permutation": "permutation_{date}.json",
    "regime_stratified": "regime_stratified_{date}.json",
    "psr_mintrl": "psr_mintrl_{date}.json",
}

# Track-record-gate verdict (C6/T6) — optional sidecar produced by
# ``scripts.track_record_gate.evaluate_track_record_gate`` and serialised
# via ``verdict_to_dict``.
_TRACK_RECORD_GATE_FILE = "track_record_gate_{date}.json"

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


@dataclass(frozen=True)
class _LoadResult:
    """Internal carrier for one sprint-output load attempt."""

    name: str
    payload: dict[str, Any] | None
    warning: str | None = None


def _load_json(path: Path) -> dict[str, Any] | None:
    """Return parsed JSON or ``None`` on any IO/decode error."""
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, IsADirectoryError, json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _resolve_date(cache_dir: Path, as_of_date: str | None) -> str | None:
    """Pick a date string. Caller-supplied wins; else newest walk_forward file."""
    if as_of_date is not None:
        return as_of_date
    candidates: list[str] = []
    for path in cache_dir.glob("walk_forward_*.json"):
        match = _DATE_RE.search(path.stem)
        if match is not None:
            candidates.append(match.group(1))
    if not candidates:
        return None
    return max(candidates)


def _load_sprint_artefacts(cache_dir: Path, date: str) -> list[_LoadResult]:
    """Load every known per-sprint artefact for the given date."""
    results: list[_LoadResult] = []
    for name, template in _FILE_PATTERNS.items():
        path = cache_dir / template.format(date=date)
        payload = _load_json(path)
        if payload is None:
            results.append(
                _LoadResult(
                    name=name,
                    payload=None,
                    warning=f"missing or malformed: {path.name}",
                )
            )
        else:
            results.append(_LoadResult(name=name, payload=payload, warning=None))
    return results


def _gate_status_from_track_record(gate: dict[str, Any] | None) -> str:
    """Map a gate verdict dict to the dashboard's traffic-light vocabulary."""
    if gate is None:
        return "unknown"
    status = str(gate.get("status", "")).strip().lower()
    if status == "green":
        return "green"
    if status == "yellow":
        # Dashboard renders yellow as "amber" to match the agreed CI vocab.
        return "amber"
    if status == "red":
        return "red"
    if status == "skipped":
        return "skipped"
    return "unknown"


def _global_summary(variants: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Aggregate gate counts for the top-of-page traffic light."""
    counts = {"total_variants": 0, "gate_green": 0, "gate_amber": 0, "gate_red": 0}
    for variant in variants:
        counts["total_variants"] += 1
        status = variant.get("gate_status")
        if status == "green":
            counts["gate_green"] += 1
        elif status == "amber":
            counts["gate_amber"] += 1
        elif status == "red":
            counts["gate_red"] += 1
    return counts


def _build_variants(
    walk_forward: dict[str, Any] | None,
    bootstrap: dict[str, Any] | None,
    permutation: dict[str, Any] | None,
    regime: dict[str, Any] | None,
    psr_mintrl: dict[str, Any] | None,
    track_record_gate: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Produce one row per ``(setup_type, symbol_group)`` variant.

    The walk-forward output is the primary key — every other artefact
    contributes optional decorations. If walk-forward itself is missing,
    we surface zero variants and rely on the warning channel to tell the
    dashboard why.
    """
    if walk_forward is None:
        return []
    raw_variants = walk_forward.get("variants")
    if not isinstance(raw_variants, list):
        return []

    bootstrap_index = _index_by_variant(bootstrap, key="variants")
    perm_index = _index_by_variant(permutation, key="variants")
    regime_index = _index_by_variant(regime, key="variants")
    psr_index = _index_by_variant(psr_mintrl, key="variants")

    gate_status = _gate_status_from_track_record(track_record_gate)

    out: list[dict[str, Any]] = []
    for raw in raw_variants:
        if not isinstance(raw, dict):
            continue
        setup_type = str(raw.get("setup_type", ""))
        symbol_group = str(raw.get("symbol_group", ""))
        key = (setup_type, symbol_group)
        bootstrap_row = bootstrap_index.get(key, {})
        perm_row = perm_index.get(key, {})
        regime_row = regime_index.get(key, {})
        psr_row = psr_index.get(key, {})
        out.append(
            {
                "setup_type": setup_type,
                "symbol_group": symbol_group,
                "regime": str(raw.get("regime", "")),
                "n_trades": int(raw.get("n_trades", 0)),
                "hit_rate": _coerce_optional_float(raw.get("hit_rate")),
                "sharpe": _coerce_optional_float(raw.get("sharpe")),
                "bootstrap_ci_low": _coerce_optional_float(
                    bootstrap_row.get("sharpe_ci_low")
                ),
                "bootstrap_ci_high": _coerce_optional_float(
                    bootstrap_row.get("sharpe_ci_high")
                ),
                "perm_p": _coerce_optional_float(perm_row.get("p_value")),
                "bh_fdr_pass": bool(perm_row.get("bh_fdr_pass", False)),
                "psr_at_0": _coerce_optional_float(psr_row.get("psr_at_0")),
                "min_trl_at_0": _coerce_optional_int(psr_row.get("min_trl_at_0")),
                "wfe": _coerce_optional_float(raw.get("wfe")),
                "max_dd": _coerce_optional_float(raw.get("max_dd")),
                "regime_concentration": _coerce_optional_float(
                    regime_row.get("regime_concentration")
                ),
                "gate_status": gate_status,
            }
        )
    return out


def _index_by_variant(
    payload: dict[str, Any] | None, *, key: str
) -> dict[tuple[str, str], dict[str, Any]]:
    """Return a ``{(setup_type, symbol_group): row}`` map. Empty if invalid."""
    if payload is None:
        return {}
    rows = payload.get(key)
    if not isinstance(rows, list):
        return {}
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        index_key = (str(row.get("setup_type", "")), str(row.get("symbol_group", "")))
        out[index_key] = row
    return out


def _coerce_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def build_dashboard_payload(
    cache_dir: Path | str = Path("cache/calibration"),
    *,
    as_of_date: str | None = None,
    track_record_gate: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Assemble the C7 Track-Record-Dashboard payload.

    Parameters
    ----------
    cache_dir
        Directory containing the per-sprint JSON outputs. May be a string
        for ergonomics; converted internally to :class:`pathlib.Path`.
    as_of_date
        ISO date string ``YYYY-MM-DD`` selecting the snapshot to render.
        ``None`` (default) picks the newest available walk-forward file.
    track_record_gate
        Optional verdict dict from
        ``scripts.track_record_gate.verdict_to_dict``. If not provided
        explicitly, the loader will look for
        ``track_record_gate_<date>.json`` in ``cache_dir``.
    now
        Injection seam for deterministic tests. Defaults to UTC now.

    Returns
    -------
    dict
        A JSON-serialisable payload with ``version``, ``computed_at``,
        ``as_of_date``, ``variants``, ``global`` and ``warnings`` keys.
    """
    cache_dir_path = Path(cache_dir)
    warnings: list[str] = []

    date = _resolve_date(cache_dir_path, as_of_date)
    if date is None:
        return {
            "version": DASHBOARD_PAYLOAD_VERSION,
            "computed_at": _utc_isoformat(now),
            "as_of_date": None,
            "variants": [],
            "global": {
                "total_variants": 0,
                "gate_green": 0,
                "gate_amber": 0,
                "gate_red": 0,
            },
            "warnings": [
                f"no walk_forward_*.json in {cache_dir_path}; nothing to render"
            ],
        }

    artefacts = _load_sprint_artefacts(cache_dir_path, date)
    by_name = {a.name: a.payload for a in artefacts}
    for a in artefacts:
        if a.warning is not None:
            warnings.append(a.warning)

    if track_record_gate is None:
        gate_path = cache_dir_path / _TRACK_RECORD_GATE_FILE.format(date=date)
        track_record_gate = _load_json(gate_path)
        if track_record_gate is None:
            warnings.append(f"missing or malformed: {gate_path.name}")

    variants = _build_variants(
        walk_forward=by_name.get("walk_forward"),
        bootstrap=by_name.get("bootstrap_ci"),
        permutation=by_name.get("permutation"),
        regime=by_name.get("regime_stratified"),
        psr_mintrl=by_name.get("psr_mintrl"),
        track_record_gate=track_record_gate,
    )

    return {
        "version": DASHBOARD_PAYLOAD_VERSION,
        "computed_at": _utc_isoformat(now),
        "as_of_date": date,
        "variants": variants,
        "global": _global_summary(variants),
        "warnings": warnings,
    }


def _utc_isoformat(now: datetime | None) -> str:
    """Stable ISO-8601 timestamp for the payload header."""
    instant = now if now is not None else datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(timezone.utc).isoformat()


__all__ = [
    "DASHBOARD_PAYLOAD_VERSION",
    "build_dashboard_payload",
]
