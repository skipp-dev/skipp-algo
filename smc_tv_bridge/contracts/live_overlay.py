"""Typed wire contract for the ``smc-live-overlay/1`` live-overlay payload.

The live overlay is the *fast* half of the "slow baseline + fast overlay"
design. The former ``SMC_Regime_and_News.pine`` REST bridge is retired; Pine
cannot call arbitrary HTTP endpoints. The payload remains the API contract for
authenticated non-Pine clients. Every data field is optional and nullable so the service can
emit only values it currently knows and leave unavailable values absent.

This module is the single source of truth shared by the FastAPI endpoint
(``smc_tv_bridge/smc_api.py``) and the contract tests. The hand-written JSON
Schema in ``spec/smc_live_overlay.schema.json`` mirrors it for non-Python
consumers.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: Contract identifier carried in the ``schema`` field of every payload.
SCHEMA_ID: str = "smc-live-overlay/1"

#: Timeframes the overlay can be requested for, in canonical Pine spelling.
SUPPORTED_TIMEFRAMES: tuple[str, ...] = ("1m", "5m", "10m", "15m", "30m", "1H", "4H")

#: Allowed non-null values for ``news_bias``.
NEWS_BIAS_VALUES: tuple[str, ...] = ("BULLISH", "BEARISH", "NEUTRAL")

#: Envelope fields that are always present on the wire.
ENVELOPE_FIELDS: tuple[str, ...] = ("schema", "symbol", "tf", "asof_ts", "stale")

TimeframeLiteral = Literal["1m", "5m", "10m", "15m", "30m", "1H", "4H"]
NewsBiasLiteral = Literal["BULLISH", "BEARISH", "NEUTRAL"]
ProviderTrustLiteral = Literal["ok", "degraded", "unavailable"]


class LiveOverlayPayload(BaseModel):
    """Flat live-overlay payload served at ``GET /smc_live``.

    Envelope fields (``schema``/``symbol``/``tf``/``asof_ts``/``stale``) are
    always present. Data fields default to ``None`` and are dropped from the
    wire form by :func:`flatten_overlay`, so the served payload only carries
    fields the overlay can actually speak to.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    # --- envelope (always present) ---
    schema_: Literal["smc-live-overlay/1"] = Field(default=SCHEMA_ID, alias="schema")
    symbol: str = Field(min_length=1)
    tf: TimeframeLiteral
    asof_ts: int = Field(ge=0)
    stale: bool

    # --- Generated-library context (additive daemon enrichment) ---
    universe_member: bool | None = None
    universe_size: int | None = Field(default=None, ge=0)
    library_asof_date: str | None = None
    library_asof_time: str | None = None
    provider_trust_status: ProviderTrustLiteral | None = None
    provider_stale_list: str | None = None

    # --- News overlay fields (served fresh); flow_rel_vol/squeeze_on are
    # baked-only here (daemon-served elsewhere, never by this endpoint) ---
    news_strength: float | None = Field(default=None, ge=0.0, le=1.0)
    news_bias: NewsBiasLiteral | None = None
    flow_rel_vol: float | None = Field(default=None, ge=0.0)
    squeeze_on: Literal[0, 1] | None = None

    # --- B2 overlay fields (served live by /smc_live: vix, flow/ATS, tone, heat) ---
    vix_level: float | None = Field(default=None, ge=0.0)
    flow_delta_proxy_pct: float | None = None
    price_candle_body_return_pct: float | None = None
    ats_state: str | None = None
    volume_accumulation_distribution_state: str | None = None
    ats_zscore: float | None = None
    volume_current_bar_zscore: float | None = None
    tone: str | None = None
    global_heat: float | None = Field(default=None, ge=-1.0, le=1.0)

    # --- Event-risk overlay fields (served from the corporate-actions reference snapshot; no calendar feed in this path) ---
    event_window_state: str | None = None
    event_risk_level: str | None = None
    next_event_name: str | None = None
    next_event_time: str | None = None
    market_event_blocked: bool | None = None
    symbol_event_blocked: bool | None = None
    event_provider_status: str | None = None

    # --- Realtime signal / trade-context fields (A0/A1/A2 engine +
    # open_prep/trade_context.py, passed through the daemon's signals
    # snapshot — the SAME numbers the Slack push shows). Display guidance,
    # not order placement. Null when the symbol has no active signal.
    signal_level: Literal["A0", "A1", "A2"] | None = None
    signal_direction: str | None = None
    trade_entry: float | None = Field(default=None, gt=0.0)
    trade_stop: float | None = Field(default=None, gt=0.0)
    trade_target: float | None = Field(default=None, gt=0.0)
    trade_r: float | None = Field(default=None, gt=0.0)


def flatten_overlay(payload: LiveOverlayPayload) -> dict[str, object]:
    """Serialize ``payload`` to the canonical flat dict served at ``/smc_live``.

    Null fields are dropped so the wire payload carries only fields the overlay
    can speak to; Pine falls back to the baked ``mp.*`` value for everything
    absent. Aliases are applied so the ``schema`` key uses its wire spelling.
    """

    return payload.model_dump(by_alias=True, exclude_none=True)
