"""Deterministic A0-Fast versus FMP shadow decision matching and reporting."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from statistics import median
from typing import Any


class ParityMatchStatus(StrEnum):
    SAME_DECISION_FAST_FIRST = "same_decision_fast_first"
    SAME_DECISION_FMP_FIRST = "same_decision_fmp_first"
    FAST_ONLY_SOURCE_SEMANTICS = "fast_only_source_semantics"
    FMP_ONLY_MISSING_STREAM_DATA = "fmp_only_missing_stream_data"
    RULE_STATE_MISMATCH = "rule_state_mismatch"
    UNMATCHED_UNKNOWN = "unmatched_unknown"


@dataclass(frozen=True, slots=True)
class ShadowDecision:
    decision_id: str
    symbol: str
    direction: str
    level: str
    decision_at: float
    source: str
    reason_codes: tuple[str, ...]
    raw_daily_volume_ratio: float | None = None
    normalized_volume_pace: float | None = None
    effective_a0_volume_threshold: float | None = None
    effective_a0_price_threshold: float | None = None


@dataclass(frozen=True, slots=True)
class ParityMatch:
    status: ParityMatchStatus
    symbol: str
    fast_decision_id: str | None
    fmp_decision_id: str | None
    fast_decision_at: float | None
    fmp_decision_at: float | None
    lead_seconds: float | None
    direction: str | None
    fast_reason_codes: tuple[str, ...]
    fmp_reason_codes: tuple[str, ...]


def match_shadow_decisions(
    fast: list[ShadowDecision],
    fmp: list[ShadowDecision],
    *,
    matching_window_seconds: float,
    stream_health_by_symbol: dict[str, str] | None = None,
) -> list[ParityMatch]:
    """Match nearest same-symbol decisions once; never mutate input events."""
    window = max(0.0, float(matching_window_seconds))
    health = {
        str(symbol).strip().upper(): str(state)
        for symbol, state in (stream_health_by_symbol or {}).items()
    }
    remaining_fmp = set(range(len(fmp)))
    matches: list[ParityMatch] = []
    for fast_event in sorted(fast, key=lambda event: event.decision_at):
        symbol = fast_event.symbol.strip().upper()
        candidates = [
            index for index in remaining_fmp
            if fmp[index].symbol.strip().upper() == symbol
            and abs(fmp[index].decision_at - fast_event.decision_at) <= window
        ]
        same_direction = [
            index for index in candidates
            if fmp[index].direction == fast_event.direction
        ]
        if same_direction:
            index = min(
                same_direction,
                key=lambda item: abs(fmp[item].decision_at - fast_event.decision_at),
            )
            fmp_event = fmp[index]
            remaining_fmp.remove(index)
            lead = fmp_event.decision_at - fast_event.decision_at
            status = (
                ParityMatchStatus.SAME_DECISION_FAST_FIRST
                if lead >= 0
                else ParityMatchStatus.SAME_DECISION_FMP_FIRST
            )
            matches.append(_matched(status, fast_event, fmp_event, lead))
        elif candidates:
            index = min(
                candidates,
                key=lambda item: abs(fmp[item].decision_at - fast_event.decision_at),
            )
            fmp_event = fmp[index]
            remaining_fmp.remove(index)
            matches.append(
                _matched(
                    ParityMatchStatus.RULE_STATE_MISMATCH,
                    fast_event,
                    fmp_event,
                    fmp_event.decision_at - fast_event.decision_at,
                )
            )
        else:
            matches.append(
                ParityMatch(
                    status=ParityMatchStatus.FAST_ONLY_SOURCE_SEMANTICS,
                    symbol=symbol,
                    fast_decision_id=fast_event.decision_id,
                    fmp_decision_id=None,
                    fast_decision_at=fast_event.decision_at,
                    fmp_decision_at=None,
                    lead_seconds=None,
                    direction=fast_event.direction,
                    fast_reason_codes=fast_event.reason_codes,
                    fmp_reason_codes=(),
                )
            )
    for index in sorted(remaining_fmp, key=lambda item: fmp[item].decision_at):
        event = fmp[index]
        symbol = event.symbol.strip().upper()
        state = health.get(symbol, "unknown")
        status = (
            ParityMatchStatus.FMP_ONLY_MISSING_STREAM_DATA
            if state != "complete"
            else ParityMatchStatus.UNMATCHED_UNKNOWN
        )
        matches.append(
            ParityMatch(
                status=status,
                symbol=symbol,
                fast_decision_id=None,
                fmp_decision_id=event.decision_id,
                fast_decision_at=None,
                fmp_decision_at=event.decision_at,
                lead_seconds=None,
                direction=event.direction,
                fast_reason_codes=(),
                fmp_reason_codes=event.reason_codes,
            )
        )
    return matches


def _matched(
    status: ParityMatchStatus,
    fast: ShadowDecision,
    fmp: ShadowDecision,
    lead: float,
) -> ParityMatch:
    return ParityMatch(
        status=status,
        symbol=fast.symbol.strip().upper(),
        fast_decision_id=fast.decision_id,
        fmp_decision_id=fmp.decision_id,
        fast_decision_at=fast.decision_at,
        fmp_decision_at=fmp.decision_at,
        lead_seconds=round(lead, 6),
        direction=fast.direction if fast.direction == fmp.direction else None,
        fast_reason_codes=fast.reason_codes,
        fmp_reason_codes=fmp.reason_codes,
    )


def build_parity_report(matches: list[ParityMatch]) -> dict[str, Any]:
    """Produce a deterministic aggregate without hiding cause classes."""
    counts = Counter(str(match.status) for match in matches)
    leads = [
        match.lead_seconds
        for match in matches
        if match.lead_seconds is not None
        and match.status is ParityMatchStatus.SAME_DECISION_FAST_FIRST
    ]
    return {
        "total": len(matches),
        "status_counts": dict(sorted(counts.items())),
        "matched_same_direction": sum(
            counts[status]
            for status in (
                ParityMatchStatus.SAME_DECISION_FAST_FIRST,
                ParityMatchStatus.SAME_DECISION_FMP_FIRST,
            )
        ),
        "median_fast_lead_seconds": round(median(leads), 6) if leads else None,
    }
