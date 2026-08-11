"""Build prospective BOS/OB/FVG/SWEEP paper-incubation setups.

The input is the point-in-time payload emitted by
``scripts.pull_databento_edge_input``. This producer deliberately rejects
``FamilyEvent`` forward windows: those belong to modeled-OOS measurement and
must never be relabelled as paper execution evidence.

The module is transformation-only. It writes setup and gate artifacts but
never connects to a broker. A separate, explicitly controlled paper pilot may
hand the artifacts to ``scripts.run_smc_live_incubation``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_json, atomic_write_text

FAMILY_VARIANTS: dict[str, str] = {
    "BOS": "smc_bos_long",
    "OB": "smc_ob_long",
    "FVG": "smc_fvg_long",
    "SWEEP": "smc_sweep_long",
}

_STRUCTURE_KEYS: dict[str, str] = {
    "BOS": "bos",
    "OB": "orderblocks",
    "FVG": "fvg",
    "SWEEP": "liquidity_sweeps",
}

_TIMEFRAME_SECONDS: dict[str, int] = {
    "5m": 300,
    "10m": 600,
    "15m": 900,
    "30m": 1_800,
    "1H": 3_600,
    "4H": 14_400,
    "1D": 86_400,
}


def _epoch_seconds(value: object, *, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be epoch seconds or an ISO timestamp")
    if isinstance(value, (int, float)):
        parsed = float(value)
    elif isinstance(value, str):
        text = value.strip()
        try:
            parsed = float(text)
        except ValueError:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            parsed = dt.timestamp()
    else:
        raise ValueError(f"{label} must be epoch seconds or an ISO timestamp")
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{label} must be a finite positive timestamp")
    return parsed


def _positive_float(value: object, *, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be numeric")
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{label} must be finite and positive")
    return parsed


def _event_anchor(event: dict[str, Any]) -> float:
    for key in ("anchor_ts", "time"):
        if event.get(key) is not None:
            return _epoch_seconds(event[key], label=f"event.{key}")
    raise ValueError("event lacks anchor_ts/time")


def _is_long_event(family: str, event: dict[str, Any]) -> bool:
    if family == "SWEEP":
        return str(event.get("side", "")).strip().upper() == "SELL_SIDE"
    direction = str(event.get("dir", event.get("direction", ""))).strip().upper()
    return direction in {"UP", "BULL", "BULLISH", "LONG"}


def _assert_no_forward_evidence(payload: object) -> None:
    """Reject any nested key that would turn modeled hindsight into paper."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            if str(key).startswith("forward_"):
                raise ValueError(
                    f"forward evidence key {key!r} is forbidden in prospective setup input"
                )
            _assert_no_forward_evidence(value)
    elif isinstance(payload, list):
        for value in payload:
            _assert_no_forward_evidence(value)


def _order_ref(
    *,
    family: str,
    symbol: str,
    timeframe: str,
    anchor: float,
    event_id: str,
) -> str:
    """Build a replay-stable reference without cross-timeframe collisions."""
    event_fingerprint = hashlib.sha256(event_id.encode("utf-8")).hexdigest()[:8]
    return (
        f"smc-{family.lower()}-{symbol[:8]}-{timeframe.lower()}-"
        f"{int(anchor)}-{event_fingerprint}"
    )


def commercial_snapshot_id(payload: dict[str, Any]) -> str:
    """Return a key-order-independent identity for one complete PIT payload."""
    try:
        canonical = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("input must be canonical JSON data") from exc
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _anchor_bar_low(bars: list[dict[str, Any]], anchor_ts: float) -> float:
    matches = [
        bar
        for bar in bars
        if _epoch_seconds(bar.get("timestamp"), label="bar.timestamp") == anchor_ts
    ]
    if len(matches) != 1:
        raise ValueError(
            f"level event anchor {anchor_ts:g} must match exactly one confirmed bar"
        )
    return _positive_float(matches[0].get("low"), label="anchor_bar.low")


