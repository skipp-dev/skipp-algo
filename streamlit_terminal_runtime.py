from __future__ import annotations

import time
from typing import Any


def resolve_live_story_state_kwargs(cfg: Any | None = None) -> dict[str, float]:
    cfg_obj = cfg
    return {
        "ttl_s": float(getattr(cfg_obj, "live_story_ttl_s", 7200.0) or 7200.0),
        "cooldown_s": float(getattr(cfg_obj, "live_story_cooldown_s", 900.0) or 900.0),
    }


def safe_float_mov(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def should_poll(
    *,
    poll_interval: float,
    last_poll_ts: float,
    provider_available: bool,
    now: float | None = None,
) -> bool:
    if not provider_available or float(poll_interval) <= 0:
        return False
    current_now = float(now if now is not None else time.time())
    return (current_now - float(last_poll_ts)) >= float(poll_interval)
