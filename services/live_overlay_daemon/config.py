"""
Config — reads from environment variables (Railway injects them, local uses .env).

Required vars:
  DATABENTO_API_KEY      — Databento API key (Unlimited plan)
  OVERLAY_SECRET_TOKEN   — random token embedded in the URL path (Pine security)

Optional vars:
  OVERLAY_REFRESH_SECS        — standard field refresh cadence, default 1800 (30 min)
  OVERLAY_FLOW_REFRESH_SECS   — flow-field fast refresh cadence, default 300 (5 min)
  OVERLAY_MAX_STALE_SECS      — threshold for marking payload stale, default 3600 (1 h)
  OVERLAY_MAX_BAR_AGE_SECS    — threshold for BAR recency (a 60s cadence, not the
                                compute cadence), default 180 = the feed's own stall threshold
  OVERLAY_ROLLING_BARS        — number of 1-min bars to keep per symbol, default 60
  NEWS_SNAPSHOT_PATH          — path to news snapshot JSON, default relative to repo root
  NEWS_SNAPSHOT_URL           — optional https URL fetched at runtime; takes precedence
                                over NEWS_SNAPSHOT_PATH and falls back to it (and the
                                baked seed) on any fetch failure
  NEWS_SNAPSHOT_URL_TOKEN     — optional bearer token for NEWS_SNAPSHOT_URL (e.g. a
                                GitHub token for the private contents API raw endpoint)
  OVERLAY_MAX_FEED_FAILURES   — circuit-breaker threshold for feed failures, default 50
  HOLD_MANAGER_SHADOW_ACCEPTING — explicit shadow-receiver switch, default 0
  HOLD_MANAGER_SHADOW_WEBHOOK_TOKEN — dedicated JSON-body token, minimum 32 chars
  HOLD_MANAGER_SHADOW_LEDGER_PATH — persistent SQLite delivery-ledger path
  PORT                        — HTTP port, default 8000
  LOG_LEVEL                   — uvicorn log level, default info
"""
from __future__ import annotations

import logging
import os
import re
import urllib.parse
from pathlib import Path

