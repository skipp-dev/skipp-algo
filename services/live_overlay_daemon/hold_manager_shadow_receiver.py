"""Fail-closed TradingView receiver for the Hold Manager R2 shadow gate."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import (
    APIRouter,
    Header,
    HTTPException,
    Request,
)
from fastapi import Path as PathParam
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
)
from starlette.concurrency import run_in_threadpool

from . import config, observability

_REQUIREMENT_ID = "R2-SHADOW-CUTOVER"
_MAX_BODY_BYTES = 8_192
_SOURCE_HASH_LENGTH = 64
_SOURCE_HASH_MODE = "micro_profile_library_pin_frozen"
_FROZEN_MICRO_PROFILE_LIBRARY_PIN = 175
_CHANNELS = (
    "HM_ENTRY",
    "HM_T1",
    "HM_T2",
    "HM_STOP",
    "HM_TIMESTOP",
    "HM_EXIT_ANY",
)

TokenCompare = Callable[[str, str], bool]


class _HoldManagerShadowEvent(BaseModel):
    """Wire fields both alert shapes carry, and the only ones persisted.

    The two shapes differ solely in how they authenticate and how they name
    the source; everything describing the event itself lives here so the two
    can never drift apart by accident.
    """

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    schema_version: int = Field(alias="schemaVersion", ge=1, le=1)
    requirement_id: str = Field(
        alias="requirementId",
        min_length=1,
        max_length=64,
    )
    channel: str = Field(min_length=1, max_length=32)
    mode: str = Field(min_length=1, max_length=32)
    script_name: str = Field(
        alias="scriptName",
        min_length=1,
        max_length=128,
    )
    layout: str = Field(min_length=1, max_length=128)
    producer: str = Field(min_length=1, max_length=128)
    bus_schema: int = Field(alias="busSchema", ge=1)
    symbol: str = Field(
        min_length=3,
        max_length=64,
        pattern=r"^[A-Z0-9._-]+:[A-Z0-9._-]+$",
    )
    timeframe: str = Field(min_length=1, max_length=8)
    bar_time: AwareDatetime = Field(alias="barTime")
    price: Decimal = Field(gt=0)

    @field_validator("symbol", mode="before")
    @classmethod
    def _uppercase_symbol(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value


class HoldManagerShadowAlert(_HoldManagerShadowEvent):
    """Legacy shape: body-borne token and a hand-typed source hash.

    Superseded by HoldManagerShadowBuildAlert. Retained until the operator has
    cut the live alerts over and the readback has proven it, because this is
    the rollback path: recreating the six alerts from
    ``smc_hold_manager_shadow_alert_templates.json`` restores exactly this
    shape. See docs/superpowers/specs/
    2026-08-13-hold-manager-alert-decoupling-design.md, step 3.
    """

    auth_token: str = Field(
        alias="authToken",
        min_length=32,
        max_length=256,
        exclude=True,
        repr=False,
    )
    source_sha256: str = Field(
        alias="sourceSha256",
        min_length=_SOURCE_HASH_LENGTH,
        max_length=_SOURCE_HASH_LENGTH,
        pattern=r"^[0-9a-f]{64}$",
    )


class HoldManagerShadowBuildAlert(_HoldManagerShadowEvent):
    """Build-pinned shape: the Pine source writes the entire body.

    A Pine script cannot state its own hash -- the value is self-referential --
    so the payload names the build instead, and the receiver resolves the hash
    from the contract. The token moves into the ``/{token}/...`` path, which is
    how this daemon already authenticates ``/{token}/smc_live`` and the only
    form that inherits the ``access_log=False`` protection in main.py.
    """

    source_build: int = Field(alias="sourceBuild", ge=1)


@dataclass(frozen=True)
class _Contract:
    source_sha256: str
    source_build: int
    source_hash_mode: str
    frozen_micro_profile_library_pin: int
    saved_script: str
    layout: str
    producer: str
    bus_schema: int
    channels: tuple[str, ...]
    market_timezone: str


def _load_contract(path: Path) -> _Contract:
    try:
        if path.stat().st_size > 131_072:
            raise ValueError("contract file exceeds 128 KiB")
        payload = json.loads(path.read_text(encoding="utf-8"))
        source = payload["source"]
        trading_view = payload["tradingView"]
        activation = payload["activationRequirements"]
        channels = tuple(activation["holdAlertChannels"])
        build_history = tuple(
            (int(entry["build"]), str(entry["sha256"]))
            for entry in payload["buildHistory"]
        )
        contract = _Contract(
            source_sha256=source["sha256"],
            source_build=int(source["build"]),
            source_hash_mode=source["hashMode"],
            frozen_micro_profile_library_pin=source[
                "frozenMicroProfileLibraryPin"
            ],
            saved_script=trading_view["savedScript"],
            layout=trading_view["validationLayout"],
            producer=trading_view["producer"],
            bus_schema=trading_view["busSchema"],
            channels=channels,
            market_timezone=trading_view["marketTimezone"],
        )
        ZoneInfo(contract.market_timezone)
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        ZoneInfoNotFoundError,
    ) as exc:
        raise RuntimeError("Hold Manager shadow contract is unavailable") from exc

    # A build number is only as trustworthy as its binding to a hash, and that
    # binding cannot be checked from a single state: two different sources
    # could carry the same number if someone forgets to increment. Reject a
    # history that maps one build to two hashes, or that does not contain the
    # pair the contract currently claims. tests/test_smc_hold_manager_build_
    # history.py enforces the same invariant in the repository; this is the
    # fail-closed copy that guards a corrupted deploy.
    hashes_per_build: dict[int, set[str]] = {}
    for build, sha256 in build_history:
        hashes_per_build.setdefault(build, set()).add(sha256)

    if (
        len(contract.source_sha256) != _SOURCE_HASH_LENGTH
        or any(char not in "0123456789abcdef" for char in contract.source_sha256)
        or contract.source_hash_mode != _SOURCE_HASH_MODE
        or contract.frozen_micro_profile_library_pin
        != _FROZEN_MICRO_PROFILE_LIBRARY_PIN
        or contract.channels != _CHANNELS
        or contract.bus_schema <= 0
        or contract.source_build < 1
        or any(len(seen) > 1 for seen in hashes_per_build.values())
        or (contract.source_build, contract.source_sha256) not in build_history
    ):
        raise RuntimeError("Hold Manager shadow contract is invalid")
    return contract


def _authenticate(token: str, compare: TokenCompare) -> None:
    expected = config.hold_manager_shadow_webhook_token()
    if len(expected) < 32:
        raise HTTPException(
            status_code=503,
            detail="Hold Manager shadow receiver is not configured",
        )
    if not compare(token, expected):
        observability.metric_counter(
            "live_overlay.hold_manager_shadow.auth_denied.total"
        )
        raise HTTPException(status_code=404)
def _ledger_path() -> Path:
    path = config.hold_manager_shadow_ledger_path()
    if path is None:
        raise HTTPException(
            status_code=503,
            detail="Hold Manager shadow ledger is not configured",
        )
    return path


def _normalize_timeframe(raw: str) -> str:
    value = raw.strip()
    return f"{value}m" if value.isdigit() else value


def _canonical_time(value: dt.datetime) -> str:
    return (
        value.astimezone(dt.UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _shared_contract_checks(
    payload: _HoldManagerShadowEvent,
    contract: _Contract,
) -> dict[str, bool]:
    return {
        "requirementId": payload.requirement_id == _REQUIREMENT_ID,
        "channel": payload.channel in contract.channels,
        "mode": payload.mode == "hold_manager",
        "scriptName": payload.script_name == contract.saved_script,
        "layout": payload.layout == contract.layout,
        "producer": payload.producer == contract.producer,
        "busSchema": payload.bus_schema == contract.bus_schema,
    }


def _reject_mismatches(checks: dict[str, bool]) -> None:
    mismatches = sorted(field for field, ok in checks.items() if not ok)
    if mismatches:
        observability.metric_counter(
            "live_overlay.hold_manager_shadow.contract_rejected.total",
            mismatches=",".join(mismatches),
        )
        raise HTTPException(
            status_code=409,
            detail={
                "error": "payload does not match the registered shadow contract",
                "fields": mismatches,
            },
        )


def _validate_contract(
    payload: HoldManagerShadowAlert,
    contract: _Contract,
) -> None:
    checks = _shared_contract_checks(payload, contract)
    checks["sourceSha256"] = payload.source_sha256 == contract.source_sha256
    _reject_mismatches(checks)


def _validate_build_contract(
    payload: HoldManagerShadowBuildAlert,
    contract: _Contract,
) -> None:
    """Same strictness as the legacy check, one indirection further out.

    A stale script deployed on TradingView emits the previous build number and
    is rejected here, exactly as a stale hash was rejected before.
    """
    checks = _shared_contract_checks(payload, contract)
    checks["sourceBuild"] = payload.source_build == contract.source_build
    _reject_mismatches(checks)


def _validate_event_time(
    payload: HoldManagerShadowAlert,
    *,
    now: dt.datetime,
) -> None:
    event_time = payload.bar_time.astimezone(dt.UTC)
    age_seconds = (now - event_time).total_seconds()
    if age_seconds > config.hold_manager_shadow_max_event_age_secs():
        raise HTTPException(
            status_code=409,
            detail="barTime is older than the shadow acceptance window",
        )
    if age_seconds < -config.hold_manager_shadow_max_future_skew_secs():
        raise HTTPException(
            status_code=409,
            detail="barTime is newer than the allowed clock skew",
        )


def _event_id(payload: _HoldManagerShadowEvent, source_sha256: str) -> str:
    """Unchanged composition: the attested hash is still the identity.

    The build-pinned shape does not carry a hash, so the caller passes the
    contract's -- which validation has just proven equivalent to whatever the
    legacy shape would have sent. Duplicate detection is therefore identical
    across both shapes and across the cutover.
    """
    identity = [
        payload.requirement_id,
        source_sha256,
        payload.channel,
        payload.symbol,
        _normalize_timeframe(payload.timeframe),
        _canonical_time(payload.bar_time),
    ]
    encoded = json.dumps(
        identity,
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()
    connection = sqlite3.connect(path, timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA synchronous = FULL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS hold_manager_shadow_events (
            event_id TEXT PRIMARY KEY,
            requirement_id TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            channel TEXT NOT NULL,
            mode TEXT NOT NULL,
            script_name TEXT NOT NULL,
            layout TEXT NOT NULL,
            producer TEXT NOT NULL,
            bus_schema INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            bar_time TEXT NOT NULL,
            price TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            first_received_at TEXT NOT NULL,
            last_received_at TEXT NOT NULL,
            delivery_count INTEGER NOT NULL CHECK (delivery_count >= 1)
        )
        """
    )
    connection.commit()
    if not existed:
        os.chmod(path, 0o600)
    return connection


