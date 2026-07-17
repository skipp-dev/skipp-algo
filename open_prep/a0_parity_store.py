"""Durable A0 shadow journal and strict replay into the parity matcher."""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .a0_contract import A0Decision, A0ThresholdContext
from .a0_parity import ShadowDecision

_SCHEMA_VERSION = 1


def shadow_decision_row(
    decision: A0Decision,
    thresholds: A0ThresholdContext,
    *,
    direction: str,
    decision_scope: str,
    cumulative_regular_volume: int | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Serialize one replayable contract decision without provider-specific I/O."""
    snapshot = decision.snapshot
    row: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        **decision.to_details(),
        "symbol": snapshot.symbol,
        "direction": direction,
        "level": decision.final_level,
        "raw_daily_volume_ratio": snapshot.raw_daily_volume_ratio,
        "normalized_volume_pace": snapshot.normalized_volume_pace,
        "effective_a0_volume_threshold": thresholds.a0_volume,
        "effective_a0_price_threshold": thresholds.a0_price,
        "price": snapshot.price,
        "previous_close": snapshot.prev_close,
        "change_pct": snapshot.change_pct,
        "expected_volume_fraction": snapshot.expected_volume_fraction,
        "ts_event": snapshot.ts_event,
        "session_date": snapshot.session_date,
        "cumulative_regular_volume": cumulative_regular_volume,
        "decision_scope": decision_scope,
    }
    if extra:
        overlap = row.keys() & extra.keys()
        if overlap:
            raise ValueError(f"extra fields overwrite contract keys: {sorted(overlap)}")
        row.update(extra)
    return row


class A0ParityJournal:
    """Append first A0 per session/symbol/direction to a durable JSONL journal."""

    def __init__(self, directory: str | os.PathLike[str], *, source: str) -> None:
        self._directory = Path(directory)
        self._source = source.strip().lower()
        if not self._source:
            raise ValueError("parity journal source must not be empty")
        self._seen: set[tuple[str, str, str, str]] = set()
        self._lock = threading.Lock()
        self._restore_seen()

    def _path_for(self, session_date: str) -> Path:
        return self._directory / f"a0_shadow_{self._source}_{session_date}.jsonl"

    def _restore_seen(self) -> None:
        if not self._directory.exists():
            return
        for path in sorted(self._directory.glob(f"a0_shadow_{self._source}_*.jsonl")):
            for decision in load_shadow_decisions(
                [path], expected_source=self._source, include_core_a0=True
            ):
                self._seen.add(_episode_key(decision))

    def record(self, row: Mapping[str, Any]) -> bool:
        """Persist a new A0 episode and fsync it; return False for a duplicate."""
        decision = shadow_decision_from_row(row, expected_source=self._source)
        if decision.level != "A0" and decision.core_level != "A0":
            raise ValueError("parity journal accepts final or core A0 decisions only")
        if not decision.session_date:
            raise ValueError("parity journal requires session_date")
        key = _episode_key(decision)
        with self._lock:
            if key in self._seen:
                return False
            self._directory.mkdir(parents=True, exist_ok=True)
            path = self._path_for(decision.session_date)
            payload = json.dumps(dict(row), sort_keys=True, separators=(",", ":"))
            with path.open("a", encoding="utf-8") as handle:
                handle.write(payload + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            self._seen.add(key)
        return True


def record_realtime_a0_signals(
    journal: A0ParityJournal,
    signals: Iterable[Any],
    *,
    now_epoch: float,
) -> int:
    """Persist final/core A0 states from the existing FMP signal contract."""
    from .signal_events import event_row

    written = 0
    for signal in signals:
        details = getattr(signal, "details", {})
        details = details if isinstance(details, dict) else {}
        final_value = details.get("final_level")
        if final_value is None or final_value == "":
            final_value = getattr(signal, "level", "")
        final_level = str(final_value)
        core_level = str(details.get("core_level") or "")
        if final_level != "A0" and core_level != "A0":
            continue
        if journal.record(event_row(signal, now_epoch=now_epoch)):
            written += 1
    return written


def _episode_key(decision: ShadowDecision) -> tuple[str, str, str, str]:
    return (
        decision.session_date or "",
        decision.symbol.strip().upper(),
        decision.direction.strip().upper(),
        decision.level,
    )


def load_shadow_decisions(
    paths: Iterable[Path],
    *,
    expected_source: str | None = None,
    include_core_a0: bool = False,
) -> list[ShadowDecision]:
    """Strictly load JSONL decisions, filtering non-A0 FMP signal-event rows."""
    deduplicated: dict[str, ShadowDecision] = {}
    for path in sorted(Path(item) for item in paths):
        with path.open("r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                if not raw_line.strip():
                    continue
                try:
                    row = json.loads(raw_line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
                if not isinstance(row, dict):
                    raise ValueError(f"{path}:{line_number}: row must be an object")
                level_value = _preferred_field(row, "final_level", "level")
                level = str(level_value or "")
                core_level = str(row.get("core_level") or "")
                if level != "A0" and not (include_core_a0 and core_level == "A0"):
                    continue
                decision = shadow_decision_from_row(
                    row,
                    expected_source=expected_source,
                )
                previous = deduplicated.get(decision.decision_id)
                if previous is not None and previous != decision:
                    raise ValueError(
                        f"{path}:{line_number}: conflicting duplicate decision_id"
                    )
                deduplicated[decision.decision_id] = decision
    return sorted(
        deduplicated.values(),
        key=lambda item: (item.decision_at, item.symbol, item.decision_id),
    )


def shadow_decision_from_row(
    row: Mapping[str, Any],
    *,
    expected_source: str | None = None,
) -> ShadowDecision:
    """Normalize either an A0-Fast journal row or an existing FMP signal row."""
    decision_id = str(row.get("decision_id") or "").strip()
    symbol = str(row.get("symbol") or "").strip().upper()
    direction = str(row.get("direction") or "").strip().upper()
    source = str(row.get("source") or "").strip().lower()
    level_value = _preferred_field(row, "final_level", "level")
    level = str(level_value or "").strip()
    if not decision_id or not symbol or direction not in {"LONG", "SHORT"}:
        raise ValueError("decision_id, symbol and LONG/SHORT direction are required")
    if not source:
        raise ValueError("decision source is required")
    if expected_source and source != expected_source.strip().lower():
        raise ValueError(f"unexpected decision source: {source}")
    decision_at = _required_float(
        _preferred_field(row, "decision_at", "fired_epoch"), "decision_at"
    )
    raw_reasons = row.get("reason_codes") or []
    if not isinstance(raw_reasons, list):
        raise ValueError("reason_codes must be a list")
    return ShadowDecision(
        decision_id=decision_id,
        symbol=symbol,
        direction=direction,
        level=level,
        decision_at=decision_at,
        source=source,
        reason_codes=tuple(str(reason) for reason in raw_reasons),
        raw_daily_volume_ratio=_optional_float(row.get("raw_daily_volume_ratio")),
        normalized_volume_pace=_optional_float(row.get("normalized_volume_pace")),
        effective_a0_volume_threshold=_optional_float(
            row.get("effective_a0_volume_threshold")
        ),
        effective_a0_price_threshold=_optional_float(
            row.get("effective_a0_price_threshold")
        ),
        price=_optional_float(row.get("price")),
        previous_close=_optional_float(row.get("previous_close", row.get("prev_close"))),
        change_pct=_optional_float(row.get("change_pct")),
        expected_volume_fraction=_optional_float(row.get("expected_volume_fraction")),
        ts_event=_optional_float(row.get("ts_event")),
        session_date=str(row.get("session_date") or "") or None,
        cumulative_regular_volume=_optional_int(row.get("cumulative_regular_volume")),
        decision_scope=str(row.get("decision_scope") or "") or None,
        decision_contract_version=_optional_int(row.get("decision_contract_version")),
        detector_version=str(row.get("detector_version") or "") or None,
        decision_basis_id=str(row.get("decision_basis_id") or "") or None,
        core_level=str(row.get("core_level") or "") or None,
        ts_recv=_optional_float(row.get("ts_recv")),
        observed_at=_optional_float(row.get("observed_at")),
        data_age_ms=_optional_float(row.get("data_age_ms")),
        data_age_unknown=_optional_bool(row.get("data_age_unknown")),
        gap_state=str(row.get("gap_state") or "") or None,
        reference_source=str(row.get("reference_source") or "") or None,
        reference_version=str(row.get("reference_version") or "") or None,
        corporate_action_version=(
            str(row.get("corporate_action_version") or "") or None
        ),
    )


def _required_float(value: Any, name: str) -> float:
    parsed = _optional_float(value)
    if parsed is None:
        raise ValueError(f"{name} must be a finite number")
    return parsed


def _preferred_field(
    row: Mapping[str, Any],
    primary: str,
    fallback: str,
) -> Any:
    """Use a compatibility alias only when the canonical field is absent."""
    value = row.get(primary)
    if value is None or value == "":
        return row.get(fallback)
    return value


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"invalid numeric value: {value!r}") from exc
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        raise ValueError(f"non-finite numeric value: {value!r}")
    return parsed


def _optional_int(value: Any) -> int | None:
    parsed = _optional_float(value)
    if parsed is None:
        return None
    if not parsed.is_integer():
        raise ValueError(f"non-integral numeric value: {value!r}")
    return int(parsed)


def _optional_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    raise ValueError(f"invalid boolean value: {value!r}")