logger = logging.getLogger(__name__)
# Uvicorn-compatible log levels (case-insensitive input, lower-cased output).
_VALID_UVICORN_LOG_LEVELS: frozenset[str] = frozenset(
    {"critical", "error", "warning", "info", "debug", "trace"}
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _REPO_ROOT / ".env"

_DEFAULT_GITHUB_OWNER = "skipp-dev"
_DEFAULT_GITHUB_REPO = "skipp-algo"


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
        # Quoted value: take the content up to the closing quote (a trailing
        # inline comment after it is dropped; a `#` inside the quotes is kept).
        # Unquoted: drop a whitespace-preceded inline comment ("9000 # note" ->
        # "9000") while keeping a bare "a#b". Without this, `PORT=9000 # note`
        # parsed as "9000 # note" and silently fell back to the default port.
        if value[:1] in {'"', "'"}:
            end = value.find(value[0], 1)
            if end != -1:
                value = value[1:end]
        else:
            for _i in range(1, len(value)):
                if value[_i] == "#" and value[_i - 1] in " \t":
                    value = value[:_i].rstrip()
                    break
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


def _snapshot_url(key: str, *, path: str, ref: str) -> str:
    """Return an explicit snapshot URL or the monitored repo's rolling file.

    An explicitly present-but-empty environment variable disables the remote
    source (useful for local/offline operation).  When the variable is absent,
    hosted deployments consume the canonical ``bot/live-*`` branch instead of
    silently serving the stale seed baked into the container image.
    """
    configured = os.getenv(key)
    if configured is not None:
        return configured.strip()
    owner, repo = github_workflow_repo()
    encoded_ref = urllib.parse.quote(ref, safe="/")
    return (
        f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
        f"?ref={encoded_ref}"
    )


def _snapshot_url_token(key: str, url: str) -> str:
    """Return a source-specific token, or reuse the repo monitor token safely.

    The generic workflow-monitor token is attached only to the configured
    repository's GitHub Contents API or its exact ``raw.githubusercontent.com``
    path.  It is never forwarded to an arbitrary custom URL or another GitHub
    repository.
    """
    explicit = _optional_str(key, "")
    if explicit:
        return explicit
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return ""
    owner, repo = github_workflow_repo()
    expected_prefix = f"/repos/{owner}/{repo}/contents/"
    is_own_contents_api = (
        parsed.scheme.lower() == "https"
        and parsed.netloc.lower() == "api.github.com"
        and parsed.path.startswith(expected_prefix)
    )
    raw_parts = [urllib.parse.unquote(part).casefold() for part in parsed.path.split("/") if part]
    is_own_raw_file = (
        parsed.scheme.lower() == "https"
        and parsed.netloc.lower() == "raw.githubusercontent.com"
        and len(raw_parts) >= 3
        and raw_parts[:2] == [owner.casefold(), repo.casefold()]
    )
    if is_own_contents_api or is_own_raw_file:
        return github_workflow_token()
    return ""


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


def max_bar_age_secs() -> int:
    """Budget for BAR recency — a different clock than ``max_stale_secs``.

    ``max_stale_secs`` is sized for the compute cadence: the refresh thread
    recomputes every ``OVERLAY_REFRESH_SECS`` (1800s default), so 3600 gives
    two cycles of headroom before a payload counts as stale. Bars arrive on a
    60-second cadence, so the SAME number is 60x too loose for them — measured
    2026-08-20: the first 60 minutes of any feed freeze were served as
    ``stale: false``, and ``_latest_bar_age_secs`` reasons in its own docstring
    about a "60s budget" that no caller supplied.

    The default is the daemon's own stall threshold
    (``feed._STALL_MAX_BAR_AGE_SECS`` = 180): what the supervisor treats as a
    stalled feed must not be served as fresh data. Not a duplicate constant —
    that one decides whether to HEAL, this one decides what to SAY.
    """
    return _clamped_int("OVERLAY_MAX_BAR_AGE_SECS", 180, 60, 3600)


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
    # Default 30 (was 120): the producer refreshes its snapshot every ~35s
    # poll cycle, so a 120s daemon cache added up to ~2min staleness to every
    # signal consumer (Pine trade context, Grafana signal panels) for no
    # gain. 30s ≈ the producer cadence; the fetch is one private-net GET.
    return _clamped_int("OVERLAY_SIGNALS_CACHE_TTL_SECS", 30, 30, 1800)


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

    Points at the rolling benchmark's output, which is the only producer that
    actually measures: it runs scripts/plan_2_8_tf_family_rollup.py over the
    day's ``scoring_<symbol>_<tf>.json`` artifacts. Until 2026-08-08 this
    defaulted to ``artifacts/experiment/latest/``, written by the
    scripts/plan_2_8_evaluate.py placeholder that drew its hit rates, event
    counts and verdicts from ``random`` -- contradicting
    :func:`experiment_snapshot_path`'s own docstring, which already named the
    rolling path as the fresh one.
    """
    return _snapshot_url(
        "EXPERIMENT_SNAPSHOT_URL",
        path="artifacts/ci/measurement_benchmark_rolling/latest/plan_2_8_tf_family_rollup.json",
        ref="bot/live-experiment-snapshot",
    )


def experiment_snapshot_url_token() -> str:
    """Optional bearer token sent when fetching :func:`experiment_snapshot_url`."""
    return _snapshot_url_token("EXPERIMENT_SNAPSHOT_URL_TOKEN", experiment_snapshot_url())


def evidence_freshness_snapshot_path() -> Path:
    """Local path to the evidence-freshness snapshot JSON.

    Produced by ``scripts/build_evidence_freshness_snapshot.py`` in CI and
    served as Prometheus gauges so a silently frozen ADR-0023 ledger /
    ``data/phase-a-audit`` branch / paper-fills chain becomes visible (the
    2026-06/07 blind-spot). Off-host daemons should set
    :func:`evidence_freshness_snapshot_url` to the published branch instead.
    """
    raw = _optional_str(
        "EVIDENCE_FRESHNESS_SNAPSHOT_PATH",
        str(_REPO_ROOT / "artifacts" / "monitoring" / "evidence_freshness.json"),
    )
    return Path(raw)


def evidence_freshness_snapshot_url() -> str:
    """Optional https URL the daemon fetches the evidence-freshness snapshot from.

    When set it takes precedence over :func:`evidence_freshness_snapshot_path`;
    on any fetch failure the daemon falls back to the local path.
    """
    return _snapshot_url(
        "EVIDENCE_FRESHNESS_SNAPSHOT_URL",
        path="artifacts/monitoring/latest/evidence_freshness.json",
        ref="bot/live-evidence-freshness",
    )


def evidence_freshness_snapshot_url_token() -> str:
    """Optional bearer token for :func:`evidence_freshness_snapshot_url`."""
    return _snapshot_url_token(
        "EVIDENCE_FRESHNESS_SNAPSHOT_URL_TOKEN",
        evidence_freshness_snapshot_url(),
    )


def sweep_trap_shadow_snapshot_path() -> Path:
    """Local path to the sweep-trap shadow snapshot JSON.

    Produced by ``scripts/eval_sweep_trap_shadow.py`` (WS4a) so the daily
    Brier-delta + sample accrual toward the sweep-trap promotion decision is
    served as Prometheus gauges. Off-host daemons should set
    :func:`sweep_trap_shadow_snapshot_url` to the published branch instead.
    """
    raw = _optional_str(
        "SWEEP_TRAP_SHADOW_SNAPSHOT_PATH",
        str(_REPO_ROOT / "artifacts" / "monitoring" / "sweep_trap_shadow.json"),
    )
    return Path(raw)


def sweep_trap_shadow_snapshot_url() -> str:
    """Optional https URL the daemon fetches the sweep-trap shadow snapshot from.

    When set it takes precedence over :func:`sweep_trap_shadow_snapshot_path`;
    on any fetch failure the daemon falls back to the local path.
    """
    return _snapshot_url(
        "SWEEP_TRAP_SHADOW_SNAPSHOT_URL",
        path="artifacts/monitoring/latest/sweep_trap_shadow.json",
        ref="bot/live-sweep-trap-shadow",
    )


def sweep_trap_shadow_snapshot_url_token() -> str:
    """Optional bearer token for :func:`sweep_trap_shadow_snapshot_url`."""
    return _snapshot_url_token(
        "SWEEP_TRAP_SHADOW_SNAPSHOT_URL_TOKEN",
        sweep_trap_shadow_snapshot_url(),
    )


def sweep_trap_shadow_cache_ttl_secs() -> int:
    """How long the daemon caches the sweep-trap shadow snapshot before reload."""
    return _clamped_int("OVERLAY_SWEEP_TRAP_SHADOW_CACHE_TTL_SECS", 900, 60, 7200)


def sweep_trap_shadow_max_age_secs() -> int:
    """Age (s) beyond which the sweep-trap shadow snapshot is treated as stale.

    Default 96h — same weekday-cadence sizing as the experiment/evidence
    snapshots: the daily eval runs Mon-Fri, so Friday's snapshot is legitimately
    ~89.5h old when Monday's arrives, and 96h tolerates one skipped weekday run.
    """
    return _clamped_int("OVERLAY_SWEEP_TRAP_SHADOW_MAX_AGE_SECS", 345600, 3600, 1209600)


def reaction_zone_shadow_snapshot_path() -> Path:
    """Local path to the reaction-zone shadow snapshot JSON.

    Produced by ``scripts/eval_reaction_zone_shadow.py`` (the observe-only
    reaction-zone follow-through study) so its per-direction lift + promotion
    accrual is served as Prometheus gauges. Off-host daemons should set
    :func:`reaction_zone_shadow_snapshot_url` to the published branch instead.
    """
    raw = _optional_str(
        "REACTION_ZONE_SHADOW_SNAPSHOT_PATH",
        str(_REPO_ROOT / "artifacts" / "monitoring" / "reaction_zone_shadow.json"),
    )
    return Path(raw)


def reaction_zone_shadow_snapshot_url() -> str:
    """Optional https URL the daemon fetches the reaction-zone shadow snapshot from.

    When set it takes precedence over :func:`reaction_zone_shadow_snapshot_path`;
    on any fetch failure the daemon falls back to the local path. Defaults to the
    same rolling ``bot/live-sweep-trap-shadow`` branch the sweep-trap-shadow-daily
    workflow publishes ``reaction_zone_shadow.json`` to (git add -f into
    ``artifacts/monitoring/latest/``, alongside ``sweep_trap_shadow.json``).
    """
    return _snapshot_url(
        "REACTION_ZONE_SHADOW_SNAPSHOT_URL",
        path="artifacts/monitoring/latest/reaction_zone_shadow.json",
        ref="bot/live-sweep-trap-shadow",
    )


def reaction_zone_shadow_snapshot_url_token() -> str:
    """Optional bearer token for :func:`reaction_zone_shadow_snapshot_url`."""
    return _snapshot_url_token(
        "REACTION_ZONE_SHADOW_SNAPSHOT_URL_TOKEN",
        reaction_zone_shadow_snapshot_url(),
    )


def reaction_zone_shadow_cache_ttl_secs() -> int:
    """How long the daemon caches the reaction-zone shadow snapshot before reload."""
    return _clamped_int("OVERLAY_REACTION_ZONE_SHADOW_CACHE_TTL_SECS", 900, 60, 7200)


def reaction_zone_shadow_max_age_secs() -> int:
    """Age (s) beyond which the reaction-zone shadow snapshot is treated as stale.

    Default 96h — same weekday-cadence sizing as the sweep-trap shadow snapshot it
    is published beside: the daily eval runs Mon-Fri, so Friday's snapshot is
    legitimately ~89.5h old when Monday's arrives, and 96h tolerates one skipped
    weekday run.
    """
    return _clamped_int("OVERLAY_REACTION_ZONE_SHADOW_MAX_AGE_SECS", 345600, 3600, 1209600)


def provider_usage_snapshot_path() -> Path:
    """Local path to the provider API-usage snapshot JSON.

    Produced by the ingest layer (``newsstack_fmp/provider_usage.py``) and
    surfaced as Prometheus gauges so provider DATA-VOLUME consumption is
    visible (the FMP-quota blind spot: a "90% of bandwidth used" email was the
    only signal). Off-host daemons set :func:`provider_usage_snapshot_url`.
    """
    raw = _optional_str(
        "PROVIDER_USAGE_SNAPSHOT_PATH",
        str(_REPO_ROOT / "artifacts" / "monitoring" / "provider_usage.json"),
    )
    return Path(raw)


def provider_usage_snapshot_url() -> str:
    """Optional https URL the daemon fetches the provider-usage snapshot from.

    Takes precedence over :func:`provider_usage_snapshot_path`; on any fetch
    failure the daemon falls back to the local path.
    """
    return _snapshot_url(
        "PROVIDER_USAGE_SNAPSHOT_URL",
        path="artifacts/monitoring/provider_usage.json",
        ref="bot/live-open-prep-snapshot",
    )


def provider_usage_snapshot_url_token() -> str:
    """Optional bearer token for :func:`provider_usage_snapshot_url`."""
    return _snapshot_url_token("PROVIDER_USAGE_SNAPSHOT_URL_TOKEN", provider_usage_snapshot_url())


def pine_library_versions_snapshot_path() -> Path:
    """Local path to the Repo↔TradingView Pine-library version snapshot JSON.

    Produced by ``scripts/build_pine_library_version_snapshot.ts`` in CI and
    surfaced as Prometheus gauges so a stale ``import preuss_steffen/<lib>/<N>``
    pin (the #3599/#3603 blind spot: micro_profiles drifted ``/1`` vs a live
    ``/152`` for ~4 months with no alert) becomes a red panel instead of a
    silent CE10272. Off-host daemons set :func:`pine_library_versions_snapshot_url`.
    """
    raw = _optional_str(
        "PINE_LIBRARY_VERSIONS_SNAPSHOT_PATH",
        str(_REPO_ROOT / "artifacts" / "monitoring" / "pine_library_versions.json"),
    )
    return Path(raw)


def pine_library_versions_snapshot_url() -> str:
    """Optional https URL the daemon fetches the Pine-library version snapshot from.

    When set it takes precedence over :func:`pine_library_versions_snapshot_path`;
    on any fetch failure the daemon falls back to the local path.
    """
    return _snapshot_url(
        "PINE_LIBRARY_VERSIONS_SNAPSHOT_URL",
        path="artifacts/monitoring/latest/pine_library_versions.json",
        ref="bot/live-pine-library-versions",
    )


def pine_library_versions_snapshot_url_token() -> str:
    """Optional bearer token for :func:`pine_library_versions_snapshot_url`."""
    return _snapshot_url_token(
        "PINE_LIBRARY_VERSIONS_SNAPSHOT_URL_TOKEN",
        pine_library_versions_snapshot_url(),
    )


def library_context_pine_path() -> Path:
    """Local path to the generated Pine library the library-context bridge parses.

    Fallback only. The baked copy is whatever the image was built from, which is
    NOT the same as "the current library" — see :func:`library_context_pine_url`.
    """
    raw = _optional_str(
        "LIBRARY_CONTEXT_PINE_PATH",
        str(_REPO_ROOT / "pine" / "generated" / "smc_micro_profiles_generated.pine"),
    )
    return Path(raw)


def library_context_pine_url() -> str:
    """HTTPS URL the daemon fetches the generated Pine library from.

    MEASURED 2026-09-01, the reason this exists: ``library_context_bridge`` was
    the only bridge without a runtime source — it parsed the copy baked into the
    container image, justified with "the daemon [...] redeploys on every main
    push". That premise is false *by design*, which is the sharp part: this
    service has no Railway git trigger on purpose (``deploymentTriggers`` is
    empty, enforced by ``live-overlay-deploy-trigger-guard.yml``) and deploys
    only through ``deploy-live-overlay-daemon.yml``, which is **path-filtered to
    ``services/live_overlay_daemon/**`` + ``scripts/deploy_live_overlay.sh``**.

    This file lives outside that filter, so a library refresh can NEVER trigger
    a redeploy — the baked copy refreshes only by accident, when an unrelated
    change to the service directory happens to ship. Measured consequence:
    between the 08-21 and 08-30 deploys main moved the library **87 times**
    while the daemon kept serving ``UNIVERSE_SIZE=6960`` and a universe from
    08-20 against main's 6952 and a different ticker set — nine days of
    ``universe_member`` decided on a stale list, with nothing alerting.

    ``ref="main"`` because ``smc-library-refresh.yml`` lands the regenerated
    library on main via PR (repo is SSOT, see CLAUDE.md) — there is no
    ``bot/live-*`` branch for this file.
    """
    return _snapshot_url(
        "LIBRARY_CONTEXT_PINE_URL",
        path="pine/generated/smc_micro_profiles_generated.pine",
        ref="main",
    )


def library_context_pine_url_token() -> str:
    """Optional bearer token for :func:`library_context_pine_url`."""
    return _snapshot_url_token(
        "LIBRARY_CONTEXT_PINE_URL_TOKEN",
        library_context_pine_url(),
    )


def library_context_cache_ttl_secs() -> int:
    """How long a fetched library stays cached before the next fetch."""
    return _clamped_int("OVERLAY_LIBRARY_CONTEXT_CACHE_TTL_SECS", 900, 60, 7200)


def tradingview_bindings_snapshot_path() -> Path:
    """Local path to the actual TradingView consumer-dropdown snapshot."""
    return Path(
        _optional_str(
            "TRADINGVIEW_BINDINGS_SNAPSHOT_PATH",
            str(_REPO_ROOT / "artifacts" / "monitoring" / "tradingview_consumer_bindings.json"),
        )
    )


def tradingview_bindings_snapshot_url() -> str:
    """Optional HTTPS URL for the actual TradingView dropdown snapshot."""
    return _snapshot_url(
        "TRADINGVIEW_BINDINGS_SNAPSHOT_URL",
        path="artifacts/monitoring/latest/tradingview_consumer_bindings.json",
        ref="bot/live-tradingview-bindings",
    )


def tradingview_bindings_snapshot_url_token() -> str:
    """Optional bearer token for :func:`tradingview_bindings_snapshot_url`."""
    return _snapshot_url_token(
        "TRADINGVIEW_BINDINGS_SNAPSHOT_URL_TOKEN",
        tradingview_bindings_snapshot_url(),
    )


def fmp_monthly_bandwidth_limit_bytes() -> int:
    """FMP plan's rolling-30-day bandwidth quota, in bytes (default 150 GB).

    Surfaced as a gauge so the dashboard can show FMP data-volume used as a
    percentage and alert before the quota is exhausted. The monthly-accumulated
    usage snapshot is a close proxy for FMP's rolling-30-day meter.
    """
    return _optional_int("FMP_MONTHLY_BANDWIDTH_LIMIT_BYTES", 150_000_000_000)


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
    """Optional https URL the daemon fetches the per-day history JSONL from.

    Same producer as :func:`experiment_snapshot_url`. The rolling history is the
    one that accumulates: measured 2026-08-07 it held 133 rows against the
    placeholder path's 1.
    """
    return _snapshot_url(
        "EXPERIMENT_HISTORY_URL",
        path="artifacts/ci/measurement_benchmark_rolling/latest/plan_2_8_history.jsonl",
        ref="bot/live-experiment-snapshot",
    )


def experiment_history_url_token() -> str:
    """Optional bearer token sent when fetching :func:`experiment_history_url`."""
    return _snapshot_url_token("EXPERIMENT_HISTORY_URL_TOKEN", experiment_history_url())


def experiment_cache_ttl_secs() -> int:
    """How long the daemon caches the experiment rollup/history before reload (also reused as the snapshot-cache TTL for the provider-usage and evidence-freshness bridges)."""
    return _clamped_int("OVERLAY_EXPERIMENT_CACHE_TTL_SECS", 900, 60, 7200)


def experiment_max_age_secs() -> int:
    """Age (s) beyond which the daily experiment rollup is treated as stale.

    Default 96h, sized to the REAL cadence: the age anchors on midnight UTC
    of the rollup's run_date, the benchmark runs Mon-Fri only and lands
    ~13:30-17:30 UTC, so Friday's rollup is legitimately ~89.5h old when
    Monday's arrives. The previous 36h default therefore fired every
    weekend (~50h of false alarm) and most weekdays around noon (found
    2026-07-08). 96h additionally tolerates one skipped weekday run.
    """
    return _clamped_int("OVERLAY_EXPERIMENT_MAX_AGE_SECS", 345600, 3600, 1209600)


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
    return _snapshot_url(
        "TRADINGVIEW_CREDENTIAL_SNAPSHOT_URL",
        path="artifacts/credential_health/latest/credential_health.json",
        ref="bot/live-tv-credential-snapshot",
    )


def tradingview_credential_snapshot_url_token() -> str:
    """Optional bearer token sent when fetching the credential snapshot URL."""
    return _snapshot_url_token(
        "TRADINGVIEW_CREDENTIAL_SNAPSHOT_URL_TOKEN",
        tradingview_credential_snapshot_url(),
    )


def tradingview_credential_cache_ttl_secs() -> int:
    """How long the daemon caches the credential-health report before reload.

    The report is refreshed at most once per day, so a 1h cache keeps load off
    the producer URL while still picking up the daily refresh promptly.
    """
    return _clamped_int("OVERLAY_TRADINGVIEW_CREDENTIAL_CACHE_TTL_SECS", 3600, 60, 86400)


def max_feed_failures() -> int:
    return _clamped_int("OVERLAY_MAX_FEED_FAILURES", 50, 1, 1000)


def port() -> int:
    raw = _optional_int("PORT", 8000)
    if not 1 <= raw <= 65535:
        # An out-of-range PORT must not silently bind a random ephemeral port
        # (raw == 0) or crash uvicorn with an opaque OverflowError (raw < 0 or
        # raw > 65535). Fall back to the documented default, like an
        # unparseable PORT does, so the failure mode is logged and predictable.
        logger.warning(
            "PORT=%d is outside the valid TCP range [1, 65535]; "
            "falling back to default 8000",
            raw,
        )
        return 8000
    return raw


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
    default = f"{_DEFAULT_GITHUB_OWNER}/{_DEFAULT_GITHUB_REPO}"
    raw = _optional_str("GITHUB_WORKFLOW_MONITOR_REPO", default)
    owner, sep, repo = raw.partition("/")
    owner = owner.strip()
    repo = repo.strip()
    if (
        sep != "/"
        or not _GITHUB_OWNER_RE.match(owner)
        or not _GITHUB_REPO_RE.match(repo)
    ):
        logger.warning(
            "GITHUB_WORKFLOW_MONITOR_REPO=%r invalid, falling back to %s",
            raw, default,
        )
        return (_DEFAULT_GITHUB_OWNER, _DEFAULT_GITHUB_REPO)
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


def github_workflow_expected() -> list[str]:
    """Workflow NAMES that must keep producing runs, from a comma-separated env var.

    Everything else about workflow health is *discovered* from the fetched runs
    page, which cannot express "this flow stopped running": a workflow with no
    runs on the page contributes no row, so its age/verdict series simply vanish
    and every rule over them goes NoData (silent under ``noDataState: OK``). The
    staler a flow gets, the likelier it is missing — so absence, not staleness,
    is the signal that needs a declared expectation to compare against.

    Names (not ids) because this list is maintained by hand alongside
    ``.github/workflows/``; ids are opaque and change when a workflow is
    recreated. Empty (the default) disables presence monitoring entirely.
    """
    raw = _optional_str("GITHUB_WORKFLOW_MONITOR_EXPECTED", "")
    if not raw:
        return []
    seen: set[str] = set()
    expected: list[str] = []
    for item in raw.split(","):
        name = item.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        expected.append(name)
    return expected


def github_workflow_timeout_secs() -> int:
    """HTTP timeout for GitHub workflow polling requests."""
    return _clamped_int("GITHUB_WORKFLOW_MONITOR_TIMEOUT_SECS", 5, 1, 30)


def github_workflow_poll_ttl_secs() -> int:
    """Cache TTL for GitHub workflow snapshot reuse."""
    return _clamped_int("GITHUB_WORKFLOW_MONITOR_POLL_TTL_SECS", 30, 5, 300)


def github_workflow_presence_ttl_secs() -> int:
    """Cache TTL for the per-workflow PRESENCE probe (own, slower cadence).

    Deliberately far above ``github_workflow_poll_ttl_secs`` (30 s): the presence
    probe costs ONE GitHub API call per declared workflow, while the snapshot
    costs one in total. At 30 s and 30 declared workflows that would be ~3600
    calls/h against a 5000/h budget -- the probe would starve the daemon's other
    GitHub traffic. At the 600 s default it is ~180/h.

    Why a dedicated probe at all: the snapshot derives everything from ONE page
    of ``/actions/runs``, and that page covered NINE hours on 2026-08-31 (five
    on 2026-08-20 -- it shrinks with repo activity). A daily workflow is absent
    from it for two thirds of the day, so a presence signal read off that page
    cannot distinguish "stopped running" from "ran this morning".
    """
    return _clamped_int("GITHUB_WORKFLOW_PRESENCE_TTL_SECS", 600, 60, 3600)


def github_workflow_per_page() -> int:
    """Number of workflow runs requested per poll.

    The single fetched page must reach back far enough to include each monitored
    workflow's newest *verdict* run; if a low-frequency flow's last success/failure
    scrolls past the window, ``latest_success`` falls back to its provisional 0 and
    ``no-green-24h`` false-fires (seen for the databento export on a heavy main-push
    day, 2026-07-08). Defaults to the max (100) so a busy day of main pushes does not
    bury a sparse workflow's last verdict. 100 is GitHub's per-page ceiling and this
    value is clamped to it, so the env var can only lower it — a flow buried past one
    page needs pagination here, not a bigger number. Until then, declare it in
    ``github_workflow_expected`` so its disappearance alerts instead of going quiet.
    """
    return _clamped_int("GITHUB_WORKFLOW_MONITOR_PER_PAGE", 100, 1, 100)


def github_workflow_branch() -> str:
    """Head branch the monitored runs are restricted to (default: ``main``).

    Scoping to the default branch stops a green feature-branch run from masking
    a red ``main`` run (and vice-versa) in ``latest_success`` / ``phase_code``.
    Set to an empty string to disable the filter and track runs on all branches
    (the pre-2026-07 behaviour). PR-only workflows (e.g. ``pr-title-concern-lint``)
    have no main run and simply drop out of the main-scoped view.
    """
    return _optional_str("GITHUB_WORKFLOW_MONITOR_BRANCH", "main").strip()


# 2026-07-28 (B-sweep): restart_cause() / LIVE_OVERLAY_RESTART_CAUSE removed.
# The env was never set in any deploy surface (railway.toml, Dockerfile,
# workflow), so the label was the constant "unknown" — and a statically-set
# env var can never distinguish deploy from crash, so the documented
# semantics ("deploy, crash, manual, …") were unreachable by construction.
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


def hold_manager_shadow_webhook_token() -> str:
    """Secret embedded in the controlled TradingView webhook URL."""
    return _optional_str("HOLD_MANAGER_SHADOW_WEBHOOK_TOKEN", "")


def hold_manager_shadow_accepting() -> bool:
    """Whether the pre-registered Hold Manager shadow receiver accepts POSTs."""
    return _optional_str("HOLD_MANAGER_SHADOW_ACCEPTING", "0") == "1"


def hold_manager_shadow_ledger_path() -> Path | None:
    """Persistent SQLite ledger path, or None when deliberately unconfigured."""
    raw = _optional_str("HOLD_MANAGER_SHADOW_LEDGER_PATH", "")
    return Path(raw).expanduser() if raw else None


def hold_manager_shadow_contract_path() -> Path:
    """Path to the pre-registered R2 shadow contract."""
    raw = _optional_str(
        "HOLD_MANAGER_SHADOW_CONTRACT_PATH",
        str(
            _REPO_ROOT
            / "artifacts"
            / "governance"
            / "smc_hold_manager_shadow_contract.json"
        ),
    )
    return Path(raw).expanduser()


def hold_manager_shadow_max_event_age_secs() -> int:
    """Maximum accepted age of a TradingView bar timestamp."""
    return _clamped_int(
        "HOLD_MANAGER_SHADOW_MAX_EVENT_AGE_SECS",
        900,
        60,
        86_400,
    )


def hold_manager_shadow_max_future_skew_secs() -> int:
    """Maximum accepted positive clock skew of a TradingView bar timestamp."""
    return _clamped_int(
        "HOLD_MANAGER_SHADOW_MAX_FUTURE_SKEW_SECS",
        120,
        0,
        3_600,
    )


def bar_max_future_skew_secs() -> int:
    """Maximum accepted positive clock skew of an ingested market bar."""
    return _clamped_int(
        "BAR_MAX_FUTURE_SKEW_SECS",
        120,
        0,
        3_600,
    )


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


# ---------------------------------------------------------------------------
# Railway volume-backup bridge
# ---------------------------------------------------------------------------


def railway_volume_backup_instances() -> dict[str, str]:
    """Volume instances to watch, as ``{human_name: volume_instance_id}``.

    Format mirrors :func:`railway_service_names` but in the readable direction,
    because the *name* is what ends up on the Prometheus label::

        RAILWAY_VOLUME_BACKUP_INSTANCES="lab-worker-volume=2ffcaeb7-...,other=..."

    The list is also the opt-in: an empty value disables the bridge. There is no
    second flag, so there is no way to "enable" it into a state where it watches
    nothing and still reports green.
    """
    raw = _optional_str("RAILWAY_VOLUME_BACKUP_INSTANCES", "")
    if not raw:
        return {}
    mapping: dict[str, str] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        name, _sep, instance_id = pair.partition("=")
        name = name.strip()
        instance_id = instance_id.strip()
        if name and instance_id:
            mapping[name] = instance_id
    return mapping


def railway_volume_backup_enabled() -> bool:
    """True iff at least one volume instance is configured and a token exists."""
    return bool(railway_api_token() and railway_volume_backup_instances())


def railway_volume_backup_timeout_secs() -> int:
    """HTTP timeout for the volume-backup GraphQL requests."""
    return _clamped_int("RAILWAY_VOLUME_BACKUP_TIMEOUT_SECS", 10, 1, 60)


def railway_volume_backup_poll_ttl_secs() -> int:
    """Cache TTL for the volume-backup snapshot.

    Backups appear at most a few times a day, so the default is far longer than
    the container-metrics TTL: polling faster buys nothing and spends Railway
    API budget on every Prometheus scrape.
    """
    return _clamped_int("RAILWAY_VOLUME_BACKUP_POLL_TTL_SECS", 600, 30, 3600)


def railway_volume_backup_max_age_secs() -> int:
    """Age at which a newest backup counts as stale (exported as a gauge).

    Exported rather than hard-coded in the alert rule so the threshold the
    daemon believes in and the one Grafana compares against cannot drift apart.
    """
    return _clamped_int("RAILWAY_VOLUME_BACKUP_MAX_AGE_SECS", 129_600, 3600, 1_209_600)
