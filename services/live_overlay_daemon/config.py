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
  NEWS_SNAPSHOT_URL           — optional https URL fetched at runtime; takes precedence
                                over NEWS_SNAPSHOT_PATH and falls back to it (and the
                                baked seed) on any fetch failure
  NEWS_SNAPSHOT_URL_TOKEN     — optional bearer token for NEWS_SNAPSHOT_URL (e.g. a
                                GitHub token for the private contents API raw endpoint)
  OVERLAY_MAX_FEED_FAILURES   — circuit-breaker threshold for feed failures, default 50
  PORT                        — HTTP port, default 8000
  LOG_LEVEL                   — uvicorn log level, default info
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)
# Uvicorn-compatible log levels (case-insensitive input, lower-cased output).
_VALID_UVICORN_LOG_LEVELS: frozenset[str] = frozenset(
    {"critical", "error", "warning", "info", "debug", "trace"}
)


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
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
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


def _clamped_int(key: str, default: int, lo: int, hi: int) -> int:
    """Read an optional int env var and clamp to [lo, hi] with a warning."""
    val = _optional_int(key, default)
    if not lo <= val <= hi:
        logger.warning(
            "%s=%d outside valid range [%d, %d], clamping", key, val, lo, hi,
        )
        val = max(lo, min(hi, val))
    return val


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
    return _clamped_int("OVERLAY_REFRESH_SECS", 1800, 10, 86400)


def flow_refresh_secs() -> int:
    return _clamped_int("OVERLAY_FLOW_REFRESH_SECS", 300, 5, 3600)


def max_stale_secs() -> int:
    return _clamped_int("OVERLAY_MAX_STALE_SECS", 3600, 60, 7200)


def rolling_bars() -> int:
    return _clamped_int("OVERLAY_ROLLING_BARS", 60, 1, 500)


def news_snapshot_path() -> Path:
    """Local path to the latest news-provider health snapshot JSON.

    The canonical tracked seed lives at ``artifacts/live_overlay/news_snapshot.json``
    so the daemon (and local dashboard) works out of the box. CI producers publish
    fresher snapshots to ``artifacts/smc_microstructure_exports/smc_live_news_snapshot.json``
    on the ``bot/live-news-snapshot`` branch; off-host daemons should set
    :func:`news_snapshot_url` to that branch instead.
    """
    raw = _optional_str(
        "NEWS_SNAPSHOT_PATH",
        str(
            _REPO_ROOT
            / "artifacts"
            / "live_overlay"
            / "news_snapshot.json"
        ),
    )
    return Path(raw)


def news_snapshot_url() -> str:
    """Optional https URL the daemon fetches the news snapshot from at runtime.

    When set it takes precedence over :func:`news_snapshot_path`; on any fetch
    failure the daemon falls back to the local path (and baked seed).
    """
    return _optional_str("NEWS_SNAPSHOT_URL", "")


def news_snapshot_url_token() -> str:
    """Optional bearer token sent when fetching :func:`news_snapshot_url`."""
    return _optional_str("NEWS_SNAPSHOT_URL_TOKEN", "")


def max_symbols() -> int:
    return _clamped_int("OVERLAY_MAX_SYMBOLS", 2000, 100, 50000)


def news_cache_ttl_secs() -> int:
    return _clamped_int("OVERLAY_NEWS_CACHE_TTL_SECS", 600, 60, 3600)


def signals_snapshot_path() -> Path:
    raw = _optional_str(
        "SIGNALS_SNAPSHOT_PATH",
        str(
            _REPO_ROOT
            / "artifacts"
            / "open_prep"
            / "latest"
            / "latest_realtime_signals.json"
        ),
    )
    return Path(raw)


def signals_snapshot_url() -> str:
    """Optional https URL the daemon fetches realtime trading signals from.

    When set it takes precedence over :func:`signals_snapshot_path`; on any
    fetch failure the daemon falls back to the local path.
    """
    return _optional_str("SIGNALS_SNAPSHOT_URL", "")


def signals_snapshot_url_token() -> str:
    """Optional bearer token sent when fetching :func:`signals_snapshot_url`."""
    return _optional_str("SIGNALS_SNAPSHOT_URL_TOKEN", "")


def signals_service_url() -> str:
    """Optional internal URL of the smc-signals-producer service.

    When set, :func:`services.live_overlay_daemon.compute._load_signals_snapshot`
    fetches live A0/A1 signals directly from the producer over the Railway
    private network before falling back to :func:`signals_snapshot_url` or
    :func:`signals_snapshot_path`. Example value:
    ``smc-signals-producer.railway.internal``.
    """
    return _optional_str("SIGNALS_SERVICE_URL", "")