def _persist(
    path: Path,
    payload: _HoldManagerShadowEvent,
    *,
    source_sha256: str,
    event_id: str,
    received_at: str,
) -> bool:
    payload_json = json.dumps(
        payload.model_dump(mode="json", by_alias=True),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    connection = _connect(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO hold_manager_shadow_events (
                event_id,
                requirement_id,
                source_sha256,
                channel,
                mode,
                script_name,
                layout,
                producer,
                bus_schema,
                symbol,
                timeframe,
                bar_time,
                price,
                payload_json,
                first_received_at,
                last_received_at,
                delivery_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                event_id,
                payload.requirement_id,
                source_sha256,
                payload.channel,
                payload.mode,
                payload.script_name,
                payload.layout,
                payload.producer,
                payload.bus_schema,
                payload.symbol,
                _normalize_timeframe(payload.timeframe),
                _canonical_time(payload.bar_time),
                str(payload.price),
                payload_json,
                received_at,
                received_at,
            ),
        )
        inserted = cursor.rowcount == 1
        if not inserted:
            connection.execute(
                """
                UPDATE hold_manager_shadow_events
                SET delivery_count = delivery_count + 1,
                    last_received_at = ?
                WHERE event_id = ?
                """,
                (received_at, event_id),
            )
        connection.commit()
        return inserted
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _empty_channel_counts() -> dict[str, int]:
    return dict.fromkeys(_CHANNELS, 0)


def _session_breakdown(
    event_rows: list[Any],  # sqlite3.Row or any mapping with the same keys
    market_timezone: str,
) -> list[dict[str, Any]]:
    """Group the per-event ledger rows into US-market session dates.

    A session date is the calendar date of the event's ``bar_time`` in the
    contract's market timezone — the same calendar the evaluator's
    ``sessions[*].sessionDate`` rows use, so the reconciliation script can
    match receiver deliveries to recorded sessions 1:1.
    """
    zone = ZoneInfo(market_timezone)
    by_date: dict[str, dict[str, dict[str, int]]] = {}
    for row in event_rows:
        channel = str(row["channel"])
        if channel not in _CHANNELS:
            continue
        bar_time = dt.datetime.fromisoformat(
            str(row["bar_time"]).replace("Z", "+00:00")
        )
        session_date = bar_time.astimezone(zone).date().isoformat()
        session = by_date.setdefault(
            session_date,
            {
                "uniqueByChannel": _empty_channel_counts(),
                "duplicatesByChannel": _empty_channel_counts(),
            },
        )
        session["uniqueByChannel"][channel] += 1
        session["duplicatesByChannel"][channel] += int(row["delivery_count"]) - 1
    return [
        {"sessionDate": session_date, **counts}
        for session_date, counts in sorted(by_date.items())
    ]


def _state(path: Path, market_timezone: str) -> dict[str, Any]:
    unique_by_channel = _empty_channel_counts()
    attempts_by_channel = _empty_channel_counts()
    duplicates_by_channel = _empty_channel_counts()
    last_received_at: str | None = None
    sessions: list[dict[str, Any]] = []
    if path.exists():
        connection = _connect(path)
        try:
            rows = connection.execute(
                """
                SELECT
                    channel,
                    COUNT(*) AS unique_events,
                    SUM(delivery_count) AS delivery_attempts,
                    SUM(delivery_count - 1) AS duplicate_deliveries,
                    MAX(last_received_at) AS last_received_at
                FROM hold_manager_shadow_events
                GROUP BY channel
                """
            ).fetchall()
            event_rows = connection.execute(
                """
                SELECT channel, bar_time, delivery_count
                FROM hold_manager_shadow_events
                """
            ).fetchall()
        finally:
            connection.close()
        sessions = _session_breakdown(event_rows, market_timezone)
        for row in rows:
            channel = str(row["channel"])
            if channel not in unique_by_channel:
                continue
            unique_by_channel[channel] = int(row["unique_events"])
            attempts_by_channel[channel] = int(row["delivery_attempts"])
            duplicates_by_channel[channel] = int(row["duplicate_deliveries"])
            received = row["last_received_at"]
            if isinstance(received, str) and (
                last_received_at is None or received > last_received_at
            ):
                last_received_at = received

    return {
        "schemaVersion": 1,
        "requirementId": _REQUIREMENT_ID,
        "accepting": config.hold_manager_shadow_accepting(),
        "uniqueEvents": sum(unique_by_channel.values()),
        "deliveryAttempts": sum(attempts_by_channel.values()),
        "duplicateDeliveries": sum(duplicates_by_channel.values()),
        "uniqueByChannel": unique_by_channel,
        "attemptsByChannel": attempts_by_channel,
        "duplicatesByChannel": duplicates_by_channel,
        "lastReceivedAt": last_received_at,
        "marketTimezone": market_timezone,
        "sessions": sessions,
    }


async def _read_payload[T: _HoldManagerShadowEvent](
    request: Request,
    model: type[T],
) -> T:
    content_type = request.headers.get("content-type", "")
    media_type = content_type.split(";", 1)[0].strip().casefold()
    if media_type != "application/json":
        raise HTTPException(status_code=415, detail="application/json required")
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            parsed_length = int(content_length)
            if parsed_length < 0:
                raise ValueError
            if parsed_length > _MAX_BODY_BYTES:
                raise HTTPException(status_code=413, detail="payload too large")
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="invalid content-length",
            ) from exc
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > _MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="payload too large")
    try:
        raw = json.loads(body)
        if not isinstance(raw, Mapping):
            raise ValueError("payload must be an object")
        return model.model_validate(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError):
        observability.metric_counter(
            "live_overlay.hold_manager_shadow.payload_rejected.total"
        )
        raise HTTPException(
            status_code=400,
            detail="invalid Hold Manager shadow payload",
        ) from None