def _levels(
    family: str,
    event: dict[str, Any],
    bars: list[dict[str, Any]],
    *,
    stop_buffer_bps: float,
    rr_target: float,
) -> tuple[float, float, float]:
    if family in {"OB", "FVG"}:
        zone_low = _positive_float(event.get("low"), label=f"{family}.low")
        zone_high = _positive_float(event.get("high"), label=f"{family}.high")
        if zone_high <= zone_low:
            raise ValueError(f"{family} requires high > low")
        entry = (zone_low + zone_high) / 2.0
        stop_base = zone_low
    else:
        entry = _positive_float(event.get("price"), label=f"{family}.price")
        stop_base = _anchor_bar_low(bars, _event_anchor(event))

    stop = stop_base * (1.0 - stop_buffer_bps / 10_000.0)
    if not 0 < stop < entry:
        raise ValueError(
            f"{family} produced invalid long risk geometry: entry={entry}, stop={stop}"
        )
    take_profit = entry + rr_target * (entry - stop)
    return tuple(round(value, 6) for value in (entry, stop, take_profit))


def build_commercial_family_setups(
    payload: dict[str, Any],
    *,
    trade_date: str,
    quantity: int = 1,
    stop_buffer_bps: float = 10.0,
    rr_target: float = 2.0,
    max_event_age_seconds: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Convert one PIT structure payload into at most one long setup/family."""
    if not isinstance(payload, dict):
        raise ValueError("input root must be a JSON object")
    _assert_no_forward_evidence(payload)
    snapshot_id = commercial_snapshot_id(payload)
    if isinstance(quantity, bool) or quantity <= 0:
        raise ValueError("quantity must be positive")
    if (
        isinstance(stop_buffer_bps, bool)
        or not math.isfinite(stop_buffer_bps)
        or not 0 < stop_buffer_bps < 1_000
    ):
        raise ValueError("stop_buffer_bps must be finite and in (0, 1000)")
    if isinstance(rr_target, bool) or not math.isfinite(rr_target) or rr_target <= 0:
        raise ValueError("rr_target must be finite and positive")
    date.fromisoformat(trade_date)

    structure = payload.get("structure")
    bars = payload.get("bars")
    provenance = payload.get("provenance")
    if not isinstance(structure, dict):
        raise ValueError("input.structure must be an object")
    if not isinstance(bars, list) or not bars or not all(isinstance(x, dict) for x in bars):
        raise ValueError("input.bars must be a non-empty list of objects")
    if not isinstance(provenance, dict):
        raise ValueError("input.provenance must be an object")
    symbol = str(provenance.get("symbol", "")).strip().upper()
    timeframe = str(provenance.get("timeframe", "")).strip()
    source = str(provenance.get("source", "")).strip()
    if not symbol:
        raise ValueError("input.provenance.symbol is required")
    if not source:
        raise ValueError("input.provenance.source is required")
    if timeframe not in _TIMEFRAME_SECONDS:
        raise ValueError(f"unsupported input.provenance.timeframe {timeframe!r}")
    as_of = _epoch_seconds(payload.get("as_of"), label="input.as_of")
    asof_trade_date = datetime.fromtimestamp(as_of, UTC).date().isoformat()
    if trade_date != asof_trade_date:
        raise ValueError(
            f"trade_date {trade_date} does not match input.as_of UTC date "
            f"{asof_trade_date}"
        )
    bar_timestamps = [
        _epoch_seconds(bar.get("timestamp"), label="bar.timestamp")
        for bar in bars
    ]
    if any(timestamp > as_of for timestamp in bar_timestamps):
        raise ValueError("input.bars contains observations after input.as_of")
    max_age = (
        _TIMEFRAME_SECONDS[timeframe]
        if max_event_age_seconds is None
        else int(max_event_age_seconds)
    )
    if isinstance(max_event_age_seconds, bool) or max_age < 0:
        raise ValueError("max_event_age_seconds must be non-negative")
    if as_of - max(bar_timestamps) > max_age:
        raise ValueError("newest confirmed bar is stale relative to input.as_of")

    setups: list[dict[str, Any]] = []
    skipped = {"short": 0, "stale": 0, "future": 0, "invalid": 0}
    for family in FAMILY_VARIANTS:
        raw_events = structure.get(_STRUCTURE_KEYS[family], []) or []
        if not isinstance(raw_events, list):
            raise ValueError(f"input.structure.{_STRUCTURE_KEYS[family]} must be a list")
        candidates: list[tuple[float, str, dict[str, Any]]] = []
        for event in raw_events:
            if not isinstance(event, dict):
                skipped["invalid"] += 1
                continue
            if event.get("valid") is False or event.get("active") is False:
                skipped["invalid"] += 1
                continue
            event_id = str(event.get("id", "")).strip()
            if not event_id:
                skipped["invalid"] += 1
                continue
            try:
                anchor = _event_anchor(event)
            except ValueError:
                skipped["invalid"] += 1
                continue
            if anchor > as_of:
                skipped["future"] += 1
                continue
            if as_of - anchor > max_age:
                skipped["stale"] += 1
                continue
            if not _is_long_event(family, event):
                skipped["short"] += 1
                continue
            candidates.append((anchor, event_id, event))
        if not candidates:
            continue
        selected: tuple[float, str, float, float, float] | None = None
        for anchor, event_id, event in sorted(
            candidates,
            key=lambda item: (item[0], item[1]),
            reverse=True,
        ):
            try:
                entry, stop, target = _levels(
                    family,
                    event,
                    bars,  # type: ignore[arg-type]
                    stop_buffer_bps=stop_buffer_bps,
                    rr_target=rr_target,
                )
            except ValueError:
                skipped["invalid"] += 1
                continue
            selected = (anchor, event_id, entry, stop, target)
            break
        if selected is None:
            continue
        anchor, event_id, entry, stop, target = selected
        order_ref = _order_ref(
            family=family,
            symbol=symbol,
            timeframe=timeframe,
            anchor=anchor,
            event_id=event_id,
        )
        setups.append({
            "variant": FAMILY_VARIANTS[family],
            "family": family,
            "symbol": symbol,
            "entry": entry,
            "stop_loss": stop,
            "take_profit": target,
            "quantity": quantity,
            "trade_date": trade_date,
            "order_ref": order_ref,
            "level_tag": f"smc_{family.lower()}_prospective",
            "evidence_class": "PAPER",
            "producer_mode": "prospective_pit",
            "source_event_id": event_id or None,
            "source_anchor_ts": anchor,
            "source_asof_ts": as_of,
            "source_timeframe": timeframe,
            "source_snapshot_id": snapshot_id,
            "source_provenance": dict(provenance),
        })

    diagnostics = {
        "schema_version": 1,
        "producer_mode": "prospective_pit",
        "symbol": symbol,
        "timeframe": timeframe,
        "source": source,
        "source_snapshot_id": snapshot_id,
        "as_of_ts": as_of,
        "max_event_age_seconds": max_age,
        "setups_emitted": len(setups),
        "families_emitted": [setup["family"] for setup in setups],
        "skipped": skipped,
    }
    return setups, diagnostics


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build PIT-safe commercial family paper setups without broker I/O."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--setups-output", type=Path, required=True)
    parser.add_argument("--gate-status-output", type=Path, required=True)
    parser.add_argument("--diagnostics-output", type=Path, required=True)
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--quantity", type=int, default=1)
    parser.add_argument("--stop-buffer-bps", type=float, default=10.0)
    parser.add_argument("--rr-target", type=float, default=2.0)
    parser.add_argument("--max-event-age-seconds", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        setups, diagnostics = build_commercial_family_setups(
            payload,
            trade_date=args.trade_date,
            quantity=args.quantity,
            stop_buffer_bps=args.stop_buffer_bps,
            rr_target=args.rr_target,
            max_event_age_seconds=args.max_event_age_seconds,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    gates = {setup["variant"]: "amber" for setup in setups}
    atomic_write_text(
        json.dumps(setups, indent=2, sort_keys=True),
        args.setups_output,
        fsync=True,
    )
    atomic_write_json(gates, args.gate_status_output, sort_keys=True, fsync=True)
    atomic_write_json(
        diagnostics,
        args.diagnostics_output,
        indent=2,
        sort_keys=True,
        fsync=True,
    )
    print(json.dumps(diagnostics, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