def signals_internal_token() -> str:
    """Bearer token used when calling :func:`signals_service_url`.

    Sent as ``Authorization: Bearer <token>``. Must match the token the
    producer requires for its ``/signals.json`` endpoint.
    """
    return _optional_str("SIGNALS_INTERNAL_TOKEN", "")


def signals_cache_ttl_secs() -> int:
    return _clamped_int("OVERLAY_SIGNALS_CACHE_TTL_SECS", 120, 30, 1800)


def signals_max_age_secs() -> int:
    """Age (s) beyond which the realtime signals snapshot is treated as stale."""
    return _clamped_int("OVERLAY_SIGNALS_MAX_AGE_SECS", 480, 60, 7200)


def experiment_snapshot_path() -> Path:
    """Local path to the latest Plan 2.8 per-TF family rollup JSON.

    The canonical tracked seed lives at ``artifacts/live_overlay/plan_2_8_tf_family_rollup.json``
    so the daemon (and local dashboard) works out of the box. CI producers publish
    fresher rollups to ``artifacts/ci/measurement_benchmark_rolling/latest/`` on the
    ``bot/live-experiment-snapshot`` branch; off-host daemons should set
    :func:`experiment_snapshot_url` to that branch instead.
    """
    raw = _optional_str(
        "EXPERIMENT_SNAPSHOT_PATH",
        str(
            _REPO_ROOT
            / "artifacts"
            / "live_overlay"
            / "plan_2_8_tf_family_rollup.json"
        ),
    )
    return Path(raw)


def experiment_snapshot_url() -> str:
    """Optional https URL the daemon fetches the daily family rollup from.

    When set it takes precedence over :func:`experiment_snapshot_path`; on any
    fetch failure the daemon falls back to the local path.
    """
    return _optional_str("EXPERIMENT_SNAPSHOT_URL", "")


def experiment_snapshot_url_token() -> str:
    """Optional bearer token sent when fetching :func:`experiment_snapshot_url`."""
    return _optional_str("EXPERIMENT_SNAPSHOT_URL_TOKEN", "")


def experiment_history_path() -> Path:
    """Local path to the Plan 2.8 per-day history JSONL.

    The canonical tracked seed lives at ``artifacts/live_overlay/plan_2_8_history.jsonl``
    so the daemon (and local dashboard) works out of the box. CI producers publish
    fresher history to ``artifacts/ci/measurement_benchmark_rolling/latest/`` on the
    ``bot/live-experiment-snapshot`` branch; off-host daemons should set
    :func:`experiment_history_url` to that branch instead.
    """
    raw = _optional_str(
        "EXPERIMENT_HISTORY_PATH",
        str(
            _REPO_ROOT
            / "artifacts"
            / "live_overlay"
            / "plan_2_8_history.jsonl"
        ),
    )
    return Path(raw)


def experiment_history_url() -> str:
    """Optional https URL the daemon fetches the per-day history JSONL from."""
    return _optional_str("EXPERIMENT_HISTORY_URL", "")


def experiment_history_url_token() -> str:
    """Optional bearer token sent when fetching :func:`experiment_history_url`."""
    return _optional_str("EXPERIMENT_HISTORY_URL_TOKEN", "")


def experiment_cache_ttl_secs() -> int:
    """How long the daemon caches the experiment rollup/history before reload."""
    return _clamped_int("OVERLAY_EXPERIMENT_CACHE_TTL_SECS", 900, 60, 7200)


def experiment_max_age_secs() -> int:
    """Age (s) beyond which the daily experiment rollup is treated as stale.

    The rolling benchmark runs roughly daily, so the default tolerates a
    skipped run (~36h) before the snapshot-age panel turns red.
    """
    return _clamped_int("OVERLAY_EXPERIMENT_MAX_AGE_SECS", 129600, 3600, 1209600)


def experiment_history_max_days() -> int:
    """Cap on the number of per-day history snapshots surfaced as metrics."""
    return _clamped_int("OVERLAY_EXPERIMENT_HISTORY_MAX_DAYS", 30, 1, 366)