def build_router(compare_token: TokenCompare) -> APIRouter:
    """Build the private router using the daemon's reviewed token comparator."""

    router = APIRouter()

    async def _ingest(
        payload: _HoldManagerShadowEvent,
        contract: _Contract,
        ledger_path: Path,
    ) -> dict[str, Any]:
        now = dt.datetime.now(dt.UTC)
        _validate_event_time(payload, now=now)
        event_id = _event_id(payload, contract.source_sha256)
        received_at = _canonical_time(now)
        try:
            # Off the event loop: sqlite3 connect + PRAGMA synchronous=FULL
            # + BEGIN IMMEDIATE + commit is an fsync on the Railway volume,
            # with a 5 s busy timeout under lock contention. Measured
            # 2026-08-05: on the loop this pushed /smc_live median latency
            # x9.4; the identical disk work threadpooled costs x2.0.
            inserted = await run_in_threadpool(
                _persist,
                ledger_path,
                payload,
                source_sha256=contract.source_sha256,
                event_id=event_id,
                received_at=received_at,
            )
        except (OSError, sqlite3.Error):
            observability.metric_counter(
                "live_overlay.hold_manager_shadow.persist_failed.total"
            )
            raise HTTPException(
                status_code=503,
                detail="Hold Manager shadow ledger is unavailable",
            ) from None

        status = "accepted" if inserted else "duplicate"
        observability.metric_counter(
            f"live_overlay.hold_manager_shadow.{status}.total",
            channel=payload.channel,
        )
        observability.audit_event(
            "hold_manager_shadow_delivery",
            status,
            channel=payload.channel,
            event_id=event_id,
            symbol=payload.symbol,
            timeframe=_normalize_timeframe(payload.timeframe),
        )
        return {
            "schemaVersion": 1,
            "requirementId": _REQUIREMENT_ID,
            "status": status,
            "eventId": event_id,
            "receivedAt": received_at,
        }

    async def _accepting_contract_and_ledger() -> tuple[_Contract, Path]:
        if not config.hold_manager_shadow_accepting():
            raise HTTPException(
                status_code=503,
                detail="Hold Manager shadow receiver is not accepting events",
            )
        ledger_path = _ledger_path()
        try:
            # Off the event loop: stat + read + json.loads on every request.
            # This coroutine shares its loop with /{token}/smc_live.
            contract = await run_in_threadpool(
                _load_contract, config.hold_manager_shadow_contract_path()
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return contract, ledger_path

    async def ingest_hold_manager_shadow(
        request: Request,
    ) -> dict[str, Any]:
        """Legacy route: token in the body, source named by hash.

        Left byte-for-byte in behaviour so the six alerts created on
        2026-07-28 keep delivering across the merge and the auto-deploy it
        triggers. Removed in step 3 of the decoupling design, once the
        readback has proven the cutover.
        """
        payload = await _read_payload(request, HoldManagerShadowAlert)
        _authenticate(payload.auth_token, compare_token)
        contract, ledger_path = await _accepting_contract_and_ledger()
        _validate_contract(payload, contract)
        return await _ingest(payload, contract, ledger_path)

    async def ingest_hold_manager_shadow_build(
        request: Request,
        token: str = PathParam(..., min_length=1, max_length=256),
    ) -> dict[str, Any]:
        """Build-pinned route: token in the path, source named by build.

        Authentication runs BEFORE the body is parsed, unlike the legacy
        route, so an unauthenticated caller cannot reach the parser at all.
        """
        _authenticate(token, compare_token)
        payload = await _read_payload(request, HoldManagerShadowBuildAlert)
        contract, ledger_path = await _accepting_contract_and_ledger()
        _validate_build_contract(payload, contract)
        return await _ingest(payload, contract, ledger_path)

    router.add_api_route(
        "/tradingview/hold-manager-shadow",
        ingest_hold_manager_shadow,
        methods=["POST"],
        include_in_schema=False,
    )

    # Token first: main.py runs uvicorn with access_log=False specifically so
    # that /{token}/... paths never reach stdout or the Railway logs, and the
    # daemon already authenticates /{token}/smc_live this way. A route shaped
    # any other way would not inherit that protection.
    router.add_api_route(
        "/{token}/tradingview/hold-manager-shadow",
        ingest_hold_manager_shadow_build,
        methods=["POST"],
        include_in_schema=False,
    )

    @router.get(
        "/tradingview/hold-manager-shadow/state",
        include_in_schema=False,
    )
    def hold_manager_shadow_state(
        token: str = Header(
            ...,
            alias="X-Hold-Manager-Shadow-Token",
            min_length=1,
            max_length=256,
        ),
    ) -> dict[str, Any]:
        _authenticate(token, compare_token)
        path = _ledger_path()
        try:
            contract = _load_contract(
                config.hold_manager_shadow_contract_path()
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        try:
            return _state(path, contract.market_timezone)
        except (OSError, sqlite3.Error):
            raise HTTPException(
                status_code=503,
                detail="Hold Manager shadow ledger is unavailable",
            ) from None

    return router
