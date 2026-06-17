"""
Config — reads from environment variables (Railway injects them, local uses .env).

Required vars:
  DATABENTO_API_KEY      — Databento API key (Unlimited plan)
  OVERLAY_SECRET_TOKEN   — random token embedded in the URL path (Pine security)

Optional vars:
  OVERLAY_REFRESH_SECS        — standard field refresh cadence, default 1800 (30 min)
  OVERLAY_FLOW_REFRESH_SECS   — flow-field fast refresh cadence, default 300 (5 min)
  OVERLAY_MAX_STALE_SECS      — threshold for marking payload stale, default 3600 (1 h)
  OVERLAY_ROLLING_BARS        — number of 1-min bars to keep per symbol, default 60
  NEWS_SNAPSHOT_PATH          — path to news snapshot JSON, default relative to repo root
  PORT                        — HTTP port, default 8000
  LOG_LEVEL                   — uvicorn log level, default info
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _REPO_ROOT / ".env"


def _load_env() -> None:
    """Load .env file if present (Railway provides vars directly via env)."""
    if not _ENV_FILE.exists():
        return
    for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if key and key not in os.environ:
            os.environ.setdefault(key, value)


_load_env()


def _require(key: str) -> str:
    value = os.getenv(key, "").strip()
    if not value:
        raise RuntimeError(
            f"Required environment variable {key!r} is not set. "
            "Set it in .env (local) or Railway environment variables (production)."
        )
    return value


def _optional_int(key: str, default: int) -> int:
    raw = os.getenv(key, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        logger.warning(
            "Invalid integer for %s=%r, falling back to default %d",
            key, raw, default,
        )
        return default


def _optional_str(key: str, default: str) -> str:
    return os.getenv(key, "").strip() or default


# ---------------------------------------------------------------------------
# Public config accessors (called lazily to allow tests to patch os.environ)
# ---------------------------------------------------------------------------

def databento_api_key() -> str:
    return _require("DATABENTO_API_KEY")


def overlay_secret_token() -> str:
    return _require("OVERLAY_SECRET_TOKEN")


def refresh_secs() -> int:
    val = _optional_int("OVERLAY_REFRESH_SECS", 1800)
    if not 10 <= val <= 86400:
        logger.warning(
            "OVERLAY_REFRESH_SECS=%d outside valid range [10, 86400], clamping",
            val,
        )
        val = max(10, min(86400, val))
    return val


def flow_refresh_secs() -> int:
    val = _optional_int("OVERLAY_FLOW_REFRESH_SECS", 300)
    if not 5 <= val <= 3600:
        logger.warning(
            "OVERLAY_FLOW_REFRESH_SECS=%d outside valid range [5, 3600], clamping",
            val,
        )
        val = max(5, min(3600, val))
    return val


def max_stale_secs() -> int:
    val = _optional_int("OVERLAY_MAX_STALE_SECS", 3600)
    if not 60 <= val <= 7200:
        logger.warning(
            "OVERLAY_MAX_STALE_SECS=%d outside valid range [60, 7200], clamping",
            val,
        )
        val = max(60, min(7200, val))
    return val


def rolling_bars() -> int:
    val = _optional_int("OVERLAY_ROLLING_BARS", 60)
    if not 1 <= val <= 500:
        logger.warning(
            "OVERLAY_ROLLING_BARS=%d outside valid range [1, 500], clamping",
            val,
        )
        val = max(1, min(500, val))
    return val


def news_snapshot_path() -> Path:
    raw = _optional_str(
        "NEWS_SNAPSHOT_PATH",
        str(
            _REPO_ROOT
            / "artifacts"
            / "smc_microstructure_exports"
            / "smc_live_news_snapshot.json"
        ),
    )
    return Path(raw)


def max_symbols() -> int:
    val = _optional_int("OVERLAY_MAX_SYMBOLS", 2000)
    if not 100 <= val <= 50000:
        logger.warning(
            "OVERLAY_MAX_SYMBOLS=%d outside valid range [100, 50000], clamping",
            val,
        )
        val = max(100, min(50000, val))
    return val


def news_cache_ttl_secs() -> int:
    val = _optional_int("OVERLAY_NEWS_CACHE_TTL_SECS", 600)
    if not 60 <= val <= 3600:
        logger.warning(
            "OVERLAY_NEWS_CACHE_TTL_SECS=%d outside valid range [60, 3600], clamping",
            val,
        )
        val = max(60, min(3600, val))
    return val


def port() -> int:
    return _optional_int("PORT", 8000)


def log_level() -> str:
    return _optional_str("LOG_LEVEL", "info").lower()