def tradingview_credential_snapshot_path() -> Path:
    """Local path to the daily credential-health report JSON.

    The canonical tracked seed lives at ``artifacts/live_overlay/credential_health.json``
    so the daemon (and local dashboard) works out of the box. CI producers publish
    fresher reports to ``artifacts/credential_health/latest/`` on the
    ``bot/live-tv-credential-snapshot`` branch; off-host daemons should set
    :func:`tradingview_credential_snapshot_url` to that branch instead.

    The daemon reads the ``tv_storage_state_age`` probe from this file to
    surface the TradingView storage-state credential age.
    """
    raw = _optional_str(
        "TRADINGVIEW_CREDENTIAL_SNAPSHOT_PATH",
        str(
            _REPO_ROOT
            / "artifacts"
            / "live_overlay"
            / "credential_health.json"
        ),
    )
    return Path(raw)


def tradingview_credential_snapshot_url() -> str:
    """Optional https URL the daemon fetches the credential-health report from.

    When set it takes precedence over
    :func:`tradingview_credential_snapshot_path`; on any fetch failure the
    daemon falls back to the local path.
    """
    return _optional_str("TRADINGVIEW_CREDENTIAL_SNAPSHOT_URL", "")


def tradingview_credential_snapshot_url_token() -> str:
    """Optional bearer token sent when fetching the credential snapshot URL."""
    return _optional_str("TRADINGVIEW_CREDENTIAL_SNAPSHOT_URL_TOKEN", "")


def tradingview_credential_cache_ttl_secs() -> int:
    """How long the daemon caches the credential-health report before reload.

    The report is refreshed at most once per day, so a 1h cache keeps load off
    the producer URL while still picking up the daily refresh promptly.
    """
    return _clamped_int("OVERLAY_TRADINGVIEW_CREDENTIAL_CACHE_TTL_SECS", 3600, 60, 86400)


def max_feed_failures() -> int:
    return _clamped_int("OVERLAY_MAX_FEED_FAILURES", 50, 1, 1000)


def port() -> int:
    return _optional_int("PORT", 8000)


def log_level() -> str:
    """Return uvicorn-compatible log level, falling back to "info"."""
    raw = _optional_str("LOG_LEVEL", "info").lower()
    if raw == "warn":
        return "warning"
    if raw not in _VALID_UVICORN_LOG_LEVELS:
        logger.warning("LOG_LEVEL=%r is not a valid uvicorn log level; using info", raw)
        return "info"
    return raw


def uptimerobot_api_key() -> str:
    """Optional UptimeRobot API key used for Grafana bridge polling."""
    return _optional_str("UPTIMEROBOT_API_KEY", "")


def uptimerobot_monitor_ids() -> list[str]:
    """Optional monitor id allow-list parsed from comma-separated env var."""
    raw = _optional_str("UPTIMEROBOT_MONITOR_IDS", "")
    if not raw:
        return []
    ids = [item.strip() for item in raw.split(",") if item.strip()]
    # Preserve order and de-duplicate.
    seen: set[str] = set()
    unique_ids: list[str] = []
    for monitor_id in ids:
        if monitor_id in seen:
            continue
        seen.add(monitor_id)
        unique_ids.append(monitor_id)
    return unique_ids


def uptimerobot_timeout_secs() -> int:
    """HTTP timeout for UptimeRobot polling requests."""
    return _clamped_int("UPTIMEROBOT_TIMEOUT_SECS", 5, 1, 30)


def uptimerobot_poll_ttl_secs() -> int:
    """Cache TTL for UptimeRobot polling results."""
    return _clamped_int("UPTIMEROBOT_POLL_TTL_SECS", 30, 5, 300)


def github_workflow_token() -> str:
    """Optional GitHub token for workflow monitoring bridge."""
    return _optional_str("GITHUB_WORKFLOW_MONITOR_TOKEN", "")


_GITHUB_OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
_GITHUB_REPO_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


def github_workflow_repo() -> tuple[str, str]:
    """Repo target for GitHub workflow polling in owner/repo format."""
    raw = _optional_str("GITHUB_WORKFLOW_MONITOR_REPO", "skippALGO/skipp-algo")
    owner, sep, repo = raw.partition("/")
    owner = owner.strip()
    repo = repo.strip()
    if (
        sep != "/"
        or not _GITHUB_OWNER_RE.match(owner)
        or not _GITHUB_REPO_RE.match(repo)
    ):
        logger.warning(
            "GITHUB_WORKFLOW_MONITOR_REPO=%r invalid, falling back to skippALGO/skipp-algo",
            raw,
        )
        return ("skippALGO", "skipp-algo")
    return (owner, repo)


def github_workflow_ids() -> list[str]:
    """Optional workflow-id allow-list parsed from comma-separated env var."""
    raw = _optional_str("GITHUB_WORKFLOW_MONITOR_IDS", "")
    if not raw:
        return []
    ids = [item.strip() for item in raw.split(",") if item.strip()]
    seen: set[str] = set()
    unique_ids: list[str] = []
    for workflow_id in ids:
        if workflow_id in seen:
            continue
        seen.add(workflow_id)
        unique_ids.append(workflow_id)
    return unique_ids


