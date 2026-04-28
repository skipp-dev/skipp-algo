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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DASHBOARD_PAYLOAD_VERSION = "1.0.0"

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


def _per_variant_gate_status(
    track_record_gate: dict[str, Any] | None,
    variant_key: str,
    fallback: str,
) -> tuple[str, list[str]]:
    """Look up a per-variant gate verdict; fall back to the global status.

    Returns ``(status, failures)`` where ``failures`` is a list of
    human-readable reasons for ``red`` verdicts. The ``track_record_gate``
    payload may carry a ``per_variant`` block (additive in 1.1.0+) of
    the shape::

        {
            "status": "green",
            "per_variant": {
                "smc_breaker_btc": {"status": "yellow", "failures": [...]},
                ...
            }
        }

    When ``per_variant`` is absent we surface the global status on every
    row so the legacy single-verdict track-record-gate stays usable.
    """
    if track_record_gate is None:
        return fallback, []
    per = track_record_gate.get("per_variant")
    if not isinstance(per, dict):
        return fallback, []
    entry = per.get(variant_key)
    if not isinstance(entry, dict):
        return fallback, []
    status = _gate_status_from_track_record(entry)
    failures_raw = entry.get("failures") or []
    failures = [str(f) for f in failures_raw if isinstance(f, (str, int, float))]
    return status, failures


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

    global_status = _gate_status_from_track_record(track_record_gate)

    out: list[dict[str, Any]] = []
    for raw in raw_variants:
        if not isinstance(raw, dict):
            continue
        setup_type = str(raw.get("setup_type", ""))
        symbol_group = str(raw.get("symbol_group", ""))
        key = (setup_type, symbol_group)
        # Composite variant key — matches the C8 drift artifact convention
        # (e.g. "smc_breaker_btc") and the columns the C7 tabs read.
        variant_key = (
            f"{setup_type}_{symbol_group}" if setup_type and symbol_group
            else (setup_type or symbol_group)
        )
        bootstrap_row = bootstrap_index.get(key, {})
        perm_row = perm_index.get(key, {})
        regime_row = regime_index.get(key, {})
        psr_row = psr_index.get(key, {})

        variant_status, variant_failures = _per_variant_gate_status(
            track_record_gate, variant_key, global_status
        )

        sharpe_ci_low = _coerce_optional_float(bootstrap_row.get("sharpe_ci_low"))
        sharpe_ci_high = _coerce_optional_float(bootstrap_row.get("sharpe_ci_high"))
        perm_p = _coerce_optional_float(perm_row.get("p_value"))
        psr_at_0 = _coerce_optional_float(psr_row.get("psr_at_0"))
        min_trl_at_0 = _coerce_optional_int(psr_row.get("min_trl_at_0"))
        wfe = _coerce_optional_float(raw.get("wfe"))
        max_dd = _coerce_optional_float(raw.get("max_dd"))

        # Sub-blocks for the C7 tab_calibration_detail drill-down.
        bootstrap_block: dict[str, Any] = {}
        if bootstrap_row:
            samples_raw = bootstrap_row.get("sharpe_samples") or []
            samples = [
                _coerce_optional_float(s) for s in samples_raw if s is not None
            ]
            bootstrap_block = {
                "sharpe_samples": [s for s in samples if s is not None],
                "n_bootstraps": int(bootstrap_row.get("n_bootstraps", 0) or 0),
            }
        perm_block: dict[str, Any] = {}
        if perm_row:
            null_raw = perm_row.get("null_samples") or []
            null = [_coerce_optional_float(s) for s in null_raw if s is not None]
            perm_block = {
                "observed": _coerce_optional_float(perm_row.get("observed")),
                "null_samples": [s for s in null if s is not None],
                "schema": str(perm_row.get("schema", "outcome_sign")),
            }
        regime_block: dict[str, Any] = {}
        if regime_row:
            per_regime = regime_row.get("per_regime") or {}
            regime_block = {
                k: dict(v) for k, v in per_regime.items()
                if isinstance(v, dict)
            }
            agg = _coerce_optional_float(
                regime_row.get("aggregate_freq_weighted_sharpe")
            )
            if agg is not None:
                regime_block["aggregate_freq_weighted_sharpe"] = agg
            if regime_row.get("regime_concentration_warning"):
                regime_block["regime_concentration_warning"] = True
        wf_folds = raw.get("walk_forward_folds")
        wf_folds_list = (
            [dict(f) for f in wf_folds if isinstance(f, dict)]
            if isinstance(wf_folds, list) else []
        )

        row: dict[str, Any] = {
            # Legacy keys (pinned by tests, kept for backward compat).
            "setup_type": setup_type,
            "symbol_group": symbol_group,
            "regime": str(raw.get("regime", "")),
            "n_trades": int(raw.get("n_trades", 0)),
            "hit_rate": _coerce_optional_float(raw.get("hit_rate")),
            "sharpe": _coerce_optional_float(raw.get("sharpe")),
            "bootstrap_ci_low": sharpe_ci_low,
            "bootstrap_ci_high": sharpe_ci_high,
            "perm_p": perm_p,
            "bh_fdr_pass": bool(perm_row.get("bh_fdr_pass", False)),
            "psr_at_0": psr_at_0,
            "min_trl_at_0": min_trl_at_0,
            "wfe": wfe,
            "max_dd": max_dd,
            "regime_concentration": _coerce_optional_float(
                regime_row.get("regime_concentration")
            ),
            "gate_status": variant_status,
            # Consumer-friendly aliases consumed by terminal_tabs/* (C7/T3-T6).
            "variant": variant_key,
            "sharpe_ci_low": sharpe_ci_low,
            "sharpe_ci_high": sharpe_ci_high,
            "permutation_p_value": perm_p,
            "permutation_schema": (
                str(perm_row.get("schema", "outcome_sign")) if perm_row else None
            ),
            "psr": psr_at_0,
            "min_trl": min_trl_at_0,
            "walk_forward_efficiency": wfe,
            "walk_forward_mode": (
                # Preserve a missing/explicit-None walk_forward_mode as None so
                # the consumer's `... or "anchored"` default applies; coercing
                # via str() would emit the literal string "None".
                str(raw["walk_forward_mode"])
                if raw.get("walk_forward_mode") is not None
                else None
            ),
            "walk_forward_folds": wf_folds_list,
            "max_drawdown": max_dd,
            "bootstrap": bootstrap_block,
            "permutation": perm_block,
            "regime_stratified": regime_block,
            "gate_failures": variant_failures,
        }
        out.append(row)
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

        **Important**: this dict must be **pre-computed** by an upstream
        offline run of ``scripts.track_record_gate.evaluate_track_record_gate``
        (or its per-variant sibling). The aggregator does NOT re-run
        the gate here — doing so would (a) drag the bootstrap-CI
        dependency into the dashboard image, breaking the C7/T8 slim-
        image policy documented in ``Dockerfile.dashboard``, and
        (b) re-execute a multi-second probabilistic computation on
        every dashboard refresh. If the file is missing, the dashboard
        renders the gate cell as ``"missing"`` rather than computing
        a fresh verdict.
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
    # C-sprint deep-review C7 MINOR fix: when EVERY artefact is missing
    # for the resolved date, downgrade the per-file warning torrent to
    # a single aggregated message. Operators were drowning in per-file
    # noise that obscured the actually-actionable signal "this date has
    # no artefacts at all".
    if all(a.payload is None for a in artefacts):
        warnings.append(
            f"no sprint artefacts found in {cache_dir_path} for date={date}"
        )
    else:
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