def github_workflow_timeout_secs() -> int:
    """HTTP timeout for GitHub workflow polling requests."""
    return _clamped_int("GITHUB_WORKFLOW_MONITOR_TIMEOUT_SECS", 5, 1, 30)


def github_workflow_poll_ttl_secs() -> int:
    """Cache TTL for GitHub workflow snapshot reuse."""
    return _clamped_int("GITHUB_WORKFLOW_MONITOR_POLL_TTL_SECS", 30, 5, 300)


def github_workflow_per_page() -> int:
    """Number of workflow runs requested per poll."""
    return _clamped_int("GITHUB_WORKFLOW_MONITOR_PER_PAGE", 30, 1, 100)


def restart_cause() -> str:
    """Deployment/runtime restart cause label for observability dashboards.

    Examples: deploy, crash, manual, autoscale, unknown.
    """
    raw = _optional_str("LIVE_OVERLAY_RESTART_CAUSE", "unknown").lower()
    normalized = re.sub(r"[^a-z0-9_]+", "_", raw).strip("_")
    return normalized or "unknown"


def ingest_queue_max() -> int:
    """Maximum number of pending bars in feed ingest queue."""
    return _clamped_int("LIVE_OVERLAY_INGEST_QUEUE_MAX", 20000, 1000, 200000)


def expect_market_traffic() -> bool:
    """Return True when the deployment should expect US-open smc_live traffic.

    Operators set ``LIVE_OVERLAY_EXPECT_MARKET_TRAFFIC=1`` to arm the
    first-zero traffic alert. When unset the gauge stays ``0`` and the alert
    stays quiet, so quiet periods outside market hours or warm-standby
    deployments do not page.
    """
    return _optional_str("LIVE_OVERLAY_EXPECT_MARKET_TRAFFIC", "0") == "1"


# ---------------------------------------------------------------------------
# Railway container metrics bridge
# ---------------------------------------------------------------------------


def railway_metrics_enabled() -> bool:
    """Return True iff Railway container metrics polling is enabled.

    The bridge is active when explicitly enabled via ``ENABLE_RAILWAY_METRICS=1``
    or when all required Railway credentials are configured, so operators do not
    need to remember two separate opt-in flags.
    """
    if _optional_str("ENABLE_RAILWAY_METRICS", "0") == "1":
        return True
    return bool(
        _optional_str("RAILWAY_API_TOKEN", "")
        and _optional_str("RAILWAY_PROJECT_ID", "")
        and _optional_str("RAILWAY_ENVIRONMENT_ID", "")
    )


def railway_api_token() -> str:
    """Railway API token for GraphQL metrics queries."""
    return _optional_str("RAILWAY_API_TOKEN", "")


def railway_project_id() -> str:
    """Railway project ID for metrics queries."""
    return _optional_str("RAILWAY_PROJECT_ID", "")


def railway_environment_id() -> str:
    """Railway environment ID for metrics queries."""
    return _optional_str("RAILWAY_ENVIRONMENT_ID", "")


def railway_service_names() -> dict[str, str]:
    """Mapping of Railway service IDs to human-readable names.

    Format: RAILWAY_SERVICE_NAMES="service-id-1=signals-producer,service-id-2=live-overlay"
    """
    raw = _optional_str("RAILWAY_SERVICE_NAMES", "")
    if not raw:
        return {}
    mapping: dict[str, str] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        service_id, _sep, name = pair.partition("=")
        service_id = service_id.strip()
        name = name.strip()
        if service_id and name:
            mapping[service_id] = name
    return mapping


def railway_metrics_timeout_secs() -> int:
    """HTTP timeout for Railway GraphQL requests."""
    return _clamped_int("RAILWAY_METRICS_TIMEOUT_SECS", 10, 1, 60)


def railway_metrics_window_secs() -> int:
    """Time window for Railway metrics query (how far back to look)."""
    return _clamped_int("RAILWAY_METRICS_WINDOW_SECS", 300, 60, 3600)


def railway_metrics_sample_secs() -> int:
    """Sample rate for Railway metrics aggregation."""
    return _clamped_int("RAILWAY_METRICS_SAMPLE_SECS", 60, 10, 600)


def railway_metrics_poll_ttl_secs() -> int:
    """Cache TTL for Railway metrics snapshot reuse."""
    return _clamped_int("RAILWAY_METRICS_POLL_TTL_SECS", 60, 10, 600)
