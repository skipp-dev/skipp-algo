# Changelog

<!-- markdownlint-disable MD024 -->

All notable changes to this project are documented in this file.

## [Unreleased]

### Fixed (2026-06-30) — TradingView settings surface DOM hint

- `automation/tradingview/lib/tv_shared.ts`:
  - Exported `hasSettingsSurfaceDomHint()` for focused DOM-hint coverage.
  - Keeps the browser-evaluated DOM probe free of transform-injected helper
    references so it can run inside the page context.
- `automation/tradingview/tests/tv_shared.test.ts`:
  - Added Playwright coverage for settings dialog/menu DOM hints, visible
    `Settings...` actions, and hidden or unrelated controls.
### Fixed (2026-06-30) — SMC library refresh advisory naming

- `.github/workflows/smc-library-refresh.yml`:
  - Renamed the soft-fail post-release normalization step to explicitly mark
    it as best-effort for the continue-on-error semantics guard.
### Fixed (2026-06-30) — TradingView add-to-chart effect tests

- `automation/tradingview/lib/tv_shared.ts`:
  - Exported `hasAddToChartClickEffect()` for focused add-to-chart click
    effect coverage.
- `automation/tradingview/tests/tv_shared.test.ts`:
  - Added Playwright coverage for the Update-on-chart, disappeared Add button,
    visible chart script, and negative no-effect branches.

### Fixed (2026-06-30) — Live overlay operations cleanup

- `services/live_overlay_daemon/railway_metrics.py`:
  - Classifies `URLError(TimeoutError(...))` Railway GraphQL failures as
    `timeout` instead of generic `network_error`.
- `services/live_overlay_daemon/OPS.md`:
  - Clarified that `live_overlay_market_us_open` is the intentional
    US-regular-session gate for **Market Traffic Health**; the historical bug
    was missing request-counter data during no-traffic startup.
- `tests/test_railway_metrics.py`:
  - Added regression coverage for wrapped timeout and non-timeout `URLError`
    bridge failures.
  - Added regression coverage for direct `TimeoutError` bridge failures.
- `tests/test_global_statement_budget.py`:
  - Refreshed the Railway metrics `reset_cache()` global anchor after the
    error-classification cleanup.

### Fixed (2026-06-30) — Live overlay Railway port default

- `services/live_overlay_daemon/railway.toml`:
  - Runs `python -m services.live_overlay_daemon.main` so Railway does not need
    to shell-expand `$PORT` inside `startCommand`.
- `services/live_overlay_daemon/main.py`:
  - Added the module entrypoint that binds uvicorn to `0.0.0.0` and reads
    `PORT` from the runtime environment, defaulting to `8000` locally.
- `tests/test_live_overlay_daemon_service_contract.py`:
  - Added a regression pin for the Python entrypoint's `PORT` handling and for
    keeping `$PORT` out of the Railway start command.

### Fixed (2026-06-30) — TradingView legend text settings fallback tests

- `automation/tradingview/lib/tv_shared.ts`:
  - Requires visible legend text matches to have a legend action/settings
    wrapper before attempting double-click or settings-button interactions.
- `automation/tradingview/tests/tv_shared.test.ts`:
  - Added Playwright coverage for opening settings from a visible legend text
    row and for ignoring matching text outside legend actions.

### Fixed (2026-06-30) — Plan 2.8 evaluation snapshot publish

- `.github/workflows/plan-2-8-evaluation.yml`:
  - Uses an explicit SHA-populated `--force-with-lease` when publishing
    `bot/live-experiment-snapshot`, avoiding implicit lease resolution.
  - Sets `persist-credentials: false` on checkout and limits workflow
    permissions to `contents: read` plus `issues: write`; the bot-branch push
    continues to use `GH_PAT`.
  - Downgrades `bot/live-experiment-snapshot` push failures to a warning so
    successful daily evaluations do not fail solely because the optional
    rolling snapshot publish credential is expired or under-scoped.
- `tests/test_plan_2_8_evaluation_workflow.py`:
  - Added regression pins for explicit force-with-lease, checkout credential
    persistence, and issue-fallback permissions.
  - Added a regression pin for the best-effort publish failure path.

### Fixed (2026-06-29) — Railway healthcheck port bindings

- `services/live_overlay_daemon/infra/alloy/Dockerfile`:
  - Passes `--server.http.listen-addr=0.0.0.0:${PORT:-12345}` to `alloy run`
    so the metrics collector binds to Railway's injected port instead of
    Alloy's default loopback listener.
  - Exports `ALLOY_SELF_ADDRESS=127.0.0.1:$PORT` by default so Alloy's
    self-scrape target follows the Railway runtime port.
- `services/live_overlay_daemon/infra/alloy/railway.toml`:
  - Declares the metrics-collector Dockerfile service and `/metrics`
    healthcheck path in repo config.
- `services/signals_producer/railway.toml`:
  - Passes `$PORT` explicitly as `--telemetry-port` so `/healthz` is served on
    the Railway healthcheck port rather than relying on runtime defaults.
- `tests/test_live_overlay_infra_alloy_contracts.py`:
  - Added a Dockerfile contract pin for the Railway listen address.
- `tests/test_signals_producer_service_contract.py`:
  - Added a Railway start-command pin for the signals producer telemetry port.
- `tests/test_live_overlay_daemon_service_contract.py`:
  - Added regression coverage for the live overlay daemon's existing
    `0.0.0.0:$PORT` Railway binding and `${PORT:-8000}` Dockerfile fallback.
- `services/live_overlay_daemon/infra/alloy/README.md`:
  - Documents the required Railway healthcheck binding.

### Fixed (2026-06-29) — SMC library refresh soft-failed TV normalization

- `.github/workflows/smc-library-refresh.yml`:
  - Normalizes the TradingView post-release validation report after a
    soft-failed raw TV validation step so strict release gates still receive a
    canonical report.
  - Tracks the normalized `tv_post_release` best-effort outcome in the
    existing failure-summary artifact.
- `tests/test_smc_library_refresh_workflow.py`:
  - Added a regression pin for running post-release normalization independent
    of `steps.tv_post_release_raw.outcome == 'success'`.
- `tests/test_workflow_continue_on_error_inventory.py`:
  - Allowlisted `id:tv_post_release` with the same fail-loud downstream release
    gate contract.
- `scripts/run_smc_release_gates.py`:
  - Classifies `POST_RELEASE_VALIDATION_FAILED` and `NO_TARGETS` as soft
    missing-input TV validation failures so a missing raw TradingView artifact
    does not keep strict release gates blocking after normalization.
- `tests/test_smc_tv_validation_stage_normalization.py`:
  - Added regression coverage for downgrading the synthetic missing-input
    post-release validation report to `blocking: false`.

### Fixed (2026-06-28) — Live overlay monitoring follow-up

- `services/live_overlay_daemon/config.py`:
  - Added `expect_market_traffic()` driven by `LIVE_OVERLAY_EXPECT_MARKET_TRAFFIC`.
- `services/live_overlay_daemon/metrics.py`:
  - Exposes `live_overlay_expected_market_traffic` gauge.
  - UptimeRobot/GitHub bridge `last_success_age_seconds` now uses the preserved
    `last_success_fetched_at_unix` timestamp and does not reset on fetch failure.
- `services/live_overlay_daemon/uptimerobot_bridge.py`:
  - Successful polls record `last_success_fetched_at_unix`.
  - Failed polls preserve the previous `last_success_fetched_at_unix`.
- `services/live_overlay_daemon/github_workflow_bridge.py`:
  - Same last-success preservation semantics as UptimeRobot bridge.
- `services/live_overlay_daemon/infra/grafana/alert-rules.yaml`:
  - Added `lo-request-rate-absent-open` warning alert that fires when
    `live_overlay_expected_market_traffic == 1`, US market is open, uptime
    exceeds 10 minutes, and `/smc_live` request rate is near zero — without
    requiring prior traffic.
- `services/live_overlay_daemon/infra/grafana/dashboard.json`:
  - Regenerated by `update_overlay_dashboard.py`.
- `scripts/update_overlay_dashboard.py`:
  - **Core Metrics Present** now also checks
    `live_overlay_smc_live_requests_total`, `live_overlay_smc_live_success_total`,
    `live_overlay_smc_live_errors_total`, and `live_overlay_smc_live_latency_ms_count`.
  - Value mappings extended up to 8 missing series.
- `services/live_overlay_daemon/OPS.md`:
  - Railway Metrics Bridge documentation now references the generic bridge
    contract (`live_overlay_bridge_enabled` + `live_overlay_bridge_scrape_success`).
  - Core Metrics Present docs list all eight checked series.
- `services/live_overlay_daemon/README.md`:
  - Metrics table documents generic bridge contract and
    `live_overlay_expected_market_traffic`.
- `tests/test_live_overlay_expected_market_traffic.py`:
  - New test file covering `config.expect_market_traffic()` env precedence.
- `tests/test_smc_live_overlay_metrics.py`:
  - Added tests for expected-traffic gauge and bridge last-success age
    preservation on failure.
- `tests/test_uptimerobot_bridge.py` / `tests/test_github_workflow_bridge.py`:
  - Added tests for `last_success_fetched_at_unix` recording and preservation.
- `tests/test_update_overlay_dashboard.py`:
  - Extended Core Metrics Present test to assert HTTP/SLO series.
- `tests/test_live_overlay_dashboard_contract.py`:
  - Added test for `lo-request-rate-absent-open` alert rule.

### Fixed (2026-06-28) — Live overlay bridge contract follow-up

- `services/live_overlay_daemon/railway_metrics.py`:
  - Added stable bridge error codes (`missing_configuration`, `network_error`,
    `timeout`, `fetch_error`) and `_failed_snapshot()` helper that preserves
    cached service data while marking the scrape as failed.
  - Snapshot now records `scrape_duration_seconds` on success and explicit
    `None` for disabled/misconfigured/failed states.
- `services/live_overlay_daemon/metrics.py`:
  - Forwards Railway `scrape_duration_seconds` into the generic
    `live_overlay_bridge_*{bridge="railway_metrics"}` contract.
- `services/live_overlay_daemon/infra/grafana/alert-rules.yaml`:
  - Bridge scrape-failure and stale alerts now use `enabled + success` only
    (dropping the redundant `configured` gate) and evaluate for `10m`.
- `services/live_overlay_daemon/infra/grafana/dashboard.json`:
  - **Railway Metrics Error** panel now queries the generic
    `live_overlay_bridge_error_info` series instead of the legacy
    `live_overlay_railway_metrics_error_info` gauge.
- `services/live_overlay_daemon/OPS.md`:
  - **Market Traffic Health** section now describes US-regular-session-only
    gating, matching the dashboard query and removing the stale major-session
    language.
- `tests/test_railway_metrics.py`:
  - Added parametrized truth-table test for the generic Railway bridge metrics.
  - Updated cache-on-error and GraphQL-error tests to assert stable error codes.
- `tests/test_live_overlay_dashboard_contract.py`:
  - Added contract tests for the Railway bridge state query and the generic
    bridge failure alert.
- `tests/test_global_statement_budget.py`:
  - Re-pinned `railway_metrics.py` global-statement ledger lines after the
    `_failed_snapshot()` insertion.
### Fixed (2026-06-28) — Live overlay dashboard UX follow-up tests and drilldown links

- `scripts/update_overlay_dashboard.py`:
  - **Signal Pipeline Ready** now links directly to the concrete
    signal-producer detail panels **Open-Prep Snapshot** (panel 2165782568),
    **Watchlist Symbols** (panel 2165782569), and **Producer Poll Age**
    (panel 2165782570), plus **Scrape Targets Up** (panel 2133310723) and
    the signals-producer Railway logs. Legacy links to the collapsed row
    header (panel 2133310722) and live-overlay readiness timeline
    (panel 1580287418) are removed so the 3 a.m. on-call click lands on the
    actual signal-pipeline cause.
  - Dashboard JSON is now written with `ensure_ascii=False`, keeping
    Unicode characters literal and reducing future diff noise.
- `services/live_overlay_daemon/infra/grafana/dashboard.json`:
  - Regenerated by the updater; Signal Pipeline Ready links updated and
    version bumped.
- `services/live_overlay_daemon/README.md`:
  - Removed stale "not yet addressed" text about External Integration
    panel misplacement; documented the current co-located layout and the
    collapsed-by-default detail rows.
- `tests/test_update_overlay_dashboard.py`:
  - Added `test_uptimerobot_panel_does_not_clobber_prior_changes` to
    preserve the regression-test intent from #2997.
- `tests/test_live_overlay_dashboard_contract.py`:
  - Signal Pipeline Ready contract test now asserts direct (non-row)
    panel targets.
  - Market Traffic Health contract test now asserts US market context
    (open/closed/session) in the description.

### Fixed (2026-06-27) — Grafana dashboard SRE review follow-up (7 items)

- `services/live_overlay_daemon/infra/grafana/dashboard.json`:
  - **Success Rate (%)** description now correctly describes `/smc_live`
    HTTP request success instead of SMC compute cycles.
  - Removed duplicate **Restart Causes (24h, counted)** table panel; the
    remaining **Restart Causes (24h)** timeseries now extracts a `cause`
    label via `label_replace(...)` and groups by it.
  - Expanded the previously collapsed rows (**External Integrations**,
    **SLO & Reliability**, **Provider Health**, **Railway Resources**) so
    their child panels are visible on load.
  - Added **Process Resident Memory** stat panel (`x=4`, `y=12`) to close
    the grid gap and to match the existing process-memory alerts.
  - **Ingest Queue Backpressure** now renders queue depth on the left axis
    and the drop rate on the right axis via field overrides, separating
    count and rate units visually.
  - Cosmetic `y=12` grid gap closed by placing the new memory panel at
    `x=4`.
- `services/live_overlay_daemon/infra/grafana/alert-rules.yaml`:
  - Verified that **SLO error-rate burn-rate alerts**
    (`lo-error-budget-burn-critical` and `lo-error-budget-burn-warning`)
    correctly evaluate both the 5-minute and 1-hour windows with an `AND`
    math expression; titles and implementation now match.
- `tests/test_live_overlay_dashboard_contract.py`:
  - Added regression tests for all seven review findings: success-rate
    description, unique restart-cause panel, expanded rows, process
    memory panel, backpressure axis separation, closed grid gap, and
    two-window burn-rate alerts.

### Fixed (2026-06-26) — Live overlay dashboard market-open wiring and no-traffic UX

- `services/live_overlay_daemon/infra/grafana/dashboard.json`
  - **Market-open Request Health** panel now uses `live_overlay_market_open`
    (any major session: US or Europe) instead of `live_overlay_market_us_open`.
    The previous wiring showed `MARKET_CLOSED` during the European pre-US
    session even though the daemon was active.
  - The panel PromQL was simplified to a single, consistently filtered
    expression so multi-select `$job` values do not create mismatched series.
  - **Market Status** panel description corrected from "US regular trading
    session" to "Major session state (US regular or Europe regular)" to match
    the metric it already displays.
- `services/live_overlay_daemon/OPS.md` documents the corrected
  Market-open Request Health expression and the rationale for using the
  major-session gauge.
- `tests/test_live_overlay_dashboard_contract.py` pins the panel wiring so
  the dashboard cannot regress to `live_overlay_market_us_open`.
### Fixed (2026-06-26) — Grafana dashboard review fixes and missing alerts

- `services/live_overlay_daemon/infra/grafana/dashboard.json`:
  - **Railway Metrics Bridge** no longer filters on `== 1` inside `max()`,
    so a disabled bridge correctly renders `0` / "DISABLED" instead of
    dropping the series.
  - **Market-open Request Health** (stat panel) now uses a fixed `[5m]`
    range vector instead of `$__rate_interval`, avoiding unstable values
    when the dashboard time range is narrow.
  - **Bridge Scrapes**, **UptimeRobot Bridge**, and **GitHub Workflow
    Bridge** aggregate `min`/`max` by `job` so a disabled or failing job
    cannot be hidden behind a healthy one when `$job` is set to `All`.
- `services/live_overlay_daemon/infra/grafana/alert-rules.yaml`:
  - `lo-workers-degraded` and `lo-overlay-stale` now include the
    `job="live_overlay"` selector, matching every other alert in the file.
  - Added proactive alerts for dashboard thresholds that previously had
    no alert coverage:
    - `lo-tradingview-credential-age-high` (high severity when credential age
      exceeds 72 h).
    - `lo-ingest-queue-lag-high` (warning when max ingest queue lag
      exceeds 5000 ms for 10 min).
    - `lo-daemon-restarts-high` (high severity when more than 3 daemon
      restarts occur within 24 h).
- Added regression tests in `tests/test_live_overlay_dashboard_contract.py`
  and `tests/test_grafana_alert_rules_upsert.py` to prevent these
  dashboard/alert regressions from recurring.

### Fixed (2026-06-26) — Live overlay success-rate dashboard shows "NO TRAFFIC" instead of misleading 0.00 %

- `services/live_overlay_daemon/metrics.py` seeds traffic counters
  (`live_overlay_smc_live_requests_total`,
  `live_overlay_smc_live_success_total`, and related counters) to `0.0` on
  every metrics render. Previously these series were only created after the
  first `/smc_live` request, so a fresh daemon with no traffic exposed no data
  for the Success Rate panel and the panel rendered `0.00 %`.
- `services/live_overlay_daemon/Dockerfile` installs `tzdata` so
  `ZoneInfo("America/New_York")` resolves correctly in the Railway container;
  without it, market-open detection silently fell back to UTC hours.
- `services/live_overlay_daemon/infra/grafana/dashboard.json` hardens the
  Success Rate panel: the PromQL query now drops the result when request rate
  is zero (`unless on()`), and `noValue` is set to `"NO TRAFFIC"`, making an
  idle-but-healthy daemon visually distinct from a real outage.
- `services/live_overlay_daemon/OPS.md` documents the root cause, the code
  fix, and the dashboard UX hardening.


### Changed (2026-06-24) — Benzinga RSS wiring + process metrics expansion

- `newsstack_fmp` now includes a free-tier Benzinga RSS adapter path in the
  production poller: lazy adapter init, RSS fetch block, persisted cursor
  (`benzinga_rss.last_seen_epoch`) and metadata export for diagnostics.
- `newsstack_fmp.config.Config` gained `enable_benzinga_rss` and includes
  `benzinga_rss` in `active_sources` when enabled.
- Feature-flag defaults were aligned to ON for both
  `ENABLE_BENZINGA_RSS` and `ENABLE_TRADINGVIEW_NEWS`.
- Process-level telemetry was expanded:
  - `open_prep/realtime_signals.py` exports `signals_producer_process_*`
    metrics via `/metrics`.
  - `services/live_overlay_daemon/metrics.py` exports
    `live_overlay_process_*` metrics (CPU/memory/fds/uptime/GC) in the daemon
    metrics payload.
  - Alloy scrape setup gained additional targets for `signals_producer` and
    `alloy_self`, enabling Grafana visibility for all three Railway containers
    (signals producer, live overlay, metric collector).
- Grafana dashboard and alert rules were extended with dedicated process
  resource panels/alerts for all three services.
- `/proc/self/status` reads in `_collect_process_metrics()` now use `encoding="utf-8"` explicitly
  instead of relying on the locale default (hardened text-IO, consistent with the
  `test_assert_and_open_encoding_pin` guard).
- **Security (F6):** `/metrics` in `open_prep/realtime_signals.py` now requires the same
  `Authorization: Bearer <token>` guard as `/signals` when `SIGNALS_INTERNAL_TOKEN` is set
  in the environment (audit finding F6; resolves the unauthenticated-endpoint gap noted in
  the previous entry).
- **Alloy auth:** `prometheus.scrape "signals_producer"` now sends `Authorization: Bearer`
  using `SIGNALS_INTERNAL_TOKEN`, ensuring scraping works when the token is set.
- Multiple pin/ledger guards were re-baselined for intentional line drift in
  touched files (`global`, `time.sleep`, `urlopen`, `mkstemp`,
  `os.unlink/remove`, `json.load`, `# type: ignore`, and related boundary
  bundle ledgers).
### Fixed (2026-06-24) — Databento merge OOM / swap-thrash prevention (WF-026)

- `scripts/databento_production_merge_shards.py` — `merge_shard_payloads()` now
  uses `pyarrow.dataset` streaming instead of `[pd.read_parquet(p) for p in
  paths] + pd.concat(...)`.  The old approach held N pandas DataFrames
  simultaneously in RAM plus the concatenated copy plus the deduped/sorted copy
  (peak ≈ 3× total frame size); on the 7 GB GitHub runner with 6 production
  shards this caused OOM / swap-thrash on 2026-06-22 (swap_used peaked at
  5 750 MB / 9 215 MB, triggering 8 consecutive job failures).
  The new path reads all shard files in a single Arrow streaming pass
  (column-oriented layout, ~2× more compact than N pandas DataFrames) and
  releases the Arrow buffer with an explicit `del` before `_dedupe_frame`
  allocates its sorted copy.  Peak is now ≈ 2× total frame size, saving
  ~2.5–3 GB on a 6-shard run.
- Two new tests cover the streaming path:
  `test_merge_shard_payloads_streaming_six_shards` (production-realistic
  6-shard scenario) and `test_merge_shard_payloads_single_shard_passthrough`.
- `pyarrow` is already a transitive dependency via pandas' parquet engine —
  no additional install step is required.

### Changed (2026-06-24) — Databento export freshness budget tightened

- `meta-watchdog.yml`: `smc-databento-production-export-sharded.yml` freshness
  budget reduced from 30 h to 14 h (weekday-adjusted).  The workflow already
  runs 9× per day on weekdays (08–22 UTC); the previous 30 h window allowed
  a full day of silent failures before alerting.  14 h absorbs one failed run
  without a false alarm but catches a real outage within ≈ 2 h.

### Added (2026-06-24) — Zero-touch TradingView storage-state refresh (TOTP)

- `scripts/create_tradingview_storage_state.ts` now accepts `TV_TOTP_SECRET`
  (env var or `--totp-secret` flag) to generate the 6-digit TOTP code via
  `otplib` and fill the 2FA input automatically.  Also accepts `TV_HEADLESS=1`
  / `--headless` for CI (no GUI required).
- New workflow `tradingview-storage-refresh.yml` runs every 48 h (03:00 UTC on
  even days) and:
  - Starts an `xvfb` virtual display for headed Playwright on CI.
  - Logs in headlessly via `TV_USERNAME` + `TV_PASSWORD` + TOTP code generated
    from `TV_TOTP_SECRET`.
  - Validates the captured storage state via `credential_health_check.py`.
  - Writes the refreshed secret back via `gh secret set TV_STORAGE_STATE`
    (requires `GH_PAT` with `repo` + `secrets:write` scope).
  - On failure: opens a `cron-failure` GitHub issue with recovery instructions.
- `package.json`: added `otplib ^12.0.1` dependency.
- Closes #2904.

### Changed (2026-06-23) — Live-overlay snapshot delivery hardening

- `scripts/publish_signals_snapshot.py` now validates `--branch` defensively
  (rejecting values that could be interpreted as git flags or invalid refs)
  before any git command is executed.
- First publish in `scripts/publish_signals_snapshot.py` now uses
  `--force-with-lease=refs/heads/<branch>:0000000000000000000000000000000000000000`
  (40-zero SHA) instead of bare `--force`, preventing silent clobber when
  another publisher creates the branch in the fetch→push race window.
- `_git_diff_has_changes()` now distinguishes real staged diffs (`returncode=1`)
  from git execution errors (`returncode>1`), surfacing the latter as command
  failures instead of false-positive "changes present".
- Snapshot write-through cleanup in `compute.py` was tightened: temporary files
  are only removed when a rename did not complete, clarifying the atomic
  `os.replace` success/failure paths.
- Runtime snapshot fetchers now apply the GitHub Contents raw `Accept` header
  only to actual GitHub Contents API endpoints, avoiding GitHub-specific
  `Accept` values on authenticated non-GitHub URLs.

### Changed (2026-06-21) — Live-overlay observability hardening

- Alert rule `lo-news-snapshot-stale-or-missing` split into two rules:
  - `lo-news-snapshot-unavailable` (high severity, 5m) fires when the snapshot
    is not loaded (`snapshot_loaded == 0`).
  - `lo-news-snapshot-stale` (warning, 15m) fires only when a loaded snapshot
    is older than 1 hour.
- `lo-request-rate-drop-open` now also requires at least 5 requests in the
  10m evaluation window to avoid flapping on very low pre-open traffic.
- `lo-no-symbols` now triggers immediately after a recent restart (uptime reset)
  in addition to the 10-minute steady-state condition.
- Grafana dashboard `Service Status` panel now maps value `0` to `STARTING`
  (yellow).
- Bridge snapshot-age panels (`UptimeRobot Snapshot Age`,
  `GitHub Workflow Snapshot Age`) now display `DISABLED` (gray) when the bridge
  is disabled instead of showing `No data`.
- Dashboard gained a `job` template variable; all hard-coded
  `job="live_overlay"` selectors were replaced with `job=~"$job"` for
  multi-environment deployments.
- GitHub workflow bridge gained optional `GITHUB_WORKFLOW_MONITOR_BRANCH`
  filter (default `main`; empty = all branches) to avoid cross-branch noise.
- README documents the new `GITHUB_WORKFLOW_MONITOR_BRANCH` variable and adds
  an SLO / reliability-targets section.
- Added unit tests for `uptimerobot_bridge` and `github_workflow_bridge` and
  extended `test_smc_live_overlay_metrics.py` with dashboard/alert contract
  assertions.

### Changed (2026-06-21) — Live-overlay cold-start seed snapshot + missing-series alert

- Added `news_snapshot_seed.json` for cold-start provider visibility in CI,
  local runs, and container images.
- `Dockerfile` now explicitly copies the cold-start news snapshot into the image.
- Added `lo-news-snapshot-series-missing` alert rule to detect absent news
  snapshot metric series explicitly via `absent(...)` checks.
- README updated to document `no_data` filtering and the missing-series alert.

### Changed (2026-06-21) — Live-overlay monitoring dashboard hardening + snapshot-age fix (PR #2879)

- **Snapshot-age false-alarm fix** (`metrics.py`): `live_overlay_provider_news_snapshot_age_seconds`
  now reads `fetched_at_unix` from the snapshot JSON instead of using `stat.st_mtime`.
  Static seed files (no live producer yet) report age 0 and never trigger the
  stale-snapshot alert; only snapshots written by a live producer carry a timestamp
  and age correctly.
- **Grafana dashboard v39 hardening** (`infra/grafana/dashboard.json`):
  - `Market Session Banner` expression guarded with `or vector(0)` on the
    `max(market_open)` operand so the fully-down state (value 0) shows
    `SERVICE DOWN` (red) instead of "No data"; renamed dead-state label
    from `OPEN SIGNAL MISSING` to `SERVICE DOWN`.
  - Bridge state formula corrected: `enabled + scrape_success`
    (was `scrape_success*2 + enabled`; old formula yielded 3 when both gauges
    were 1).
  - No-Data Guard dual-series fix: replaced `1 - (absent(...) or vector(0))`
    with `clamp_max(count(...), 1) or vector(0)` to avoid phantom second
    series over long Prometheus windows.
  - Market-closed UX gating: 8 request/latency/SLO panels now gate their
    queries with `and on(job) (market_open == 1)` and display
    `noValue: "MARKET CLOSED"` instead of showing zeros.
  - Market-open Request Health panel hardened: `(max(market_open) * (1 + ...)) or vector(0)`.
- **Dockerfile**: cold-start seed snapshot `smc_live_news_snapshot.json` now
  explicitly `COPY`-ed into the container image, ensuring the service starts
  with provider data even before the first live fetch.
- **`news_snapshot_seed.json`** added to version control (was untracked):
  provides provider cold-start visibility in CI and local runs.

### Changed (2026-06-21) — Live-overlay provider-health monitoring + drill-down (PR #2875)

- Added provider-health telemetry for the live-overlay news snapshot:
  `live_overlay_provider_news_snapshot_loaded`,
  `live_overlay_provider_news_snapshot_age_seconds`, aggregate provider counts,
  and binary health state gauges (`ok` / `degraded` / `unknown`).
- Added provider-specific drill-down gauges emitted per known provider key in
  the snapshot (`live_overlay_provider_news_<provider>_ok`,
  `..._degraded`, `..._state_code`), enabling operational visibility without
  changing overlay response contracts.
- Grafana dashboard expanded with provider-health panels (aggregate +
  per-provider drill-down timelines).
- Dashboard UX refresh (v12): section rows (`External Integrations`,
  `SLO & Reliability`, `Provider Health`), built-in alert list panel
  (`Active Alerts (live_overlay)`), and provider drill-down query
  refinement to exclude aggregate health series from per-provider timelines.
- Provider alerts tuned to reduce noise:
  - degraded alert now requires **multiple degraded providers** and longer
    persistence (`for: 15m`)
  - stale/missing snapshot alert threshold increased to 1h and
    persistence increased to 15m.
- README metrics catalog updated with aggregate and per-provider health metric
  families.

### Changed (2026-06-21) — Live-overlay hardening + observability follow-ups (PR #2866, #2867, #2869, #2870, #2872, #2873, #2874)

- **Feed lifecycle thread-safety**: feed start/stop now serialized with
  `_lifecycle_lock` to avoid concurrent lifecycle races under repeated
  start/stop calls.
- **Timeframe-aware overlay payloads**: non-`5m` requests now aggregate
  cached 1-minute bars on demand before indicator computation
  (`5m/10m/15m/30m/1H/4H`), with stale evaluation based on latest bar recency.
- **`/smc_live` error hardening**: unexpected internal exceptions are now
  observed (`live_overlay.smc_live_errors.total`) and returned as deterministic
  HTTP 500 (`internal error`) while preserving native `HTTPException` behavior.
- **Metrics endpoint security posture**: preferred scrape path is now
  `GET /metrics` with Basic auth (`OVERLAY_SECRET_TOKEN` as password), while
  legacy `/{token}/metrics` remains backward-compatible.
- **Cache safety**: overlay payloads are deep-copied on read to prevent
  accidental caller mutation of shared in-process cache state.
- **Daemon observability expansion**:
  - market/session-aware health gauges
  - `live_overlay_max_stale_seconds` gauge for runtime-configured stale budget
  - latency histogram counters and bucket telemetry for `smc_live`
  - richer Grafana SLO panels/alerts consuming these series.
- **Config hardening**: `LOG_LEVEL` is validated against uvicorn-compatible
  values with warning + fallback to `info` on invalid input.
- **Dependencies**: `databento` pinned to `0.79.0` and guarded by live-client
  contract tests.

### Changed (2026-06-20) — Live-overlay telemetry rollout + Grafana/Alloy stabilization

- Expanded live-overlay telemetry and dashboard coverage (market-aware health,
  request quality, stale budget, latency, worker state).
- Added and iterated Grafana alert rules for market-aware monitoring and
  corrected datasource wiring.
- Alloy scrape configuration hardened (including explicit job alignment and
  env-driven secret handling) to keep dashboard selectors and scrape labels
  consistent.
- Documentation and runbook updates landed for compute/timeframe constraints and
  live-overlay telemetry operations.

### Security (2026-06-20) — Torch GHSA remediation refresh (GHSA-rrmf-rvhw-rf47)

- `requirements-rl.txt`: `torch==2.12.0` → `torch==2.12.1`.
- `requirements-rl-gpu.txt`: CUDA override switched from
  `https://download.pytorch.org/whl/cu128` + `torch==2.11.0+cu128` to
  `https://download.pytorch.org/whl/cu129` + `torch==2.12.1+cu129`.
- `requirements-rl.lock` regenerated from the updated RL requirements.
- Supersedes the older note from 2026-06-12 that no patched torch version was
  available for this GHSA; patched `2.12.1` is now available on PyPI and on
  the official CUDA channels used above.

### Fixed (2026-06-19) — Open-prep pdh/pdl strictly previous-day + mixed date sorting (PR #2855)

**Strict previous-day pdh/pdl fields (B9)**
- `open_prep/run_open_prep.py` (`_add_pdh_pdl_context`): Strictly use previous day values, excluding today's session `dayHigh` or `dayLow` fallbacks, to prevent off-by-one session index shifts in distance metrics. Added separate `current_day_high` and `current_day_low` fields for current intraday session.

**Chronological sorting of heterogeneous date formats (B10)**
- `open_prep/run_open_prep.py`: Replaced string-based date sorting with `_parse_calendar_date` parsed date objects in `_momentum_z_score_from_eod`, `_calculate_atr14_from_eod`, and `_fetch_symbol_atr`. Prevents sorting errors caused by mismatched formats (e.g., YYYY-M-D vs YYYY-MM-DD).

### Fixed (2026-06-18) — TV automation async-race fix + token/corpus hardening (PR #2843)

**TV-automation — async "My scripts" rows (run #456 RCA)**
- `automation/tradingview/lib/tv_shared.ts` (`collectVisibleIndicatorMyScriptNames`):
  replaced the fixed `waitForTimeout(500)` with `waitFor({state:'visible', timeout:3_000})`
  on the first `[data-name="indicators-dialog"] [data-id^="USER;"]` element.
  Root cause: TradingView began lazy-loading "My scripts" asynchronously; the prior
  500 ms flat wait was insufficient after a tab switch, causing `collectVisible` to
  return `[]` for all three targets (`auth_ok=True, ui_green=True` but
  `"No private My scripts rows were visible" → overall_preflight_ok=False`).
- Added `tracePageEvent('add-to-chart-indicators-rows-ready:<count>')` so future
  failure artifacts include how many USER rows were visible at collection time.
- Locator dedup (Copilot finding): extracted shared `allScriptRowsLocator` constant
  (`page.locator('[data-name="indicators-dialog"] [data-id^="USER;"]')`); was
  previously duplicated between `firstScriptRowLocator` and the `count()` call.

**smc-library-refresh.yml — token-masking + pipefail hardening**
- `Configure git credentials for metrics push` step: moved `${{ github.token }}`
  out of the inline shell command into a dedicated `env: GIT_PUSH_TOKEN:` block
  and references `${GIT_PUSH_TOKEN}` instead — matches the `GITHUB_TOKEN` env-var
  indirection pattern used elsewhere and ensures reliable secret masking.
- Added `set -euo pipefail` so a failed `git remote set-url` exits immediately
  instead of silently continuing with a misconfigured remote.
- `GIT_PUSH_TOKEN` renamed to `GITHUB_TOKEN` in one step `env:` block (Copilot:
  non-standard name caused confusion); `${{ github.repository }}` swapped to
  `${GITHUB_REPOSITORY}` (built-in GHA env var, not a template expression).

**Corpus + ledger fixes (co-landed on this branch)**
- `scripts/collect_drift_calibration_corpus.py`: `_append_rows` was returning
  `None` instead of the written-row count (`return written` was missing;
  `written = 0` was also inside the `with`-block). Fixed: initialise before
  the `with`-block, add explicit `return written`.
- `scripts/collect_drift_calibration_corpus.py`: replaced bare `except
  ImportError: pass` with `fcntl = None; _FLOCK_SUPPORTED = False` null-fallback,
  eliminating `# noqa: F821` workarounds and satisfying the POSIX import-guard
  pattern.
- `pin_registry.toml`: bumped `set +e` count 1→2 for the new
  `Annotate probe results` step in `meta-watchdog.yml`.

### Changed (2026-06-17) — Monitoring hardening + Q&A audit follow-up (PR #2841, #2842)

**W11-1 — Skip `hit_rate=None` families in advisory FDR layer (PR #2841)**
- `_aggregate_family_events` in `run_ab_comparison.py` now skips metric pairs
  where `hit_rate is None` instead of laundering them to `k=0` via `or 0.0`.
  Ghost k=0 entries distorted the two-proportion z-test (one-sided for
  treatment > control): a None control arm inflated the apparent treatment
  advantage → false significant-lift rejection on null evidence.
- Comment corrected: "treatment significantly worse" → "ghost significant lift
  (treatment appearing better than it is)" to match the one-sided test direction.
- Regression test strengthened: changed from both-arms-None (degenerate p, old
  code also wouldn't reject) to one-arm-None (control None, treatment 0.50) so
  old code produces k_ctrl=0 vs k_treat=25 → p≈0 ghost lift. Assertion changed
  from conditional `if ghost: not rejected` to unconditional `GHOST not in
  families_by_name`.
- `_family_fdr_layer` now returns `skipped_family_details` list in the result
  dict so downstream operators can see which families were skipped and why
  instead of a silent count decrement.
- `test_run_ab_comparison_fdr.py` and schema-pin tests updated accordingly.

**Monitoring staleness guards + observability gaps (PR #2842)**
- `adr0023-magnitude-shadow-daily.yml`: raised `GAP_BUDGET_DAYS` 7→10 days
  to absorb workstation restarts without false staleness alerts.
- `c13-daily-cron.yml`: new audit-branch staleness guard step checks whether
  `origin/data/phase-a-audit` has received a commit in the last N days;
  emits `::warning::` if stale (soft-alert, does not fail the job). Fixed
  YAML parse error (Python heredoc at col-1 replaced with `date -d` shell
  arithmetic). Replaced raw-epoch-seconds arithmetic with UTC
  calendar-day normalization (`LAST_DATE`/`TODAY` via `date -u +%Y-%m-%d`)
  so `GAP_DAYS` is an exact calendar-day count regardless of commit
  time-of-day, eliminating the old `LAST_TS=0`-on-parse-failure false
  positive (parse failure now emits `::notice` + skips the check).
- `tests/test_workflow_adr0023_magnitude_shadow_daily_contract.py`: updated
  `GAP_BUDGET_DAYS` pin from 7 to 10.
- `f2-promotion-gate-daily`: was **disabled** in GHA UI (3 missed weekday runs
  discovered during monitoring). Re-enabled and dispatched manually.
- TV StorageState (`automation/tradingview/auth/storage-state.json`): secret
  `TV_STORAGE_STATE` refreshed; `create_tradingview_storage_state.ts` patched
  to always write `meta.authValidatedAt` in standard session mode (previously
  only written in persistent-profile mode), fixing `credential-health-check`
  `storage_state missing meta block` error.
- `scripts/credential_health_check.py`: HTTP 429 probes now extract and surface
  the `Retry-After` response header in `ProbeResult.message` and `.details`
  (`retry_after` key). Works for `urllib.error.HTTPError` (`.headers` direct)
  and httpx/requests (`.response.headers` fallback).
- `tests/test_credential_health_check.py`: two new parametrized 429 cases —
  no-header path (`retry_after='unknown'`) and with-header path
  (`Retry-After: 60` → `retry_after='60'`, message contains
  `"Retry-After=60s"`).
- `tests/test_workflow_yaml_flag_centralization.py` (new): companion guard to
  `test_feature_flag_centralization.py` covering the YAML `env:` blind spot —
  scans all `*.yml` workflow files and fails if any `ENABLE_*` key has a
  hardcoded literal value rather than a `${{ vars.* }}` expression, preventing
  inline feature-flag drift in CI configuration.
- `tests/test_workflow_library_refresh_artifact_handoff_contract.py` (new, Q6):
  7 YAML contract tests for the `reject_stale_export_fallback` step in
  `smc-library-refresh.yml` — covers step existence, `exit 1` hard-fail, no
  `continue-on-error`, correct 3-clause AND condition
  (`event_name != dispatch` AND today-artifact absent AND fallback present),
  and ordering relative to both restore steps.
- `meta-watchdog.yml`: new Library-Refresh DAG health step that polls
  `smc-databento-production-export-sharded` → `smc-library-refresh` →
  `f2-promotion-gate-daily` → `credential-health-check` as a causal chain and
  surfaces gaps via `::error::` annotation.

### Changed (2026-06-17) — Bug-hunt audit R4/R4b hardening (PR #2837, #2838, #2839)

Round of defensive fixes surfaced by the periodic bug-hunt audit. Each finding
landed on its own branch with auto-merge armed.

**F1 — Structured CLI error handling (PR #2838)**
- Wrapped the `if __name__ == "__main__"` blocks of 15 maintenance/CLI scripts
  in a uniform try/except: `KeyboardInterrupt` → exit 130, `SystemExit`
  re-raised, unexpected `Exception` → `logger.critical(..., exc_info=True)` +
  exit 1. Replaces silent tracebacks on operator Ctrl-C and gives non-zero
  exit codes a single audit trail.

**F2 — Durable JSONL appends (PR #2837)**
- Added `flush()` + `os.fsync()` after best-effort JSONL record writes so a
  runner killed mid-write cannot leave a half-line that breaks the tolerant
  loader on the next run.

**W1/W2/W4/W8 — Workflow gate hardening (PR #2839)**
- Tightened conditional gates and `if:` guards on several CI workflow steps so
  best-effort/observability steps can no longer flip a job conclusion.

**W3 — Cumulative best-effort failure summary + cross-run trend (this PR)**
- New `scripts/best_effort_failure_trend.py`: records the per-run outcome of
  each best-effort step (`record` subcommand → append-only JSONL + JSON
  snapshot, fsync-durable) and renders a Markdown `digest` (per-step failure
  counts and failure-rate over a configurable window, default 30 runs).
- Three new `continue-on-error: true` steps appended to the `refresh` job of
  `.github/workflows/smc-library-refresh.yml`: download prior history artifact
  (`dawidd6/action-download-artifact`), record + emit digest to
  `$GITHUB_STEP_SUMMARY`, re-upload history artifact (90-day retention). Trend
  state is persisted via the artifact-passing pattern (no commits to `main`),
  matching `plan-2-8-weekly-digest.yml`.
- Inventory allowlist (`tests/test_workflow_continue_on_error_inventory.py`)
  extended with the three new step anchors; count-pin derives automatically.

### Added (2026-06-16) — SMC Live Overlay Daemon (PR #2794, PR #2795)

New FastAPI micro-service (`services/live_overlay_daemon/`) that subscribes to
Databento `EQUS.MINI` live feed (schema `ohlcv-1m`, `ALL_SYMBOLS`) and exposes
a per-symbol 16-field overlay JSON endpoint for TradingView Pine scripts.

**Service (`services/live_overlay_daemon/`)**
- `main.py` — FastAPI app with `/health` (GET + HEAD) and `/{token}/smc_live`
  endpoints. Token validated via `hmac.compare_digest`; wrong token returns 404.
- `feed.py` — `db.Live()` consumer background thread with reconnect loop and
  dedicated asyncio event loop (`asyncio.new_event_loop()`).
- `cache.py` — Thread-safe bar and overlay cache (`threading.Lock`).
- `compute.py` — Computes 16 overlay fields: `news_strength`, `news_bias`,
  `flow_rel_vol`, `flow_delta_proxy_pct`, `squeeze_on`, `ats_state`,
  `ats_zscore`, `vix_level`, `tone`, `global_heat`, `event_window_state`,
  `event_risk_level`, `next_event_name`, `next_event_time`,
  `market_event_blocked`, `symbol_event_blocked`.
- `config.py` — Env-var loader with `_require()` guards for `DATABENTO_API_KEY`
  and `OVERLAY_SECRET_TOKEN`.
- `Dockerfile` / `railway.toml` — Railway deployment (Starter, 512 MB).
  Root Directory is empty (repo root = build context).

**Key engineering decisions**
- `uvicorn` without `[standard]` extras to avoid `uvloop`/Databento TCP conflict
  (`TypeError: object Future can't be used in 'await' expression` on reconnect).
- Start command: `--loop asyncio --http h11` for full compatibility.
- `/health` accepts both `GET` and `HEAD` (PR #2795) — UptimeRobot sends HEAD;
  without this every probe returned `405 Method Not Allowed`.

**Pine consumer (`pine/smc_live_overlay_consumer.pine`)**
- Pine Script v6 indicator that calls the Railway daemon via `request.raw()`.
- All 16 fields exposed as named `plot()` series (importable via
  `request.security()`).
- Dashboard table in top-right corner (toggle off in indicator settings).
- Requires TradingView Premium for `request.raw()` (Free tier → all fields stale
  until Premium is activated).

**Deployment**
- Production URL: `https://liveoverlaydaemon-production.up.railway.app`
- Monitoring: UptimeRobot free-tier, `GET/HEAD /health`, 5-min interval.
- See `services/live_overlay_daemon/README.md` for full ops runbook.

### Changed (2026-06-16) — F-V8-D1: Option D — 9-tick incremental producer cadence + consumer stall guard (commit `293e89af`)

Replaces the prior 2×/day Databento producer/consumer schedule (12:00 / 16:00 UTC
producer, 16:00 / 20:00 UTC consumer) with a 9×/day incremental cadence tuned for
freshness and GHA cost efficiency.

**Producer (`smc-databento-production-export-sharded.yml`)**
- Cron expanded from 2 → 9 ticks: `08/10/12/14/16/18/20/21/22 UTC` Mon–Fri.
- All schedule triggers now run incremental mode:
  `INCREMENTAL="${{ (inputs.incremental_from_manifest || github.event_name == 'schedule') && 'true' || '' }}"`.
  Each tick downloads only the delta since the last baked manifest
  (`databento_incremental_window.py` with `safety_overlap_days=1`), bringing
  per-tick wall-clock from ~60 min → ~20 min. Cold starts (no manifest) fall
  back to the full 30-day lookback automatically.

**Consumer (`smc-library-refresh.yml`)**
- Safety-net crons expanded from 2 → 9 ticks, each +60 min after the matching
  producer tick: `09/11/13/15/17/19/21/22/23 UTC`.
- Added `timeout-minutes: 45` hard cap to the "Generate SMC library with v5
  enrichment" step. Root cause of the prior >2 h hangs: FMP client
  (`retry_attempts=2`, `timeout_seconds=12`, `max_delay=60`) allows 84 s
  worst-case per call; ~100 per-ticker calls × 84 s ≈ 8400 s (observed runs:
  8552 s, 9337 s, 5468 s). The 45-min cap hard-kills the step and releases the
  concurrency slot; the `workflow_run` fast-path remains unchanged.
- Job-level `timeout-minutes: 240` cap unchanged (enforced by
  `test_consumer_timeout_is_tight`).

**Cost / freshness impact**
- Estimated GHA billed minutes: ~675 billed-min/day (9 × ~75 min) vs. ~480
  (2 × ~240 min full-scan) — trade-off accepted for 4.5× freshness improvement.
- Overnight gap (post-market → pre-market data age): 15 h → 10 h.
- All 41 test assertions pass: 9 producer ticks == 9 consumer ticks, all
  forward gaps ≥ 60 min, all timeouts ≤ 240 min.

### Fixed (2026-06-14) — live-window Dual-Marker bereinigt (PR #2723)

Fünf Workflows trugen einen zweiten `# live-window:`-Header-Marker mit der
Posture `off-hours-only`, obwohl ihr Primärmarker (Zeile 1) korrekt
`mutating-on-cron` deklariert und alle fünf Write-Permissions besitzen
(`contents`/`issues`/`pull-requests: write`). Da `_read_marker` nur den ersten
Treffer in den ersten 10 Zeilen auswertet, blieb der Widerspruch testgrün — der
Sekundärmarker war jedoch tote, irreführende Config. Betroffen:
`plan-2-8-weekly-digest.yml`, `run-open-prep-daily.yml`, `c13-daily-cron.yml`,
`fvg-quality-quartile-gate.yml`, `fvg-context-pine-refresh.yml`. Die
Sekundärmarker sind jetzt zu reinen `# Schedule:`-Kommentaren degradiert
(Cron-Zeit-Dokumentation bleibt erhalten, ohne kollidierendes Posture-Keyword).
Neuer Regressions-Test `test_at_most_one_live_window_marker` erzwingt künftig
genau einen `# live-window:`-Marker je Workflow.

### Fixed (2026-06-14) — smc-library-refresh konsumiert Producer-Bundle statt Consumer-Scan

`smc-library-refresh.yml` stellt das kanonische
`smc-databento-production-export-sharded.yml`-Artefakt jetzt vor dem
Generate-Step wieder her, flacht es ab und fail-closed verified den
Manifest-Fund, bevor überhaupt Library-Generation startet. Der
Generate-Step nutzt damit den Bundle-Pfad
`scripts/generate_smc_micro_base_from_databento.py --bundle artifacts/smc_microstructure_exports`
und entfernt den redundanten Consumer-seitigen
`--run-scan --incremental-base-only`-Pfad samt Incremental-Seed-Cache.
Root Cause der langen Cancel/Runner-Shutdown-Serie war nicht ein zu kleiner
240-Minuten-Timeout, sondern dass der Consumer bei offline self-hosted
ASUS-Runnern auf GitHub-hosted kalt fiel und dort den vollen
Databento-Producer-Scan erneut ausführte. Automatische Runs verweigern
weiterhin stale Fallback-Bundles; ein Databento `402 account_delinquent_invoice`
bleibt ein separater Provider-/Account-Health-Fall im Producer.

### Changed (2026-06-13) — WS3 #56: `HERO_ACTION` becomes the single action surface + `library_field_version` v8.0a (BREAKING for Pine consumers)

Resolved the parallel-channel split between Producer-A `HERO_ACTION`
and Producer-B `HERO_ACTION_VERB*`. `scripts.smc_hero_action` remains
the canonical action decision table (`act` / `wait` / `watch` /
`avoid` plus reason/degradation/quality), while `scripts.smc_hero_state`
now projects that recommendation onto the existing uppercase Pine
boundary field `HERO_ACTION` (`ACTIVE` / `WATCH` / `AVOID` /
`BLOCKED`). The generated Pine library no longer exports the five
reserved action fields `HERO_ACTION_VERB`, `HERO_ACTION_VERB_DE`,
`HERO_ACTION_REASON`, `HERO_ACTION_DEGRADATION`, or
`HERO_ACTION_QUALITY`; German/display wording is a UI concern rather
than a library-boundary field. This removes five `export const` fields,
so `library_field_version` and
`deprecated_field_policy.preferred_field_version` bump **v7.0a →
v8.0a**. `BLOCKED` is preserved by mapping Producer-B
`degradation == "no_trade"` to the uppercase `HERO_ACTION` contract.

### Fixed (2026-06-13) — Stat-Review W7-4/W7-5: Red-Flag-Fenster + Anchor-Staleness im Weekly-Judgement

**W7-4:** `eval_magnitude_shadow_weekly.detect_all_pass_red_flag`
prüfte die All-PASS-Artefakt-Signatur nur auf dem *einzelnen* neuesten
Datums-String — gestaffelte/partielle Dispatches (BOS+SWEEP heute,
FVG+OB gestern graded) teilen nie ein Datum, sodass genau die
Pipeline-Artefakte, die der Flag fangen soll, ihn umgehen konnten;
der Red Flag suspendiert zudem Demotionen, ein Bypass re-aktiviert
also Vertrauen in artefakt-förmige Daten. Jetzt wird pro Family die
frischeste Zeile in einem trailing Fenster
(`RED_FLAG_WINDOW_DAYS = 3`, geankert am neuesten Ledger-Datum)
herangezogen: ≥ 2 Familien im Fenster und alle PASS ⇒ Flag. Familien
außerhalb des Fensters (Wochen-alter Feed) zählen weder dafür noch
dagegen. **W7-5:** Das Weekly-Judgement ankert am neuesten
*Ledger*-Datum, nie an „heute" — bei eingefrorenem Ledger urteilte
jeder künftige Montags-Run rc 0 „clean" über dasselbe historische
Fenster. Der Report trägt jetzt `anchor_age_days`/`anchor_stale`
(> `ANCHOR_STALE_DAYS = 10` Tage, injizierbare `today`-Clock), der
Text-Renderer eine `STALE ANCHOR`-Zeile und `main()` eine laute
stderr-Warnung; rc bleibt verdict-getrieben (der Daily-Gap-Guard
eskaliert den eingefrorenen Feed unabhängig). Neue Tests: gestaffelte
Dispatches feuern, frischer FAIL blockt, Out-of-window-Family zählt
nicht (weder PASS noch FAIL), Single-Family-Fenster feuert nie,
Staleness-Grenze 10/11 Tage, Render- und CLI-Warnung.
### Changed (2026-06-13) — Audit E-1 TQ-2/TQ-3/TQ-4: Fail-Open-Tests nachgeschärft (mit Observability-Assertions)

Testhärtung für fail-open Pfade, damit "nicht crashen" nicht mehr still
fehlertolerant ohne Diagnose bleibt:

- `tests/test_newsstack_fmp.py::TestPollOnceFailOpen`
  asserten jetzt zusätzlich den Log-Kontrakt:
  - FMP-Fetch-Fehler → `WARNING` (`"FMP stock-latest fetch failed"`),
  - Export-Fehler → `WARNING` (`"export_open_prep failed"`).
- `tests/test_production_gatekeeper.py::test_invalid_cutoff_does_not_crash`
  wurde von reiner Typ-Prüfung auf konkretes Verhalten verschärft:
  unfiltered Event-Rückgabe bleibt erhalten *und* der ERROR-Logmarker
  `"Invalid --pre-open-cutoff-utc"` muss sichtbar sein (`caplog`).
- Relevante Fail-Open-Docstrings wurden datiert und die Intent-Notizen
  auf Audit-E-1 referenziert (TQ-4), damit Scope/Trade-off im Testtext
  nachvollziehbar bleibt.

Test-only, kein Produktionscode.

### Fixed (2026-06-13) — Audit E-2 AW-7-B: Reader-Fallbacks mit Diagnoselog

Zwei bisher stille/diagnoseschwache Reader-Fallbacks wurden observability-
seitig gehärtet:

- `open_prep/feature_importance_report.py::_load_previous_latest` loggt bei
  korruptem oder unlesbarem `latest.json` jetzt explizit auf DEBUG
  (`"FI latest.json unlesbar, starte ohne Vorgänger-Report"`) statt still
  `None` zu liefern.
- `open_prep/run_open_prep.py::_probe_data_capabilities` ergänzt beim
  Capability-Cache-Read-Fallback `exc_info=True`, sodass bei seltenen
  I/O-/Parse-Fehlern ein vollständiger Traceback im Debug-Log verfügbar ist.

Neue Regressionen:

- `tests/test_feature_importance_report.py::test_load_previous_latest_invalid_json_logs_debug`
- `tests/test_feature_importance_report.py::test_load_previous_latest_invalid_utf8_logs_debug`

### Fixed (2026-06-13) — Audit E-2 AW-7-A: Manifest-Reader fail-loud nach Resolve (TOCTOU-Härtung)

`scripts/load_databento_export_bundle.py::load_export_bundle` las das
aufgelöste `*_manifest.json` nach `resolve_manifest_path(...)` ungeschützt
mit `json.loads(read_text(...))`. Wenn zwischen Resolve und Read ein
Race/TOCTOU auftrat (oder das Manifest anderweitig korrupt wurde),
propagierte ein nackter `JSONDecodeError`/`OSError` aus dem Loader ohne
stabilen Fehlervertrag.

Der Read/Parse-Schritt ist jetzt fail-loud gehärtet: parse-/I/O-Fehler werden
als `RuntimeError("Manifest read/parse failed after resolve: <path>")`
mit Pfadkontext neu geworfen. Das stabilisiert die Fehlersemantik für die
kritischen Konsumenten (`smc_integration.service`,
`smc_integration.measurement_evidence`, `smc_integration.structure_batch`).

Neue Regression:
`tests/test_load_databento_export_bundle.py::test_load_export_bundle_parse_fails_after_resolve_raises_runtime_error`.
### Changed (2026-06-13) — Audit E-1 AW-2/AW-3/AW-5: Atomic-Write-Hardening + optionale fsync-Policy

Bundle B2 schließt Atomic-Write-Risiken ohne Verhaltensbruch in
Bestands-Callsites:

- `newsstack_fmp/shared_fetch.py`: Payload-Write nutzt jetzt
  `tempfile.mkstemp(...)+os.replace` statt fester `*.tmp`-Pfadnamen
  (kollisions-/race-robuster, mit Cleanup auf Fehlerpfad).
- `databento_universe.py::save_universe_snapshot`: auf die zentrale
  `_replace_atomic`-Primitive umgestellt (kein fester `.tmp`-Name mehr).
- `scripts/smc_atomic_write.py`: optionale `fsync`-Schalter für
  `atomic_write_text/json/csv/parquet` ergänzt (`fsync=False` default,
  API-kompatibel). Bei `fsync=True` wird die Temp-Datei vor `os.replace`
  explizit geflusht.

Begleitend wurden die betroffenen Ledger-Pins aktualisiert
(`time.sleep`, `hashlib weak-hash`, `tempfile`) sowie die
Unreleased-Datumssortierung im CHANGELOG korrigiert.

Validierung: targeted Guards (84 passed) + Full Sweep
`pytest -n auto -q` (19,454 passed, 126 skipped).

### Fixed (2026-06-13) — Stat-Review W7-2/W7-3: Vote-Integrität des Magnitude-Shadow-Ledgers

Zwei Wege, auf denen die weekly k-of-n-Mehrheit Stimmen aus dem Nichts
erzeugen konnte, sind geschlossen. **W7-2 (stale feed):** Der
Daily-Runner (`scripts/run_magnitude_shadow_ledger.py`) lud das
Benchmark-Events-Artefakt täglich neu und gradete es unter dem neuen
Datum — bei eingefrorenem Feed (Producer kaputt, dawidd6 liefert
denselben letzten erfolgreichen Run) stimmt damit EINE eingefrorene
Beobachtung einmal pro Tag in der Wochen-Mehrheit ab, und das weiter
wachsende Ledger blendet zugleich den Commit-Back-Gap-Guard
(MITTEL-5). Jetzt prüft `main()` vor dem Append, ob derselbe
`events_hash` bereits unter einem früheren Datum gradet wurde: falls
ja, kein Append, lauter stderr-Hinweis, neuer rc 5. Der Daily-Workflow
mappt rc 5 auf `status=stale_feed` + `::warning` (Job bleibt grün);
bleibt der Feed eingefroren, wächst das Ledger nicht mehr und der
fail-loude Gap-Guard eskaliert nach seinem 7-Tage-Budget — die
MITTEL-5-Schutzwirkung ist wiederhergestellt. Same-Day-Re-Runs mit
gleichem Hash bleiben idempotente Merges (rc 0). **W7-3
(Doppel-Stimme):** `eval_magnitude_shadow_weekly.weekly_evaluations`
zählte `pass_days`/`fail_days` pro Ledger-*Zeile*; der Merge-Key des
Ledgers enthält `events_hash`, sodass ein Same-Day-Re-Run gegen
aktualisierte Events zwei Zeilen für denselben Kalendertag hinterlässt
— ein Tag stimmt doppelt ab und kann ein Unentschieden (FAIL) in eine
strikte Mehrheit (PASS) kippen. Jetzt werden die Wochen-Zeilen vor der
Zählung pro Kalenderdatum kollabiert (späteste Listenposition gewinnt,
derselbe Tie-Break wie `latest_rows_by_family` im Gate-Wiring). Neue
Tests: rc-5-Guard (inkl. „build_report wird gar nicht erst
gerechnet“), Idempotenz-Grenzfall, Ein-Tag-eine-Stimme,
Latest-wins-Tie-Break, Workflow-Contract-Pin für `status=stale_feed`.
Beide Pfade sind seit BOS+SWEEP ARMED (2026-06-11) live
entscheidungstragend.

### Fixed (2026-06-13) — Stat-Review W7-1: Magnitude-Shadow-Ledger liest fail-closed

`scripts/run_magnitude_shadow_ledger.py::load_ledger` hat malformed
JSONL-Zeilen bisher still übersprungen (`except JSONDecodeError:
continue`) — fail-open in drei entscheidungstragenden Konsumenten
zugleich: (a) die weekly k-of-n-Bewertung
(`eval_magnitude_shadow_weekly`) verliert Stimmen, wodurch korrupte
FAIL-Zeilen eine strikte Wochen-Mehrheit auf PASS kippen können und das
Demotions-Fenster einer armed Family dauerhaft partial bleibt („partial
window never demotes"); (b) das Gate-Wiring
(`magnitude_snapshot_wiring.latest_rows_by_family`) nimmt die neueste
*parsebare* Zeile, sodass eine korrupte heutige FAIL-Zeile still das
gestrige PASS als Gate-Verdikt wiederbelebt; (c) der Daily-Runner hätte
beim atomischen Rewrite die unparsebaren Historien-Zeilen endgültig
verworfen. Jetzt wirft `load_ledger` bei malformed oder
Nicht-Objekt-Zeilen `ValueError` mit `pfad:zeilennr`; alle vier
CLI-Konsumenten (Daily-Runner, Weekly-Eval, Snapshot-Wiring,
Step-Summary-Renderer) und `run_promotion_gate` (Magnitude-Feed) mappen
das auf rc 1 (fail-loud, Workflow rot). Eine fehlende Datei bleibt
Cold-Start (`[]`). Der Test
`test_load_ledger_skips_malformed_lines`, der das fail-open-Verhalten
als Soll pinnte, ist invertiert
(`test_load_ledger_raises_on_malformed_line`); neue rc-1-Regressionstests
für alle Konsumenten.

### Changed (2026-06-13) — Audit E-1 RS-1..7: Streamlit Render-Layer Observability + Cooldown Fail-Safe

`open_prep/streamlit_monitor.py` hatte mehrere fail-open Pfade mit
`except ValueError` ohne Log-Signal sowie stille Broad-Except-Fallbacks,
die die Diagnose bei Zeitformat-/Session-State-Problemen erschwerten.
Im Audit-E-1 Bundle A wurden die Render-Layer-Guards observability-first
nachgeschärft, ohne das UI fail-open Verhalten aufzugeben:

- RS-1/2/3/4/6: `except ValueError` in Zeitformat-Helfern und
  Soft-Refresh-Routen loggen jetzt strukturiert auf `DEBUG` mit dem
  unparsebaren Rohwert (`updated_at`/`timestamp_utc`/`last_live_fetch_utc`).
- RS-5: `_remaining_cooldown_seconds` hebt Cooldown bei kaputtem
  Timestamp nicht mehr still auf (`return 0`), sondern setzt
  konservativ `RATE_LIMIT_COOLDOWN_SECONDS` und loggt `WARNING`.
- RS-7: bisher stille `except Exception`-Fallbacks bei
  Streamlit-Secrets-/Session-Probe und OPRA-Import sind jetzt als
  `DEBUG` sichtbar (keine Verhaltensänderung, nur Diagnosepfad).

Begleitend wurden die Audit-Pin-Tests aktualisiert (Ledger-Drift):
`tests/test_dynamic_import_and_todo_tripwires.py`,
`tests/test_silent_error_swallow_pin.py`,
`tests/test_broad_except_silent_budget.py`.

Keine API-/Datenmodell-Änderung; primär Logging + defensiver
Rate-Limit-Schutz.

### Changed (2026-06-13) — Audit E-1 TQ-1: eod-bulk Fail-Open-Test ehrlich gemacht + Observability gepinnt

`tests/test_open_prep.py::TestGetEodBulkInvalidJsonFallback` pinnte das
Fail-Open-Verhalten von `get_eod_bulk()` unter dem irreführenden Namen
`test_unrelated_error_still_propagates` — der Name behauptete Propagation,
das Assert pinnte das Gegenteil (`result == []`). Triage ergab: Das
Fail-Open ist by design korrekt (eod-bulk ist eine ATR-Cache-Optimierung;
der Caller `_fetch_quotes_with_atr` hat einen vollständigen
Per-Symbol-Fallback), und die Produktionsseite war bereits gehärtet
(`_log_feature_unavailable_once`: permanent → INFO einmalig, transient →
WARNING bei jedem Auftreten). Fix daher testseitig:

- Test umbenannt zu `test_transient_error_fails_open_but_warns_every_time`
  mit Begründungs-Docstring (warum Fail-Open hier akzeptabel ist).
- Alle drei Tests asserten jetzt zusätzlich den Log-Kontrakt via
  `assertLogs`: permanent (invalid JSON, HTTP 402) → genau eine
  INFO-Zeile pro Prozess; transient (network timeout) → WARNING bei
  JEDEM Aufruf (2 Aufrufe → 2 WARNINGs, kein Dedup).
- `setUp` resettet `_FMP_FEATURE_UNAVAILABLE_LOGGED`, damit die
  Once-per-Process-Semantik pro Test isoliert beobachtbar ist.

Test-only, kein Produktionscode. (Audit E-1, Bundle C1)

### Changed (2026-06-13) — Audit E-1 AW-1: Atomic-Write-Guards auf alle Produktions-Surfaces erweitert

Beide Atomic-Write-Pin-Tests scannten nur Teilflächen:
`tests/test_atomic_write_call_sites.py` (open/fdopen-Writes) deckte
`scripts/ open_prep/ ml/ rl/ governance/` ab,
`tests/test_no_direct_to_csv_in_production.py`
(to_csv/to_parquet/write_text/json.dump) sogar nur `scripts/`. Neue
non-atomic Writer in `smc_core/`, `smc_integration/`, `newsstack_fmp/`
oder den Repo-Root-Modulen (`databento_*`, `terminal_export`,
`streamlit_terminal`, `pine_*`) regressierten still. Beide Guards
scannen jetzt alle acht Verzeichnisse plus Repo-Root (non-rekursiv);
der Bestand wurde site-für-site verifiziert und als dokumentierte
Baseline-Allowlist aufgenommen (überwiegend bereits korrekte
mkstemp+os.replace-Muster). `_FILE_LEVEL_EXEMPT`-Keys sind jetzt
repo-relative POSIX-Pfade statt kollisionsanfälliger Dateinamen; neuer
Pin `test_file_level_exempt_keys_exist` verhindert stale Einträge.
Härtungs-Kandidaten (fixer tmp-Name ohne Exception-Cleanup) sind als
AW-2/AW-3 in den Rationales markiert. Test-only, kein Produktionscode.

### Removed (2026-06-12) — drift-watchdog-Cron stillgelegt (#2726)

`.github/workflows/drift-watchdog.yml` (Montags-Cron) ist entfernt. Der
Faktencheck zu #2726 ergab: Die erwartete WFO-Baseline
`artifacts/wfo/walk_forward_latest.json` wurde von keiner Pipeline je
produziert (keinerlei Git-Historie unter `artifacts/wfo/`; der im
Workflow-Header zitierte „C2 walk-forward cron“ existiert nicht im
aktuellen Workflow-Set — dasselbe hatte bereits
`docs/ci-proposals/j3-followup-cron-workflow-run-2026-05-01.md`
notiert). Seit dem Fail-loud-Fix #2725 wäre jeder Lauf ein
garantiertes rc=4 gewesen; davor war er ein stiller No-op.

- Drift-Abdeckung läuft heute über `c13-daily-cron.yml`
  (täglich, `compute_live_drift` + Issue-Opener) und das
  Phase-B-Promotion-Gate — der wöchentliche Watchdog war redundant
  *und* funktionsunfähig.
- `scripts/run_drift_watchdog.py` und seine Tests bleiben erhalten:
  Das CLI ist weiter manuell mit explizit übergebener Baseline nutzbar
  und dient als gepinnte Referenz-Implementierung des
  Atomic-Write-Patterns (`tests/test_atomic_write_call_sites.py`,
  `tests/test_csprint_atomic_write_fsync.py`).
- Inventory-Pin `tests/test_workflow_continue_on_error_inventory.py`
  um den drift-watchdog-Eintrag reduziert; stale Kommentar-Verweise in
  `c13-daily-cron.yml`, `phase-b-promotion-readiness.yml`,
  `scripts/check_phase_b_drift_readiness.py` (dessen Wiring-Claim schon
  vorher falsch war) und dem Script-Docstring aktualisiert.

### Fixed (2026-06-12) — f2-promotion-gate: Rollback-Ping in falsches Issue (Label-only-Suche)

Der Step „Open rollback Issue (§2.4 G2 ping)“ in
`f2-promotion-gate-daily.yml` suchte ein bestehendes Issue nur über
`--label cron-failure` — ohne Titel-Filter. Da mehrere Workflows
(credential-health-check, workflow-freshness-monitor, …) dasselbe Label
verwenden, traf die Suche das erste beste offene cron-failure-Issue:
der Rollback-Ping vom 2026-06-12 (SPRT accept_h0, n=1664) landete als
Kommentar im fachfremden credential-health-Issue #2732 statt in einem
`[F2 rollback]`-Issue. Die Suche filtert jetzt zusätzlich mit dem
GitHub-Suchfilter `"[F2 rollback]" in:title` (matcht die Phrase
irgendwo im Titel; der Wert wird zur Laufzeit aus
`scripts/f2_render_rollback_issue.py::TITLE_PREFIX` importiert); der
Step-Kommentar (der fälschlich ein nicht existentes „f2-rollback label“
behauptete) ist mitkorrigiert.

### Security (2026-06-12) — tsx ^4.22.4 → esbuild 0.28.1 (Dependabot #5/#6)

`tsx` von `^4.20.5` auf `^4.22.4` gehoben, wodurch das transitive
`esbuild` von 0.27.4 auf 0.28.1 springt. Schließt Dependabot-Alert #6
(high: fehlende Binary-Integritätsprüfung im Deno-Modul → RCE via
`NPM_CONFIG_REGISTRY`) und #5 (low: arbitrary file read im Dev-Server
unter Windows). Beide Alerts betreffen nur dev-Tooling (tsx-Runner für
die `tv:*`-Skripte), kein Produktionscode. Der damalige Hinweis zu
verbleibenden Torch-Alerts ohne Patch ist durch das Security-Update vom
2026-06-20 überholt (Upgrade auf `torch==2.12.1` bzw.
`torch==2.12.1+cu129`).
### Added (2026-06-12) — pre-push Hook: pin/ledger drift guard (fast-gates parity)

Neues `scripts/run_ledger_drift_guard.sh` + pre-commit-Hook
`ledger-pin-drift-guard` (`stages: [pre-push]`): extrahiert die
Testdatei-Liste zur Laufzeit aus dem autoritativen
"Run pin / ledger drift guard"-Step in `smc-fast-pr-gates.yml`
(Single Source of Truth — die Liste wächst, kein Hardcoding) und führt
sie mit denselben pytest-Flags lokal aus (~60s, `-n auto` wenn xdist
installiert; andernfalls seriell — gleiche Korrektheit, langsamere Ausführung).
Motivation: am 2026-06-12 drifteten vier Ledger-Pins
(mkstemp/sys.exit/unlink/basicConfig in `open_prep/outcome_backfill.py`)
durch einen +6-Zeilen-Docstring in PR #2729 und fielen erst in CI auf.
Aktivierung: `pre-commit install --hook-type pre-push`.

### Added (2026-06-12) — Runbook: TradingView storage-state capture + Secret-Rotation

Neues `docs/tradingview-storage-state-capture-runbook.md`: dokumentierte
Prozedur für `npm run tv:storage-state`
(`scripts/create_tradingview_storage_state.ts`) — Capture-Ablauf (headed
Chromium, Login/MFA, Auth-Heuristik, `meta.authValidatedAt`),
CLI-Flags/Env-Tabelle, Standard-Rotation via
`gh secret set TV_STORAGE_STATE`, Verify über
`credential-health-check.yml`,
persistent-profile-Alternative (`tv:profile-login`), Security-Regeln
(`tv:auth-security`-Guard, Session-Cookie-Hygiene) und der am 2026-06-12
beobachtete Secret-Snapshot-Pitfall (GHA liest Secrets bei Job-Start —
laufende library-refresh-Jobs preflighten mit dem alten Cookie).
Querverweis aus §7.3 des operativen Publish-Runbooks ergänzt.
### Added (2026-06-12) — credential-health: Billing-Alarm (HTTP 402) + Databento-Delivery-Probe

Post-mortem: Eine unbezahlte Databento-Rechnung blieb 12 Tage unbemerkt,
weil (a) HTTP 402 Payment Required im generischen Vendor-Probe in den
"other → warn"-Bucket fiel statt laut zu alarmieren und (b) der
Auth-Probe (`metadata.list_publishers`) auch bei gestörtem Billing
weiter HTTP 200 liefert. Zwei Fixes in
`scripts/credential_health_check.py`:

1. **HTTP 402 → error** (alle Vendor-Probes, via neuem
   `_map_vendor_http_error`): "BILLING problem … check the vendor portal
   for an unpaid invoice / failed payment NOW" — öffnet damit das
   tägliche `cron-failure`-Issue.
2. **Neuer Probe `databento_delivery`**: ruft
   `metadata.get_dataset_range` (kostenloser Metadata-Call) für das
   konsumierte Dataset `DBEQ.BASIC` auf und alarmiert mit `error`, wenn
   das verfügbare `end`-Datum > 5 Tage stagniert — Symptom eines wegen
   Zahlungsverzug suspendierten Accounts, den der reine Key-Probe nicht
   sieht. Netzwerk-/Parse-Fehler bleiben `warn` (inconclusive), kein
   Flapping.

Keine Workflow-Änderung nötig: `credential-health-check.yml` reicht
`DATABENTO_API_KEY` bereits durch; der neue Probe läuft automatisch im
täglichen 06:00-UTC-Lauf mit. Tests: 402-Kontrakt für alle 4 Probes +
8 Delivery-Probe-Fälle (frisch/stale/Schwelle/leerer Key/kein
`end`/Netzfehler/date-only/Basic-Auth-URL).
### Changed (2026-06-12) — F2 contextual candidate: SPRT accept_h0 final, Spec auf rolled_back

Das F2-Kontextual-Experiment (`f2-contextual-zone-priority-promotion`)
ist abgeschlossen: Gate-Run 27426121665 akzeptierte H0 auf dem
Post-Fix-Dual-Arm-Korpus (n=1664 > max_n=1200, LLR=−5.14 <
Wald-Lower −1.56; Treatment-Brier 0.2804 vs. Control 0.2375 —
Arme nachweislich verschieden, anders als beim void 2026-06-09-Verdict).
Spec-Status `live → rolled_back` geflippt (Treatment-Artefakt war nie
production; Revert = noop_already_shadow). Neuer ADR
`2026-06-12 f2-contextual-sprt-h0-final` in `docs/DECISIONS.md`.
`f2-promotion-gate-daily.yml` bekommt einen `spec-status`-Guard-Job,
der das Gate bei `status=rolled_back` soft-skippt, statt täglich mit
rc=2 rot zu laufen. Ein neuer Kandidat braucht eine frische
Spec-Registrierung plus `plumbing_only → live`-Flip (Auto-Reset des
SPRT-States via `scripts/f2_flip_status.py`).

### Fixed (2026-06-12) — Workflow-Audit MITTEL-11: newsapi bot-branch push fail-loud

`continue-on-error: true` vom Step "Publish snapshot to rolling bot
branch" in `smc-live-newsapi-refresh.yml` entfernt und der zugehörige
`_ALLOWED`-Eintrag in
`tests/test_workflow_continue_on_error_inventory.py` gestrichen.
Begründung: der Step-Body ist seit F-V5-F1 bereits explizit fail-loud
(`if git push … else … exit 1`), aber das Step-Attribut neutralisierte
genau das — ein dauerhaft scheiternder Push (abgelaufener PAT,
Ruleset-Änderung) blieb für immer grün und der
`bot/live-news-snapshot`-Staleness-Floor verrottete still. Transiente
Fehler heilen sich über den nächsten 5-Minuten-Tick selbst; persistente
Fehler müssen rot werden.

### Fixed (2026-06-12) — f2-promotion-gate: leere Dual-Arm-Bäume → status=skipped statt rc=1 (Cron-Health-Audit)

Der `locate`-Step prüfte nur die **Existenz** der per-Datum-Verzeichnisse
(`artifacts/ci/f2/{static_global_weights,contextual_weights}/<DATE>`).
Der Dual-Arm-Step in `smc-measurement-benchmark-rolling.yml` läuft aber
unter `if: always()` — an Tagen mit Producer-Artifact-Ausfall lädt er
LEERE Arm-Bäume hoch (Datums-Verzeichnisse + Manifest mit null
`pair_runs`). Der Orchestrator brach dann mit rc=1 („no benchmark pairs
in control_dir=…") ab: ein CI-roter Run für eine by-design Upstream-Lücke,
die der L-2-Skip-Pfad eigentlich absorbieren soll (beobachtet: 11/11
Schedule-Runs rot im 14-Tage-Fenster bis 2026-06-12). Der `locate`-Step
verlangt jetzt zusätzlich ein lesbares `benchmark_run_manifest.json` mit
≥ 1 `pair_runs`-Eintrag in BEIDEN Armen, sonst `status=skipped` (mit dem
bestehenden L-2-`::warning`). Pin:
`tests/test_f2_promotion_gate_daily_workflow_contract.py::test_locate_step_requires_nonempty_pair_runs`.

### Changed (2026-06-11) — C9/T7: Bauchgefühl-Detektoren → p-Wert-Tests (#298, struktureller Teil)

Die Interim-Effektgrößen-Regeln der C9-Drift-Konsensus-Detektoren 3+4
(Mean-Shift ≥ 0.3σ, Varianz-Ratio außerhalb [0.5, 2.0] — dokumentierte
Bauchgefühl-Schwellen) sind durch Signifikanztests ersetzt, deren
Feuerrate über ein Alpha-Level statt eines willkürlichen
Effektgrößen-Cutoffs kontrolliert wird:

- **`scripts/drift_alert.py`**: neu `welch_t_two_sample` (Detector 3 —
  zweiseitiger Welch-t auf den Mittelwert) und
  `brown_forsythe_two_sample` (Detector 4 — median-zentrierter Levene
  auf die Skala; robust gegen Heavy Tails, anders als der plain
  F-Ratio-Test). P-Werte über die regularisierte unvollständige
  Beta-Funktion (pure stdlib, kein scipy; gegen scipy auf 1e-9
  verifiziert). Alle drei p-Wert-Detektoren (KS/Welch-t/BF) teilen eine
  Alpha-Leiter.
- **Produktions-Default** in `compute_drift_report`: `p_red 0.01→0.005`,
  `p_yellow 0.05→0.025` — Grid-Sieger auf BEIDEN synthetischen Bänken
  (Gauss: TPR 0.80/FPR 0.03; gemischt t(4)+lognormal: TPR 0.90/FPR
  0.07); der alte Default riss auf der gemischten Bank die
  FPR<0.10-Akzeptanz (0.12), sobald Detektoren 3+4 p-Wert-Tests wurden.
- **`scripts/c9_threshold_replay.py`**: `_episode_fires` nutzt dieselben
  Tests; neues Provenance-Flag `CALIBRATION_SOURCE = "synthetic"`.
- **Anker umgebaut** (`tests/test_c9_threshold_finalisation_anchor.py`):
  feuert jetzt, wenn der C12-Trigger GREEN ist und `CALIBRATION_SOURCE`
  noch `"synthetic"` lautet — der Live-Retune der Alpha-Leiter gegen
  ≥ 90 Tage Live-Daten bleibt offen, Issue #298 bleibt dafür offen.
- Doku: `docs/c9_threshold_tuning.md` mit Grid-Ergebnissen (2026-06-11)
  und Live-Retune-Prozedur aktualisiert. Neue Tests in
  `tests/test_drift_alert.py` (Welch-t/BF inkl. scipy-Referenzwerte,
  Degenerate-Input-Guards, Heavy-Tail-Robustheit).
### Fixed (2026-06-11) — Outcome-Ledger: pytest-Write-Guard gegen Testverschmutzung des kanonischen Artefakt-Baums

Zwei Full-Pipeline-Tests in `tests/test_open_prep.py` riefen
`generate_open_prep_result(..., now_utc=2026-02-23)` ohne Persistenz-Stub auf;
`store_daily_outcomes` löste das relative `OUTCOMES_DIR` gegen das Repo-Root
auf und überschrieb bei **jedem lokalen Testlauf** das getrackte Artefakt
`artifacts/open_prep/outcomes/outcomes_2026-02-23.json`. Die Verschmutzung
wurde zweimal nach main committet (#2687; erneut mit vix9d-Feldern nach
#2688/#2692), und die Backfill-Automation (#1926) labelte den synthetischen
NVDA-Datensatz als echten Trade — Kontamination der Hit-Rate-Statistik.

- **`open_prep/outcomes.py`** (`store_daily_outcomes`) und
  **`open_prep/outcome_backfill.py`** (`_save_outcome_file`): fail-loud
  `guard_against_canonical_repo_write_under_pytest` (bestehendes Muster aus
  `smc_core/_pytest_canonical_write_guard.py`, PR #33) — Schreibzugriffe auf
  `artifacts/open_prep/outcomes/` unter pytest ⇒ `RuntimeError` statt
  stiller Verschmutzung. Produktionspfad (kein `PYTEST_CURRENT_TEST`)
  unverändert.
- **`tests/test_open_prep.py`**: die beiden Verursacher-Tests stubben jetzt
  `store_daily_outcomes` explizit.
- **`artifacts/open_prep/outcomes/outcomes_2026-02-23.json` gelöscht**: von
  Geburt an synthetisch (einzelne NVDA-Zeile mit `gap_pct=0.0`/`rvol=0.0`,
  exakt die Mock-Fixture; erzeugt durch einen Testlauf, committet in
  `6c0ced38`). Echte Outcome-Tage (2026-02-24 ff.) unangetastet.
- Neue Tests: `tests/test_outcomes_pytest_write_guard.py` (Guard blockt
  kanonischen Pfad, erlaubt `tmp_path`-Redirect; Tripwire gegen
  Wiederauftauchen des synthetischen Artefakts).
- Ledger-Rebaseline (Zeilenverschiebung durch Import + Guard-Aufrufe):
  `tests/test_random_tempfile_ledger_pin.py`,
  `tests/test_os_unlink_remove_ledger.py`,
  `tests/test_mutable_defaults_and_loads_pins.py`.

### Fixed (2026-06-11) — Rolling benchmark: manifest workbook provenance (#2678 fallout)

- **`scripts/export_smc_structure_artifacts_from_workbook.py`**: `--workbook`
  no longer defaults to the hardcoded `DEFAULT_WORKBOOK` path. In CI the
  bundle workbook `.xlsx` does not exist (per-TF data comes from the parquet
  bundle), so the exporter stamped a non-existent path into
  `resolved_inputs.workbook_path` and the benchmark consumer's provenance
  check rejected every manifest with `NONCANONICAL_MANIFEST_WORKBOOK_PATH`
  (run 2026-06-11 16:49, first scheduled run after #2678). This killed the
  rolling-benchmark lane and starved the F2 promotion gate
  ("no benchmark pairs in control_dir"). The CLI now defaults to `None` so
  the library applies `artifact_resolution.resolve_production_workbook_path()`
  — the SAME canonical-first resolution the consumer check uses.
- Tests: CLI default-None pin, forward-None-when-omitted, explicit-workbook
  passthrough (`tests/test_per_tf_structure_artifact_wiring.py`).

### Fixed (2026-06-11) — §5-Kostenmodell: Review-Findings aus #2697

- **Fee-only-Legs zählen in den Round-Turn-Cost**
  (`governance/execution_costs.py`): Trailing-Exits ohne Limit-Referenz
  wurden komplett aus `per_side` ausgeschlossen — das unterschätzte die
  Round-Turn-Kosten für jeden Trade mit Trail-Exit systematisch (und
  widersprach dem Modul-Docstring "contribute fee only"). Jetzt gehen
  sie mit ihrer Commission (Slippage unmessbar ⇒ 0) in die
  Per-Side-Samples und damit in Punktschätzer + CI ein.
- **Gate fail-closed bei kaputtem measurable-Report**
  (`scripts/run_epnl_after_cost_gate.py`): ein Report mit
  `measurable: true` aber fehlendem/nicht-koerzierbarem
  `conservative_cost_bps` führte zu einem unbehandelten Crash statt
  Exit 1 mit klarer Meldung.
- Test-Fixtures: synthetische `order_id`/`perm_id` über `zlib.crc32`
  statt `hash()` (PYTHONHASHSEED-unabhängig, keine Modulus-Kollisionen).

### Fixed (2026-06-11) — Phase-B-Readiness-Workflow: Drift-Artifact-Download (C8 Phase A → B)

`phase-b-promotion-readiness.yml` konnte strukturell nie erfolgreich laufen:
Der Gate-Glob `artifacts/drift/drift_report_*.json` zeigte auf den frischen
Checkout, aber die Drift-Artefakte mit dem Gate-Feld
`slippage_ks_reference_type` werden von `compute_live_drift`
(`c13-daily-cron.yml` Step 4) ausschließlich als **Run-Artefakt**
(`c13-daily-<DATE>`, Pfad `cache/live/drift_<DATE>.json`) hochgeladen und nie
ins Repo committet — jeder Dispatch wäre mit Exit 64 (`no files matched`)
geendet. Deshalb hatte der Workflow seit Erstellung (Deep-Review 2026-04-27)
null Läufe. (Das `drift-report`-Artefakt des drift-watchdog ist ein anderer
Report-Typ ohne das Gate-Feld — empirisch verifiziert; das Gate darf nicht
darauf zeigen.)

- **`.github/workflows/phase-b-promotion-readiness.yml`**: neuer Step
  `Fetch latest compute_live_drift artifact` scannt die letzten 10
  erfolgreichen `c13-daily-cron`-Runs (Step 4 soft-skippt an Wochenenden
  mangels Walk-Forward-Inputs) und kopiert das jüngste `drift_<DATE>.json`
  als `artifacts/drift/drift_report_<DATE>.json` in den Checkout (Glob-Pin
  des Contract-Tests bleibt gültig). Kein Treffer → Exit 2
  (`EXIT_NOT_READY`). Skip, wenn der Caller-Glob bereits Dateien im Checkout
  matcht (workflow_call-Pfad). `permissions` um `actions: read` erweitert
  (weiterhin rein lesend).
- **`tests/test_phase_b_promotion_readiness_workflow_contract.py`**:
  Permissions-Pin auf `{contents: read, actions: read}` aktualisiert.

### Added (2026-06-11) — CI: ruff als obligatorisches Lint-Gate in smc-fast-pr-gates

`ruff check .` ist ab sofort ein Pflicht-Schritt im `fast-gates`-Job (blocks
merge). Konfiguration lebt in `pyproject.toml [tool.ruff]`; das Gate läuft
direkt nach dem PYTHONUNBUFFERED-Lint und schlägt bei jedem Code-Fehler fail.

- Alle bestehenden Verletzungen (359 auto-fixbar + 85 manuell) bereinigt:
  - `ruff check --fix` entfernte 278 auto-fixbare (unsortierte Imports, I001;
    obsolete noqa-Direktiven, RUF100; trailing whitespace, W292; u.a.).
  - Manuelle Korrekturen: SIM103/SIM115/SIM117/SIM118/RUF034/B007/F841/
    RUF059/RUF005/RUF007/E741/E731/F401/UP007 in Tests, Scripts, Governance.
  - Neue `per-file-ignores` für plan-gating Sonderfälle: E402 in open_prep/*,
    E701/E702/E741/B007 in scripts/c10b_* (Analyse-Skripte mit kompaktem Stil),
    S108 nur gezielt für c10b/c10c-Research-Skripte + Provenance-Scanner
    (dokumentierte lokale /tmp-Korpora bzw. Regex-Pattern); S603/S607 nur für
    eine explizite, grandfathered Dateiliste (neue Scripts bekommen volles
    Subprocess-Linting),
    F821 in streamlit_terminal.py (Forward-Referenz, Runtime korrekt), UP047 in
    skipp_config/trading_thresholds.py.
  - `ruff==0.15.16` zu `requirements.txt` hinzugefügt; `_DEP_LINE_BUDGET`
    26 → 27.

### Fixed (2026-06-11) — ADR-0023: Weekly-k-of-n bewertete Tageszeilen statt ISO-Wochen

Der Stage-1-Weekly-Evaluator (`scripts/eval_magnitude_shadow_weekly.py`)
nahm als Fenster die **letzten n Tageszeilen** (`rows[-n:]`) — präregistriert
ist aber „k of n consecutive **weekly** evaluations" (Handover §3/§4.4).
Tageszeilen sind Pseudo-Replikate (rollierender Events-Export, hoch
autokorreliert): Stage-2-Eligibility wäre nach 3 PASS-**Tagen** erreichbar
gewesen, Auto-Demotion der armierten Familien (BOS/SWEEP) schon nach 4
dünnen/verrauschten **Tagen** — beides um Wochen zu früh.

- **ISO-Wochen-Bucketing**: Tageszeilen werden per ISO-Woche gebucketet
  (`weekly_evaluations()`); Wochen-Status = strikte Mehrheit der messbaren
  Tageszeilen (Gleichstand/Fail-Mehrheit ⇒ FAIL; keine messbaren ⇒
  INCONCLUSIVE). Kalenderwochen ohne Daten belegen einen Fenster-Slot als
  INCONCLUSIVE (Outage verzögert, beschleunigt nie).
- **Globaler Anker**: Fenster aller Familien endet an der ledger-weiten
  jüngsten Woche — eine stale Familie wird mit INCONCLUSIVE gepolstert
  statt ihr Fenster zu verschieben (fail-safe).
- **`window_size` = messbare Wochen**: Cold-Start-Ledger mit einer Woche
  Tageszeilen ⇒ `window_size == 1` ⇒ weder Stage-2-Arming noch
  Auto-Demotion möglich (Demotion verlangt weiterhin das volle n-Wochen-
  Fenster). Report enthält jetzt `weeks` (pro Familie) + `anchor_week`.
- CLI, Exit-Codes (0/2/3/4/1), `stage2_status_line()`-Format und der
  Weekly-Workflow bleiben unverändert; Red-Flag-Detektor bleibt bewusst
  tagesbasiert (Artefakt-Signatur). Step-Summary-Fußnote
  (`render_shadow_step_summary.py`) stellt klar: Tabelle = Tages-Preview,
  maßgeblich ist der ISO-Wochen-Evaluator.
- Tests: Fixtures auf Wochenabstand umgestellt; neue Regressionstests für
  Same-Week-Collapse (der Bug), Tie⇒FAIL, Gap-Wochen-Padding, globalen
  Anker, Cold-Start-Demotion-Sperre, ISO-Label-Format.

### Changed (2026-06-11) — PG-Kalibrierung: explizites RECALIBRATION_REQUIRED-Signal (#2693 Follow-up)

`#2693` hat nur die Eligibility-Schwelle verschoben (20→30), nicht das
Problem gelöst. Ein ECE-Breach **bei n ≥ Floor** ist per Konstruktion
kein Small-Sample-Rauschen mehr (das ist das supprimierte n<Floor-Band) —
er zeigt ein echtes Kalibrierungsproblem an, dessen richtige Antwort
Recalibration ist, nicht der nächste Floor-Bump:

- **`smc_integration/release_policy.py`**: die
  `MEASUREMENT_CALIBRATED_ECE_ABOVE_THRESHOLD`-Degradation trägt jetzt
  `recalibration_required: true` + `recommended_action: "recalibrate"`,
  und das `detail` nennt n_events, den Floor und das
  RECALIBRATION_REQUIRED-Verdikt explizit. Additive Felder auf dem
  bestehenden Code — Governance unverändert (kein neuer Degradation-Code,
  HARD_BLOCKING bleibt).
- Damit ist der Fall „echtes Kalibrierungsproblem bei n≥30" im
  Gate-Report maschinell vom (supprimierten) Small-Sample-Fall
  unterscheidbar.
- Tests: Marker-Felder bei n=30 mit PG-Inzidenzwert (0.331385),
  Scoping-Test (Brier-Degradation trägt den Marker NICHT).
- Ledger-Rebaseline: S603-noqa-Site `release_policy.py` 1107→1119
  (`pin_registry.toml`, `tests/test_subprocess_spawn_sites_ledger.py`).

### Fixed (2026-06-11) — Credential-Health: FMP-Probe-Endpoint plan-gated (Issue #2682)

Die tägliche FMP-Key-Probe schlug seit der Stable-API-Migration dauerhaft mit
`warn` fehl: `/stable/is-the-market-open` ist plan-gated und liefert mit
gültigem Key HTTP 404 (verifiziert 2026-06-11: 404 mit echtem Key, 401 mit
ungültigem Key — der Pfad existiert, das Abo deckt ihn nicht). Jede Probe war
damit "inconclusive" und das Warnsignal permanent verrauscht.

- `scripts/credential_health_check.py::probe_fmp` probt jetzt
  `/stable/quote?symbol=AAPL` — die Endpoint-Familie, von der die
  Produktions-Pipeline tatsächlich abhängt (weiterhin ~1 Quota-Call/Tag).
- Regressionstest `test_fmp_probe_uses_production_quote_endpoint` pinnt den
  Probe-Endpoint auf `/stable/quote` und verbietet `is-the-market-open`.
- Stale-Doc-Sweep: Workflow-Header in
  `.github/workflows/credential-health-check.yml` aktualisiert.

### Added (2026-06-11) — ADR-0023 Stage-1: Ledger-Verdicts → Promotion-Gate-Snapshot (Handover §5 Punkt 2)

Der Stage-1-Shadow-Runner lief täglich, aber seine Verdicts erreichten das
Promotion-Gate nie — `magnitude_resolution_pass`/`magnitude_auc` blieben
`None`, der `ok_magnitude`-Zweig war dauerhaft dormant (Stage-1 hätte ins
Leere gemessen).

- **`scripts/build_promotion_gate_bundle.py`**: neues Flag
  `--magnitude-ledger` (Default: das Shadow-Ledger
  `artifacts/governance/magnitude_resolution_shadow.jsonl`). Die jüngste
  Ledger-Zeile pro **Kandidaten**-Familie (BOS/SWEEP via
  `magnitude_snapshot_wiring.gate_snapshots`; FVG/OB-Controls erreichen das
  Gate nie) wird in die Bundle-Felder `magnitude_resolution_pass` /
  `magnitude_auc` + Provenance (`magnitude_ledger`, `magnitude_ledger_date`,
  `magnitude_status`) gefaltet. Fail-soft: fehlendes/leeres Ledger ⇒ Felder
  bleiben absent ⇒ Gate dormant (exakt das Vorverhalten).
- **`.github/workflows/promotion-gate-daily.yml`**: Bundle-Step übergibt
  `--magnitude-ledger` explizit; das Ledger liegt per Commit-back des
  13:30-UTC-Shadow-Runs bereits im 14:00-UTC-Checkout.
- Gate bleibt **lax** (Stage 1): Werte werden in den Decision-Metrics
  aufgezeichnet, nicht enforced. Handover §4.1/§5.2-Status aktualisiert.
- Tests: Bundle-Faltung (latest-wins, Controls ausgeschlossen,
  INCONCLUSIVE→unmeasured, fehlendes Ledger dormant), Full-Chain
  Ledger→Bundle→Gate→Decision-Metrics
  (`tests/test_promotion_gate_producer_e2e.py`), Workflow-Contract-Pin
  (`tests/test_promotion_gate_daily_workflow_contract.py`).

### Added (2026-06-11) — ADR-0023 §5: Empirische Execution-Cost-Kalibrierung aus C8-Paper-Fills

Der §5-E[PnL]-after-cost-Check rechnete bislang mit dem flachen
pre-registrierten Haircut (`DEFAULT_COST_BPS = 5.0`). Für die
Stage-3-Aktivierung braucht es die **empirische** Kostenbasis aus den
C8-Phase-A-Paper-Sessions (IBKR, `run_ibkr_open_execution.py`).

- **`governance/execution_costs.py` (neu, pure stdlib)**: Kostenmodell aus
  Session-Fills — `commission_bps()` (IBKR Fixed: max($1, $0.005/Share),
  Cap 1 % Notional), `slippage_bps()` (vorzeichenbehaftet ggü. Limit;
  Price-Improvement zählt negativ), `extract_leg_costs()` (Order-Ref-Gruppierung,
  VWAP über Partial-Fills, Dedupe über Snapshots+Final; Trailing-Legs
  fee-only) und `calibrate_costs()` → `CostCalibration` mit Bootstrap-CI
  (Seed 230022, B=1000) und `conservative_cost_bps = CI-high` (Round-Turn).
  Measurability-Floors: ≥ 20 Cost-Samples UND Entry-Fill-Rate ≥ 0.5,
  sonst `measurable: false` mit `fail_reasons`.
- **`scripts/calibrate_execution_costs.py` (neu)**: CLI — Session-JSONs rein,
  Kalibrierungs-Report raus (atomic write). Exit 0 = measurable,
  2 = unmeasurable (Report wird trotzdem geschrieben), 1 = Usage-Fehler.
- **`scripts/run_epnl_after_cost_gate.py`**: neues Flag
  `--cost-calibration <report.json>` — überschreibt `--cost-bps` mit dem
  konservativen empirischen Round-Turn-Cost. **Fail-closed**: eine nicht
  messbare Kalibrierung ist Exit 1, kein stilles Fallback auf den flachen
  Default. Report trägt `cost_source` (`empirical_calibration` |
  `flat_default`) und bettet die Kalibrierung unter `cost_calibration` ein.
- Tests: `tests/test_execution_costs.py` (Commission-Regime-Grenzen,
  Slippage-Vorzeichen BOT/SLD, VWAP/Partial-Fills, Dedupe, Fill-Rate,
  Measurability-Floors, Seed-Determinismus, CLI-Exit-Codes,
  Gate-Wiring inkl. Fail-closed).

### Changed (2026-06-11) — ECE-Eligibility-Floor 20→30 (#2693)

- **`min_events_for_calibrated_thresholds: 20 → 30`**
  (`smc_integration/release_policy.py`): margin above the Platt-scaler
  fitting minimum (`_MIN_PLATT_EVENTS=20`). At exactly n=20 ECE sampling
  noise (~±0.15) dwarfs the 0.30 ceiling — incident 2026-06-10: PG hit
  n=20 with calibrated_ece 0.331/0.381 and hard-failed three consecutive
  smc-library-refresh runs (27297623388, 27299755086, 27309262730).
  Governance unchanged: `MEASUREMENT_CALIBRATED_ECE_ABOVE_THRESHOLD`
  stays HARD_BLOCKING; only the eligibility floor moves.
- **Suppression now observable**: the measurement-shadow baseline payload
  carries `calibrated_thresholds_eligible` + `calibrated_thresholds_floor`
  so gate reports show why a calibrated-threshold breach below the floor
  did not fire (review finding on #2693).
- Tests: incident regression at n=20 (PG values), boundary pair n=29
  (suppress) / n=30 (fire), eligibility-flag asserts.

### Fixed (2026-06-11) — FI pipeline: component persistence + sample dedup (c10b follow-up)

Blast-radius remediation after the FDR-gate wiring fix: the FI
pipeline's inputs were structurally degenerate, independent of the gate.

- **Component persistence** (`open_prep/outcomes.py`):
  `prepare_outcome_snapshot()` now flattens the 14 weighted
  `score_breakdown` components (keys from `FEATURE_TO_WEIGHT_KEY`) into
  every outcome record. Previously `outcomes_<date>.json` never carried
  them, so `backfill_feature_importance()` defaulted every component to
  `0.0` — all FI reports since 2026-04-30 were computed on all-zero
  feature vectors (c10b side-finding). Absent breakdown ⇒ `None`, not
  `0.0`, so absence stays distinguishable from a genuine zero.
- **Era-gate** (`open_prep/outcome_backfill.py`):
  `backfill_feature_importance()` skips labeled records lacking the full
  component schema (legacy pre-fix outcome files) instead of laundering
  the missing keys into all-zero samples; skip count is logged.
- **(symbol, date) dedup** (`open_prep/outcomes.py`):
  `compute_feature_importance()` deduplicates samples across the
  overlapping daily fi_samples files (the backfill re-emits its full
  lookback window each day, inflating n ~3× and the Welch t-stats
  feeding the BH-FDR gate by ~√3). Newest file wins; report gains
  `duplicate_samples_dropped`.
- **Historical artifacts annotated, not recomputed**: README notes in
  `artifacts/open_prep/feature_importance/` and
  `artifacts/open_prep/outcomes/feature_importance/` mark all reports ≤
  2026-06-09 as vacuous (zero-variance inputs; recommendations are not
  evidence). No production weight adjustment ever consumed them
  (verified: no candidate-weight artifacts, `DEFAULT_WEIGHTS`
  unchanged); historical component values were never persisted, so
  recomputation is impossible — clean samples accumulate forward.
- Tests: `tests/test_fi_component_persistence.py` (new; E2E
  snapshot→backfill→report) + fixture alignment in
  `tests/test_outcome_backfill.py`/`tests/test_feature_importance_report.py`.

### Fixed (2026-06-11) — FDR-gate wiring + GAP_FADE zero-gap direction (Copilot findings on #2687)

- **BH-FDR gate was defined but never invoked** (`open_prep/outcomes.py`):
  `compute_feature_importance()` never called `_benjamini_hochberg()`, so
  live FI reports lacked the `fdr_significant` key and the
  `compute_weight_adjustments()` gate (`feat.get("fdr_significant",
  False)`) silently neutralized ALL features — weight auto-tuning was
  dead since #2687. The gate is now wired: per-feature p-values are
  collected, BH-adjusted at q=0.05, and stamped onto every feature entry.
  The "strong predictor" recommendation additionally requires
  FDR significance.
- **GAP_FADE direction for zero/missing gap**: `infer_trade_direction()`
  returned "short" for `gap_pct == 0` (and missing gap defaulting to 0),
  contradicting its documented long default. `>=` → `>`.
- Tests: `tests/test_eval_findings_fixes.py` — 7 new regression tests
  incl. E2E noise-vs-signal FDR gating and a live-report
  weight-adjustment movement check.

### Added (2026-06-11) — VIX9D term-structure observe-only feature (eval D5)

- **`vix9d_vix_ratio`** (VIX9D ÷ VIX): > 1 ⇒ inverted short-term vol
  term structure ⇒ the market prices an imminent event risk. Fetched via
  the existing FMP `get_index_quote("^VIX9D")` endpoint (verified live:
  FMP serves all CBOE vol indices), stamped market-wide onto every ranked
  v2 row and recorded in outcome snapshots. Appended to
  `FEATURE_KEYS`/`PASS_THROUGH_FEATURE_KEYS` — observe-only, NOT wired
  into regime classification or scoring until FI evidence exists.
  Fail-closed: ratio is `None` when either quote is missing or VIX ≤ 0.
- Tests: `tests/test_vix9d_term_structure.py` (new).

### Changed (2026-06-11) — Eval-findings remediation (B1/B2/B3/B5/B7/B8/D7, C4)

Implementation of the actionable findings from the open-prep scoring/
feature-importance evaluation. All label/feature additions are
observe-only; scoring weights are unchanged:

- **B1 — direction-aware labels** (`open_prep/outcome_backfill.py`,
  `open_prep/outcomes.py`): new `infer_trade_direction()` (GAP_FADE fades
  the gap sign; all other playbooks are continuation) and new outcome
  fields `pnl_30m_pct_signed` + `profitable_30m_directional`. Legacy
  long-only `pnl_30m_pct`/`profitable_30m` unchanged for continuity.
- **B2 — triple-barrier label**: `compute_pnl_from_bars()` now also walks
  the 30-min window bar-by-bar against ATR-scaled barriers
  (target = `atr_pct`, stop = `0.5×atr_pct`; defaults 1.0%/0.5% when ATR
  is missing) producing `label_tb` ∈ {target, stop, timeout_win,
  timeout_loss} + `profitable_tb`; stop is checked first within a bar
  (conservative tie-break).
- **B3 — FI hardening** (`open_prep/outcomes.py`): `mean_separation` now
  uses the POOLED std (Cohen's d) instead of σ_win-only; per-feature
  Welch t-test `p_value` (normal approximation); Benjamini–Hochberg FDR
  gate at q=0.05 → `fdr_significant` flag; recommendations and
  `compute_weight_adjustments()` only act on FDR-significant features
  (non-significant ⇒ neutral importance 0.5); `_MIN_TUNING_SAMPLES`
  raised 30 → 200.
- **B5/D3 — gap×playbook report**: new `compute_gap_playbook_report()`
  aggregating hit-rate/avg-PnL per `gap_bucket:playbook` cell (prefers
  directional labels, falls back to legacy).
- **B7 — EMA seed** (`open_prep/technical_analysis.py`): `_ema()` now
  seeds with the SMA of the first `span` values (TA-Lib convention)
  instead of `values[0]`, removing first-bar bias on 200-bar EMAs.
- **B8 — macro surprise scale** (`open_prep/macro.py`): diagnostic
  `surprise` divisor floor `max(|consensus|, 1.0)` → `max(|consensus|,
  1e-6)` with a ±10 cap; low-consensus series (CPI MoM ~0.2) are no
  longer 5× understated. `contribution` (sign-only) unchanged.
- **D7 — real ADX/BB-width**: new `compute_adx_from_bars()` (Wilder, 14)
  and `compute_bb_width_pct_from_bars()` (20, 2σ) from daily bars; the
  regime-detection enrichment in `open_prep/run_open_prep.py` prefers
  them (`regime_source="daily_bars"`) and falls back to the previous
  ATR-proxy heuristics (`"atr_proxy"`).
- **C4 — observe-only features**: `gap_range_pos` (price position vs.
  prior-day range via new `compute_gap_range_position()`) and
  `eps_surprise_pct` recorded on outcome snapshots and appended to
  `FEATURE_KEYS`/`PASS_THROUGH_FEATURE_KEYS` (unweighted until FI
  evidence exists).
- **Deferred (data-gated)**: D6 Platt calibration (needs ~200 labels),
  D8 meta-labeling (~500 labels), VIX9D term structure + short interest
  (no data source in repo), RSI/breakout threshold changes ("measure
  first").
- Tests: `tests/test_eval_findings_fixes.py` (new) +
  `tests/test_scorer_tuning.py` FDR-gating coverage.

### Added (2026-06-11) — Trend-state features (observe-only) + ZLEMA MA type

Outcome of the ZLEMA/trend-filter analysis: daily trend-state context is
recorded for feature-importance evidence BEFORE any scoring decision
("measure first, wire later"):

- **`compute_trend_state_features()`** in `open_prep/technical_analysis.py`:
  three observe-only features from daily bars — `trend_alignment`
  (EMA20>50>200 ordinal +1/0/−1), `dist_to_ema20_pct` (pullback depth vs.
  EMA20, uses live price when available), `ema50_slope_pct` (5-bar EMA50
  slope). Fail-closed: each feature is `None` below its bar minimum
  (20/55/200).
- **Pipeline**: stamped onto ranked v2 rows in the breakout-enrichment loop
  (`open_prep/run_open_prep.py`); daily-bars lookback widened 120→320
  calendar days (≈220 trading days) so the EMA-200 is computable.
  Breakout/consolidation detection slice their own shorter windows and are
  unaffected.
- **Outcome records**: `prepare_outcome_snapshot()` and `FEATURE_KEYS`
  carry the three keys; new `PASS_THROUGH_FEATURE_KEYS` SSOT
  (`open_prep/outcomes.py`) marks them — together with
  `zone_priority_score` — as intentionally unweighted (absent from
  `FEATURE_TO_WEIGHT_KEY` and scorer `DEFAULT_WEIGHTS`; enforced by
  `tests/test_scorer_tuning.py` + `tests/test_trend_state_features.py`).
  Promotion to a weighted component requires FI evidence from ≥ ~200
  labeled outcomes first.
- **Pine**: `ZLEMA (Zero Lag Exponential)` added to `SmcLibMovingAverage`
  (`SMC++/smc_core_types.pine`) and `smc_lib_get_ma`/`smc_lib_zlema`
  (`SMC++/smc_utils.pine`) so SMC++ studies can select it; no default or
  strategy change.

### Added (2026-06-11) — Per-TF structure artifacts in the rolling benchmark (#2667)

Un-voids Plan 2.8 Phase-E2 (see ADR "2026-06-10 - Plan 2.8 Phase-E2
verdicts void — cross-TF structure aliasing" in docs/DECISIONS.md):

- **Workflow**: `smc-measurement-benchmark-rolling.yml` gained an
  "Export per-TF structure artifacts" step that runs
  `scripts/export_smc_structure_artifacts_from_workbook.py` for every
  benchmark timeframe (default `5m,15m,1H,4H`) against the restored
  Databento export bundle BEFORE the benchmark, writing
  `reports/smc_structure_artifacts/manifest_<tf>.json` +
  `<SYMBOL>_<tf>.structure.json` — the provider resolves these ahead
  of the legacy single-file 1D artifact, so each chart TF scores its
  own structural events. The step also becomes the single source of
  truth for the validated SYMBOLS/TIMEFRAMES (published via
  `GITHUB_ENV`; the benchmark step consumes them instead of
  re-deriving its own copy).
- **Exporter CLI**: `--export-bundle-root` flag on
  `scripts/export_smc_structure_artifacts_from_workbook.py` — without
  it the always-explicit `--workbook` suppressed bundle
  auto-discovery, making intraday timeframes impossible to export
  from CI (`WorkbookFallbackTimeframeError` per symbol).
- **Disclosure**: `build_measurement_evidence` now propagates
  contract-level warnings (notably `legacy_tf_fallback`) into the
  evidence warning stream; `benchmark_run_manifest.json` carries a
  `structure_tf_integrity` block listing every pair served via the
  legacy cross-TF fallback.
- **Strict mode**: new `--strict-structure-tf` flag on
  `scripts/run_smc_measurement_benchmark.py` fails the run (exit 1)
  when any pair was served aliased structure. Default is warn-only so
  the rolling lane cannot hard-fail while per-TF artifacts roll out;
  FOLLOW-UP: flip the default (pass the flag in the rolling workflow)
  once the rollup reports `measured` / `insufficient_data` instead of
  `degenerate_aliased_input` and the benchmark logs are free of
  `legacy_tf_fallback` warnings.
- Pins: tests/test_per_tf_structure_artifact_wiring.py.

### Fixed (2026-06-11) — Outcome backfill: defer unpublished Databento windows

The late-evening scheduled `open-prep-outcome-backfill` run (GH run
27313823758) exited 2 because Databento's historical API had not yet
published the day's 1-minute bars (HTTP 422
`data_start_after_available_end`) and all pending symbols were counted
as `failed`. That condition is transient — the next scheduled run picks
the date up naturally — so it is now classified as **deferred** instead
of failed:

- `open_prep/outcome_backfill.py`: `_fetch_bars` detects the
  `data_start_after_available_end` error substring and returns a
  `DATA_NOT_YET_PUBLISHED` sentinel; `backfill_outcomes` counts the
  affected pending symbols in a new `deferred` summary field and leaves
  the records unresolved for retry; `main()` exits 0 for deferred-only
  runs (exit 2 is preserved for genuine zero-progress failures), and
  deferrals count as progress for the `--require-progress` tripwire.
- Run log (`artifacts/open_prep/outcome_backfill/*.json`) gains a
  `deferred` count and a `deferred` status (with `failed` taking
  precedence when both occur).
- Tests: sentinel detection, defer-not-fail classification, exit-code
  semantics, run-log status — `tests/test_outcome_backfill.py`,
  `tests/test_outcome_backfill_automation.py`.

### Fixed (2026-06-10) — Stat-review second pass S1–S5 (#2674)

Implements the senior-quant stat-review second-pass findings:

- **S1 — `watchdog_status_not_red` promotion criterion**: the watchdog
  stack (green/yellow/red via 4-detector consensus in
  `scripts/drift_alert.py`) and the incubation drift stack
  (pass/acceptable/… via drift_score) were unreconciled — a variant
  with stable mean PnL but blown-out tails could machine-pass Phase-A
  while the watchdog stood RED. New `extra` criterion in
  PHASE_A/B_CRITERIA + fail-closed checker in
  `scripts/evaluate_phase_criteria.py` reading
  `watchdog_report["aggregate_severity"]` (missing report ⇒ not
  passed). Runbook §Phase-A/§Phase-B updated.
- **S2 — TF-rollup power honesty**: `scripts/plan_2_8_tf_family_rollup.py`
  Phase-E2 comparisons now carry a Wald 95 % CI on Δhit-rate, a
  two-proportion z-test p-value and the 80 %-power MDE; comparisons
  whose observed |Δ| is below the MDE are labelled
  `measured_underpowered` instead of `measured`.
- **S3 — horizon-truncation refusal**: `governance/family_returns.py`
  immediate-mode windows shorter than the family outcome horizon are
  refused (`None`) instead of silently clamping the exit to the last
  available bar (which mislabelled 3-bar returns as 8-bar BOS
  outcomes); degenerate embargo intervals (`embargo_bars > 0` with a
  non-positive event-bar interval) likewise refuse instead of
  embargoing nothing.
- **S4 — trade-clock Sharpe**: `scripts/track_record_gate.py` accepts
  `trades_per_year` and rescales the Sharpe CI to the observed trade
  frequency instead of unconditionally annualising per-trade returns
  at `freq=252` (daily-bar assumption); the gate detail string now
  discloses which clock was used. `scripts/build_track_record_gate.py`
  forwards `trades_per_year` from the returns payload when present.
- **S5 — synthetic slippage reference honesty**:
  `scripts/compute_live_drift.py` placeholder defaults
  (mean 0.005 / std 0.003) are now explicitly documented as uncited
  placeholders, and the Phase-A `slippage_ks_pvalue_gt_0.05` checker
  scores as not machine-evaluable (`passed: null`) when the KS
  reference is `synthetic_normal`.

### Added (2026-06-10) — Stat-review F1/F6/F10 + runbook/ADR honesty (F2, F5, F11, F13)

Implements the 2026-06-10 promotion-chain statistical-validity review
findings that do not collide with in-flight PRs:

- **F1/F6 — `scripts/evaluate_phase_criteria.py` (new)**: the
  `PhasePassCriteria` dataclasses in `run_smc_live_incubation.py` were
  evaluated by no code anywhere; every `extra` criterion string was
  unenforced prose. The new fail-closed evaluator machine-checks every
  numeric field and every `extra` string (via the `_EXTRA_CHECKERS`
  registry) against the drift artifact, incubation audit JSONL and
  watchdog report. Criteria it cannot verify count as **not passed**;
  the Phase-C Scale-Phase/Kelly marker never machine-passes by design,
  making `live_full` structurally unreachable via the evaluator. A
  structural test asserts every `extra` string has a registered checker
  — an unmapped string is now a test failure, not a silent gate hole.
  `run_smc_live_incubation --phase live_small/live_full` now requires
  `--phase-eval-report` with a fresh (≤ 7 days) **passing** evaluation
  of the prior phase. Promotion remains manual sign-off only.
- **F10 — watchdog per-setup honesty**: `run_drift_watchdog` pooled all
  setups into one `pnl_per_trade` metric against a pooled baseline,
  which can mask per-setup drift (Simpson-style). `extract_metric_pairs`
  now emits `pnl_per_trade[setup=<name>]` metrics when live outcomes
  carry a `setup_type` attribution and the baseline has the matching
  `per_setup` block; reports without attribution disclose the pooling
  limitation explicitly (`per_setup_live_attribution`, `pooling_note`).
- **F2/F5/F11 — C8 runbook**: Phase-B's `window_complete` criterion now
  names which watchdog report it refers to (the incubation outcome
  stream, not the default open_prep directory); Phase-A carries a
  statistical-power caveat (at n = 20 the drift_score is noise-dominated
  — ~43 % false-pass / ~53 % true-pass at the 0.70 line); a new
  sequential-looks section requires sign-off to read the verdict history
  over the whole phase, not a cherry-picked day.
- **F13 — ADR-0008 §12/§13**: `compute_live_drift._VERDICT_BANDS`
  (0.85/0.65/0.40) and the phase drift-score lines (0.70 Phase-A,
  0.50 Phase-B) are now documented as operator-judgment (**O**)
  thresholds with the standard 100-promotions/6-month recalibration
  cadence.

### Added (2026-06-10) — Stat-review wave 2: cadence disclosure, E2 p-value, rollup malformed-row honesty, KS twin alignment (F7, F8, F9, F12)

Second wave of the 2026-06-10 promotion-chain statistical-validity
review (first wave: F1/F2/F5/F6/F10/F11/F13; F3 = PR #2671, F4 =
PR #2666):

- **F7 — `scripts/compute_live_drift.py`**: drift schema **1.2.0 →
  1.3.0** (additive; `DRIFT_SCHEMA_MIN_COMPATIBLE` stays 1.0.0). The
  √252 Sharpe annualisation is applied to *per-trade* returns on both
  sides, so `drift_score` moves when live cadence differs from backtest
  cadence even at identical per-trade edge — likely in incubation
  (fewer symbols, earnings filter, size caps). New per-variant fields
  `trades_per_year_live` (from the trade count over the live window)
  and `trades_per_year_backtest` (from the reference's
  `trades_per_year`, or `n_trades`+`window_days`; `null` when absent)
  disclose the confound to the operator.
- **F8 — `scripts/plan_2_8_tf_family_rollup.py`**: at the `n ≥ 30`
  verdict floor, SE(Δhr) is ~12.9 pp — a 5 pp delta at the floor is
  indistinguishable from noise but carried the same `"measured"` label
  as a 30 pp delta at n = 500. Phase-E2 `measured` verdicts now carry
  `delta_hr_p_value`, a two-sided pooled two-proportion z-test p-value
  (self-contained `math.erfc`-based implementation in the rollup script;
  correction 2026-06-11, Copilot #2675 — this entry previously claimed
  the `run_ab_comparison` helper was reused, which it is not);
  `null` when the pooled variance is degenerate. Vocabulary additive.
- **F9 — `scripts/plan_2_8_tf_family_rollup.py`**: the
  `int(payload.get("n_events") or 0)` / `float(... or 0.0)` pattern
  laundered `hit_rate: null` into 0.0 — an artifact with
  `n_events: 40, hit_rate: null` contributed 40 events at 0.0 HR and
  silently dragged the family aggregate down (kills a good variant).
  Rows with missing/non-numeric `n_events`/`hit_rate` (file-level and
  per-family) and unreadable files are now skipped and counted:
  new manifest fields `n_skipped_malformed` + `skipped_malformed`.
- **F12 — `scripts/compute_live_drift.py`**: `ks_two_sample` returned
  `(0.0, 1.0)` ("perfectly compatible") on empty input while its twin
  `drift_alert.ks_two_sample` returns `(0.0, None)` ("not evaluable").
  Currently unreachable (callers guard non-empty) but one refactor away
  from a p = 1.0 laundering. Aligned on `(0.0, None)`; a test pins both
  twins to the same convention.

### Changed (2026-06-10) — silent-fallback audit: drift verdicts, 1D resample, source-matrix honesty

Four silent-fallback / misdeclaration fixes from the static review of
`compute_live_drift.py`, `explicit_structure_from_bars.py`,
`repo_sources.py` and `provider_matrix.py`:

- **`scripts/compute_live_drift.py`** — drift schema **1.1.0 → 1.2.0**
  (additive; `DRIFT_SCHEMA_MIN_COMPATIBLE` stays 1.0.0). A missing or
  non-numeric backtest reference no longer collapses to `sharpe=0.0`
  (which the `max(backtest, 0.001)` denominator clamp turned into
  drift-score 1.5 → verdict `pass` for an unreferenced variant): new
  explicit verdicts `missing_backtest_reference` and
  `non_positive_backtest_sharpe`. Reference-only variants with zero
  live trades in the window are now emitted as `no_live_data` rows
  instead of vanishing. All three fail closed against the
  `run_smc_live_incubation` pass/acceptable allowlist. New additive
  boolean `overperformance_capped` marks variants whose raw live/backtest
  ratio exceeded the 1.5 cap (live ≫ backtest is frequently a data
  defect, previously indistinguishable from a healthy pass).
- **`scripts/explicit_structure_from_bars.py`** — the `1D` branch of
  `resample_bars_to_timeframe` was an unconditional identity pass-through
  that silently served intraday bars as "1D" (mirror image of the
  PR #2666 cross-TF aliasing). It now aggregates to calendar days via the
  generic bucket path (with a warning) whenever any symbol has >1 row per
  calendar day; genuinely daily input keeps the identity regardless of
  stamp time. The legacy high/low liquidity-sweep fallback now logs a
  warning when the profile engine produced no sweeps.
- **`smc_integration/repo_sources.py`** — `_can_supply_domain` derives
  technical/news membership from `_DOMAIN_SOURCE_ORDER` (single source of
  truth) instead of hand-duplicated name sets; the structure auto-select
  loop warns when a lower-priority source is served after higher-priority
  failures; production-dead `_source_priority_key` removed;
  `volume_domain_status` is set explicitly in the mandatory-volume
  fallback branch.
- **`smc_integration/provider_matrix.py`** — `live_news_snapshot_json`
  (the PRIMARY runtime news source) and `largecap_watchlist_json` now have
  explicit potential/current/known-gaps declarations instead of falling
  through to misdeclaring generic defaults; databento
  `snapshot_structure_mode` corrected `partial` → `none` (its mapped
  structure arrays are empty); `_pick_best_candidate` ranks by the
  authoritative `_DOMAIN_SOURCE_ORDER` runtime fallback order instead of
  alphabetically — `best_current_news_candidate` is now
  `live_news_snapshot_json`.

### Added (2026-06-04) — ADR-0019: order-flow imbalance shadow feature (recorded-only)

New ADR-0019 order-flow candidate on the aggressor-signed data path:
**order-flow imbalance** (`governance/family_ofi_imbalance_v2.ofi_imbalance_at`),
`abs(sum(signed_volume)) / sum(abs_volume)` in `[0, 1]` over the trailing
`ATR_PERIOD` window ending at the anchor — the net one-sidedness of aggressor
flow. This is the *direction* axis of order flow, orthogonal to turnover
*magnitude* (`relative_volume`), price *impact* slope (Kyle's lambda) and
*participant size* (`average_trade_size`): a deep book absorbs very one-sided
flow at low lambda, a thin book shows high lambda at modest imbalance. It is a
*simplified bar-level imbalance*, **not** canonical VPIN (VPIN buckets on
equal-volume bars with bulk-volume classification; here the aggressor side is
known per trade). To supply the honest denominator the producer
(`scripts/pull_databento_edge_input.aggregate_signed_volume`) now also embeds
per-bar `abs_volume` (the sum of all trade sizes, an unsigned magnitude)
alongside `signed_volume` + `trade_count`; the OHLCV `volume` (a different
source) is *not* used as the denominator (extended-hours mismatch). Strictly
point-in-time, leak-free and honest-None (returns `None` rather than fabricating
when `signed_volume`/`abs_volume` are absent or the window carries no traded
size); the ratio is clamped to `[0, 1]`. Recorded onto both zone and level
family events via `family_event_adapter`; **RECORDED-ONLY** — it does not feed
the v1 score or any gate. Pending its pre-registered purged walk-forward A/B
verdict (which requires a fresh EV-20 `with_trades` run carrying `abs_volume`).

### Added (2026-06-04) — ADR-0019: average trade size shadow feature (recorded-only)

New ADR-0019 order-flow candidate on the live aggressor-signed data path:
**average trade size** (`governance/family_avg_trade_size_v2.average_trade_size_at`),
the volume-weighted mean shares-per-trade `sum(volume) / sum(trade_count)` over
the trailing `ATR_PERIOD` window ending at the anchor. This is the
*participant-size* axis of order flow (institutional-footprint / block-trade
proxy), orthogonal to the magnitude axis (`relative_volume`) and the
direction/impact axis (`signed_volume` / Kyle's lambda). Because
`volume = trade_count * avg_size` is an identity, `trade_count` alone is *not* a
separate candidate — only the economically meaningful average size is taken
(one new degree of freedom). The producer already embeds `trade_count`
per-bar alongside `signed_volume`. Strictly point-in-time, leak-free and
honest-None (returns `None` rather than fabricating when volume/trade_count are
absent or the window's total count is zero). Recorded onto both zone and level
family events via `family_event_adapter`; **RECORDED-ONLY** — it does not feed
the v1 score or any gate. Pending its pre-registered purged walk-forward A/B
verdict before any wiring is considered.

The Lo & MacKinlay (1988) Variance Ratio `VR(2)` — the strongest close-only
proxy for the *persistence / serial-dependence* axis — was evaluated as the next
ADR-0019 shadow candidate. Because it is close-only (no live plumbing needed),
its pre-registered purged walk-forward A/B was run pre-merge on the same harness
and the same REAL Databento data as the WVF/ribbon candidates (two regimes,
~22k events, 99.6% coverage; confirmed orthogonal beforehand, VR vs `score`
Spearman −0.173). It returned `no_lift` across **all four** families (BOS, FVG,
OB, SWEEP), so it was **not merged** — no dead shadow code is carried. Together
with the already-zeroed `hurst_50` weight this closes the persistence axis.
Recorded in `docs/governance/resolution_feature_gap_analysis.md` §5, which
confirms the un-tapped lever is order-flow/volume and names the producer
volume-plumbing as the next workstream.

### Fixed (2026-06-03) — ADR-0019: EV-20 producer now carries `open` + `volume` per bar

The real-data edge-input producer
(`scripts/pull_databento_edge_input._resampled_bars_payload`) emitted only
`timestamp/high/low/close` per resampled bar, silently dropping the `open`
(first) and `volume` (sum) columns the resampler already aggregates. That
starved every ADR-0019 order-flow candidate of its only input:
`governance.family_score_features_v2.relative_volume_at` (and the planned
Amihud illiquidity proxy) honestly returned `None` on every bar, so the
order-flow axis could never be A/B-tested on real data — the one axis the
resolution feature-gap analysis pins as the largest un-tapped signal.

- `_resampled_bars_payload` now emits the full OHLCV bar
  (`open/high/low/close/volume`), still byte-aligned with
  `_prepare_symbol_resampled_bars` so the pipeline's anchor/lookahead
  arithmetic is unchanged.
- Extended `tests/test_pull_databento_edge_input.py` to assert the bar key set
  is `{timestamp, open, high, low, close, volume}` and that the emitted `open`
  and `volume` match the resampled frame exactly.
- Point-in-time and leak-free by construction (volume is the bar's own
  aggregate). Unblocks the pre-registered `relative_volume` A/B; the v1
  `score`, `SCORE_SOURCE`, and the promotion gate are untouched.

### Removed (2026-06-03) — ADR-0019: retire the Williams VIX Fix candidate (no lift)

The `williams_vix_fix` candidate (Larry Williams' public-domain "VIX Fix", a
price-only downside-deviation fear gauge,
`(max(close[anchor-21..anchor]) - low[anchor]) / max(close) * 100`) was
A/B-tested against the v1 `score` on REAL Databento data over two independent
regimes via the paired purged walk-forward harness: a calm window
(2025-01-02..2025-04-01) and a volatile one (2024-07-15..2024-10-15). Over
22,114 recorded events it returned `no_lift` across **all four** families (BOS,
FVG, OB, SWEEP) — out-of-sample resolution did not improve and the candidate
discriminated worse than baseline in every family (e.g. BOS AUC 0.524 vs 0.567,
FVG 0.510 vs 0.558, SWEEP 0.473 vs 0.527). Per the pre-registered ADR-0019 gate,
a candidate that fails to lift resolution is retired rather than carried as dead
shadow code.

- Deleted `governance/family_vix_fix_v1.py` and `tests/test_family_vix_fix_v1.py`.
- `governance/family_event_adapter` no longer records `williams_vix_fix`; the
  optional `FamilyEvent.williams_vix_fix` field is removed.
- The generic A/B on-ramp `scripts/run_feature_ab` is kept (reusable for the
  next OHLC-pure candidate); default `--feature-key` stays `relative_volume`.
- No change to the v1 `score`, `SCORE_SOURCE`, the promotion gate, or the
  generic harness (`family_returns` / `family_calibration` / `family_feature_ab`).

### Removed (2026-06-03) — ADR-0019: retire the momentum-ribbon candidate (no lift)

The `momentum_ribbon` candidate (the smoothed-RSI "USI" multi-length stack
score) was A/B-tested against the v1 `score` on REAL Databento data over two
independent regimes via the paired purged walk-forward harness: a calm window
(2025-01-02..2025-04-01) and a volatile one (2024-07-15..2024-10-15). Both
returned `no_lift` across **all four** families (BOS, FVG, OB, SWEEP) — the
candidate did not improve out-of-sample resolution and in the two cash-bearing
families (BOS, FVG) discriminated slightly worse than the baseline. Per the
pre-registered ADR-0019 gate, a candidate that fails to lift resolution is
retired; it is removed rather than carried as dead shadow code.

- Deleted `governance/family_momentum_ribbon_v2.py` and its tests.
- Deleted `docs/governance/momentum_ribbon_v2_shadow_candidate.md`.
- `governance/family_event_adapter` no longer records `momentum_ribbon`; the
  optional `FamilyEvent.momentum_ribbon` field is removed.
- The generic A/B on-ramp `scripts/run_feature_ab` is kept (reusable for the
  next candidate) but its default `--feature-key` is now `relative_volume`;
  `tests/test_run_feature_ab.py` exercises the driver against that feature.
- No change to the v1 `score`, `SCORE_SOURCE`, the promotion gate, or the
  generic harness (`family_returns` / `family_calibration` / `family_feature_ab`).

### Added (2026-06-02) — ADR-0019 step 3: paired purged walk-forward A/B harness

Builds on steps 1-2 (the extractor + the recorded feature). Adds the shadow
measurement that answers the pre-registered ADR-0019 question: over a purged
walk-forward, does the candidate feature discriminate event outcomes better
than the v1 `score`? Primary metric is out-of-sample **resolution** (the Murphy
discrimination component) — the binding promotion deficit. Changes **no** score,
`SCORE_SOURCE`, or gate; v1 stays the default until the A/B clears on real data.

- New `governance/family_calibration.walk_forward_ab`: a PAIRED purged
  walk-forward that Platt-calibrates both arms (v1 `score` vs v2 feature) on the
  same training events over identical folds, emitting a fold only when both arms
  fit — so the two arms share one out-of-sample index set and their Brier /
  resolution are directly comparable (an unpaired comparison would confound the
  feature with a differing event sample).
- New `governance/family_returns.extract_family_ab_samples`: per family, the
  paired `(scores, features, returns, anchor_ts, guard_end_ts)` for events
  carrying both arms, reusing the calibration purge guard so the A/B is
  leak-safe by construction.
- New module `governance/family_feature_ab`: the `resolution` metric plus
  `family_feature_ab` / `family_feature_ab_report`, which return a shadow
  verdict (`candidate_lifts_resolution` / `no_lift` / `regresses_calibration`).
  A family with too few shared OOS points is not measurable yet: `family_feature_ab`
  returns `None` and `family_feature_ab_report` omits it (never silently scored).
  No-regression guards are a Brier proper-scoring check
  plus an **absolute** ECE ceiling (deliberately not relative to the baseline —
  a near-constant baseline trivially wins ECE and would perversely veto a sharp,
  discriminating candidate).
- Scope: this step compares feature-alone vs score-alone. The incremental
  question (does the feature add resolution on top of the score) is the next
  step.
- 13 new tests (`tests/test_family_feature_ab.py`); calibration / returns /
  adapter suites stay green.

### Fixed (2026-06-02) — f2 bootstrap PR title fails the ADR-0013 title lint

The `workflow_dispatch` regeneration workflow
`f2-frozen-artifact-bootstrap.yml` opened its PR with a `data(f2): …`
title, but `data` is not in `ACCEPTED_CONCERNS`
(`scripts/check_pr_title_concern.py`), so every recalibration PR would
have been blocked by `pr-title-concern-lint`. Switched the commit message
and PR title to the `chore(f2)` concern (matching how
`edge-pipeline-real-run.yml` already uses `chore(ev-20)` for the same
artifact-regeneration class). Root fix on the generator — the governance
lint is unchanged.

- `f2-frozen-artifact-bootstrap.yml`: `git commit -m` and `gh pr create
  --title` now use `chore(f2): …`.
- Contract test `test_pr_creation_uses_canonical_gh_pat_pattern_and_label`
  updated in lockstep to pin the `chore(f2)` title.
- Historical recipe in `docs/f2_contextual_promotion_decision_2026-04-21.md`
  updated to match.

### Added (2026-06-02) — fractional differentiation feature transform

Standalone, pure-numpy fixed-width fractional differentiation (López de Prado
2018, ch. 5) as a candidate feature transform. Stationary-but-memory-
preserving inputs are the one transform class that can plausibly add
*discrimination* (the binding promotion blocker), so this is wired to be
graded by the ADR-0019 A/B harness as just another `feature_key` — it earns
its place only on a `candidate_lifts_resolution` verdict, never by assertion.

- New `ml/features/frac_diff` with `ffd_weights` (binomial-recursion weights,
  threshold-truncated to a fixed window) and `frac_diff_ffd` (window
  convolution; `nan` warm-up region, `d=0` identity, `d=1` ≈ first difference).
- Re-exported from `ml/features/__init__`.
- 8 property tests pin the weight recursion, the identity/first-difference
  edge cases, the warm-up masking, and that fractional differencing reduces
  random-walk lag-1 autocorrelation (`tests/test_frac_diff.py`).
- No change to `SCORE_SOURCE`, the v1 score, or any gate.

### Added (2026-06-02) — ADR-0019 step 2: record the order-flow feature for the A/B

Builds on step 1 (the `relative_volume_at` extractor). Captures the candidate
feature on every real event and pairs it with outcomes, so the pre-registered
purged walk-forward A/B (ADR-0019) has the per-event `(feature, outcome)` data
it needs — still **without** touching the v1 score, `SCORE_SOURCE`, or the gate.

- `governance/family_event_adapter` now records an optional `relative_volume`
  on each `FamilyEvent` (mirroring how `score` / `regime` are attached),
  computed leak-free from the trailing bars and omitted when volume is absent.
- New optional `FamilyEvent` field `relative_volume` (recorded only — not a
  calibration input, not a gate input).
- New pure `governance/family_returns.extract_family_feature_samples`: per
  family, collects the recorded feature paired with the binary sign-of-return
  `outcomes` label (the same target `family_calibration` grades the v1 score
  on) plus `anchor_ts`. Measurement groundwork for the A/B; it does not
  calibrate, score, or gate anything.
- 5 new tests pin the recording and extraction semantics
  (`tests/test_family_relative_volume_recording.py`); existing adapter/score
  suites stay green.

### Added (2026-06-02) — ADR-0019 step 1: point-in-time order-flow extractor (family score v2)

The verified resolution feature-gap analysis
(`docs/governance/resolution_feature_gap_analysis.md`) found the v1 per-family
score is pure geometry and that the largest un-tapped resolution lever is
**order-flow / volume** — available in the data but dropped at the governance
boundary. This lands the first ADR-0019 v2 candidate feature as a pure,
leak-free extractor, **without** touching the v1 score or the promotion gate
(ADR-0019 mandates a shadow-first, pre-registered purged walk-forward A/B
before any v2 feature may join calibration).

- New `governance/family_score_features_v2.relative_volume_at`: the formation
  (anchor) bar's volume divided by its trailing `ATR_PERIOD`-bar mean volume —
  an institutional-footprint proxy from ADR-0019's tier-1 hierarchy that needs
  no trade-side data. Strictly point-in-time (baseline reads only bars before
  the anchor), with honest omitted-not-zero-filled semantics
  (`RELATIVE_VOLUME_SOURCE = "orderflow_relative_volume_v2"`).
- `governance/family_event_adapter.BarRow` gains an optional `volume` field
  (additive, `total=False`): bars without it stay fully supported and the v2
  feature is simply reported as absent. No v1 score, regime, or gate behaviour
  changes.
- 11 new tests pin the ratio, leak-freedom, and absent-feature semantics
  (`tests/test_family_score_features_v2.py`); the existing adapter/score
  suites stay green.

### Added (2026-06-02) — ADR-0016 pipeline-provenance classes (no-ML pipelines)

Under `strict_provenance` the gate required three caller-declared provenance
keys that describe an upstream ML-modelling layer — `bootstrap_method` (BCa
bootstrap), `block_size` (block permutation) and `stacked_used` (stacking
ensemble). The SMC-direct edge pipeline performs no such modelling (returns
come straight from events, scores are raw event scores, no ensemble), so those
three keys describe work that does not exist; declaring them would fabricate
evidence. The gate therefore held a legitimate no-ML pipeline permanently at
ADR-0015 tier-1 `inconclusive` on three guards that are *not-applicable*, not
*unmeasured* (ADR-0016).

- `governance/promotion_gate` adds a `pipeline_class` provenance key and
  recognised no-ML classes (`NO_ML_PIPELINE_CLASSES`, initially
  `smc_direct_no_ml`). When a family declares such a class the three
  `ML_MODELLING_PROVENANCE_KEYS` are treated as not-applicable: their absence
  emits no blocker and does not fail `ok_provenance`.
- The waiver is conditional, never a global relaxation: an absent or unknown
  `pipeline_class` grants no waiver, and the pipeline-agnostic keys
  (`wf_scheme`, `wf_embargo_bars`, `psr_method`) stay required for every class.
  `conformal_coverage` is unchanged — it is computed on the OOS pairs and
  remains an applicable, measured guard.
- `governance/family_returns.to_build_spec` declares
  `pipeline_class = "smc_direct_no_ml"` on every family it builds, so the
  classification flows end-to-end into the gate snapshot.
- New tests pin the waiver, the unknown-class non-waiver, the
  pipeline-agnostic keys staying required, conformal staying required, and the
  producer declaration (`tests/test_promotion_gate.py`,
  `tests/test_family_returns.py`). See `docs/adr/0016-pipeline-provenance-classes.md`.

### Added (2026-06-02) — ADR-0018 split-conformal coverage from walk-forward OOS

The promotion gate's `conformal_coverage` check could never evaluate: the
SMC-direct producer never emitted a `conformal` block, so coverage was always
"not yet measured" and the guard held every family at ADR-0015 tier-1
`inconclusive` (see ADR-0018).

- `governance/family_calibration.partition_conformal` splits the pooled
  chronological walk-forward OOS pairs at `CONFORMAL_CALIBRATION_FRACTION`
  (0.5): the earlier half calibrates the split-conformal (Vovk) conformity
  quantile, the held-out later half measures empirical marginal coverage
  against the `1 - alpha` guarantee (`CONFORMAL_ALPHA` = 0.1 -> 90% target).
- The block is emitted ONLY when both sides clear `CONFORMAL_MIN_SIDE`
  (= `MIN_OOS_SAMPLES`, 40), i.e. the pool holds at least 80 OOS pairs. Below
  that no block is emitted and `conformal_coverage` stays honestly unmeasured.
- `governance/family_returns.to_build_spec` computes the conformal split from
  the full pooled block (independent view of the ADR-0017 live surrogate) and
  tags it with audit-only provenance `ev26_conformal_source`. The producer's
  existing `_conformal_slice` then measures `conformal_coverage` /
  `conformal_target`, enabling the gate check to evaluate.
- Honesty preserved: a low-resolution score yields wide prediction sets, so
  coverage is high by design (certifies set calibration, NOT discrimination).
  A family can clear `conformal_coverage` and still fail the tier-2 Brier bar;
  this removes only the "not yet measured" info-block and never promotes a
  family on its own.

### Added (2026-06-02) — ADR-0017 live-incubation surrogate for `live_vs_wf_ratio`

In an offline backtest there is no real live feed, so `live_brier` was always
"not yet measured" and the `live_vs_wf_ratio` drift check could never evaluate
— it info-blocked every family indefinitely (see ADR-0017).

- `governance/family_calibration.partition_live_tail` splits a pooled
  walk-forward block into `{walkforward (older remainder), live (most-recent
  tail)}`. The pooled out-of-sample pairs are chronological, so the last
  `LIVE_TAIL_MIN_SAMPLES` (= 20) pairs are DECLARED the live-incubation
  surrogate; the older remainder is the walk-forward reference.
- The split is emitted ONLY when the pool stays adequately powered on both
  sides (`len >= LIVE_TAIL_MIN_SAMPLES + MIN_OOS_SAMPLES`). Below that the full
  pooled block is kept and `live_brier` stays honestly unmeasured rather than
  splitting a small sample into two noisy halves.
- `governance/family_returns.to_build_spec` wires the split in after
  `walk_forward_calibration` and tags it with audit-only provenance
  `ev25_live_source` (`LIVE_SOURCE_TAG`). The producer's existing `live`
  consumer (`scripts/build_family_metrics._calibration_slice`) then measures
  `live_brier`, enabling the `live_vs_wf_ratio` gate check to evaluate.
- Honesty preserved: the live tail is intentionally small, so the resulting
  ratio is a coarse drift alarm, not a precise threshold; it removes only the
  "not yet measured" info-block and never promotes a family on its own.

### Changed (2026-06-02) — EV-08 verdict adopts the ADR-0015 two-tier taxonomy (`risk_sizeable`)

`governance/family_verdict` previously fused "has an edge" with "is calibrated
for sizing": a family the gate blocked solely on the calibration checks
(`brier_threshold` / `brier_ci_upper` / `ece_threshold`) was reported as
`no_edge`, letting a documented `sign_return_secondary_diagnostic` veto the
primary PSR edge proof (see ADR-0015).

- `edge_supported` (tier 1) is now keyed on the **edge** evidence only —
  primary metric measured, sample adequate, no edge-failure blocker, and the
  integrity/provenance guards measured and clear. Calibration blockers no
  longer gate it.
- New boolean field `risk_sizeable` (tier 2, strictly stronger) is tier 1
  **plus** the calibration checks cleared — i.e. the gate's full `promoted`
  decision on a measured, adequately-powered family. `build_verdict_report`
  gains a top-level `risk_sizeable_count`.
- Honesty preserved: when the edge metrics are strong but an integrity guard
  is merely *unmeasured* (strict-provenance `info`), the verdict is
  `inconclusive` — never an over-claimed `no_edge`. No threshold is changed;
  the calibration checks are mapped to the tier they evidence (sizing).
- 6 new tests pin the tier mapping (`tests/test_family_verdict.py`); the
  `tests/test_verdict_panel.py` end-to-end fixture now carries a realistic
  `psr_minimum` edge blocker for its `no_edge` assertion.

### Added (2026-06-02) — EV-20 time-basis diagnostic: observed events-per-year cadence

The per-family return series the edge pipeline scores is **event-driven** (one
return per SMC event), but the producer annualized its Sharpe/MinTRL against the
caller-declared `periods_per_year` (default `252`, a *daily-bar* basis). When the
true event cadence is several hundred per year, any annualized Sharpe read off a
`252` basis stands on the wrong time-basis — not investor-grade (EV-20 audit).

- `governance/point_in_time.py` adds `observed_span_seconds(timestamps)`: the
  `max - min` span of a timestamp series in seconds (absolute offset cancels, so
  naive/aware both yield a correct span), `None` for fewer than two timestamps or
  a collapsed span.
- `scripts/build_family_metrics.py` — `build_family_metrics_from_returns` now
  derives the **realized** events-per-year from the supplied event-timestamp span
  and surfaces it as `extras.observed_periods_per_year` (omitted when timestamps
  are absent or the span collapses). Purely diagnostic: the declared
  `periods_per_year` and the gate's MinTRL arithmetic are **unchanged**, so any
  annualized Sharpe in the decision JSON can now be re-annualized on its true
  cadence without touching promotion semantics.

### Added (2026-06-02) — promotion-gate archives carry per-symbol run context (REPORT_SCHEMA_VERSION 2)

The `edge-pipeline-real-run` workflow archives one promotion-decisions report
**per symbol** into `governance/promotion_decisions/`, but neither the filename
nor the payload recorded *which* symbol/dataset/schema/window produced it. That
made the governance archive hard to audit and caused
`scripts/build_promotion_gate_dashboard.py` (which scans **all**
`governance/promotion_decisions/*.json`) to aggregate heterogeneous symbol runs
together with no way to filter — and two symbols archiving in the same second
could collide on the timestamp-only filename.

- `governance/promotion_report.py` bumps `REPORT_SCHEMA_VERSION` to `2`: reports
  may now carry an optional top-level `context` object (symbol/dataset/schema/
  timeframe/window). The key is **omitted** on context-less runs, so the loader
  contract ("dict with a `decisions` list") is unchanged.
- `scripts/run_promotion_gate.py` — `build_report(..., context=...)` embeds the
  run context only when supplied; new `_label_slug()` helper and
  `_archive_report(..., label=...)` slug the symbol into the filename
  (`promotion_decisions_<LABEL>_<stamp>.json`) so per-symbol runs are
  self-describing and can't overwrite each other within the same second. The
  shared `promotion_decisions_*.json` consumer glob still matches.
- `scripts/run_edge_pipeline.py` threads the input payload's `provenance` into
  the report `context` and uses its `symbol` as the archive label.
- `scripts/pull_databento_edge_input.py` records `dataset`, `schema` and the
  fetch `window` (start/end) in the payload provenance alongside the symbol, so
  the downstream archive is fully self-describing. Non-CLI callers that omit the
  window get explicit `None` placeholders.

### Added (2026-06-02) — EV#7: regime-conditional degradation (C5.1 `regime_degraded`)

The promotion gate's C5.1 regime-degradation slot was consumed by the gate
but always reported "not yet measured" because the family-event path carried
no per-event regime label. EV#7 now derives one **from the same bars the
event already reads** — no external macro/VIX data, no fabrication — and
emits a measured, monotonic (block-only) `regime_degraded` verdict. See
`docs/adr/0014-ev6-psi-trend-source-and-ev7-regime-deferral.md`.

- `governance/family_event_score.point_in_time_regime(...)` labels each
  anchor with the Kaufman **Efficiency Ratio** over the trailing
  `REGIME_WINDOW = ATR_PERIOD` closes ending at the anchor (same leak-free
  trailing read as `atr_at`): `TRENDING` (ER ≥ 0.5), `RANGING` (ER ≤ 0.3),
  else `NEUTRAL`; abstains (`None`) below the window or on a flat path. Tag
  `kaufman_efficiency_ratio_trailing_closes_v1`. ER reproduces the
  trend/range split from closes alone, so it pulls **no** `open_prep`
  macro/VIX import chain into the governance module (deliberate deviation).
- `governance/family_event_adapter` attaches `regime` to each family event;
  `governance/family_returns` adds `extract_family_regime_samples(...)` and
  `regime_degradation(...)`: pooled mean ≤ 0 → `False` (no pooled edge;
  PSR/MinTRL own it); otherwise the **current** regime (regime of the
  chronologically last event) must hold ≥ 20 samples → returns
  `current_mean ≤ 0` (degraded), else `None`. Lookahead-free and monotonic.
- `to_build_spec` attaches `entry["regime_degraded"]` + provenance
  `ev24_regime_source = kaufman_efficiency_ratio_trailing_closes_v1`,
  flowing through `build_family_metrics` to the gate verbatim. This
  **supersedes the EV#7 DEFERRED note** in the EV#6 entry below and in
  ADR-0014.

### Added (2026-06-02) — EV#6: real PSI-trend (C9 `psi_slope`) producer

The promotion gate's C9 population-stability-trend slot was wired on the
consumer side but every family reported "not yet measured" because no
producer emitted a `psi_trend` block. EV#6 now produces one from **real**
data — the EV-24 walk-forward score series — so `psi_slope` becomes a
measured, monotonic (block-only) gate input. See
`docs/adr/0014-ev6-psi-trend-source-and-ev7-regime-deferral.md`.

- `governance/family_calibration.py` adds `walk_forward_psi_trend(...)`: a
  **fixed reference Platt calibrator** is fit on the earliest chronological
  block and applied to that block *and* to each later monitoring window, so
  the PSI series isolates score-**population** drift from per-fold
  calibrator-refit drift (standard fixed-reference / moving-window PSI). The
  series is split into `k + 1` equal segments (`k` ∈ [2, 4], each ≥
  `max(MIN_TRAIN_SAMPLES, 10)` events); it abstains (`None`) below threshold
  or on a single-class / degenerate reference block, keeping the gate
  blocking honestly.
- `governance/family_returns.to_build_spec` attaches `entry["psi_trend"]`
  and audit-only provenance
  `ev24_psi_trend_source = ev24_fixed_reference_calibrator_chronological_windows_v1`,
  flowing through `build_bundle` → `build_family_metrics` → measured
  `psi_slope` (+ `psi_trend_method` provenance).
- **EV#7 (regime-conditional degradation) is now implemented** in this same
  release — see the EV#7 entry above. It derives a per-event regime label
  from the bars the event already reads (Kaufman Efficiency Ratio), so the
  C5.1 `regime_degraded` slot is measured without a new external producer.
  This supersedes the earlier "explicitly DEFERRED" plan recorded in
  ADR-0014.
- Tests: producer abstention/validity/drift-detection in
  `tests/test_family_calibration.py`; end-to-end spec→bundle wiring in
  `tests/test_family_returns.py`.

### Fixed (2026-06-02) — promotion-gate CLI tests leaked archives into the real repo tree

`scripts/run_promotion_gate.py` archives a timestamped copy of every run to
`governance/promotion_decisions/` resolved **relative to the current working
directory** (`--archive-dir` default). Four CLI/E2E tests invoked `main()`
without isolating cwd, so each run wrote a stray
`promotion_decisions_*.json` into the committed `governance/` tree instead of
a temp dir.

- Added an `autouse` `monkeypatch.chdir(tmp_path)` fixture to
  `tests/test_promotion_gate_producer_e2e.py` and
  `tests/test_run_promotion_gate_strict_universe.py` so the cwd-relative
  archive lands under each test's `tmp_path`. Future tests added to these
  modules inherit the isolation.
- No production change: the archive contract (cwd-relative default,
  `--archive-dir ''` to opt out) is unchanged.

### Added (2026-06-02) — GAP-4: block-bootstrap Brier confidence-interval gate

The promotion gate now blocks on the **upper bound of a block-bootstrap CI
on the Brier score**, not just the point estimate. At the few-hundred-event
scale the Brier sampling distribution is wide under serial dependence
(Bailey & López de Prado 2012; Wilks 2010), so a point estimate below the
0.22 bar with a CI poking above it is not 95 %-confident evidence of
calibration.

- `scripts/build_family_metrics.py` resamples the per-event Brier-loss series
  `(p − y)²` with the stationary block bootstrap (Politis–Romano 1994, seed 42,
  B = 2000, mean block length 5) and reports the 95th-percentile upper bound as
  `brier_ci_upper` (+ provenance `brier_ci_method`). Stays `None` below 30 OOS
  events ("not yet measured") rather than shipping a noisy interval.
- `governance/promotion_gate.py` adds `brier_ci_upper` to `FamilyMetrics` and
  `brier_ci_upper_max` (= `brier_max` = 0.22) to `GateThresholds`. Once
  measured a breach always blocks; when unmeasured it only blocks under
  `strict_provenance` so legacy snapshots stay valid. Documented in ADR-0008.
- This closes the GAP-4 follow-up explicitly deferred in
  `governance/family_calibration.py`.

### Fixed (2026-06-01) — `SMC_TV_Bridge.pine` malformed `//@version` directive + Pine version/provenance guards

`SMC_TV_Bridge.pine` declared `// @version=5` (stray space after `//`).
Pine only honours the exact form `//@version=N`; the malformed variant is
parsed as a plain comment, silently downgrading the script to the oldest
language version. Two prior reviews missed this because the existing check
(`tests/test_pine_input_surface.py::test_version_tag`) only asserted a
*substring* match on a single file. Directive corrected to `//@version=6`
(matching the rest of the active suite).

New regression guards:

- `tests/test_pine_version_directive.py` — anchored regex pinned to the
  *supported* set `^//@version=(?:5|6)\s*$` across the active suite
  (repo-root `*.pine` **and** the `pine/skipp_*.pine` libraries); fails on
  malformed directives (e.g. the stray-space form) *and* on unsupported
  versions (e.g. `//@version=999`), with an explanatory message. Closes the
  substring-match blind spot.
- `tests/test_pine_tv_bridge_fail_closed.py` — fail-closed guards for the
  untrusted-JSON bridge: `request.get` must not appear in live code (network
  stays opt-in/inert), numeric reads carry explicit `str.tonumber(_, default)`
  fallbacks, drawing blocks are gated on non-empty payloads, plus a faithful
  Python reference port of `f_getField` pinned against malformed JSON
  (empty/missing-key/unterminated-string/garbage → fail closed to `""`).

New machine-readable input-provenance artifact (closes the hidden-input
provenance gap from the SMC Suite review):

- `pine_input_surface.py` gains a `provenance` subcommand emitting per-input
  provenance JSON (file, line, varname, kind, label, group,
  `has_display_none`, policy visibility) for the whole suite.
- `reports/pine_input_provenance.json` — committed artifact covering 526
  inputs incl. hidden operator inputs.
- `tests/test_pine_input_provenance.py` — drift guard that regenerates the
  map from source and compares against the committed artifact (ledger
  discipline: any added/removed/renamed/regrouped/hidden input requires a
  deliberate `provenance --out` refresh).

### Changed (2026-05-28) — WS3 #58: `HERO_MARKET_TRUST` vocab converges onto `HERO_TRUST` + `library_field_version` v7.0a (BREAKING for Pine consumers)

`HERO_MARKET_TRUST` (Producer B, `scripts/smc_hero_market_mode.py`) now
derives from the canonical `TrustState` via
`scripts.smc_hero_state.project_trust_state_to_hero` instead of a
parallel label table. Label changes on the Pine export:

- `HEALTHY` → `"healthy"` (was `"trusted"`)
- `DEGRADED` → `"degraded"` (was `"advisory"`)
- `WATCH_ONLY` → `"degraded"` (collapse, was `"watch_only"`) — matches the
  intentional info-loss already documented for `HERO_TRUST` via
  `project_trust_state_to_hero`.
- `STALE` → `"stale"` (unchanged)
- `UNAVAILABLE` → `"unavailable"` (unchanged)

New module-level pin `scripts.smc_hero_market_mode.HERO_MARKET_TRUST_VOCAB`
locks the convergence:

    HERO_MARKET_TRUST_VOCAB == HERO_TRUST_VOCAB - {"warmup"}

(`"warmup"` is Hero-local with no `TrustState` counterpart). Enforced by
`tests/test_hero_trust_market_trust_alignment.py` (5 parametrized
TrustState mappings + 3 vocab-set invariants).

This is a breaking change to the Pine `export const string HERO_MARKET_TRUST`
literal → `library_field_version` bumped **v6.0a → v7.0a** (MAJOR) and the
`deprecated_field_policy.preferred_field_version` follows. Regenerated
artifacts: `pine/generated/smc_micro_profiles_generated.{pine,json}`,
`tests/fixtures/generated_seed/...`,
`artifacts/tradingview/smc_product_cut_manifest.json`. No Pine consumer
currently gates on `HERO_MARKET_TRUST` values (only the export constant
exists in non-generated Pine), so this is a producer-only contract change.

### Changed (2026-05-26) — WS3-UI #55: HERO waiting-state sentinels + `library_field_version` v6.0a (BREAKING for Pine consumers)

`HERO_MARKET_MODE`, `HERO_BIAS`, and `HERO_SETUP_QUALITY` now distinguish a
*waiting state* (no enrichment data yet) from a substantive neutral / flat
/ low reading:

- `HERO_MARKET_MODE` default: `NEUTRAL` → `UNKNOWN`
- `HERO_BIAS` default: `FLAT` → `UNKNOWN`
- `HERO_SETUP_QUALITY` default: `low` → `unavailable`

The three sentinels are first-class vocab members (`HERO_MARKET_MODE_VOCAB`
4 → 5, `HERO_BIAS_VOCAB` 3 → 4, `HERO_SETUP_QUALITY_VOCAB` 4 → 5) and the
Producer-A → Producer-B action map gains
`HERO_QUALITY_A_TO_B["unavailable"] = "avoid"`.

Pine dashboards (`SMC_Dashboard.pine`, `SMC_Mobile_Dashboard.pine`) render
`⚪ awaiting data` (grey-80 background) for the sentinel; the bias chip is
suppressed for both `FLAT` and `UNKNOWN`.

This is a breaking change to Pine literal gates → `library_field_version`
bumped **v5.5c → v6.0a** (MAJOR) and the
`deprecated_field_policy.preferred_field_version` follows. Regenerated
artifacts: `pine/generated/smc_micro_profiles_generated.{pine,json}`,
`tests/fixtures/generated_seed/...`, `artifacts/tradingview/smc_product_cut_manifest.json`.
Snapshot/fingerprint pins regenerated:
`tests/governance/vocab_fingerprint.json`,
`tests/test_hero_schema_fingerprint.py`,
`tests/test_central_vocab_fingerprint_gate.py`. Closes #55. See
[ADR-0007 §2026-05-26 amendment](docs/adr/0007-hero-field-invariants.md)
for the full rationale.

ML schema pin `ml/schemas/v1_hero_features.json` bumped to
`schema_version: v2` (per drift policy `new_vocab_value_added`) with new
`pinned_source_sha256` and the three new vocab members listed.

### Added (2026-05-17) — W1.b: PromotionGate daily producer path

End-to-end wiring of the W1 schema-v2 `PromotionGate` contract into a
real daily producer (PR #2261). Closes the gap audited in
`/memories/repo/promotion-gate-adoption-audit-2026-05-17.md` where the
gate had zero non-test callers on `main`.

- **Bundler** — `scripts/build_promotion_gate_bundle.py` reads
  `artifacts/ci/measurement_benchmark_rolling/<DATE>/plan_2_8_tf_family_rollup.json`
  and emits a `FamilyMetrics`-shaped JSON list, one entry per
  `EventFamily` (BOS / OB / FVG / SWEEP). Unmeasured W1 metrics
  (Brier/ECE/PSI/conformal/...) pass through as `None`; per-family event
  totals land in `extras.n_events_total`; `provenance` names the source
  artifact + run date.
- **Daily workflow** — `.github/workflows/promotion-gate-daily.yml`
  runs at 09:30 UTC (between rolling-bench at 07:30 and F2 gate at
  10:00), downloads the most-recent `smc-measurement-benchmark-rolling-<DATE>`
  artifact via `gh run list/download`, runs the bundler + gate, and
  publishes a dated report plus the stable
  `artifacts/promotion_decisions.json` alias consumed by the
  Decision-First Streamlit tab.
- **Advisory strict semantics** — workflow keeps
  `strict_provenance=True`. Gate `rc=2` (blocked / metrics missing)
  emits `::warning::` + step summary but does **not** fail CI; only
  `rc=1` (config error) fails. The honest "red" report is the product.
- **E2E test** — `tests/test_promotion_gate_producer_e2e.py` pins the
  full chain (bundler → runner → loader → panel) via public CLI / loader
  surfaces only.
- **#2251 superseded** — the C9 PSI-trend signal feeds in as a
  precomputed scalar (`psi_slope`) per W1 schema v2 rather than as raw
  `psi_history` inside the gate.

### Added (2026-05-13) — P5.4 doc-train: Copilot-review hardening + repo-resident MD lint

End-to-end remediation of recurring Copilot review-comment classes via
the P5.4 doc-train (PRs #2173–#2179) plus deep-review follow-ups
(#2184 = sibling `_progress` flush parity, #2185 = repo-resident MD lint
warn-only, #2186 = bulk-fix existing doc findings, #2187 = protocol +
standing-orders + this CHANGELOG entry).

- **MD inline-backtick lint** — `scripts/lint_md_inline_backticks.py`
  (PR #2185) catches the cross-line inline-backtick spans that were the
  dominant Copilot finding-class through the P5.3 / P5.4 trains. Ships
  warn-only via `.github/workflows/docs-lint.yml`; flips to `--strict`
  once the existing `docs/` corpus is clean (PR #2188).
- **Sibling `_progress` flush parity** — all four sibling `_progress`
  implementations (`databento_production_export.py`,
  `databento_preopen_fast.py`,
  `generate_smc_micro_base_from_databento.py`,
  `smc_microstructure_base_runtime.py`) now carry the canonical
  `sys.stderr.flush(); sys.stdout.flush()` pair after `logger.info(...)`
  (PR #2184). Closes the silent-buffering gap discovered when only the
  canonical site had the flush.
- **Triage-protocol expansion** — `docs/COPILOT_REVIEW_TRIAGE_PROTOCOL.md`
  §5.6 (pre-flight MD lint), §5.7 (pre-flight `sort -n`/`-V` check),
  §5.8 (pre-flight dual-stream-flush check) added so future authors
  catch these classes before push, not after Copilot does (PR #2187).
- **New repo-anchored protocol** —
  `docs/PRE_FLIGHT_LINT_PROTOCOL.md` (PR #2187) is the repo-resident
  sibling to the operator-local memory note, ensuring any maintainer
  can run the pre-flight gates without operator-local context.

Rationale for filing under P5.4 (not P5.3): CHANGELOG is phase-blind;
this entry exists for audit-trail completeness of the doc-train. It is
**not** claiming P5.3 also documented this — that section never existed.

### Changed (2026-05-12) — Audit L-1 finalization: provider-rationalization train + post-audit follow-ups

End-to-end consolidation of the Audit L-1 provider stack. Eight PRs landed on
main as a focused merge train (#2154 → #2161, #2163), plus #2153 (Watchdog),
#2152, and #2164 (post-audit follow-ups):

- **Unusual Whales options-flow DECOMMISSIONED** — replaced by self-hosted
  Databento OPRA.PILLAR UOA detector in `newsstack_fmp/opra_uoa.py` (PRs
  #2155 / #2157 / #2163). The remaining `UnusualWhalesAdapter` methods
  (darkpool, spot-GEX, market-tide, insider-transactions, news-headlines)
  are DORMANT (silently return `[]` after subscription cancel; no production
  consumer left). Sunset-TODO `2026-Q3-uw-review` filed at top of
  `newsstack_fmp/ingest_unusual_whales.py` (owner: ops, deadline 2026-08-31)
  to drop the entire module + `UNUSUAL_WHALES_API_KEY` if no consumer
  reactivated.
- **OPRA UOA detector ACTIVE** — gated by `ENABLE_OPRA_UOA` (default `1`
  since 2026-05-12 PR #2155 commit 6d6196cf). Consumes Databento
  OPRA.PILLAR via the ingestion wrapper
  `newsstack_fmp/ingest_opra_options_flow.py`.
- **Finnhub adapter Option-B duplicate-drop** (PR #2160) and **macro g5
  stub removal** (PR #2156) — line-pinned ledgers reconciled in
  `tests/test_mutable_defaults_and_loads_pins.py` and
  `tests/test_os_environ_mutation_ledger.py` (PR #2164).
- **Probe coverage** — `scripts/probe_providers.py` gains a
  `probe_databento_opra_entitlement` mock-friendly probe (SKIPs on missing
  key / disabled feature; FAILs only when `ENABLE_OPRA_UOA=1` but the key
  lacks `OPRA.PILLAR` entitlement). Replaces the pre-decommission
  `probe_uw_options_flow`.
- **Operator runbook** — `docs/OPEN_PREP_OPS_QUICK_REFERENCE.md` §13
  "Provider Decision Matrix" captures the new state of all four provider
  surfaces (UW UOA flow, UW dormant adapters, NewsAPI.ai dual-state,
  OPRA UOA detector); `ENABLE_OPRA_UOA` default reconciled (`0` → `1`).

No runtime regressions: pin-tests, posture markers, and orphan-inventory
all green.

### Added (2026-05-12) — CI: smc-export-cron-watchdog backup workflow

New workflow `.github/workflows/smc-export-cron-watchdog.yml` acts as a
safety-net for missed/delayed scheduled triggers of
`smc-databento-production-export`. The heavy export runs on the scarce
`ubuntu-latest-l` (64 GB) larger-runner pool, where GHA scheduled events
are observably delayed under load
(documented:
https://docs.github.com/en/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows#schedule).

**Empirical evidence motivating this:**

- 2026-05-11 16:00 UTC slot fired at 17:49 UTC = **109 min delay** (run
  25687318767).
- 2026-05-12 12:00 UTC slot did not fire at all by +11 min — manual
  dispatch was used instead (run 25733577369).
- All other small-runner schedule events on 2026-05-12 (08:04, 08:05,
  08:06, 08:50, 08:52, 10:06, 10:37, 10:41, 11:22, 11:50) fired on
  time — confirms the issue is the larger-runner pool, not the GHA
  scheduler in general.

**Design:**

- Watchdog runs on `ubuntu-latest` (separate, reliable pool).
- Ticks at 12:45 / 13:00 / 13:15 / 13:30 UTC and 16:45 / 17:00 / 17:15 /
  17:30 UTC (Mon-Fri).
- Threshold: 45 min after slot start before dispatching (gives the cron
  a realistic chance to fire late).
- Race-condition guard: queries the heavy workflow's run list filtered
  by `created_at >= slot_start`. If ANY run exists in the slot — queued,
  in_progress, or completed regardless of conclusion — the watchdog
  no-ops. Prevents duplicate dispatch + Databento double-billing when
  cron is merely late, not missing.
- Original `schedule:` triggers in
  `smc-databento-production-export.yml` are intentionally **kept**.
  Watchdog is a backup, not a replacement.

Permissions: `actions: write` (for `gh workflow run`), `contents: read`.
Concurrency-grouped to prevent overlapping watchdog ticks. 5-min timeout.

### Changed (2026-05-12) — F-V8-Q5b: skip oversized second_detail sheets from canonical workbook

`scripts/databento_production_export.py::_write_canonical_production_workbook`
now omits `full_universe_second_detail_open` and
`full_universe_second_detail_close` from the canonical xlsx workbook's
`additional_sheets` dict. Both data series remain available as parquet
artifacts written by `_write_exact_named_exports()` in Step 10/10b
(`<export_dir>/full_universe_second_detail_{open,close}.parquet`), which
is the path all known consumers already use (verified consumer audit
across `smc_integration/`, `scripts/`, `docs/`, `README.md`).

**Trigger:** five consecutive failures of `smc-databento-production-export`
on cron lookback=30 (2026-05-07 / 2026-05-08). Heartbeat-diagnostic probe
run **25693860630** (branch `workbook-heartbeat-diagnostic`, PR #2146,
landed as `cc5f6f9d`) ran for 141 min on 64 GB `ubuntu-latest-l` and was
killed by **exit 143 / SIGTERM** at chunk 4-of-7 of sheet 8
(`full_universe_second_detail_open`, 7,270,261 rows × ~10 cols), 9 min
20 s into Step 10/10c. All per-chunk and per-styling-step heartbeats fired
right up to the kill, falsifying the GHA no-output watchdog hypothesis.

**Root cause:** *likely* memory pressure (cgroup / systemd-oomd on the
hosted runner, openpyxl is non-streaming and accumulates every written
sheet in memory), but **not formally confirmed**. Alternative hypotheses
considered but **not falsified**: GHA process watchdog, hosted-runner
eviction, `/mnt` disk pressure. The symptom-fix (skip these sheets) is
valid regardless of the exact mechanism — the workbook cannot
accommodate sheets of this size on the production runner, the parquet
path is the source of truth for downstream consumers anyway, and
manual inspection of a chunk-split 7.27 M-row sheet in Excel is
unusable in practice.

Mirrors the F-V8-Q5a precedent from 2026-05-09
(`full_universe_close_trade_detail`, killed at peak RSS ~6.9 GB on the
old 7 GB runner). The producer emits a second `progress_callback` line
documenting the skip, so the canonical Step 10/10c log shows both Q5a
and Q5b suppressions explicitly.

**Bonus diagnostics:** `scripts/databento_production_workbook.py` now
emits a per-sheet memory snapshot (`rss=…MB vms=…MB uss=…MB` via
`psutil.Process().memory_full_info()`, with a `resource.getrusage`
fallback when psutil is unavailable) at workbook begin, before/after
every sheet, before openpyxl context-exit, and after context-exit. This
gives a per-sheet memory-delta trace for any future bottleneck hunt.
`psutil>=5.9.0` is now declared explicitly in `requirements.txt` (it
was previously only available transitively, which made the diagnostic
silently fall back on the production runner).

Workflow docstring (`.github/workflows/smc-databento-production-export.yml`)
updated to reference Q5b and corrected from `32 GB / 300 GB` to the
actual `64 GB / 600 GB` runner spec.

### Added (2026-05-11) — Real-day ranking snapshot dump (opt-in)

Add an opt-in snapshot writer to `open_prep/run_open_prep.py` that
captures the **exact** inputs passed to `rank_candidates_v2` (quotes,
bias, top_n, news side-channels, sector context, weight_label) plus
the resulting ranked / filtered_out outputs and a diagnostic context
block (`regime`, `run_date_utc`, `vix_level`; the latter is observed in
this code path but not currently passed into `rank_candidates_v2`).
Triggered via env var `OPEN_PREP_DUMP_SNAPSHOT=1` (defaults off — no
production behaviour change). Output goes to
`artifacts/open_prep/snapshots/ranking_snapshot_<YYYYMMDD_HHMMSS_%fZ>_<pid>.json`
via an atomic temp-file write + replace.

Purpose: prerequisite for a planned real-day smoke-anchor golden test
(follow-up to PR #2138 once that PR merges). The fixture-based golden
in PR #2138 covers all known scorer branches synthetically; this
snapshot path will let a real production run be replayed
deterministically as a second golden once captured.

No tests added — the dump path is diagnostic-only, opt-in, and wraps
its work in a broad `except` so any failure logs a warning without
affecting the run.

### Added (2026-05-11) — PR #2138 ranking golden + news-tier tuning

Two coordinated additions to the production ranking surface:

**A. Golden-file regression test for `open_prep.scorer.rank_candidates_v2`**

`rank_candidates_v2` is the production ranking boundary and is fully
deterministic when called with `dirty_manager=None` and
`weight_label="default"`. New artefacts:

- `tests/fixtures/ranking_archetypes_input.json` — 7 quote archetypes
  covering distinct pipeline branches: `MEGA_CAP_EARNINGS`,
  `SECTOR_LEADER`, `SECTOR_LAGGARD`, `NEWS_PUMP`, `ENERGY_RISK_OFF`,
  `PENNY_REJECT`, `SEVERE_GAP_DOWN_REJECT`.
- `tests/fixtures/ranking_archetypes_golden.json` — captured expected
  output (ranked + filtered_out, floats rounded to 6 places).
- `tests/test_ranking_golden.py` — three tests: full golden match,
  determinism (two runs identical), and hard-invariant filter contracts
  (penny + severe-gap-down always rejected; no overlap between ranked
  and filtered; score-descending order).

Workflow for intentional weight/threshold changes:

```
REGEN_RANKING_GOLDEN=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_ranking_golden.py
git diff tests/fixtures/ranking_archetypes_golden.json
```

The diff makes every scoring change reviewable; commit source change and
golden update together in the same PR.

**B. News source-tier discounting + low-tier rumor penalty**

The first golden run surfaced a real ranking pathology: under
`DEFAULT_WEIGHTS`, an unverified Stocktwits rumor (`PUMP` archetype,
TIER_3 source) ranked **#1 above** a tier-1 confirmed earnings beat
(`NVDA` archetype) on raw gap × rvol alone. Three coordinated changes
to `open_prep/scorer.py`:

1. `NEWS_SOURCE_TIER_MULTIPLIERS` — discount `news_component` by source
   credibility:

   | Tier | Multiplier | Examples |
   |------|------------|----------|
   | TIER_1 | 1.00 | Reuters, Dow Jones, MarketWatch |
   | TIER_2 | 0.70 | TradingView, DPA-AFX, CNBC TV |
   | TIER_3 | 0.30 | GuruFocus, Stocktwits, Zacks, Invezz |
   | TIER_4 | 0.10 | unknown / anything else |

2. `DEFAULT_WEIGHTS["news"]: 0.8 → 2.5` — tier-1 confirmed news now
   carries roughly the same component magnitude as `earnings_bmo`
   (1.5 × DR), instead of being a minor afterthought.

3. `LOW_TIER_NEWS_RUMOR_PENALTY = 0.75` — multiplicative final-score
   haircut applied when `news_source_tier ∈ {TIER_3, TIER_4}` AND
   `news_score >= 0.5`. Stops technically-strong moves driven by
   unverified social chatter from out-ranking confirmed catalysts.
   Surfaced as new `score_breakdown.low_tier_news_rumor_penalty` field
   for production traceability.

Effect on golden archetypes (rank order):

```
Before:  PUMP 11.71 → LEAD 9.38 → NVDA 9.09 → ENRG 5.31 → LAGG 1.30
After:   NVDA 10.65 → LEAD 9.38 → PUMP 8.72 → ENRG 5.31 → LAGG 1.29
```

Verification: `tests/test_open_prep.py` (280 passed) +
`tests/test_ranking_golden.py` (3 passed) + filter contracts preserved.

### Fixed (2026-05-10) — PR #2112 Copilot review follow-ups (PR #2113)

Three small follow-ups raised by the Copilot review on PR #2112.
No behavioural changes outside the redaction surface.

- **Copilot #1 — webhook URL token redaction (extends PR #2112 M1)**:
  extend `databento_utils._API_KEY_REDACTION_PATTERNS` with two
  additional URL-path patterns so the canonical redactor also masks
  Discord (`https://discord.com/api/webhooks/{id}/{token}`, including
  `ptb.` / `canary.` / `discordapp.com` variants) and Slack
  (`https://hooks.slack.com/services/T…/B…/{token}`) webhook secrets.
  These are embedded in the URL **path** (not as `?token=…`), so the
  pre-existing `api_key=` / `token=` / `Authorization: Bearer` patterns
  could not catch them. `repr(httpx_exc)` typically includes the
  request URL, which is how those tokens would otherwise leak into the
  three M1 sites (`terminal_export.py`, `terminal_tradingview_news.py`,
  `terminal_notifications.py`). Adds 3 unit tests in
  `tests/test_databento_provider.py::TestRedaction`.
- **Copilot #2 — `terminal_background_poller.py` L2 comment refinement**:
  reword the L2 explanatory comment. The original wording suggested
  the lock prevents a "torn intermediate value under tsan", which is
  misleading for CPython where the GIL makes a single `int` read
  atomic. The lock is taken purely for **lock-parity** with every other
  access of `poll_count` — same code, no semantic change.
- **Copilot #3 — `databento_volatility_screener.py` L5 follow-through**:
  the PR #2112 changelog claimed `utc=True` was added to the
  `pd.to_datetime(src["trade_date"], errors="coerce")` coercion in
  `_build_close_trade_aggregates`, but the code change was not actually
  landed. This PR applies it (now at the close-trade detail builder
  *and* the close-outcome minute detail builder for parity), with an
  explanatory comment.

### Fixed (2026-05-09) — Quantum sweep medium/low findings (M1, M2, L1–L6)

Hardening pass on the quantum-sweep audit (PR #2112). No behavioural
changes; tightens redaction parity and threading discipline, and
documents three intentional-but-non-obvious numeric/calendar edge cases.

- **M1 — `repr(...)` payload redaction parity** (3 sites): wrap
  `repr(item)` / `repr(exc)` / `repr(err)` through the canonical
  `databento_utils._redact_sensitive_error_text` helper before they are
  persisted to disk (`terminal_export.py` JSONL fallback) or to the
  in-memory health-state dicts that the dashboard reads
  (`terminal_tradingview_news.py`, `terminal_notifications.py`).
  Closes a redaction gap where wrapped httpx/urllib3 exceptions whose
  `__repr__` includes auth tokens (`api_key=`, `token=`,
  `Authorization: Bearer …`) could leak into artifacts/logs.
- **M2 — terminal_technicals.py redaction parity**: replace the local
  narrow `_APIKEY_RE` regex (`(apikey|api_key|token|key)=…`) with an
  import of `_redact_sensitive_error_text`, picking up the canonical
  patterns (Bearer tokens, additional key shapes). Removes duplicate
  regex source of truth.
- **L1 — `terminal_finnhub.py` global consolidation**: hoist the
  nested `global _social_sentiment_blocked` (was buried inside the 403
  branch) up to the top of `_get(...)` alongside the existing
  `global _rate_limit_backoff_until, _consecutive_429_count`. All
  mutation surface for the function is now declared in one place,
  matching the convention used elsewhere in the file.
- **L2 — `terminal_background_poller.py` `poll_count` lock parity**:
  read `self.poll_count` under `self._stats_lock` for the periodic
  prune trigger (was the only unprotected access; every other read /
  write of the counter is already serialised).
- **L3 — `smc_core/htf_context.py` + `smc_core/session_context.py`
  ISO-week boundary comment**: document that `%G-W%V` (ISO-8601
  year-week) and `%Y-%m` (calendar year-month) intentionally use
  different year axes and diverge at year boundaries (e.g. 2024-12-30
  → ISO `2025-W01` but calendar `2024-12`) — that is the correct
  semantics for prev-week vs. prev-month bucketing.
- **L4 — `rl/simulator/execution_env.py` fractional-share comment**:
  document that `max(parent_qty, 1.0)` floors the implementation-shortfall
  divisor at 1.0 and *understates* the bps figure for fractional-share
  parents (`parent_qty < 1.0`); revisit if/when the simulator supports
  fractional parents.
- **L5 — `databento_volatility_screener.py` `pd.to_datetime(...,
  utc=True)`**: add `utc=True` to the `trade_date` coercion to suppress
  the pandas "mixed timezone" `FutureWarning` when upstream joins
  accidentally inject tz-aware Timestamps. The trailing `.dt.date`
  still returns naive `datetime.date` instances downstream.
- **L6 — `newsstack_fmp/ingest_unusual_whales.py` non-JSON body
  sample**: extend the existing "UW returned non-JSON" warning to
  include `r.text[:200]`, so silent UW schema changes (HTML
  maintenance pages, plain-text gateway responses) are diagnosable
  from logs without round-tripping through `curl`.

Tripwire ledgers refreshed for the global / urlopen / sleep / unlink
line-number drift caused by the added imports and the consolidated
`global` declarations.

### Fixed (2026-05-09) — Copilot review follow-ups for PRs #2109/#2110

Addresses post-merge Copilot inline review on the Provider Audit 2.0 stack:

- **`newsstack_fmp/pipeline.py`** (`meta_sources`): use **singular** provider
  labels `fmp_senate_trade` / `fmp_house_trade` to match
  `normalize_fmp_political_trade`, `Config.active_sources`, and
  `ingest_counts_by_source`. The plural form (added by PR #2109) made the
  exported `meta['sources']` telemetry list inconsistent with observed
  provider tags downstream.
- **`newsstack_fmp/ingest_fmp_political.py`**: corrected the inline audit
  comment — `_TIER_LIMITED_CODES = {401, 403, 404}` does **not** include
  400, so a 400 response is caught by the wrapper but does **not**
  auto-disable the endpoint. The comment now warns to keep
  `ENABLE_FMP_SENATE_TRADES=0` / `ENABLE_FMP_HOUSE_TRADES=0` until
  per-symbol iteration lands, otherwise the path will be polled every
  tick and burn quota in a 400-loop.
- **`terminal_finnhub.py`** (`fetch_company_news`): docstring updated to
  reflect that the cache key now includes `max_items` (not just
  `(symbol, days_back)`).
- **`newsstack_fmp/normalize.py`** (`normalize_fmp_filing_13f`): docstring
  reworded — cross-provider hard-dedup is keyed off `cluster_hash`
  (headline + tickers), not `item_id`.
- **`newsstack_fmp/ingest_fmp_filings.py`** (`FmpFilingsAdapter`): class
  docstring expanded to mention both 8-K and 13F-HR endpoints.
- **`tests/test_time_sleep_budget.py`**: refreshed `_FROZEN_SITES` line
  numbers in `newsstack_fmp/ingest_fmp_filings.py`,
  `newsstack_fmp/ingest_fmp_political.py`, and `newsstack_fmp/pipeline.py`
  for the +N-line drift introduced by the docstring/comment edits above.

### Fixed (2026-05-09) — FMP `/stable/` endpoint paths (live-audit, PR #2110)

Live API smoke-tests across all newsstack providers (post-PR #2104–#2109)
uncovered three FMP endpoint-path mismatches against the current
financialmodelingprep.com `/stable/` API:

- **`newsstack_fmp/ingest_fmp_filings.py`** (`FMP_8K_LATEST_PATH`):
  changed from `/sec-filings/8-K-latest` (404) to **`/sec-filings-8k`**
  (verified live: returns a list of 8-K filings with keys `symbol`,
  `cik`, `filingDate`, `acceptedDate`, `formType`, …).
- **`newsstack_fmp/ingest_fmp_filings.py`** (`FMP_13F_LATEST_PATH`):
  no working `/stable/` 13F bulk path located after probing 7 variants
  (`sec-filings-13f`, `sec-filings-13F-HR`, `sec-filings-form-13f`,
  `form-13F-rss-feed`, etc. — all 404). Constant updated to
  `/sec-filings-13f` for consistency; the existing 404 → `mark_disabled`
  short-circuit will self-mute the endpoint on first call. `ENABLE_FMP_13F`
  remains default-off until the correct path is documented (TODO comment
  inline in the adapter).
- **`newsstack_fmp/ingest_fmp_political.py`** (senate/house): the
  `/stable/senate-trades` and `/stable/house-trades` paths are *per-ticker*
  detail endpoints (return 400 without a `symbol=` param), not bulk
  feeds. Legacy `/v4/senate-trading-rss-feed` is now restricted to
  pre-2024-08-31 subscribers (403). `ENABLE_FMP_SENATE_TRADES` and
  `ENABLE_FMP_HOUSE_TRADES` remain default-off; an inline TODO documents
  the situation and proposes per-symbol iteration as a follow-up.

Verified-working endpoints in the same audit (no changes required):
`finnhub.fetch_company_news`, `fetch_recommendation_trends`,
`fetch_insider_sentiment`, `unusual_whales.fetch_uw_news_headlines`.
`finnhub.fetch_news_sentiment` returns 403 on the free tier as expected.

### Fixed (2026-05-09) — Provider Audit 2.0 post-merge follow-ups (PR #2109)

- **`fix(provider-audit-2): post-merge audit fixes`** — quantum sweep
  follow-ups across the merged PR2104–PR2108 stack. 11 findings:
  - **Critical (data correctness)**:
    - `terminal_finnhub.fetch_insider_sentiment`: skip caching `[]` on
      empty `_get` payload (rate-limit / key-miss). Previously a single
      429 silenced the endpoint for the full 6h TTL.
    - `terminal_finnhub.fetch_company_news`: include `max_items` in
      cache key. Previously a caller asking for 200 items would receive
      a 50-item cached truncation if a prior caller hit the path first.
    - `newsstack_fmp/pipeline.py`: 4 cursor-filter sites changed
      `it.updated_ts > fmp_*_last` → `>=` (senate, house, 8K, 13F).
      FMP returns date-only timestamps for these endpoints; `>` was
      dropping same-day records on subsequent polls. `mark_seen()`
      remains the authoritative per-id dedup.
  - **Important**:
    - `newsstack_fmp/normalize.py:334` (UW news headline-derived id):
      `hashlib.sha1(..., usedforsecurity=False)` flag added (matches
      the other 4 sha1 sites).
    - `newsstack_fmp/pipeline.py`: `enrich_budget=3` absolute cap (was
      `max(0, 3 - _enrich_ctr[0])` which under-budgeted the
      other-provider batch when the FMP batch had already consumed
      enrichments — `_enricher` carries the shared counter anyway).
    - `newsstack_fmp/pipeline.py` `meta_sources`: added 6 missing
      telemetry entries (`uw_news`, `fmp_general_latest`,
      `fmp_senate_trades`, `fmp_house_trades`, `fmp_8k_latest`,
      `fmp_13f_latest`).
    - Removed 3 dead exception classes never raised:
      `UnusualWhalesEndpointDisabledError`,
      `FmpFilingsEndpointDisabledError`,
      `FmpPoliticalEndpointDisabledError`. Mute mechanism is the
      `mark_*_disabled()` flag plus generic-Exception catch in callers.
  - **Minor**:
    - `tests/test_terminal_finnhub.py:120`: replaced duplicate
      `import unittest.mock as _mock` with alias `_mock = mock`
      (the module is already imported at file top).
    - Tripwire ledgers refreshed: weak-hash pin, weak-hash sites,
      `# noqa` budget, `time.sleep` budget, `global` statement budget,
      HTTP client discipline, `# type: ignore` budget.

### Added (2026-05-09) — newsstack: FMP Form-13F follow-up (B6)

- **`feat(newsstack): FMP /sec-filings/13F-HR-latest provider`** —
  Closes the **B6** follow-up deferred from PR #2106. Adds the latest-filings
  feed for institutional 13F-HR submissions (no CIK iteration needed —
  treats it as a news-shaped event stream like 8-K).
  - `FmpFilingsAdapter.fetch_13f_latest(page, limit)` in
    `newsstack_fmp/ingest_fmp_filings.py` reusing the existing
    `mark_fmp_filings_disabled` short-circuit on 403/404.
  - Module wrapper `fetch_fmp_13f_latest(api_key, page, limit)`.
  - `normalize_fmp_filing_13f(rec)` in `newsstack_fmp/normalize.py`
    synthesizing `13F-HR filing: {institution}` headlines (`tickers=[]`
    since 13F-HR is institution-keyed via CIK, not symbol-keyed).
  - Pipeline cursor `fmp.13f.last_seen_epoch` (block 2.9). Items flow
    via `other_items` so they inherit the PR1 cross-provider hard-dedup
    automatically.
  - Config: `enable_fmp_13f` (default 0, env `ENABLE_FMP_13F`),
    `fmp_13f_limit` (default 50, env `FMP_13F_LIMIT`). `active_sources`
    appends `fmp_13f_latest` when both flag + key are set.
- **Tests** — `tests/test_newsstack_fmp.py` 172 → 176 cases:
  fetch returns items, DISABLED-path short-circuit, normalize basic +
  synthesized item_id when no URL.

### Added (2026-05-09) — terminal: Finnhub free-tier extensions (company-news / news-sentiment / recommendations / insider)

- **`feat(terminal): Finnhub free-tier endpoints — company-news + news-sentiment + recommendations + insider-sentiment`** —
  Phase D (PR4) of Provider Audit 2.0, surfacing four free-tier Finnhub
  endpoints that the existing `terminal_finnhub.py` ignored (only
  premium-locked `/stock/social-sentiment` was wired previously).
  Stacked on PR3 (FMP extras), PR2 (UW news/headlines), PR1
  (cross-provider hard-dedup).
  - `fetch_company_news(symbol, days_back=7, max_items=50)` →
    `list[CompanyNewsItem]` — endpoint `/company-news`. 5-min cache.
  - `fetch_news_sentiment(symbol)` → `NewsSentimentSummary | None` —
    endpoint `/news-sentiment` (buzz + bullish/bearish split + sector
    score). 30-min cache.
  - `fetch_recommendation_trends(symbol)` → `list[RecommendationTrend]` —
    endpoint `/stock/recommendation` (analyst grade tally per month).
    6-h cache.
  - `fetch_insider_sentiment(symbol, months_back=6)` →
    `list[InsiderSentimentMonth]` — endpoint `/stock/insider-sentiment`
    (monthly insider net-flow + MSPR). 6-h cache.
  - All four reuse the existing `is_equity_symbol` guard (rejects
    crypto / forex / index symbols), the existing `_get_cached/_set_cached`
    TTL cache, the existing `_get` helper with 429 exponential backoff,
    and a new generalised **DISABLED-path short-circuit**: any 403/404
    response now adds the path substring to `_blocked_path_substrings`
    so further calls return `{}` immediately for the rest of the process
    (mirrors the per-endpoint pattern from PR2/PR3 newsstack adapters).
  - `clear_blocked_paths()` test helper to reset the short-circuit in
    unit tests.
- **Tests** — `tests/test_terminal_finnhub.py` grows from 18 → 33 cases:
  parsing, equity-guard rejection, empty-payload handling, max-items cap,
  per-key caching, `data` field unwrap for insider sentiment, and the
  generalised blocked-path reset helper.

### Added (2026-05-09) — newsstack: FMP extras (general / Senate-House / 8-K)

- **`feat(newsstack): FMP general-latest + Senate/House trades + 8-K filings`** —
  Three new FMP-backed providers extending PR2's pattern. Stacked on PR2
  (UW news/headlines) and PR1 (cross-provider hard-dedup). All default-OFF
  except `fmp_general_latest` (default-ON since it complements the existing
  per-symbol `fmp_stock_latest` and corporate `fmp_press_latest` feeds with
  macro / market-wide coverage). Senate/House/8-K adapters mirror PR2's
  DISABLED-endpoint short-circuit so tier-locked endpoints (401/403/404)
  auto-suppress for the rest of the process.
  - `FmpAdapter.fetch_general_latest(page, limit)` in
    `newsstack_fmp/ingest_fmp.py` (provider label `fmp_general_latest`,
    reuses `normalize_fmp`, wired through the existing
    `_fetch_cached_provider_items` cache layer).
  - `newsstack_fmp/ingest_fmp_political.py` — new `FmpPoliticalAdapter`
    with `fetch_senate_trades` / `fetch_house_trades` and module-level
    wrappers `fetch_fmp_senate_trades` / `fetch_fmp_house_trades`.
    DISABLED helpers: `is_fmp_political_disabled`,
    `mark_fmp_political_disabled`, `clear_fmp_political_disabled`,
    `FmpPoliticalEndpointDisabledError`.
  - `newsstack_fmp/ingest_fmp_filings.py` — new `FmpFilingsAdapter`
    with `fetch_8k_latest` and module wrapper `fetch_fmp_8k_latest`.
    Same DISABLED-pattern surface area.
  - `normalize_fmp_political_trade(rec, *, chamber)` and
    `normalize_fmp_filing_8k(rec)` in `newsstack_fmp/normalize.py` —
    synthesise stable headlines and sha1-derived item_ids for non-news
    payload schemas. Handles FMP's `dateRecieved` typo.
  - Pipeline cursors `fmp.general.last_seen_epoch`,
    `fmp.senate.last_seen_epoch`, `fmp.house.last_seen_epoch`,
    `fmp.8k.last_seen_epoch`. Senate / House / 8-K items flow via
    `other_items` so they automatically inherit PR1's cross-provider
    hard-dedup cache.
  - Config flags: `enable_fmp_general` (env `ENABLE_FMP_GENERAL`,
    default `1`), `enable_fmp_senate_trades` /
    `enable_fmp_house_trades` / `enable_fmp_8k` (env
    `ENABLE_FMP_SENATE_TRADES` / `ENABLE_FMP_HOUSE_TRADES` /
    `ENABLE_FMP_8K`, all default `0`). New limits: `fmp_general_limit`
    (50), `fmp_political_pages` (1), `fmp_8k_limit` (50).

  New tests in `tests/test_newsstack_fmp.py::TestFmpExtras`:
  Senate fetch + DISABLED short-circuit + 403-marks; political-trade
  normalize basic + FMP-typo handling; 8-K fetch + DISABLED + 404-marks;
  8-K normalize basic + synthesised-id.

  **Form-13F (B6) deferred** — it's an analytics endpoint that doesn't
  fit the news-pipeline model cleanly without CIK iteration. Will land
  separately if user opts in.

### Added (2026-05-09) — newsstack: Unusual Whales /news/headlines provider

- **`feat(newsstack): UW /news/headlines provider with DISABLED-endpoint pattern`** —
  New broad-market news provider via Unusual Whales `/news/headlines` (default-OFF
  via `ENABLE_UW_NEWS=1`). Mirrors the proven `_bz_http.py` DISABLED pattern: on
  401/403/404 the endpoint is marked permanently disabled for the process so
  subsequent polls short-circuit without burning quota. UW news items flow through
  `other_items` so they automatically participate in the cross-provider hard-dedup
  cache from PR #2104. New cursor `uw_news.last_seen_epoch` for delta polling.
  Stacked on PR #2104 (will resolve cleanly after that merges).

  Components:
  - `UnusualWhalesAdapter.fetch_news_headlines(limit, ticker)` + module-level
    `fetch_uw_news_headlines` wrapper in `newsstack_fmp/ingest_unusual_whales.py`.
  - DISABLED helpers: `is_uw_endpoint_disabled`, `mark_uw_endpoint_disabled`,
    `clear_uw_disabled_endpoints`, `UnusualWhalesEndpointDisabledError`.
  - `normalize_uw_news_headline(rec) -> NewsItem` in `newsstack_fmp/normalize.py`
    with sha1-derived id fallback. `raw` preserves UW-specific fields
    (`is_major`, `tags`, `sentiment`).
  - Pipeline sink in `newsstack_fmp/pipeline.py::poll_once` between Benzinga REST
    and the symbol-scoped providers.
  - Config flags `enable_uw_news`, `uw_news_limit` in `newsstack_fmp/config.py`;
    `active_sources` reports `uw_news` when enabled.

  New tests in `tests/test_newsstack_fmp.py::TestUWNewsHeadlines`:
  data-unwrap, disabled-short-circuit, 403/404 mark, normalize basic /
  invalid-drop / synthesised-id.

### Added (2026-05-09) — newsstack: cross-provider hard-dedup for enrichment

- **`feat(newsstack): cross-provider hard-dedup for enrichment HTTP calls`** —
  Same news cluster (chash) arriving from multiple providers in one poll cycle
  now triggers exactly ONE `Enricher.fetch_url_snippet()` HTTP call. Subsequent
  items reuse the cached snippet via a new optional `_enriched_clusters: dict`
  parameter on `process_news_items()`, threaded through `poll_once()` so the
  fmp_items batch and the other_items batch share one cache.

  `cluster_hash()` excludes `provider` (verified, was already the case), so
  FMP+Benzinga+Unusual-Whales+NewsAPI.ai variants of the same story share a
  chash. Previously the soft novelty decay scored duplicates down but each
  duplicate still ran its own enrichment HTTP call — wasting quota
  proportional to provider overlap. Each candidate now also carries a
  `cluster_dedup: bool` field for downstream observability.

  Backward compatible: parameter defaults to `None` → existing direct callers
  / tests unchanged. Soft-dedup mechanisms (`mark_seen`, `cluster_touch`
  novelty decay, `best_by_ticker` max-score selection) preserved unchanged.

  New tests in `tests/test_newsstack_fmp.py::TestCrossProviderHardDedup`:
  `test_same_cluster_skips_second_enrich`, `test_no_clusters_param_backward_compat`,
  `test_cluster_dedup_field_set_on_candidate`. All 155 newsstack_fmp tests green.

### Changed (2026-05-09) — Probe v3 cap-hit bundle (Q1–Q5b) + A1 followup

Audit-trail completion for the seven PRs merged on 2026-05-09 that closed the
Probe v3 sharded-producer cap-hit investigation. All entries doc-only here; the
behavior changes already shipped in their respective PRs. Validated end-to-end
by sharded run `25597406066` (6/6 shards green at 49.6 min / 120 min cap).

- **Q1 (PR #2095)** — `obs(workbook): per-sheet progress in canonical xlsx
  write (Step 10/10b)`. Adds per-sheet progress prints inside the Excel write
  loop in `scripts/smc_microstructure_base_runtime.py` so cap-hit / OOM
  failures during workbook assembly are localisable to a specific sheet rather
  than a vague "Step 10". Pure observability, zero behavior change.
- **Q2 + Q3 (PR #2098)** — `obs(load_daily_bars): per-batch progress + opt-in
  parallel fetch (Step 5/10)`. Adds per-batch progress in the daily-bar loader
  AND introduces opt-in parallel fetch via `DATABENTO_DAILY_MAX_WORKERS` env
  var (default = 1, behavior preserved when unset). Single PR carries Q2's
  observability + Q3's parallelism scaffold.
- **Q3a (PR #2099)** — `ci(sharded): activate parallel-fetch via
  DATABENTO_DAILY_MAX_WORKERS=4 (Q3a)`. Activates the Q3 parallel path in
  `smc-databento-production-export-sharded.yml` only (non-sharded variant left
  on default `=1`). Decision-gated by Q3 KPI evidence.
- **Q4 (PR #2097)** — `ci(sharded): bump per-shard cap 90->120 (Q4 of Probe v3
  Cap-Hit)`. Raises `timeout-minutes:` in `smc-databento-production-export-
  sharded.yml` from 90 → 120 min after Q1+Q2+Q3 instrumentation showed the
  worst-case shard wallclock approaching the 90-min cap with no further easy
  wins inside the per-shard process. Cap is per-shard, not aggregate.
- **Q5a (PR #2100)** — `remove(workbook): drop full_universe_close_trade_detail
  from canonical xlsx (Q5a — OOM mitigation)`. Removes the
  `full_universe_close_trade_detail` sheet from the canonical workbook in
  `scripts/smc_microstructure_base_runtime.py`. Cause: this sheet alone drove
  peak RSS to 6.9 GB / 7 GB on `ubuntu-latest`, OOM-killing shards 3 & 6 of
  run `25593357307` with `exit 143` + "runner has received a shutdown signal".
  Data still available via the parquet export pathway; only the in-memory
  openpyxl assembly is dropped.
- **Q5b (PR #2101)** — `Q5b: write parquet exports BEFORE canonical workbook
  (defense-in-depth)`. Reorders `_write_outputs` so all parquet artifacts are
  flushed to disk *before* the openpyxl workbook is materialised in memory.
  Ensures partial success: even if a future workbook OOM recurs, the parquet
  layer is intact and downstream consumers (rolling-bench, library-refresh)
  still have data.
- **A1 (PR #2102)** — `A1 (post-Q5b followup): watchlist comment for openpyxl
  OOM mirror site`. Adds a 14-line watchlist comment block above the
  `pd.ExcelWriter` call in `_write_base_snapshot_workbook` marking it as a
  Q5a mirror site. Pure documentation: same failure class as the sheet Q5a
  removed, currently mitigated by the chunked write loop. Comment defines
  three explicit triggers for future action and an anti-noise rule
  (dual-occurrence OR confirmed root cause). No preemptive refactor.

### Changed (2026-05-06) — F-V8-C4 / cron restructure 4×→2× + cap 120→240 min (#2066), and (2026-05-07) F-V8-C4-D doc-drift sync

- **F-V8-C4 (PR #2066, squash `5db4cfd3`)**: restructured the Databento
  producer/consumer cron pair from 4×/day to 2×/day on weekdays after
  three consecutive 120-min cap-busts (n=1/n=2/n=3, runs 25438174407,
  25446229916, 25450506584) confirmed the producer's worst-case runtime
  (~2 h 0 min on `ubuntu-latest-l`, peak RSS 18.6 GB / 32 GB) cannot
  reliably fit inside a 2 h tick. Producer cron now ticks at 12:00 /
  16:00 UTC; consumer (`smc-library-refresh`) follows 240 min later at
  16:00 / 20:00 UTC. Both `timeout-minutes` caps bumped 120 → 240 in
  lockstep with the new 4 h cron interval — anything > 240 would let a
  zombie run overlap the next tick. Per-ref `concurrency:` guards from
  F-V8-C3.1-D remain in place; the `workflow_run` fast-path trigger on
  the consumer is unchanged.
- **F-V8-C4-D (this PR)**: doc-drift sync identified by Copilot review
  of #2066 — purely comment/docstring/CHANGELOG, zero behavior change:
  - `CHANGELOG.md`: add the missing F-V8-C4 entry above (was the gap).
  - `.github/workflows/smc-databento-production-export.yml`: replace
    stale "Schedule: 12/14/16/18 UTC, 30-min headroom, 120 min cap"
    header with F-V8-C4 reality. `cron:`, `concurrency:`, and
    `timeout-minutes:` keys are unchanged (already correct).
  - `.github/workflows/smc-library-refresh.yml`: replace stale "Runs 4x
    per trading day at 13/15/17/19 UTC" header with the F-V8-C4
    schedule. Same constraint: keys unchanged, comments only.
  - `tests/test_workflow_databento_handoff_timeouts.py`: docstring
    update from "30 minutes later (12:00→12:30…)" + "2-hour cron
    interval" to F-V8-C4 reality (240 min handoff, 4 h cron). Test
    logic and pinned constants (`_PRODUCER_TIMEOUT_MAX = 240`,
    `_CONSUMER_TIMEOUT_MAX = 240`, `_CRON_HEADROOM_MIN_MINUTES = 30`)
    are unchanged.
  - **Date correction**: also corrects 7 pre-existing `2026-05-08`
    references to `2026-05-06` in the same files. The squash
    `5db4cfd3` actually landed `2026-05-06 21:24:53 UTC`
    (`author/commit time 2026-05-06 23:24:53 +0200`); the
    `2026-05-08` string was systemic doc-drift introduced during
    PR #2066 authorship. One additional reference in
    `tests/test_workflow_databento_cron_respacing.py:37` carries the
    same drift but is **out-of-scope** for this PR (file not
    otherwise touched here); follow-up cleanup recommended.
- Subsequent A8-telemetry PR #2071 added Step 9 RSS bracketing in
  `build_daily_features_full_universe` to localise the SIGTERM-after-
  39-min-silence failure mode observed in n=4 (run 25462396194) under
  the new 240-min cap. The A8 real-fix (chunking / streaming /
  intermediate release of aggregator intermediates) will follow in a
  separate PR once n=5 KPI data lands.

### Changed (2026-05-03) — main unbreaker: concurrency dup + line-shift cascade + 2 hygiene fixes

- Removed second (ref-less) `concurrency:` block from
  `smc-databento-production-export.yml` and `smc-library-refresh.yml`
  that YAML-last-wins overrode the per-ref F-V8-C3.1-D guards above.
- Re-anchored `# CONTINUE-ON-ERROR-INTENTIONAL:` marker on
  `c13-daily-cron.yml` Step 1b backfill_progress (drift from PR #2033).
- Bumped `actions/upload-artifact@v4 → @v7` on the producer stdout-log
  step and refreshed the ubuntu-latest-m comment to satisfy the runner
  pin literal check.
- Migrated `smc-live-newsapi-refresh.yml` `git push ... || echo` to an
  `if !` block so push failures surface (F-V5-F1) instead of being
  silently downgraded; cron tick still auto-recovers.
- Bulk-updated `tests/test_workflow_continue_on_error_inventory.py`
  line allow-lists for 7 workflows after PR #2033 PYTHONUNBUFFERED dedup.
- Wrapped `tests/test_workflow_databento_handoff_concurrency.py`
  parametrize source in `sorted(...)` for xdist determinism.
- Removed `public-calibration-dashboard.yml` from
  `tests/test_workflow_orphan_inventory.py::ALLOWED_ORPHANS` (now has
  test coverage).
- Moved 2026-05-01 F-V4-E1 CHANGELOG entry above 2026-04-30 v3 P-1..P-10
  block to satisfy [Unreleased] date-monotonicity pin.
- Migrated 9 scripts to import-after-`sys.path.insert` order with
  `# noqa: E402` to satisfy first-party import-order pin.

### Changed (2026-05-02) — F-V8-C3.1 PR C / runner-tier maximization (`ubuntu-latest-l` default)

- Every workflow under `.github/workflows/` now uses the unified
  expression `runs-on: ${{ vars.SMC_GH_HOSTED_RUNNER || 'ubuntu-latest-l' }}`
  for every job. Previously the repo was split 14 / 14 between literal
  `ubuntu-latest` and `${{ vars.SMC_GH_HOSTED_RUNNER || 'ubuntu-latest-m' }}`.
  The new default lifts all 28 workflows from `-m` (4 vCPU / 16 GB,
  eviction-prone, blamed for 12 consecutive Databento producer
  timeouts) to `-l` (8 vCPU / 32 GB).
- Operator escape hatch is unchanged: set
  `vars.SMC_GH_HOSTED_RUNNER` in repo Settings → Variables to override
  globally without touching code (e.g. roll back to `-m`, or test a
  larger tier).
- New pin test `tests/test_workflow_runner_pinned.py` (30 cases, one per
  workflow plus two repo-wide invariants) prevents drift: no job may
  use `ubuntu-latest` (literal) or `ubuntu-latest-m` (literal) again
  without an explicit allowlist entry.
- Composite-action constraint documented in the pin test docstring:
  `runs-on:` is a job-level key and cannot be wrapped by a composite
  action; the GitHub-Actions-native equivalent for a single source of
  truth is the repo variable + literal fallback used here.

### Documentation (2026-05-01) — V4 audit deferred-followups batch summary (#1991–#1996)

Roll-up entry for the six independent PRs that closed out the SMC Review
V4 Proactive CI/Pipeline Robustness Audit deferred-followups queue
(after Steps 1–8 + 7b shipped as #1982–#1990). Each PR carries its own
`F-V4-<class> (2026-05-01)` markers, defense ledger (where applicable),
and rollback notes:

- **#1991 — F-V4-PATHIO-DRIFT** (`fix(tests)`): bumped
  `tests/test_path_text_io_encoding_ledger.py` for
  `run_smc_e2e_smoke_test.py` ({53,97,133}→{56,100,136}) and added
  `scripts/phase5_perf_trend.py` ({163}). Drift-only ledger refresh.
- **#1992 — F-V4-D2** (`fix(ci)`): `actions/upload-artifact`
  failure-resilience audit. 4/831 unguarded sites: 2 hardened with
  `if: always()` (`fvg-quality-quartile-gate.yml`, `g23-ab-watchdog.yml`
  — diagnostic artifacts must survive failed runs); 2 documented with
  intent comments as intentional `success()`
  (`fvg-context-pine-refresh.yml`, `public-calibration-dashboard.yml` —
  publish artifacts where partial output would mislead). New defense
  ledger `tests/test_workflow_upload_artifact_unguarded_inventory.py`
  with frozen `ALLOWED_UNGUARDED` allow-list.
- **#1993 — F-V4-F3** (`fix(ci)`): workflow permissions defense ledger.
  Audit found zero workflows missing `permissions:` and zero using
  `write-all`. New defense test
  `tests/test_workflow_permissions_present.py` (parametrised over every
  workflow + global `write-all` check) prevents regression.
- **#1994 — F-V4-H2** (`fix(ci)`): pinned all 14 `runs-on: ubuntu-latest`
  sites to `ubuntu-24.04` (current `-latest` target → zero behaviour
  change today, but locks runner-image upgrades to change-control). New
  defense ledger `tests/test_workflow_runner_pinned.py` forbids floating
  `-latest` runner aliases anywhere.
- **#1995 — J3-FOLLOWUP** (`docs(ci)`): cron→`workflow_run` conversion
  candidate map at
  `docs/ci-proposals/j3-followup-cron-workflow-run-2026-05-01.md`.
  Analysis-only — documents the cascade map (8 candidate workflows
  across 4 chains), risk-orders conversions, provides `workflow_run`
  template + caveats (default-branch firing, missing inputs, head_sha
  vs main checkout, weekday filters). Recommends per-workflow follow-up
  PRs starting with `g23-ab-watchdog ← public-calibration-dashboard`.
- **#1996 — F-V4-E1** (`refactor(databento)`): routed
  `terminal_databento._fetch_chunk` through the canonical
  `_databento_get_range_with_retry` helper from `databento_client`
  (transient TLS / RemoteDisconnected / 5xx retry semantics for daily
  bars). New defense ledger `tests/test_databento_safe_fetch_callers.py`
  with frozen `ALLOWED_DIRECT_CALLERS` allow-list (`databento_client.py`
  + `databento_volatility_screener.py`, the latter having a parallel
  helper — consolidation tracked separately).

Bundled drift bumps (pre-existing main drift folded into the relevant
PRs): `tests/test_workflow_continue_on_error_inventory.py` for
`smc-deeper-integration-gates.yml` ({55,99}→{69,113}) in PRs #1992 and
#1994; `tests/test_global_statement_budget.py` for
`terminal_databento.py` (124→130, 308→314) in PR #1996.

### Changed (2026-05-01) — F-V4-E1 databento safe-fetch caller migration

- `terminal_databento._fetch_chunk` migrated from raw
  `client.timeseries.get_range` to the canonical
  `_databento_get_range_with_retry` helper from `databento_client`.
  Daily-bar fetches now inherit transient-error retry semantics
  (TLS / RemoteDisconnected / 5xx) instead of failing fast on the
  first network blip.
- New defense ledger `tests/test_databento_safe_fetch_callers.py`
  scans top-level `*.py` for raw `client.timeseries.get_range`
  callers, with a frozen `ALLOWED_DIRECT_CALLERS` allow-list
  (`databento_client.py` itself + `databento_volatility_screener.py`,
  which carries a parallel helper — consolidation tracked separately).
- Drift bump: `tests/test_global_statement_budget.py` line numbers
  for `terminal_databento.py` (124→130, 308→314) shifted by the
  helper-import + 5-line F-V4-E1 intent comment.

Consolidated entry for the v3 provider-stack audit shipped 2026-04-30.
The audit covers the following PRs (specific subset of #1951..#1969;
PRs in that range not listed here are unrelated):
#1951, #1952, #1954, #1955, #1961, #1962, #1963, #1964, #1965, #1966,
#1967, #1968, #1969. Each P-class shipped as its own PR; this is the
at-a-glance index. See `docs/BLOOMBERG_TERMINAL_PLAN.md` §10–11,
`docs/OPEN_PREP_BENZINGA_NEWS_WIRING.md` §11–12, and
`docs/FMP_ENDPOINT_GAP_ANALYSE.md` "Retired FMP Paths" for the
narrative versions.

**Added — Unusual Whales provider** (`UNUSUAL_WHALES_API_KEY`, Bearer
auth + mandatory `UW-CLIENT-API-ID: 100001` header):

- **#1965 — v3 P-3b** (`feat(providers)`): Unusual Whales adapter
  `newsstack_fmp/ingest_unusual_whales.py` + options-flow surface in
  `open_prep/streamlit_monitor.py`. Replaces ad-hoc flow gating.
- **#1967 — v3 P-4a** (`fix(providers)`): `UW-CLIENT-API-ID` header
  marked mandatory (hardcoded `100001`) per provider docs; omission may
  be enforced by the API.
- **#1968 — v3 P-4b/d** (`feat(providers)`): UW dark-pool prints,
  spot-GEX, and market-tide surfaces wired into the macro-flow tape.
- **#1969 — v3 P-4c** (`feat(providers)`): UW bulk Form-4 insider
  transactions added in parallel to the FMP insider feed.
- **#1966 — v3 P-3c** (`refactor(monitor)`): monitor insider-feed
  swapped from Benzinga to FMP + UW probe (Benzinga insider remains
  available via the Intelligence section as secondary).

**Removed — dead/redundant FMP paths:**

- **#1962 — v3 P-6** (`refactor(fmp)`): dropped FMP `fear-and-greed`
  path. Dead code with no production consumer; fear/greed sentiment
  remains covered via CNN (equity, `open_prep/sentiment_fng.py`) and
  alternative.me (crypto, `terminal_bitcoin.py`).
- **#1964 — v3 P-2** (`refactor(fmp)`): dropped FMP `short-interest`
  enrichment after FMP retired `/stable/short-interest` with no free
  replacement.

**Fixed / Standardised:**

- **#1951, #1952 — v3 P-1** (`fix(benzinga)`): corrected
  `quantified_news` endpoint path (was misconfigured / returning HTTP 400;
  post-fix the endpoint is reachable but entitlement-gated — 401 without
  the right plan); auth retained as `?token=` query param (revert in #1952).
- **#1955 — v3 P-8** (`refactor(ibkr)`): `ib_insync` → `ib_async`
  drop-in import-surface swap; `requirements.txt` pin
  `ib_async>=2.1.0`. No behaviour change for existing
  `scripts/execute_ibkr_watchlist.py`.
- **#1961 — v3 P-7** (`fix(newsapi)`): NewsAPI.ai shared `httpx`
  timeout bumped 20s → 45s; reduces false-negative timeouts on Event
  Registry feeds.
- **#1963 — v3 P-5** (`ci`): standardised the larger-runner pattern
  (`runs-on: ${{ vars.SMC_GH_HOSTED_RUNNER || 'ubuntu-latest-m' }}`)
  across long-running workflows (later pinned to `ubuntu-24.04` in
  F-V4-H2 / #1994).

**Docs-only review entries:**

- **#1954 — v3 P-9 / P-10** (`docs(audit)`): review-trail entries +
  audit-trail markers `F-V3-<class>` for the audit step itself.

### Changed (2026-04-26) — pytest-xdist as local default + determinism regression fix

- `pyproject.toml` `[tool.pytest.ini_options]` gains
  `addopts = "-n auto --dist=loadfile"`. This aligns the local default
  with the CI `validate` invocation (`pytest -n auto --dist=loadfile`)
  that has been the supported mode since the AST determinism pin
  landed in PR #104. `requirements.txt` already includes the
  `pytest-xdist>=3.6.0` requirement constraint, so no dependency-file
  change is needed.
- Fixed one determinism regression caught by
  `tests/test_pytest_xdist_parametrize_determinism.py`:
  `tests/test_hero_defaults_vocab_coverage.py:41` consumed
  `_VOCAB_MAP.items()` directly; now wrapped in `sorted(...)` so all
  xdist workers collect the same parametrize ids.
- Override locally with `pytest -n0` for interactive `pdb` debugging.
  To disable the plugin entirely, also clear `addopts`:
  `pytest -o addopts= -p no:xdist`.
- Safety rationale documented inline in `pyproject.toml`. Existing
  guards (`structure_batch._guard_against_canonical_repo_write_under_pytest`,
  `sys.executable` in subprocess tests per PR #40) remain the
  shared-state safety net.

### Tests / Quality (2026-04-26) — Defense ledger: `while True:` site lock (10 sites)

- Added `tests/test_while_true_termination_ledger.py` (1 test)
  pinning every `while True:` loop in production by `(path, line)`.
  Unbounded loops are a CWE-835 surface (loop with unreachable exit
  condition); the most common refactoring foot-gun is removing the
  only `break`/`return`/`raise` from the body. Locked sites span
  pollers, watchers, websocket runners, and signal-driven main
  loops:
  - `databento_volatility_screener.py:1051`
  - `terminal_background_poller.py:160`, `:341`
  - `databento_universe.py:248`
  - `open_prep/realtime_signals.py:2661`
  - `open_prep/macro.py:81`
  - `smc_core/resilient.py:79`
  - `newsstack_fmp/ingest_benzinga.py:498`
  - `newsstack_fmp/shared_fetch.py:265`
  - `newsstack_fmp/pipeline.py:817`
  A strict body-must-contain-`break` invariant was considered and
  rejected because some legitimate signal-driven main loops here
  rely on `KeyboardInterrupt` propagating out of an outer `try`/
  `except KeyboardInterrupt`. Pinning the (path, line) is the right
  primitive.

### Tests / Quality (2026-04-26) — Defense ledger: `subprocess.run` / `subprocess.Popen` site lock (3 sites)

- Added `tests/test_subprocess_spawn_sites_ledger.py` (4 tests)
  pinning every production process-spawn call by `(path, line)`.
  Complements the existing kwarg-shape invariants
  (`test_subprocess_run_check_invariant.py` for `check=`,
  `test_dangerous_call_tripwires.py` /
  `test_shell_true_tripwire.py` for `shell=True`) — neither covers
  *where* commands are spawned. The site ledger surfaces drift,
  doubles as a one-grep audit of every place we shell out, and
  forces a reviewer to ask "is this new shell-out actually
  necessary?". Locked sites:
  - `subprocess.run`:
    - `smc_integration/release_policy.py:1066`
      (`git rev-parse HEAD` for release-manifest provenance)
    - `open_prep/realtime_signals.py:181`
      (`pgrep` to discover daemon PID)
  - `subprocess.Popen`:
    - `open_prep/realtime_signals.py:325`
      (detached re-launch of the realtime-signals daemon)
- Defense-only — no production changes.

### Tests / Quality (2026-04-25) — Defense ledger: `os.unlink` / `os.remove` (23 sites)

- Added `tests/test_os_unlink_remove_ledger.py` (1 test) pinning every
  production `os.unlink(...)` / `os.remove(...)` call site (23 entries
  spanning the open-prep pipeline, terminal export, and newsstack
  helpers). File deletion is destructive and irreversible — locking
  the locations means:
  - drift detection: any line shift surfaces in the same PR (same
    pattern as `test_hashlib_weak_hash_ledger.py` /
    `test_nonlocal_budget.py` / `test_warnings_simplefilter_ledger.py`);
  - growth gate: new callers must explicitly extend the ledger with a
    justification in the commit message;
  - surface map: doubles as a quick audit of every place the codebase
    deletes a file. Complements
    `tests/test_dangerous_io_zero_surface_pin.py` which already
    confines `shutil.rmtree(...)` to `scripts/`.

### Tests / Quality (2026-04-25) — Defense pin: dynamic `setattr` / `hasattr` zero-surface (CWE-470)

- Added `tests/test_dynamic_setattr_hasattr_zero_surface.py` (2 tests)
  pinning the *write* (`setattr`) and *probe* (`hasattr`) reflection
  counterparts of the existing dynamic-`getattr` ledger
  (`test_dynamic_getattr_ledger.py`). Same security family (CWE-470 —
  unsafe reflection): runtime attribute names defeat static analysis,
  hide cross-module coupling, and are dangerous when any caller can
  influence the name string. Locked sites:
  - `setattr`: `terminal_live_story_state.py:50` (`_set_field` helper,
    name from a trusted in-module field-name registry)
  - `hasattr`: `streamlit_terminal.py:597` (test-mode config
    field-existence probe over a trusted override mapping)
  Literal-name calls (`setattr(obj, "field", v)` /
  `hasattr(obj, "field")`) are statically equivalent to plain
  attribute access and are intentionally not tracked.

### Tests / Quality (2026-04-25) — Defense ledger: dynamic `getattr(obj, <expr>)` (10 sites)

- Added `tests/test_dynamic_getattr_ledger.py` (1 test) pinning every
  production `getattr(obj, <non-literal>)` call site (10 entries across
  the SMC core, terminal state layers, and Streamlit alerts). Dynamic
  reflection defeats static analysis (CWE-470), hides cross-module
  coupling, and makes refactor-renames silently break. Literal-name
  `getattr(obj, "field")` is treated as safe and stays out of the
  ledger. Locking the dynamic call sites gives drift detection (line
  shifts surface here) and a growth gate (new lookups must extend the
  ledger explicitly). Same drift-protection pattern as
  `test_warnings_simplefilter_ledger.py` /
  `test_os_unlink_remove_ledger.py`.

### Tests / Quality (2026-04-25) — Defense pin: `asyncio.new_event_loop` / `asyncio.set_event_loop` zero-surface

- Added `tests/test_asyncio_event_loop_zero_surface.py` (4 tests)
  pinning the manual asyncio event-loop installation pair. Manual
  `asyncio.new_event_loop()` + `asyncio.set_event_loop(loop)` is a
  known foot-gun: it competes with `asyncio.run` on the same thread
  and produces flaky `RuntimeError: no current event loop in thread X`
  / `This event loop is already running` failures. The only
  legitimate shape is owning a loop on a non-main thread for its
  full lifetime. Locked sites:
  - `asyncio.new_event_loop`: `newsstack_fmp/ingest_benzinga.py:509`
  - `asyncio.set_event_loop`: `newsstack_fmp/ingest_benzinga.py:510`
  Both inside the `BenzingaWsAdapter._run_loop` daemon-thread entry
  point, which owns the loop for the websocket session.
- Defense-only — no production changes.

### Tests / Quality (2026-04-25) — Defense pin: `atexit.register(...)` zero-surface

- Added `tests/test_atexit_register_zero_surface.py` (1 test) pinning
  the single legitimate `atexit.register(...)` call site at
  `terminal_bitcoin.py:106` (closes a lazily-created httpx client).
  `atexit` handlers run after structured logging has been torn down,
  swallow exceptions silently, and can deadlock pytest workers / CI
  runners / Streamlit reload cycles if they block on network I/O. Any
  new call site (or any drift from that line number) fails the test
  and forces a deliberate, reviewed allow-list update.

### Tests / Quality (2026-04-25) — Defense ledger: `warnings.simplefilter("always")` (6 sites)

- Added `tests/test_warnings_simplefilter_ledger.py` (2 tests) pinning
  the 6 production `warnings.simplefilter(...)` call sites
  (`databento_volatility_screener.py:554/1573/2090/2536/2653` +
  `databento_universe.py:163`). Every site currently passes the literal
  `"always"` action — the loud / safe behavior that surfaces warnings
  to the surrounding `warnings.catch_warnings()` block. Complements
  `test_silent_security_and_boundary_bundle.py` Layer 4 (which bans
  the silent `"ignore"` counterpart) by:
  - locking the locations so any drift forces a deliberate ledger
    update in the same PR (same drift-protection pattern used by
    `test_hashlib_weak_hash_ledger.py` and `test_nonlocal_budget.py`);
  - failing if anyone flips an entry from `"always"` to `"ignore"` /
    `"default"` (second test asserts the literal action explicitly).

### Tests / Quality (2026-04-25) — Defense pin: `globals()` zero-surface

- Added `tests/test_globals_call_zero_surface.py` (1 test) pinning the
  single legitimate `globals()` call site at `streamlit_terminal.py:2226`
  (read-only `globals().get("_INTEL_ENABLED", False)` lookup whose target
  is bound by the sidebar toggle block above). `globals()` defeats
  static analysis and is the stepping stone to `globals()[name] = ...`
  mutation; the codebase has been moving toward explicit dataclass /
  TypedDict context layers (see `terminal_attention_state` /
  `terminal_posture_state`) for exactly this reason. Any new call site
  (or any drift from that line number) now fails CI and forces a
  reviewed allow-list update.
- Defense-only — no production changes.

### Tests / Quality (2026-04-25) — Defense pin: dangerous IO/process primitives zero-surface

- Added `tests/test_dangerous_io_zero_surface_pin.py` (3 tests) pinning
  three small IO/process surfaces, each currently confined to a
  known-good caller set so any new caller in production trips the guard:
  - `os.kill(pid, sig)` — process signalling. Allow-listed only as the
    two signal-0 liveness probes inside
    `open_prep/realtime_signals.py:172,198`. Any new call site (or any
    drift from those line numbers) fails the test.
  - `shutil.rmtree(...)` — recursive deletion. Allow-listed only inside
    `scripts/` (artifact-refresh tooling). Recursive deletion is
    destructive and must stay out of runtime code.
  - `socket.socket(...)` — raw socket creation. Allow-listed only
    inside `scripts/` (local port-probe helpers). Production network
    access should go through the dedicated provider clients
    (Databento/Finnhub/FMP) that already centralise retry/auth/telemetry.
- Defense-only — no production changes.

### Tests / Quality (2026-04-25) — Hotfix: ledger line-number drift after upstream merges

- Bumped frozen line numbers in two ledger tests after an upstream
  insertion in `open_prep/realtime_signals.py` and
  `databento_volatility_screener.py` shifted production lines by +1:
  - `tests/test_hashlib_weak_hash_ledger.py`: `realtime_signals.py`
    `md5` site `1009 → 1010`.
  - `tests/test_nonlocal_budget.py`: `databento_volatility_screener.py`
    `4686/4687/4688/4689 → 4687/4688/4689/4690`
    (`_fast_progress_pct/_step/_total/_eta_smooth_seconds`).
- Defense-only — no production changes. Unblocks `main` and the open
  defense-pin queue.

### Tests / Quality (2026-04-25) — Defense pin: exec / tempfile.mktemp / subprocess shell=True zero-surface

- Added `tests/test_exec_mktemp_shelltrue_zero_surface.py` (3 tests)
  pinning three classic foot-guns at zero offenders today:
  - `exec(...)` — CWE-95 (Code Injection). Closes the gap left by
    #219 which banned `eval(...)` and `pickle.load(s)`.
  - `tempfile.mktemp(...)` — CWE-377 / CWE-367 (TOCTOU race);
    deprecated since Python 2.3. Use `tempfile.mkstemp` or
    `tempfile.NamedTemporaryFile`.
  - `subprocess.*(..., shell=True, ...)` — CWE-78 (OS Command
    Injection); applies to `run / Popen / call / check_call /
    check_output`. Use list-form invocation without `shell=`.
- Defense-only — no production changes.

### Tests / Quality (2026-04-25) — Defense pin: subprocess.run(...) must pass explicit check=

- Added `tests/test_subprocess_run_check_invariant.py` (1 test) enforcing
  that every `subprocess.run(...)` call in first-party non-test code passes
  an explicit `check=` kwarg (CWE-754 — improper check of unusual or
  exceptional condition).
- Default is `check=False` → non-zero exits silently swallowed → callers
  proceed with empty stdout under the illusion of success.
- Fixed the only offender: `open_prep/realtime_signals.py:181` (the
  `pgrep` lookup) now passes `check=False` explicitly. Surface today:
  7 sites, **100% compliant**.
- Sister of the threading.Thread daemon= (#211), httpx timeout= (#208),
  mkdir/makedirs exist_ok= (#216), tempfile.NamedTemporaryFile delete=
  (#207) invariants. No ledger.

### Tests / Quality (2026-04-25) — Fix: add scripts/check_pine_legacy_drift.py to sys.path ledger

- The pre-existing `scripts/check_pine_legacy_drift.py` script bootstraps
  the repo root onto `sys.path` so it can import `scripts.pine_path_resolver`
  when invoked directly by `smc-fast-pr-gates` (rather than via
  `python -m`). The site is justified and documented in-place but had
  not been added to `tests/test_sys_path_mutation_ledger.py::_FROZEN_SITES`,
  causing the `validate` job to fail across all open PRs.
- Added the entry (count=1). No production change.
- Also bumped the frozen line for `streamlit_terminal.py`'s `global` site
  in `tests/test_global_statement_budget.py` from 602 → 603 (line drifted
  by one after the prior unrelated edit landed on `main`). No production
  change.
- Bumped further drifted ledger line numbers caused by the same +1 shift
  in `open_prep/realtime_signals.py` and an independent +1 shift in
  `databento_volatility_screener.py`:
  - `tests/test_time_sleep_budget.py`: realtime_signals 264/337/1589/2690/2703 → 265/338/1590/2691/2704
  - `tests/test_mutable_defaults_and_loads_pins.py`: realtime_signals 1455/2573/2609 → 1456/2574/2610; databento_volatility_screener 780 → 781
  - `tests/test_random_tempfile_ledger_pin.py`: realtime_signals 2495/2536 → 2496/2537; databento_volatility_screener 298 → 299
  - `tests/test_silent_security_and_boundary_bundle.py`: realtime_signals 1061/2629 → 1062/2630
  No production change — pure ledger line-number drift fix.

### Tests / Quality (2026-04-25) — Defense ledger: built-in open() text-mode without encoding=

- Added `tests/test_builtin_open_encoding_ledger.py` (5 tests) freezing
  today's surface of built-in `open(...)` text-mode calls in first-party
  non-test code that omit an explicit `encoding=` kwarg.
- Mirror of #218 (Path text-IO encoding= ledger) — same locale-fallback
  hazard (`locale.getpreferredencoding(False)` differs by platform).
- Frozen surface: **4 sites across 3 files** (all under `scripts/`).
  Total + no_new_files + per-file line invariants. Ledger may only shrink.

### Tests / Quality (2026-04-25) — Defense pin: zero-surface — dangerous builtins / os process APIs

- Added `tests/test_dangerous_builtins_zero_surface.py` (6 tests) banning
  in first-party non-test code:
  - `os.popen(...)` (CWE-78 alternative path; sister of #209's `os.system` ban)
  - `os.spawn*(...)` (legacy process-spawn family)
  - `os.exec*(...)` (process replacement)
  - `os.fork()` (bypasses our threading + asyncio model)
  - built-in `compile(...)` (CWE-95 dynamic code compilation)
  - built-in `breakpoint()` (left-in debugger)
- All six surfaces are **zero** today; this pin keeps them that way.
- Sister of #214 (pickle write + os.path.join), #219 (pickle read + eval),
  #209 (os.system / input / assert).

### Tests / Quality (2026-04-25) — Defense pin: zero-surface — pickle.load(s) read side + eval()

- Added `tests/test_pickle_read_and_eval_zero_surface.py` (2 tests) banning
  in first-party non-test code:
  - **CWE-502**: `pickle.load`, `pickle.loads`, `cPickle.load(s)`,
    `dill.load(s)`, `marshal.load(s)` — read-side counterpart of #214
    (which closed the write side).
  - **CWE-95**: built-in `eval(...)` — code injection vector.
- Both surfaces are **zero** today; this pin keeps them that way.
- Sister of #214 (pickle write side + os.path.join literal absolute),
  #212 (TLS / JWT skip-verify), #209 (os.system / input / assert).
- Defense-only — no production changes.

### Tests / Quality (2026-04-25) — Defense ledger: Path.read_text/write_text without encoding=

- Added `tests/test_path_text_io_encoding_ledger.py` (11 tests) freezing
  today's surface of `Path.read_text(...)` / `Path.write_text(...)` calls
  in first-party non-test code that omit an explicit `encoding=` kwarg.
- Default falls back to `locale.getpreferredencoding(False)` → UTF-8 on
  Linux/macOS, cp1252 on Windows containers, ASCII on stripped-down CI →
  silent encoding drift / artifact corruption.
- Frozen surface: **24 sites across 8 files**. Total + no_new_files +
  per-file line invariants — ledger may only shrink.
- Sister of #213 (silent-error-swallow ledger). Defense-only — no
  production changes.

### Tests / Quality (2026-04-25) — Defense ledger: `# noqa` suppression growth

- Added `tests/test_noqa_suppression_ledger.py` (29 tests) freezing today's
  surface of `# noqa` lint-suppression markers in first-party non-test code.
- Total + no_new_files + per-file count invariants. Ledger may only **shrink**.
- Frozen surface: **50 suppressions across 27 files**. Adding a new
  suppression requires a deliberate ledger bump in the same PR; removing
  one is welcome and leaves the test green.
- Sister of #213 (silent-error-swallow ledger), #218 (Path text-IO encoding),
  #220 (built-in open encoding). Defense-only — no production changes.

### Tests / Quality (2026-04-25) — Defense pin: mkdir / makedirs must pass explicit exist_ok=

- Added `tests/test_mkdir_makedirs_exist_ok_invariant.py` (2 tests)
  enforcing that every `*.mkdir(...)` and `os.makedirs(...)` call in
  first-party non-test code passes an explicit `exist_ok=` kwarg.
- Default is `exist_ok=False` → `FileExistsError` on the second
  invocation: race-condition + bug-on-restart foot-gun. Surface
  today: 555 `*.mkdir` + 9 `os.makedirs` sites, **100% compliant**.
- Sister of the threading.Thread daemon= (#211), httpx timeout= (#208),
  and tempfile.NamedTemporaryFile delete= (#207) invariants. No ledger.
- Defense-only — no production changes.

### Tests / Quality (2026-04-25) — Defense pin: triple zero-surface (os.system + input + assert)

- Added `tests/test_os_system_input_assert_zero_surface.py` pinning three
  cheap-to-pin invariants in first-party non-test code:
  - **CWE-78**: no `os.system(...)` calls (closes the backdoor left by the
    subprocess shell-injection pin in #201).
  - **CWE-400**: no blocking `input(...)` calls (keeps automated runs
    deterministic; surface is empty today).
  - **CWE-617**: no `assert` statements in production code (Python `-O`
    strips them; assertions belong only under `tests/`).
- Defense-only — no production changes; AST scan walks every first-party
  `*.py` and excludes `tests/`, `.venv`, `node_modules`, `artifacts`,
  `docs`, `SMC++`. Any reintroduction is a forced design decision.

### Tests / Quality (2026-04-25) — Defense pin: library-discipline zero-surface (requests / asyncio / shutil.copy)

- Added `tests/test_library_discipline_zero_surface.py` (3 tests)
  pinning three "this codebase doesn't use that library / API"
  invariants, each a deliberate architectural choice that has held
  to date:
  - **No `requests.<verb>(...)`** — codebase is exclusively on `httpx`
    (see #208). Mixing libs doubles connection-pool/TLS/timeout surface.
  - **No `asyncio.run` / `asyncio.create_task`** — codebase is
    synchronous + threaded (see the `threading.Thread` daemon= pin #211).
  - **No `shutil.copy` / `shutil.copyfile`** — both non-atomic; use the
    atomic-write helpers in `scripts/smc_atomic_write.py` (sister of #207).
- All three surfaces empty in first-party non-test code today.

### Tests / Quality (2026-04-25) — Defense pin: TLS context tampering + JWT skip-verify zero-surface

- Added `tests/test_tls_jwt_verification_zero_surface.py` (3 tests)
  pinning three "skip-the-verification" call shapes that the existing
  `verify=False` tripwire (in the silent-security bundle) does NOT catch:
  - `ssl._create_unverified_context(...)` — disables TLS hostname +
    chain verification (CWE-295).
  - `ssl.CERT_NONE` (and bare `CERT_NONE` after `from ssl import …`)
    — marker for "trust any peer cert" (CWE-295).
  - `jwt.decode(..., verify=False)` — silently accepts unsigned tokens
    (CWE-347). Repo doesn't use PyJWT today; pin prevents future drift.
- All three surfaces empty in first-party non-test code; pin keeps
  them empty.

### Tests / Quality (2026-04-25) — Defense pin: pickle write-side + os.path.join absolute-path zero-surface

- Added `tests/test_pickle_write_and_abs_pathjoin_zero_surface.py`
  (2 tests) pinning two more empty surfaces:
  - **Pickle write side** — `pickle.dump(s)` (also `cPickle` / `dill` /
    `marshal`). Symmetric guard for the read-side ban in #202: if no
    code produces pickled bytes, no code can ever be tempted to
    consume them.
  - **`os.path.join(base, "/abs")` foot-gun (CWE-22)** — `os.path.join`
    silently *discards* every component before an absolute path. Pin
    the literal-absolute case to zero (variable second args still
    require call-site sanitization).
- Both surfaces empty in first-party non-test code today.

### Tests / Quality (2026-04-25) — Defense pin: silent error swallow ledger + bare-except zero-surface

- Added `tests/test_silent_error_swallow_pin.py` (17 tests) pinning two
  closely related "errors disappear" shapes:
  - **Bare `except:`** — zero-surface invariant (catches BaseException;
    breaks Ctrl-C). 0 sites today.
  - **`except Exception: pass`** — frozen 17-site ledger across 13
    files. Mix of opportunistic best-effort cleanup, data-source
    fallbacks, and Streamlit UI guards. New silent swallows must
    either fix the swallow, log it, or extend `_FROZEN_SITES` with
    justification.
- Per-file parametrized line-drift tests + total-count + no-new-files +
  no-removed-files (same ledger pattern as the hashlib pin #206 and
  the urllib timeout ledger #204).
- Defense-only — no production changes.

### Tests / Quality (2026-04-25) — Defense pin: datetime tz-safety zero-surface (4 shapes)

- Added `tests/test_datetime_tz_safety_zero_surface.py` pinning the four
  call shapes that produce a *naive* (no `tzinfo`) datetime:
  - `datetime.utcnow()` (deprecated in Python 3.12)
  - `datetime.utcfromtimestamp(...)` (deprecated in Python 3.12)
  - `*.now()` without `tz=` / `tzinfo=`
  - `*.fromtimestamp(...)` without `tz=` / `tzinfo=`
- All four surfaces are empty in first-party non-test code today; the
  pin keeps them empty. Detection is by attribute name (covers every
  binding style: `datetime.datetime.now()`, `dt.now()`,
  `from datetime import datetime` then `datetime.now()`, etc.).

### Tests / Quality (2026-04-25) — Defense pin: threading.Thread daemon= invariant (5 sites compliant)

- Added `tests/test_threading_thread_daemon_invariant.py` enforcing
  that every `threading.Thread(...)` constructor passes an explicit
  `daemon=` kwarg. Sister of the httpx / urlopen `timeout=` invariants.
- Surface today: 5 `threading.Thread` sites across 3 files, all 100%
  compliant. No ledger to maintain — any new construction without
  `daemon=` fails CI immediately.
- Defense-only — no production changes; one test, one assertion.

### Tests / Quality (2026-04-25) — Defense pin: urllib.urlopen ledger + mandatory timeout=

New `tests/test_urllib_urlopen_ledger.py` (7 tests) — sister of the
`subprocess` shell-injection pin (#201). Two layers:

- **Layer 1 (hard invariant, CWE-1088 / availability)**: every
  `urlopen(...)` call MUST pass `timeout=` as a keyword argument. A
  missing timeout makes the caller block on a slow / hung server
  forever — the most common availability bug in Python network code.
  This is not a per-site ledger; it is an absolute invariant.
- **Layer 2 (per-(file, lineno) ledger)**: 4 sites pinned across 3
  files — `terminal_notifications.py:201,265`,
  `scripts/smc_alert_notifier.py:482`,
  `scripts/verify_branch_protection.py:103`. Refuses both new and
  removed sites; line-number-aware (similar to the
  `subprocess` ledger).

All 4 currently pass `timeout=10` or `timeout=15`. Defense-only — no
production changes.

### Tests / Quality (2026-04-25) — Defense pin: tempfile.NamedTemporaryFile mandatory delete= kwarg

New `tests/test_tempfile_namedtemp_delete_kwarg_invariant.py` (1
test) freezes the call shape: every
`tempfile.NamedTemporaryFile(...)` MUST pass `delete=` as an
explicit keyword argument. The default `delete=True` is the wrong
default for the atomic-write pattern used throughout this repo
(open temp → write → fsync → `os.replace`); without `delete=False`
the temp file vanishes before the rename and corrupts output.

Sister of #176 (which freezes the *inventory* of `tempfile.*` calls);
this pin freezes a *call shape* — different layer, same defense.
All 3 current `NamedTemporaryFile` sites already pass
`delete=False`. Defense-only — no production changes.

### Tests / Quality (2026-04-25) — Defense pin: socket.socket / bind() ledger + loopback-only invariant

New `tests/test_socket_bind_loopback_pin.py` (6 tests). Two layers:

- **Layer 1 (hard invariant, CWE-1327 / unintended-exposure)**: every
  `.bind(...)` whose host arg is a string literal MUST bind to a
  loopback address (`127.0.0.1` / `localhost` / `::1` / `127.*`).
  Calls with non-literal host args are silently skipped (the ledger
  catches their existence regardless). Empty-string host (`""` =
  all-interfaces) is explicitly forbidden.
- **Layer 2 (per-(file, lineno) ledger)**: only 1 site —
  `scripts/start_open_prep_suite.py` (`socket()@15`, `bind()@18`),
  a port-finding helper that loopback-binds to `("127.0.0.1", port)`.

### Tests / Quality (2026-04-25) — Defense pin: hashlib.md5 / sha1 weak-hash ledger

New `tests/test_hashlib_weak_hash_ledger.py` (12 tests) freezes the
inventory of weak-hash call sites: 13 sites across 8 files (`md5` and
`sha1`). All current uses are non-security fingerprints (cache keys,
dedup IDs, atomic-write content hashes) — the pin documents that and
forces any new use through review. Test message points reviewers at
SHA-256 / BLAKE2 if a new use crosses into auth / signature /
integrity territory.

Detection: direct `hashlib.md5(...)` / `hashlib.sha1(...)` plus
`hashlib.new("md5"|"sha1", ...)` constant variants. HMAC / PBKDF2 /
scrypt are out of scope (legacy-compat algorithm names internally).

Defense-only — no production changes.

### Tests / Quality (2026-04-25) — Defense pin: httpx mandatory timeout= invariant

New `tests/test_httpx_timeout_invariant.py` (2 tests) — sister of
the urllib.urlopen invariant (#204) extended to httpx, the repo's
primary HTTP client. Two call shapes covered:

- `test_every_httpx_client_constructor_passes_timeout`
  → `httpx.Client(...)` and `httpx.AsyncClient(...)` MUST pass
  `timeout=` explicitly. Today: 21 sites across 11 files, all pass.
- `test_every_httpx_module_level_verb_passes_timeout`
  → `httpx.get / post / put / delete / patch / head / options /
  request / stream` MUST pass `timeout=`. Today: 1 site
  (`terminal_notifications.py:225 httpx.post`), passes.

Out of scope: instance-method calls like `client.get(...)` (those
inherit the client's timeout, which the constructor invariant already
covers). Defense-only — no production changes.

### Tests / Quality (2026-04-25) — Defense pin: os.environ mutation site ledger

New `tests/test_os_environ_mutation_ledger.py` (AST-based, 13 tests) freezes
the inventory of `os.environ[K] = V` (WRITE) and `os.environ.setdefault(K, V)`
(SDFLT) sites in first-party production / scripts / streamlit code:
9 sites total — 6 WRITE (CA-bundle wiring + Streamlit secrets fall-through),
3 SDFLT (NewsAPI / Streamlit operator-set defaults). Refuses any new mutation
kind (`.update`, `.pop`, ...) without a ledger update. Defense-only — no
production changes.

### Tests / Quality (2026-04-25) — Defense pin: dynamic-exec + pickle zero-surface invariant

New `tests/test_dynamic_exec_and_pickle_zero_surface.py` (3 tests) freezes
two adjacent CWE families at **zero** sites in first-party code:

- **CWE-95 (dynamic exec)**: bare `eval(...) / exec(...) / compile(...)`
  builtin calls. False-positive scope is narrow — only `ast.Name` calls
  are matched, so `re.compile`, `pandas.eval`, etc. are ignored.
- **CWE-502 (unsafe deserialization)**: `pickle / cPickle / dill / marshal`
  imports AND `<mod>.load|loads|Unpickler(...)` call sites. Two-layer
  check (import + call) so even a "imported but not yet called" creep is
  flagged.

Both surfaces are currently empty; the tests are pure invariants and
require zero ledger maintenance unless someone genuinely needs to
re-open a surface (in which case the test message documents the
escape-hatch convention). Defense-only — no production changes.

### Tests / Quality (2026-04-25) — Defense pin: yaml + xml zero-surface invariant

New `tests/test_yaml_xml_zero_surface.py` (2 tests) — sister of the
`dynamic-exec + pickle` zero-surface pin — freezes two more adjacent
CWE families at **zero** sites in first-party code:

- **CWE-502 (unsafe YAML)**: `yaml.load / load_all / full_load /
  full_load_all / unsafe_load / unsafe_load_all` calls. PyYAML's
  `yaml.load` on untrusted input is arbitrary code execution; only
  `yaml.safe_load` is generally safe.
- **CWE-611 (XML / XXE)**: any import of stdlib `xml.*` or
  third-party `lxml*`. Historically all carry XXE / billion-laughs /
  external-DTD risk. Repo doesn't need XML at all today, so the
  cleanest invariant is to forbid the import surface entirely.

Both surfaces are currently empty; tests are pure invariants with no
ledger to maintain. Defense-only — no production changes.

### Tests / Quality (2026-04-25) — Defense pin: subprocess shell-injection surface

New `tests/test_subprocess_shell_injection_pin.py` (AST-based, 14 tests)
freezes two layers:

- **Hard invariant**: `subprocess.X(..., shell=True)` count must remain `0`
  in first-party code. Any new occurrence trips `test_no_shell_true_anywhere`
  (CWE-78 surface kept empty).
- **Per-(file, attr) ledger**: 11 spawn sites in 7 files
  (`run`, `Popen`, `check_output`) — adding/removing/swapping requires an
  explicit ledger bump. Refuses brand-new `subprocess.<attr>` spawning
  methods via `_SPAWN_ATTRS` allow-list.

Defense-only — no production changes.

### Fixed (2026-04-25) — main RED hotfix: continue-on-error inventory line resync

`tests/test_workflow_continue_on_error_inventory.py` `_ALLOWED` for
`smc-library-refresh.yml` was pinned to lines `{592, 735, 755}` for the three
best-effort sites (alerts dispatch, breaking-change notify, end-of-run status).
Actual offsets in the workflow on `main` are `{601, 744, 764}` (+9 line shift)
— the three sites are unchanged in content; only their position drifted. This
left every PR's `validate` job RED. Resync `_ALLOWED` to the real offsets;
no semantic change to silent-fail surface inventory (still 5 lines, same 3 hops).

### Tests / Quality (2026-04-25) — ADR-0006 Doc + Salvaged Pins from PR #123

Net-additive salvage from the closed PR #123 (`chore/smc-system-review-2026-04-24`),
which was closed as superseded after #186 shipped its production half. These five
files have **zero overlap** with anything on main and were trial-tested green
against post-#186 state (15 passed).

- `docs/adr/0006-hero-vocab-discipline.md` (NEW): ADR completing the documentation
  for the HERO vocab discipline whose runtime contract was restored by hotfix #186.
- `tests/test_adr_0005_extended_islands_audit.py` (NEW): audit pin for ADR-0005
  extended-islands invariants.
- `tests/test_hero_observed_vocab_pin.py` (NEW): observed-vocab pin — gates that
  every value emitted at runtime by `build_hero_state` belongs to the corresponding
  `HERO_*_VOCAB` frozenset (closes the gap between *defined* vocab and
  *actually-emitted* values).
- `tests/test_lru_cache_bounded_sweep.py` (NEW): cross-repo sweep that every
  `@functools.lru_cache(...)` carries an explicit `maxsize=` (companion to the
  existing `test_lru_cache_maxsize_discipline.py`).
- `tests/test_pine_library_version_consistency.py` (NEW): pin that the generated
  Pine library's `library_field_version` matches the Python-side schema version,
  so a vocab change without a version bump fails fast.

No production-code changes. No test deletions. No conflicts with the recently
merged audit wave (#186, #188–#193).

### Defense (2026-04-25) — `sys.path` Mutation Site Ledger

- New defense pin `tests/test_sys_path_mutation_ledger.py`: AST-based
  inventory of every first-party `sys.path.insert(...)` /
  `sys.path.append(...)` site, frozen by `(file, count)`. Currently
  37 files / 38 sites (only `scripts/smc_zone_priority_calibration.py`
  has count 2, two `__main__`-style entry blocks).
- Three checks: (1) no new file may introduce a mutation without a
  ledger bump in the same PR, (2) a frozen site disappearing must drop
  the entry explicitly (so we don't silently regress later), (3) the
  per-file count must match exactly. Aggregate cross-check against
  `_FROZEN_TOTAL` catches drift the per-file parametrize might miss.
- Rationale: mutating `sys.path` at import time is a load-order
  foot-gun (same `import foo` resolves differently depending on which
  script booted the process), masks packaging bugs (missing console
  scripts / `__init__.py`), and is exactly the line that has to come
  out when a script is later promoted to a CLI / module / library —
  but tends to stick around because nobody notices it. The ledger
  forces the conversation in PR review.
- AST is used so textual occurrences inside triple-quoted subprocess
  runner strings (e.g. `scripts/measure_databento_ops_run.py:116`)
  are correctly excluded.
- Defense-only — no production code changes.

### Fixed (2026-04-25) — Restore Missing HERO Vocab Constants + Bundled Ledger Drift (Main-RED Hotfix)

- **Primary fix:** `scripts/smc_hero_state.py`: restore `HERO_BIAS_VOCAB`,
  `HERO_MARKET_MODE_VOCAB`, and `HERO_RISK_VOCAB` (plus their per-value
  string constants and the `HERO_RISK_NONE = ""` Pine boundary sentinel)
  that were referenced by tests landed via PR #143 ("recover PR #126
  onto main") but whose production-side counterparts were never folded
  into `main`. CI on `main` was failing at COLLECTION with
  `ImportError: cannot import name 'HERO_BIAS_VOCAB'` since
  `ebcd622f`, blocking every open auto-merge PR (#150/#174/#175/#176).
- Refactor `_derive_bias`, `_derive_action`, and `_derive_risk` to
  return the named constants instead of bare string literals. Pure
  behavioural no-op — every literal value is preserved exactly,
  including the empty-string sentinel that gates
  `SMC_Dashboard.pine:1769` (`mp.HERO_RISK != ""`).
- Source-of-truth: extracted from PR #123
  (`chore/smc-system-review-2026-04-24`), which carries the production
  half of ADR-0006 but is otherwise blocked by extensive add/add
  conflicts with the freshly-merged pin wave.
- **Bundled drift fixes (only surfaced once collection succeeds):**
  - `tests/test_changelog_format_lint.py`: extend `ALLOWED_CATEGORIES`
    with `Defense` and `Fixes & Pins`; widen `_CATEGORY_RE` to allow
    `&` so multi-word categories like `Fixes & Pins` parse cleanly.
  - `tests/test_assert_and_open_encoding_pin.py`: drop both entries
    from `_FROZEN_OPEN_COUNTS` — `open_prep/realtime_signals.py` and
    `test_usi_lint.py` no longer have any text-mode `open()` without
    `encoding=` (PR #138 cleared them; the pin was never bumped).
  - `tests/test_assert_in_production_budget.py`: clear `_FROZEN_SITES`
    to `frozenset()` — all 4 production `assert` sites
    (`databento_volatility_screener`, `databento_universe`,
    `newsstack_fmp/ingest_benzinga`, `newsstack_fmp/shared_fetch`)
    were already removed.
  - `tests/test_nonlocal_budget.py`: bump 4 `databento_volatility_screener.py`
    `_fast_progress_*` / `_fast_eta_smooth_seconds` lines 4678–4681 → 4686–4689.
  - `tests/test_time_sleep_budget.py`: bump
    `newsstack_fmp/shared_fetch.py` 272 → 273.
- Local pin sweep: `pytest -k "ledger or pin or budget or format_lint or vocab or hero"`
  → 2439 passed, 5 skipped (was: ImportError at collection on `main`,
  cascading 14+ test failures behind it).

### Fixed (2026-04-25) — `_FROZEN_URLOPEN_SITES` Line Bump

- `tests/test_http_client_discipline.py`:
  bump `_FROZEN_URLOPEN_SITES` entry for `databento_volatility_screener.py`
  from line 1102 → 1109. The `urlopen(request, timeout=30, context=_ssl_ctx)`
  in `_download_nasdaq_trader_text` shifted 7 lines down after a
  `logger.warning(...)` was inserted above it (same root cause as the
  env-subscript bump in PR #184). Pure line drift; the call still passes
  `timeout=`.

### Fixed (2026-04-25) — `_ALLOWED` Workflow continue-on-error Line Bumps

- `tests/test_workflow_continue_on_error_inventory.py`:
  re-sync `_ALLOWED` line numbers for 5 workflows after upstream YAML
  edits. All entries are pure line drift; the same set of best-effort
  hops remains tolerated:
  - `smc-live-newsapi-refresh.yml`: 104 → 106
  - `smc-library-refresh.yml`: {162, 370, 583, 723, 740} → {165, 376, 592, 735, 755}
  - `smc-deeper-integration-gates.yml`: {51, 92} → {54, 98}
  - `plan-2-8-weekly-digest.yml`: {441, 655, 931} → {444, 661, 940}
  - `smc-release-gates.yml`: 169 → 172

### Fixed (2026-04-25) — `_FROZEN_ENV_SUBSCRIPT_SITES` Line Bump

- `tests/test_mutable_defaults_and_loads_pins.py`:
  bump frozen `os.environ[X]` subscript ledger entry for
  `databento_volatility_screener.py` from line 773 → 780. The
  assignment `os.environ[env_name] = cafile` shifted 7 lines down
  after a `logger.warning(...)` was inserted above it (no functional
  change). This unblocks the CI `validate` check that was failing
  on every PR with `AssertionError: New os.environ[X] subscript
  site(s)`.

### Fixed (2026-04-25) — Reconcile assert ledger after zero-budget migration

- `tests/test_assert_and_open_encoding_pin.py`:
  drop `_FROZEN_ASSERT_COUNTS` to `{}`. The four prod `assert`
  sites pinned by PR #166 were migrated to explicit `raise` blocks
  in PR #171 (zero-budget pin). The legacy ledger was never updated,
  so `test_assert_total_frozen` failed with `expected 4, got 0` on
  every PR. The `test_assert_no_new_files` guard remains in place
  (now paired with the dedicated zero-budget pin from #171).

### Fixed (2026-04-25) — `broad_except_silent` Line Bump

- `tests/test_broad_except_silent_budget.py`:
  bump `_FROZEN_SITES` entry for `newsstack_fmp/ingest_benzinga.py`
  from line 546 → 547. The `except Exception:` around `ws.send(auth_msg)`
  shifted by one line after upstream edits. Pure line drift; identical
  silent-handler kept. Same drift class as the env-subscript bump above.

### Tests / Quality (2026-04-25) — Extend CHANGELOG ALLOWED_CATEGORIES

- `tests/test_changelog_format_lint.py`:
  add `Hardening`, `Tests / Quality / Pine`, `Tests / Quality / Workflows`
  to `ALLOWED_CATEGORIES`. All three are in active use in `[Unreleased]`
  (introduced by merged PRs #170, #171, #177, #131, #130 etc.).
  The whitelist had lagged real usage, so the lint test was failing
  on `main`; it was masked by `pytest --maxfail=1` + alphabetical
  ordering (the assert-ledger drift fixed above failed first).

### Hardening (2026-04-25) — Pin: `sys.exit` 7-Site Ledger + bare `exit/quit` Tripwire

- Neuer Pin [`tests/test_sys_exit_ledger_pin.py`](tests/test_sys_exit_ledger_pin.py)
  mit 2 Layern:
  1. **`sys.exit` 7-Site Frozen Ledger** — alle CLI/`__main__`-Guards:
     `open_prep/{candidate_weights:241, feature_importance_report:351,
     outcome_backfill:529}`, `pine_input_surface.py:{400,402}`,
     `test_usi_lint.py:{90,93}`. Library-Code muss `raise`-en, nicht
     den Prozess killen.
  2. **Bare `exit()` / `quit()` Zero-Tripwire** — REPL-Helper, fehlen
     in embedded interpreters / stripped builds → Crash-on-Import.
     Heute 0.
- 10/10 Tests grün (1× tripwire + 2× ledger guards + 7× parametrised existence).
- Defense-only.
- OWASP A09 (Logging & Monitoring Failures — silent process termination).

### Hardening (2026-04-25) — `assert` → `raise` Migration (Production)

- Migration der 4 verbliebenen `assert`-Statements in First-Party-Production
  zu expliziten `if … : raise RuntimeError(...)`-Blöcken:
  - `databento_universe.py:314` (retry-loop type-narrowing)
  - `databento_volatility_screener.py:1116` (retry-loop type-narrowing)
  - `newsstack_fmp/ingest_benzinga.py:211` (HTTPStatusError response narrowing)
  - `newsstack_fmp/shared_fetch.py:128` (cached_payload narrowing nach reusability check)
- Hintergrund: `assert`-Statements werden unter `python -O` (Optimisation
  Mode) silently stripped — Type-Narrowing-Asserts kollabieren dann zu
  latenten `AttributeError`/`TypeError`-Bugs irgendwo downstream. Explizite
  `raise`-Statements überleben `-O` und liefern eine deterministische,
  diagnoseable Fehlerklasse.
- Pin: `tests/test_no_prod_assert_pin.py` (2 Layers — global zero-budget
  + parametrised per-site sentinel). Verhindert Regression. Ledger im
  bestehenden `tests/test_assert_and_open_encoding_pin.py` (PR #166)
  bleibt als Obergrenze; dieser Pin enforced den jetzigen Zustand (0).
- Verhalten: Bei legitimer "this can't happen"-Zustand wird `RuntimeError`
  geworfen statt `AssertionError`. Keine ID-Rotation, keine Schema-Änderung.

### Defense (2026-04-25) — `shell=True` / `os.popen` Zero-Tripwire

- Neuer `tests/test_shell_true_tripwire.py` mit 2 Layers (beide aktuell 0):
  1. **No-shell-True**: `subprocess.run/Popen/call/check_output(..., shell=True)`
     auf jeder Call-Site verboten. AST-Detection per `kw.arg=='shell'` mit
     `ast.Constant(value=True)`.
  2. **No-os.popen**: `os.popen(...)` (immer shell-mode, immer shell-injection-prone).
- OWASP A03 Defense. Codebase aktuell sauber → Tripwire lockt jede neue
  Regression sofort. Standard `_DIR_EXCLUDE`.

### Defense (2026-04-25) — Pine `var` / `varip` Declaration-Budget Pin

- Neuer `tests/test_pine_var_budget_pin.py` mit 4 Layers:
  1. **Total-Budget**: Sum aller `var`/`varip`-Deklarationen über alle
     `.pine`-Dateien ≤ 859 (current state).
  2. **No-Unledgered-File**: Jede neue `.pine`-Datei mit ≥1 Deklaration
     muss explizit ins Ledger aufgenommen werden.
  3. **No-Stale-Entries**: Ledger-Einträge müssen weiterhin existieren.
  4. **Per-File-Budget** (parametrisiert, 36 Sites): Jede einzelne Datei
     darf ihren eingefrorenen Stand nicht überschreiten.
- Top-Site: `SMC_Core_Engine.pine: 415` (Bloat-Indikator — markiert für
  künftiges Refactor in Library/Context-Module).
- Verhindert "stealth state growth" und zwingt deliberate Ledger-Updates
  bei neuen `var`/`varip`-Deklarationen.
- Ledger-Stand 2026-04-25 captured.

### Hardening (2026-04-25) — Pin: GitHub-Actions Workflow `permissions:` explizit

- Neuer Pin [`tests/test_workflow_permissions_pin.py`](tests/test_workflow_permissions_pin.py)
  prüft, dass jede Datei in `.github/workflows/*.{yml,yaml}` einen expliziten
  `permissions:`-Block deklariert — entweder Top-Level (bevorzugt, least-privilege
  als Default) oder auf jedem Job einzeln.
- Hintergrund: Ohne expliziten Block bekommt `GITHUB_TOKEN` weite Default-Schreibrechte
  (`contents`, `issues`, `pull-requests`, `checks`, …). Eine kompromittierte
  Action-Dependency könnte Code pushen, Branches löschen, Reviews dismissen.
- Stand: 21/23 Workflows hatten bereits Top-Level-`permissions:`,
  1/23 (`smc-release-gates.yml`) Job-Level (akzeptiert), 1/23
  (`manifest-pytest-poison-scan.yml`) ohne — in diesem PR mit
  `permissions: { contents: read }` versorgt.
- OWASP A05 (Security Misconfiguration) + Supply-Chain-Härtung.

### Hardening (2026-04-25) — Pin: `requirements.txt` Discipline (3-Layer)

- Neuer Pin [`tests/test_requirements_discipline_pin.py`](tests/test_requirements_discipline_pin.py)
  mit 3 Defense-Layern für `requirements.txt`:
  1. **Specifier-Pflicht** (parametrisiert per Zeile, 23 deps): jede Zeile
     muss `>=`/`==`/`~=`/`<`/`>`/`!=` tragen — keine bare `requests`-Imports
     mehr möglich.
  2. **Index-URL-Allowlist** (zero-tripwire): kein `--index-url` /
     `--extra-index-url` erlaubt — Defense gegen Dependency-Confusion.
  3. **Linecount-Budget** (gefroren bei 23): neue Deps müssen Budget
     bewusst aktualisieren, surface-growth wird im Review sichtbar.
- Future Work (nicht-blockierend): Migration zu
  `pip-compile --generate-hashes` für SHA-256-Pinning. Erfordert Wechsel
  von `>=` zu `==` (separate Entscheidung).
- OWASP A06 (Vulnerable Components) + A08 (Software & Data Integrity).

### Hardening (2026-04-25) — Pin: `random.*` + `tempfile.*` Ledger (2-Layer)

- Neuer Pin [`tests/test_random_tempfile_ledger_pin.py`](tests/test_random_tempfile_ledger_pin.py)
  mit 2 Defense-Layern:
  1. **`random.*` 1-Site Ledger** — 1 legitimer Non-Security-Site
     (`open_prep/error_taxonomy.py:111`, Retry-Jitter). Neue Sites
     müssen reviewed werden — bei Security-Verwendung ist `secrets`
     Pflicht (Mersenne Twister ist nicht kryptografisch).
  2. **`tempfile.*` Method-Allowlist + 20-Site Ledger** — nur
     `tempfile.mkstemp` erlaubt. Verbietet `mktemp` (CWE-377 Race),
     `NamedTemporaryFile(delete=False, …)` (Resource-Leaks),
     `gettempdir()` (Race-Window). Alle 20 bestehenden Sites nutzen
     bereits `mkstemp` für Atomic-Write — keine Prod-Änderungen.
- 25/25 Tests grün (2× random + 3× tempfile + 20× parametrised existence).
- Defense-only, 0 Prod-Änderungen.
- OWASP A02 (Cryptographic Failures) + CWE-377 (Insecure Temp File).

### Hardening (2026-04-25) — `usedforsecurity=False` Flag auf allen md5/sha1-Aufrufen

- An 7 Sites `usedforsecurity=False` zu bestehenden `hashlib.md5(...)` /
  `hashlib.sha1(...)` Aufrufen hinzugefügt:
  [`databento_utils.py`](databento_utils.py),
  [`databento_volatility_screener.py`](databento_volatility_screener.py) (3×),
  [`open_prep/dirty_flag_manager.py`](open_prep/dirty_flag_manager.py),
  [`open_prep/realtime_signals.py`](open_prep/realtime_signals.py),
  [`newsstack_fmp/scoring.py`](newsstack_fmp/scoring.py).
- Effekt: keine ID-Rotation (Digest-Bytes unverändert), aber explizite
  Annotation der Non-Crypto-Intent. Macht Bandit B324 / Ruff S324 stumm
  und erlaubt Ausführung unter FIPS-Mode-Interpretern, wo md5/sha1 sonst
  `ValueError` werfen.
- Neuer Pin [`tests/test_weak_hash_usedforsecurity_pin.py`](tests/test_weak_hash_usedforsecurity_pin.py)
  parametrisiert über jeden weak-hash-Aufruf und erzwingt das Flag bei
  allen zukünftigen Erweiterungen. Komplementär zum Count-Ledger aus
  PR #169 ([`tests/test_weak_hash_pin.py`](tests/test_weak_hash_pin.py)).

### Tests / Quality (2026-04-25) — Pine `alertcondition()` + Declaration-Pin

- Neuer Pin [`tests/test_pine_alertcondition_and_declaration_pin.py`](tests/test_pine_alertcondition_and_declaration_pin.py)
  fixiert zwei Pine-Surface-Eigenschaften:
  1. **`alertcondition()` Ledger**: Total = 20 in 3 Dateien
     (`SMC_Core_Engine.pine` 16, `SMC_Event_Overlay.pine` 2,
     `SkippALGO_Confluence.pine` 2). Schutz gegen unbeabsichtigtes
     Hinzufügen neuer User-sichtbarer Alert-Slots ohne Compile-Preflight-
     Registrierung.
  2. **Single-Declaration-Discipline**: Jede `*.pine`-Datei hat genau
     eine `indicator(...)`/`strategy(...)`/`library(...)` Top-Level-
     Deklaration und der Kind ist gepinnt (16 Dateien, davon 1
     `strategy` = `SMC_Long_Strategy.pine`, Rest `indicator`). Eine
     zweite Deklaration würde die erste in TradingView still
     überschatten; ein Wechsel `indicator <-> strategy` ist breaking.
- Helper `_strip_strings_and_comments` ist quote/`//`-comment-aware.
  Generiertes `_snippet.pine` ausgeschlossen. Reine Test-Schicht,
  0 Pine-Codeänderung.

### Tests / Quality (2026-04-25) — Weak-hash (md5/sha1) usage ledger

- Neuer Pin [`tests/test_weak_hash_pin.py`](tests/test_weak_hash_pin.py)
  fixiert die 13 `hashlib.md5(...)` / `hashlib.sha1(...)` /
  `hashlib.new("md5"|"sha1", ...)` Aufrufe in 8 First-Party-Prod-Modulen.
  Diese Stellen nutzen Weak-Hashes ausschließlich für **non-cryptographic
  Content-Addressing** (Cache-Schlüssel, Dirty-Flag-Fingerprints,
  Dedupe-IDs) — niemals für Auth/Integrity. Schutz gegen versehentliche
  Re-Use von md5/sha1 in Security-Kontexten und gegen unkontrolliertes
  Wachstum dieser Surface.
- 5-Layer-Defense: Total-Budget (13), no-new-files, no-stale-entries,
  parametrised per-file count, parametrised file-exists. Reine Test-
  Schicht, 0 Prod-Codeänderung.

### Tests / Quality (2026-04-25) — Pine `request.security` HTF discipline

- Neuer Pin [`tests/test_pine_request_security_htf_pin.py`](tests/test_pine_request_security_htf_pin.py)
  schützt jeden `request.security(...)`-Aufruf in den standalone `*.pine`-
  Dateien gegen Same-TF-Aufrufe. Same-TF (`timeframe.period`, `""`,
  `syminfo.period`) ist äquivalent zum normalen Series-Zugriff, kostet aber
  ein Slot des Request-Quotas und führt bei vergessenem `lookahead_off` zu
  stiller Repaint-Drift.
  - **Layer 1 — Zero-Tripwire**: `tf`-Argument darf keine der drei
    Same-TF-Konstanten sein. Inventar 0.
  - **Layer 2 — Total-Budget**: genau 3 Aufrufe in `*.pine` (alle in
    `SMC_Core_Engine.pine`: HTF-Trend `get_confirmed_structure_trend` Zeile
    2367 + 2× HTF-FVG-Detect Zeilen 4693/4694). Neue HTF-Aufrufe sind
    erlaubt, müssen aber Ledger + CHANGELOG mit aktualisieren.
  - **Layer 3 — Per-File-Ledger**: `SMC_Core_Engine.pine: 3` eingefroren.
  - **Layer 4 — Datei-Existenz**: Ledger-Datei muss existieren.
  - **Layer 5 — Inventar-Sanity**: ≥15 Pine-Dateien sichtbar.
- Defense-only — kein Pine-Code geändert.
### Tests / Quality (2026-04-25) — prod `print()` ledger

- Neuer Pin [`tests/test_prod_print_ledger.py`](tests/test_prod_print_ledger.py)
  fixiert die `print()`-Verteilung über First-Party-Prod-`*.py` (7 Dateien,
  Total = 38). Service-Code (`databento_*`, `terminal_*`, `streamlit_*`)
  loggt über `logging`; CLI-Skripte (`pine_input_surface.py`,
  `pine_apply_surface_reduction.py`, `test_usi_lint.py`) und Reporting-
  Helfer (`open_prep/{candidate_weights,feature_importance_report,
  outcome_backfill}.py`, `smc_integration/provider_health.py`) dürfen
  nach stdout schreiben. Der Pin sorgt dafür, dass kein Service-Modul
  versehentlich anfängt zu printen (würde z.B. JSON-RPC stdio oder Pine-
  Surface-Reduction-Artefakte zerstören).
- Drei-Lagen-Schutz: total-budget + no-new-files + no-stale-entries +
  parametrisierter per-File-Count + Datei-Existenz. Reine Test-Schicht.
### Tests / Quality (2026-04-25) — prod `assert` + `open()` encoding pin

- Neuer Pin [`tests/test_assert_and_open_encoding_pin.py`](tests/test_assert_and_open_encoding_pin.py)
  fixiert zwei stille Drift-Quellen:
  1. **Prod-`assert` Ledger** (4 Sites:
     `databento_volatility_screener.py`, `databento_universe.py`,
     `newsstack_fmp/ingest_benzinga.py`, `newsstack_fmp/shared_fetch.py`).
     Schutz gegen `python -O`/`PYTHONOPTIMIZE`-Builds, die `assert` zum
     No-Op machen — neue Sites zwingen Review (raise vs. ledger-bump).
  2. **Text-Mode `open()` ohne `encoding=`** (3 Sites:
     `open_prep/realtime_signals.py` ×2, `test_usi_lint.py` ×1). Verhindert
     stille Fallback-Drift auf `locale.getencoding()`. Binary-Mode
     (`"rb"`/`"wb"`) wird per AST-Mode-Literal ausgeklammert.
- Drei-Lagen-Schutz pro Layer: total-budget + no-new-files +
  no-stale-entries + parametrisierter per-File-Count + Datei-Existenz.
  Inventar-Sanity ≥30 Prod-`*.py`. Reine Test-Schicht.

### Tests / Quality (2026-04-25) — dangerous-call zero-tripwire 6-fold bundle

- Neuer Pin [`tests/test_dangerous_call_tripwires.py`](tests/test_dangerous_call_tripwires.py)
  bündelt sechs AST-Scans über first-party Prod-`*.py` — alle Inventare 0,
  reine Tripwires gegen Wiederauftauchen historisch katastrophaler
  Primitive:
  1. **`import pickle` / `from pickle import …` / `import cPickle`** —
     Pickle-Deserialisierung = Arbitrary Code Execution. Use json/msgpack.
  2. **`pickle.load(...)` / `pickle.loads(...)`** — Defence-in-Depth via
     Attribute-Call (für Re-Export-Module).
  3. **`os.system(...)`** — Shell-Injection-Vektor; spawnt Shell. Use
     `subprocess.run([...], shell=False)`.
  4. **`subprocess.<call>(..., shell=True)`** — gleiche Wurzel.
  5. **`eval(...)`** — Code aus String. Use `ast.literal_eval` für Safe-
     Constants.
  6. **`exec(...)`** — gleiche Wurzel.
- Plus Inventory-Sanity ≥30 Prod-Dateien.
- Defense-only. 0 Prod-Codeänderung.

### Tests / Quality (2026-04-25) — loopback & Docker base-image pin

- Neuer Pin [`tests/test_loopback_and_baseimage_pin.py`](tests/test_loopback_and_baseimage_pin.py)
  fixiert zwei stille Drift-Quellen:
  1. **Loopback-Ledger** (`localhost` / `127.0.0.1`): Total-Budget = 8 Sites
     plus per-File-Ledger (5 Dateien) plus Datei-Existenz-Parametrisierung.
     Verhindert sowohl heimliche neue Loopback-Bindings (Telemetry-Server,
     hartkodierte Client-URLs) als auch das versehentliche Entfernen der
     definierten Schutz-Regexes (`open_prep/alerts.py`,
     `streamlit_terminal_alerts.py`, `newsstack_fmp/enrich.py` Private-Network
     Filter).
  2. **Dockerfile FROM Form-Sanity**: genau eine `FROM`-Zeile, jede Base
     muss einen expliziten Tag oder einen `sha256`-Digest tragen, kein
     `:latest`. Schützt vor stillem Base-Image-Drift bei Rebuilds.
- Inventar-Sanity: ≥30 Prod-`*.py`. Reine Test-Schicht, keine Prod-Code-
  Änderungen.

### Tests / Quality (2026-04-25) — silent-security & boundary 6-fold bundle

- Neuer Pin [`tests/test_silent_security_and_boundary_bundle.py`](tests/test_silent_security_and_boundary_bundle.py)
  bündelt sechs Defense-Layer in einem PR:
  1. **TLS `verify=False`** in beliebigen Call-Kwargs verboten
     (httpx/requests). MITM-Schutz darf nicht abgeschaltet werden.
     Inventar 0, reine Tripwire.
  2. **`tempfile.mktemp`** verboten (Race-Condition-Klasse vor
     `mkstemp()`). Inventar 0.
  3. **stdlib `xml.*` Imports** verboten — XXE-anfällig, `defusedxml`
     verwenden. Inventar 0.
  4. **`warnings.simplefilter("ignore")` / `filterwarnings("ignore")`**
     in Production verboten — versteckt Deprecation/Runtime-Warnings.
     Inventar 0.
  5. **`logging.basicConfig(...)`** Frozen-7-Site-Ledger
     (`newsstack_fmp/run.py`, 5× `open_prep/*.py` Entry-Points,
     `smc_tv_bridge/smc_api.py`). Library-Code darf den Root-Logger
     nicht konfigurieren.
  6. **`sys.path.insert/append`** Frozen-6-Site-Ledger (Streamlit-Shims
     + `smc_tv_bridge/smc_api.py` + `open_prep/{realtime_signals,
     streamlit_monitor}.py`). Path-Hacks bleiben auf bekannte
     Entry-Point-Shims beschränkt.
- Drei-Schichten-Guard pro Ledger + parametrisierte Datei-Existenz +
  Inventar-Sanity. Defense-only.

### Tests / Quality (2026-04-25) — six-fold zero-tripwire bundle

- Neuer Pin [`tests/test_six_zero_tripwires_bundle.py`](tests/test_six_zero_tripwires_bundle.py)
  bündelt sechs zero-inventory Defense-Layer in einem PR:
  1. **Python `from x import *`** in Production verboten (linter-defeat,
     Namespace-Opazität). Inventar 0.
  2. **`pytest.mark.xfail` / `pytest.xfail()`** komplett verboten — Tests
     müssen entweder grün laufen oder mit Reason geskipt werden, xfail
     versteckt Regressions. Inventar 0.
  3. **Repo-tracked Secret-shaped Filenames**: `.env*`, `*.pem`, `*.key`,
     `id_rsa*`, `*_secret*`, `*.p12`, `*.pfx` dürfen nicht committed sein.
     Allowlist für `.env.example/.sample/.template`. Inventar 0.
  4. **Pine deprecated `study(...)`** verboten (Pine v4 → v5 mit
     `indicator(...)`). Inventar 0.
  5. **Pine `//@version=N` Pflicht** mit N ≥ 5 für alle Standalone-
     `.pine`-Dateien (Generated `_snippet.pine` Fragmente exempt).
     Erlaubt führendes Whitespace nach `//`.
  6. **YAML Workflow + docker-compose Parse-Tripwire**: alle
     `.github/**/*.yml`/`*.yaml` und `docker-compose.yml` müssen via
     `yaml.safe_load` parsen. Fängt Syntax-Bricks vor CI.
- Defense-only, keine Production-Änderungen.
### Tests / Quality (2026-04-25) — mutable defaults + json.load + os.environ subscript

- Neuer Pin [`tests/test_mutable_defaults_and_loads_pins.py`](tests/test_mutable_defaults_and_loads_pins.py)
  bündelt drei AST/Text-Layer:
  1. **Mutable default arguments** verboten (`def f(x=[])`/`{}`/`set()`/
     `list()`/`dict()`). Klassischer Python-Footgun (shared state über
     alle Calls). Inventar 0, pure Tripwire.
  2. **`json.load(...)` Site-Ledger** — 9 frozen Sites in `open_prep/`.
     Jeder Call ist eine Untrusted-Parse-Boundary; neue Sites brauchen
     Review (try/except, Size-Limit) bevor sie ins Ledger aufgenommen
     werden.
  3. **`os.environ[X]` Subscript-Ledger** — 6 frozen Sites. Subscript
     wirft `KeyError` bei fehlender Variable; neue Sites müssen
     bewusst zwischen Hard-Fail vs. `.get(X, default)` entscheiden.
- Defense-only.
### Tests / Quality (2026-04-25) — GitHub Actions trusted-publisher allowlist

- Neuer Pin [`tests/test_gha_action_allowlist.py`](tests/test_gha_action_allowlist.py)
  verlangt für jede `uses:`-Zeile in `.github/workflows/*.y*ml`
  entweder einen 40-Zeichen-SHA-Pin oder einen Eintrag in der
  eingefrorenen Trusted-Publisher-Liste (8 owner/repo: `actions/*`,
  `dawidd6/action-download-artifact`).
- Verteidigung gegen Tag-Mutation-Supply-Chain-Angriffe auf
  ungeprüfte Drittanbieter-Actions. Lokale `./...` und `docker://...`
  Actions sind ausgenommen.
- Drei-Schichten-Guard: Pin-or-allowlist, no-stale-entries, Form-Sanity
  + Inventur-Sanity (≥10 uses-Zeilen). Defense-only.

### Tests / Quality (2026-04-25) — pytest.skip per-file count budget

- Neuer Pin [`tests/test_pytest_skip_budget.py`](tests/test_pytest_skip_budget.py)
  friert die aktuelle pytest-Skip-Verteilung als per-file Budget ein
  (`_FROZEN_FILE_COUNTS`, 13 Files / 15 Skip-Sites). Drei-Schichten-Guard:
  - **No new sites:** unbekannte Files mit Skips schlagen Alarm.
  - **No count growth:** Files dürfen ihr Budget nicht überschreiten.
  - **Bidirektional:** veraltete Ledger-Einträge (Datei hat keine Skips
     mehr) müssen entfernt werden.
- Reduktionen sind explizit erwünscht; jedes Reduzieren erfordert
  Decrement im Ledger.

### Tests / Quality (2026-04-25) — bare `# type: ignore` site ledger

- Neuer Pin [`tests/test_bare_type_ignore_ledger.py`](tests/test_bare_type_ignore_ledger.py)
  friert die 15 bestehenden bare `# type: ignore` Sites ein
  (1× `newsstack_fmp/_bz_http.py`, 14× `terminal_bitcoin.py`).
  Komplementiert PR #152 (per-file Count Budget): neue Suppressions
  müssen narrowed sein (`# type: ignore[return-value]` etc.) oder mit
  Begründung ins Ledger.
- Drei-Schichten-Guard: no-new-sites + stale-entry + parametrisierte
  Datei-Existenz-Sanity. Defense-only.

### Tests / Quality (2026-04-24) — serialization & shell-injection zero-tripwires + `__all__` integrity

- Neuer Pin [`tests/test_serialization_and_shell_tripwires.py`](tests/test_serialization_and_shell_tripwires.py)
  bündelt drei Defense-Schichten:
  1. **Insecure-Deserialization-Tripwires** (CWE-502): `pickle`,
     `cPickle`, `marshal`, `shelve` — alle vier aktuell nicht in
     Production importiert. Schaltet RCE-Klasse präventiv aus.
  2. **Shell-Injection-Tripwires**: `os.system(...)` und `os.popen(...)`
     komplettieren das in PR #154 etablierte `subprocess(..., shell=True)`-
     Verbot.
  3. **`__all__`-Integritätsprüfung**: jeder via `__all__` exportierte
     Name muss tatsächlich auf Top-Level definiert oder importiert sein
     (inkl. Top-Level-If/Try-Blöcken für Optional-Dependency-Patterns).
     Fängt den klassischen "Helper gelöscht, `__all__` vergessen"-Bug.

### Tests / Quality (2026-04-24) — Pine same-TF `request.security` + legacy root tripwires

- Neuer Pin [`tests/test_pine_audit_pins.py`](tests/test_pine_audit_pins.py)
  bündelt zwei Pine-spezifische Defense-Layer:
  1. **Same-TF `request.security`-Tripwire** verbietet das stille
     No-Op-Pattern `request.security(syminfo.tickerid, timeframe.period, …)`,
     das nur die aktuelle Bar zurückgibt und unnötig die Cross-Script-
     Latenz zahlt. Aktuell 0 Treffer in allen `*.pine`-Dateien.
  2. **Pine-Legacy-Root-Tripwire** sperrt die 23 nach `pine/legacy/`
     verschobenen Skripte (BFI/CHOCH/QuickALGO/REV/USI/VWAP/etc.)
     gegen ein Wieder-Auftauchen im Repo-Root. Bidirektionaler
     Inventar-Check stellt sicher, dass die Ledger-Einträge unter
     `pine/legacy/` existieren — verhindert Silent-Drift in beide
     Richtungen.
- Defense-only, keine Production-Änderungen.

### Tests / Quality (2026-04-24) — `# type: ignore` per-file count budget

- Neuer Pin [`tests/test_type_ignore_budget.py`](tests/test_type_ignore_budget.py)
  fixiert die `# type: ignore`-Suppressionen pro Datei als Budget
  (Zeilen-genaue Ledger wären zu churn-anfällig in den dichten
  pandas/streamlit-Bridge-Files). Aktuell 19 Dateien / 81 Suppressions
  (top: `terminal_bitcoin.py` 18, `open_prep/streamlit_monitor.py` 18,
  `terminal_poller.py` 13). Drei-Schicht-Schutz: kein Datei-Count darf
  über sein Budget steigen, neue Dateien dürfen ohne Ledger-Eintrag
  gar keine `# type: ignore` einführen, und Stale-Einträge werden
  geflaggt. Reduktion erwünscht — fallender Count soll Budget senken.

### Tests / Quality (2026-04-24) — `nonlocal` keyword frozen-inventory budget

- Neuer Pin [`tests/test_nonlocal_budget.py`](tests/test_nonlocal_budget.py)
  fixiert die 5 bekannten `nonlocal`-Sites (4× progress-bar-Closure in
  `databento_volatility_screener.py`, 1× weighted-aggregate Accumulator
  in `smc_core/ensemble_quality.py`). Drei-Schicht-Schutz:
  Tripwire gegen neue Sites, parametrisierter Stale-Site-Test und
  Inventur-Parität. Per-Site Namen-Tuple wird gefroren — fängt also
  auch stille Erweiterungen einer bestehenden `nonlocal`-Deklaration.

### Tests / Quality (2026-04-24) — dynamic-execution & shell-injection zero-tripwires

- Neuer Pin [`tests/test_dynamic_exec_and_shell_tripwires.py`](tests/test_dynamic_exec_and_shell_tripwires.py)
  bündelt fünf Zero-Inventory-Tripwires:
  `exec(...)`, `eval(...)`, `compile(...)`, `input(...)` und
  `subprocess.{run,Popen,call,check_call,check_output}(..., shell=True)`.
  Aktuelle Production-Inventur: **0 Treffer für jeden** — pure Tripwires
  gegen Wiedereinführung von Arbitrary-Code-Execution- bzw.
  Shell-Injection-Vektoren.
- AST-basiert: bare-Name-Call für die Builtins (vermeidet False-Positive
  auf pandas/numpy `df.eval(...)`-Methode), Attribute- oder Name-Call
  mit `shell=True`-Konstante für die subprocess-Variante.
- Defense-only, keine Production-Änderungen.

### Tests / Quality (2026-04-24) — no eager-format in `logger.<level>(...)` calls

- Neuer Pin [`tests/test_no_eager_format_in_logger_calls.py`](tests/test_no_eager_format_in_logger_calls.py)
  verbietet eager-evaluierte Message-Templates an Logger-Methoden in
  Produktion. Logger-API will ein **Lazy**-Format-Template + positional
  args, damit die Interpolation erst nach dem Level-Filter passiert
  und structured-log-Handler die Argument-Trennung sehen.
- AST-Erkennung deckt drei eager-Formen am ersten Message-Argument ab
  (zweites bei `logger.log(LEVEL, msg, …)`):
  1. **f-string** (`ast.JoinedStr`)
  2. **`%`/`+`-BinOp** auf Strings (`"foo %s" % bar`, `"foo " + bar`)
  3. **`.format(...)`** Call
- Logger-Detection: `logger`/`log`/`_logger`/`_log`/`LOGGER`/`LOG` als
  `Name` oder `Attribute`-Zugriff (deckt `self.logger.info(...)` und
  `cls._log.info(...)` ab); Methoden-Set
  `{debug, info, warning, warn, error, critical, exception, log}`.
- Aktuelle Inventur: **0 Verstöße** in Production-`*.py` — pure
  Tripwire, kein Allowlist nötig. Closes "f-string baut Message immer,
  auch bei DEBUG-off" Bug-Klasse + Performance-Falle bei teuren `repr`-
  Aufrufen in disabled Levels.
### Tests / Quality (2026-04-24) — `# noqa` frozen-inventory budget (with code-set capture)

- Neuer Pin [`tests/test_noqa_budget.py`](tests/test_noqa_budget.py)
  friert die aktuelle Inventur von 27 `# noqa`-Suppressions in
  First-Party-Production ein. Kategorien aktuell:
  - `F401` (re-export only `__init__.py` imports — `terminal_tabs`)
  - `E402` (deferred imports nach `sys.path`-Manipulation / atexit)
  - `F401, F811` (typing-only optional imports — `terminal_bitcoin`)
  - `PLW0603` (Modul-Singleton `global` — bereits via
    `test_global_statement_budget.py` separat gepinnt)
  - `PERF203` (explicit retry-loop `try/except` shape)
  - `ANN001` (`*args, **kwargs` callback signature)
- Ledger erfasst zusätzlich das exakte Code-Set je Site — wenn
  jemand stillschweigend eine Suppression erweitert (z.B. `F811` zu
  einem bestehenden `# noqa: F401` hinzufügt), schlägt der Stale-Site-
  Guard mit dem Code-Tuple-Vergleich an.
- Drei Schichten: no-new-sites Tripwire + parametrisierter Stale-Site-
  Guard (line + sorted-codes tuple) + bidirektionale Inventur-Parity.
  Jede neue `# noqa` zwingt Review (could the lint be fixed instead?).
- 30 Tests grün, keine Produktions-Anpassungen nötig. Closes
  "stille Lint-Suppression-Erweiterung" Bug-Klasse.

### Tests / Quality (2026-04-24) — `__import__()` budget + TODO/FIXME zero-tripwire

- Neuer Pin [`tests/test_dynamic_import_and_todo_tripwires.py`](tests/test_dynamic_import_and_todo_tripwires.py)
  bündelt zwei Defense-Schichten:
  1. **`__import__("...")` budget**: 5 bekannte Lazy-Import-Sites in
     `open_prep/streamlit_monitor.py` (Streamlit-Reload-Hot-Path,
     `time.{time,monotonic}` Import inside-fence) eingefroren via
     no-new-sites Tripwire + parametrisierter Stale-Site-Guard +
     bidirektionale Inventur-Parity. Jeder neue `__import__`-Call
     fordert bewussten Review (top-level `import` oder
     `importlib.import_module(...)` bevorzugen, damit static-analysis
     und Dependency-Graphen die Dependency sehen).
  2. **TODO/FIXME/XXX/HACK zero-tripwire**: Production-Code enthält
     aktuell **0 Marker** in Comments — alle Notes leben in `docs/`,
     `scripts/` und Tracker. Reine Tripwire — neuer Marker forciert
     Issue-Filing, Fix oder Move-to-docs. Whole-word Match in
     Comment-Position (`# … TODO …`), keine String/Identifier-False-
     Positives.
- 9 Tests grün, keine Produktions-Anpassungen nötig. Closes
  "stille Lazy-Imports + verwesende Marker rutschen rein" Bug-Klasse.

### Tests / Quality (2026-04-24) — `time.sleep(...)` frozen-inventory budget

- Neuer Pin [`tests/test_time_sleep_budget.py`](tests/test_time_sleep_budget.py)
  friert die aktuelle Inventur von 26 `time.sleep(...)`-Sites in
  First-Party-Production ein. Alle 26 sind legitim:
  - Rate-Limit zwischen API-Calls (TradingView 429, FMP, Benzinga)
  - Retry-Backoff (exponential `2 ** attempt`)
  - Inter-Poll-Throttle (Streamlit/realtime poll loops)
  - SQLite-Contention-Backoff
- Drei Schichten: no-new-sites Tripwire + parametrisierter Stale-Site-
  Guard + bidirektionale Inventur-Parity. Jede neue `time.sleep`-Site
  fordert bewussten Review (asyncio? threaded worker? statt
  fixed wall-clock pause? `await asyncio.sleep(...)`?).
- 29 Tests grün, keine Produktions-Anpassungen nötig. Closes
  "stiller Event-Loop-Block / Spin-Wait rutscht rein" Bug-Klasse.

### Tests / Quality (2026-04-24) — `global` statement frozen-inventory budget

- Neuer Pin [`tests/test_global_statement_budget.py`](tests/test_global_statement_budget.py)
  friert die aktuelle Inventur von 26 `global`-Statements in
  First-Party-Production ein (alle dokumentierte Modul-Singletons:
  TradingView/Finnhub 429-Backoff-Counter, Lazy-Provider-Singletons in
  `newsstack_fmp/pipeline.py`, Regime-State-Remembrance,
  Streamlit-Tab-Availability-Flags, Databento Quote/Dataset Caches).
- Ledger erfasst zusätzlich die deklarierten Namen je Site — wenn
  jemand stillschweigend einen neuen Namen an ein bestehendes
  `global` anhängt, schlägt der Stale-Site-Guard an (Names-Tuple
  Vergleich).
- Drei Schichten: no-new-sites Tripwire + parametrisierter Stale-Site-
  Guard (line + names tuple) + bidirektionale Inventur-Parity. Jeder
  neue `global` zwingt Review (class attribute? injected dependency?
  `contextvars.ContextVar`?).
- 29 Tests grün, keine Produktions-Anpassungen nötig. Closes
  "stille neue Modul-State-Mutation rutscht rein" Bug-Klasse.

### Tests / Quality (2026-04-24) — `except Exception: pass` defense pin (frozen-inventory budget)

Defense-Pin friert die aktuelle Anzahl und exakten Locations aller
`except Exception: pass` (und `: continue`) Sites in First-Party-
Produktionscode ein. Klasse "broad-except + silent body" schluckt
Exceptions ohne Spur — Bugs werden so unsichtbar. Wir haben 11
legitime Sites (DNS-Best-Effort, `conn.close()`, optionales
`yfinance`/`ws`, Module-Import-Fallback, Wall-Clock-Fallback); statt
jeden zu refactorn, frieren wir den Stand ein und blocken neue Sites.

**Defense-Pin (`tests/test_broad_except_silent_budget.py`)**

AST-Walk über alle First-Party `*.py` (Top-Level + Subdirs außer
`tests/`, `scripts/`, `docs/`, `SMC++/`, Caches, Venvs). "Broad" =
`except Exception`, `except BaseException`, bare `except:`, oder
Tuple das einen davon enthält. Spezifische Exception-Typen
(`OSError`, `ValueError`, …) sind explizit nicht abgedeckt.

`_FROZEN_SITES` enthält alle 11 vorhandenen Sites als
`(rel_path, lineno)`. Drei Sub-Tests:

1. `test_first_party_files_present` — Pfaddrift-Wächter (≥ 50 Dateien).
2. `test_no_unexpected_broad_except_silent_sites` — neue Sites lassen
   die Suite fail; PR-Author muss entweder Exception-Typ verengen +
   loggen, oder Site mit Justification in `_FROZEN_SITES` aufnehmen.
3. `test_frozen_sites_still_match` — parametrierter Stale-Check
   (13 Tests, einer pro Eintrag): Refactors, die einen Site verschieben,
   müssen die Linenummer im selben PR aktualisieren.

**Production behaviour unchanged.** Reine Tripwire — kein Code-Change.

**Warum jetzt:** Die 11 Sites sind real, intentional, und werden ohne
Pin schleichend mehr. Defense-Pin pro frozen-inventory ist das
gleiche Pattern wie FDR/SPRT vocab pins — billig (sub-Sekunde, AST
only) und blockt eine ganze Bug-Klasse strukturell.
### Tests / Quality (2026-04-24) — HTTP client discipline: no `requests` library + urllib `urlopen()` timeout pin

- Neuer Pin [`tests/test_http_client_discipline.py`](tests/test_http_client_discipline.py)
  bündelt zwei Schutzschichten über denselben First-Party-AST-Walk:
  1. **`requests`-Library bleibt out-of-bounds in Production.** Codebase
     hat auf `httpx` standardisiert (Quartett: budget × singleton ×
     timeout-consistency × named-timeout). Jeder neue `import requests`,
     `from requests import …` oder `requests.<method>(...)`-Call würde
     diese Disziplin lautlos umgehen → reine Tripwire, kein Allowlist
     (Inventur aktuell 0).
  2. **`urlopen(...)` muss `timeout=` mitgeben.** `urllib.request.urlopen`
     defaultet auf einen blockierenden Socket ohne Timeout → kann einen
     Worker-Thread unbegrenzt festsetzen. Alle 8 aktuellen
     Produktions-Sites passen `timeout=` (mixed: bare `urlopen` nach
     `from urllib.request import urlopen` und qualified
     `urllib.request.urlopen`). Frozen-Site-Tripwire + parametrisierter
     Stale-Site-Guard sperrt die Inventur ein.
- 12 Tests grün, keine Produktions-Anpassungen nötig.

### Tests / Quality (2026-04-24) — `assert` in production code defense pin (frozen-inventory budget)

Defense-Pin friert die aktuelle Anzahl und exakten Locations aller
`assert`-Statements in First-Party-Produktionscode ein. `assert` wird
unter `python -O` / `PYTHONOPTIMIZE=1` vom Interpreter komplett
entfernt — jede Logik, die darauf beruht (Runtime-Contracts oder
Type-Narrowing für mypy/pyright), ändert in Optimised-Builds still ihr
Verhalten. Latente Bug-Klasse, auch wenn jeder Einzelort heute "klar
sicher" aussieht.

**Defense-Pin (`tests/test_assert_in_production_budget.py`)**

AST-Walk über alle First-Party `*.py` (Top-Level + Subdirs außer
`tests/`, `scripts/`, `docs/`, `SMC++/`, Caches, Venvs). Sammelt jeden
`ast.Assert`-Knoten.

`_FROZEN_SITES` enthält die 4 vorhandenen Sites — alle sind narrow
`assert <var> is not None`-Type-Narrowing-Crutches direkt vor dem
Use-Site:

- `databento_volatility_screener.py:1109` — Retry-Loop `last_error`
- `databento_universe.py:314` — Retry-Loop `last_error`
- `newsstack_fmp/ingest_benzinga.py:211` — `httpx` response narrowing
- `newsstack_fmp/shared_fetch.py:128` — Cache-Payload narrowing

Drei Sub-Tests:

1. `test_first_party_files_present` — Pfaddrift-Wächter (≥ 50 Dateien).
2. `test_no_unexpected_assert_sites` — Tripwire: jeder neue `assert`
   schlägt fehl. Autor muss entweder durch explizites
   `if not …: raise` ersetzen (bevorzugt für Runtime-Contracts), oder
   — nur falls es ein narrow Type-Narrowing-Crutch direkt am Use-Site
   ist — den Eintrag mit Begründung zu `_FROZEN_SITES` hinzufügen.
3. `test_frozen_sites_still_match` (parametrisiert, 4 Einträge) —
   zwingt Refactors, Linenos in derselben PR mitzuziehen; verhindert
   dass das Inventar zu einer Free-Pass-Liste verfault.

**Produktionsverhalten unverändert.** Reines AST-Tripwire,
sub-Sekunde. Gleiches Defense-Pin-Pattern wie FDR / SPRT-Vocab /
broad-except.

### Tests / Quality (2026-04-24) — Blocking `subprocess.*` timeout discipline (+1 production fix)

Schließt einen CI-Hänger-Korridor: blockierende `subprocess`-Aufrufe
(`run`, `check_output`, `check_call`, `call`) warten ohne `timeout=`
unbeschränkt auf das Kind. Genau diesen Bug hatten wir bereits einmal
am `git rev-parse HEAD`-Site in `smc_integration/release_policy.py` —
wenn das lokale Git unter Lock-Contention oder auf einem Network-FS
festhängt, wedget der ganze Job.

**Tripwire-Pin (`tests/test_subprocess_timeout_discipline.py`)**
AST-Walk über alle First-Party `*.py` (Top-Level + Subdirs außer
`tests/`, `scripts/`, `docs/`, `SMC++/`, Caches, Venvs). Fail wenn ein
`subprocess.<run|check_output|check_call|call>(...)` ohne `timeout=`
auftaucht. `subprocess.Popen` ist **bewusst exempt** — es ist das
Launch-Primitiv für detached, langlaufende Kinder (z. B. der
`open_prep/realtime_signals.py`-Engine-Boot), wo ein Timeout am Spawn
selbst keinen Sinn ergibt. Drei Sub-Tests:

1. `test_first_party_files_present` — Pfaddrift-Wächter (≥ 50 Dateien).
2. `test_blocking_subprocess_calls_specify_timeout` — die Disziplin.
3. `test_site_allowlist_entries_still_apply` — parametrierter
   Stale-Allowlist-Wächter (Allowlist startet leer).

**Production Fix (1 Site)**

- `smc_integration/release_policy.py:1059` — `resolve_git_commit()` ruft
  `git rev-parse HEAD` ohne Timeout. Hängendes Git → CI hängt unbegrenzt.
  Fix: neuer Modul-Konstant `_GIT_REV_PARSE_TIMEOUT = 5.0` (lokales Git
  antwortet im Millisekundenbereich; lieber Commit-Hash verlieren als
  Job wedgen) und Übergabe an `subprocess.run(..., timeout=…)`.

**Warum jetzt:** Vervollständigt die Timeout-Disziplin-Familie:
**httpx** Quartett (Budget × Singleton × Timeout-Konsistenz × Named-Timeout)
+ jetzt **subprocess** Blocking-Timeout-Pin. Gleiche Bug-Klasse "default
unbounded wait" für die zwei wichtigsten Out-of-Process-Kanäle
geschlossen.

### Tests / Quality (2026-04-24) — terminal_*.py httpx timeout named-constant discipline

- Neuer Pin [`tests/test_terminal_httpx_timeout_named.py`](tests/test_terminal_httpx_timeout_named.py):
  AST-walk über alle `terminal_*.py`-Module. Jeder
  `httpx.Client(timeout=…)`-Konstruktor und jeder direkte Call von
  `httpx.{get,post,put,delete,patch,head,options,request,stream}(...)`
  mit explizitem `timeout=`-kwarg muss als Wert eine `Name`/`Attribute`
  -Referenz übergeben (z.B. `_API_TIMEOUT`) — keine bare numerische
  Literale. Macht Timeouts auf Modul-Ebene grep-bar und auditierbar.
  Site-Allowlist + Stale-Entry-Test (aktuell leer).
- Companion zur Per-Script httpx-Schutzschicht aus PR #133:
  budget × singleton-guard × timeout-consistency × **named timeout**.

**Produktions-Anpassungen** (zwei harmlose Konstanten-Promotions, damit der Pin universell anwendbar ist):
- `terminal_bitcoin.py`: neue Modul-Konstante `_API_TIMEOUT = 15.0`;
  `httpx.Client(timeout=15.0)` und `make_fmp_client(..., timeout_seconds=15.0)`
  konsumieren jetzt `_API_TIMEOUT`.
- `terminal_notifications.py`: neue Modul-Konstante `_WEBHOOK_TIMEOUT = 10`;
  Discord-Webhook `httpx.post(..., timeout=10)` konsumiert jetzt
  `_WEBHOOK_TIMEOUT`.

### Tests / Quality (2026-04-24) — `open()` text-mode encoding discipline (+3 production fixes)

Schließt eine plattform-abhängige Quelle für stillen Daten-Drift in
First-Party-Produktionscode. Pythons Default-Textencoding ist OS-abhängig
(macOS/Linux: `utf-8`, Windows: `cp1252`); fehlt `encoding=` an einem
text-mode `open(...)`, schreibt/liest derselbe Code je nach Host
unterschiedliche Bytes — eine Klasse von Bug, die wir bei `.env`- und
Lock-Dateien bereits gesehen haben.

**Tripwire-Pin (`tests/test_open_encoding_discipline.py`)**
AST-Walk über alle First-Party `*.py` (Top-Level + Subdirs außer
`tests/`, `scripts/`, `docs/`, `SMC++/`, Caches, Venvs). Jeder
`open(...)`-Aufruf, der text-mode ist (Default oder Mode ohne `b`) und
kein `encoding=`-Keyword führt, lässt die Suite rot werden. Binär-Modi
(`"rb"`, `"wb"`, `"ab"`, `"r+b"`, …) sind exempt. Statisch nicht
auflösbare Modi gelten konservativ als Text. Drei Sub-Tests:

1. `test_first_party_files_present` — Pfaddrift-Wächter (≥ 50 Dateien).
2. `test_open_calls_specify_encoding` — die eigentliche Disziplin.
3. `test_file_allowlist_entries_still_apply` — parametrierte
   Allowlist-Hygiene (Allowlist aktuell leer, kein Eintrag verschimmelt).

**Production Fixes (3 Sites)**

- `open_prep/realtime_signals.py:251` — Engine-Lockfile
  (`open(_RT_ENGINE_LOCK_FILE, "w")` → `encoding="utf-8"`).
- `open_prep/realtime_signals.py:2601` — Stdlib-Fallback `.env`-Loader.
- `test_usi_lint.py:6` — Top-Level Pine-Linter.

**Warum jetzt:** Defense-in-Depth-Tripwire (sub-Sekunde, AST only)
gegen die Klasse "silent platform-dependent default". Allowlist startet
leer und wird durch den Stale-Check selbst gepflegt.

### Tests / Quality (2026-04-24) — SPRT decide() AST + Decision-Consumer Coverage + httpx Timeout Consistency + Test-File Naming + CHANGELOG Unreleased Format

Fünf kleine Tripwire-Pins, alle ohne Surface-Risiko (regression-guard):

**SPRT `decide()` AST Return-Literal Pin**

- Neuer Pin [`tests/test_sprt_decide_ast_return_literal.py`](tests/test_sprt_decide_ast_return_literal.py):
  AST-Walk über [`scripts/smc_sprt_stop_rule.py`](scripts/smc_sprt_stop_rule.py)`::decide`
  stellt sicher dass *jeder* `Return`-Knoten ein `Constant(str)` aus
  dem 5er-Vocab ist (kein dynamisches `f"..."`, keine Variable).
  Schließt die "structural ↔ usage"-Lücke zur Vocab-Membership-Pin
  von PR #133. (3 tests)

**SPRT Decision-Consumer Coverage Pin**

- Neuer Pin [`tests/test_sprt_decision_consumer_coverage.py`](tests/test_sprt_decision_consumer_coverage.py):
  jede Datei unter `scripts/` die SPRT-Decision-Sentinels referenziert
  muss ≥ 2 verschiedene Sentinels nutzen, oder explizit auf
  `_SINGLE_BRANCH_ALLOWLIST` stehen. Verhindert silent fall-through
  bei Vocab-Erweiterung. Allowlist-Stale-Test fängt veraltete
  Einträge. (3 tests)

**httpx.Client Timeout-Consistency Pin**

- Neuer Pin [`tests/test_newsapi_ai_client_timeout_consistency.py`](tests/test_newsapi_ai_client_timeout_consistency.py):
  ergänzt PR #133's Budget+Guard-Pin um Wert-Konsistenz: alle 4
  `httpx.Client(timeout=20.0)` müssen denselben Timeout haben. (2 tests)

**Test-File Naming-Convention Pin**

- Neuer Pin [`tests/test_test_file_naming_convention.py`](tests/test_test_file_naming_convention.py):
  jede `tests/test_*.py` muss ≥ 1 `def test_*` definieren — sonst
  dead test code (kein pytest-discovery). Allowlist für legacy
  module-level-assert smoke-scripts. (3 tests)

**CHANGELOG Unreleased-Subsection Format Pin**

- Neuer Pin [`tests/test_changelog_unreleased_subsection_format.py`](tests/test_changelog_unreleased_subsection_format.py):
  jede `### `-Subsection im `## [Unreleased]`-Block ab Enforcement-
  Datum 2026-04-22 muss canonical format folgen:
  `### <Category> (YYYY-MM-DD) — <Title>` (em-dash U+2014). Historische
  Einträge grandfathered. (2 tests)

**Acceptance**

- 13/13 neue Tests grün (3 + 3 + 2 + 3 + 2).

**Pattern-Notes**

- SPRT-Schutz jetzt 3-fach: Vocab-Membership (PR #133) ×
  Producer-Struktur (decide-AST) × Consumer-Coverage.
- httpx-Schutz jetzt 3-fach: Budget × Guard × Timeout-Consistency.
- CHANGELOG-Pin ist date-scoped (≥ 2026-04-22) — convention-
  introduction ohne historischen Big-Bang.

### Tests / Quality (2026-04-24) — SPRT Decision Vocab + httpx Client Budget + Float-Eq Discipline + Pine Security Per-File Budget

Vier kleine Pins, alle Tripwire/Budget-Stil:

**SPRT Decision Vocab Pin**

- Neuer Pin [`tests/test_sprt_decision_vocab_pin.py`](tests/test_sprt_decision_vocab_pin.py):
  friert die 5er-Membership des `Decision`-Literal in
  [`scripts/smc_sprt_stop_rule.py`](scripts/smc_sprt_stop_rule.py)
  ein (`continue`, `accept_h0`, `accept_h1`, `max_n_reached`,
  `inconclusive`), prüft `INCONCLUSIVE_DECISIONS ⊆ Decision`, und
  verifiziert dass `decide()` / `evaluate()` / `terminal_decision()`
  vocab-member zurückgeben (nicht `None` / free-form). Verhindert
  silent gate-deadlock bei Decision-Drift. (6 tests)

**NewsAPI httpx.Client Instantiation Budget**

- Neuer Pin [`tests/test_newsapi_ai_client_instantiation_budget.py`](tests/test_newsapi_ai_client_instantiation_budget.py):
  friert Anzahl der `httpx.Client(...)` Konstruktionen in
  [`scripts/smc_newsapi_ai.py`](scripts/smc_newsapi_ai.py) auf 4
  (eine Fallback pro public fetch). Jede Konstruktion muss
  `if client is None:` guard ≤ 3 Zeilen davor haben. Bei 5. Fetch:
  shared `_get_or_create_client(client)` helper extrahieren statt
  Budget bumpen. (3 tests)

**`smc_core/` Float-Equality Discipline (Regression-Pin)**

- Neuer Pin [`tests/test_smc_core_float_equality_discipline.py`](tests/test_smc_core_float_equality_discipline.py):
  verbietet `==` / `!=` gegen Float-Literale (`0.0`, `1.5`, `2e-3`)
  in `smc_core/*.py`. Discovery: smc_core 100% sauber — Pin friert
  das gegen ULP-Equality-Regression ein. Konvention:
  `math.isclose(...)` für Wertvergleich, `abs(x) < eps` für
  Zero-Check. (2 tests)

**Pine `request.security` Per-File Budget**

- Neuer Pin [`tests/test_pine_request_security_per_file_budget.py`](tests/test_pine_request_security_per_file_budget.py):
  ergänzt PR #132's qualitative Discipline um quantitatives Budget:
  - `SMC_Core_Engine.pine` ≤ 6 Calls (current=5)
  - `SMC++/smc_utils.pine` ≤ 5 Calls (current=4)
  Neue Calls forcieren explizite Budget-Bumps. Stale-Entry-Test
  fängt verschwundene/leere Budget-Einträge. (2 tests)

**Acceptance**

- 13/13 neue Tests grün (6 + 3 + 2 + 2).

**Pattern-Notes**

- Vocab-Triangle wächst: SPRT `Decision` ist die 5. eingefrorene
  Vocab-Surface (nach `HERO_TRUST`, `HERO_SETUP_QUALITY`,
  `HERO_ACTION`, `TrustState`).
- Budget-Pins komplementär zu Discipline-Pins (PR #132 D verbietet
  *was nicht erlaubt*, dieser PR limitiert *wieviel erlaubt*).
- Float-Eq-Pin erneut "freeze the good state" — Audit-Backlog wandert
  von Bug-Fix zu Regression-Guard.

### Tests / Quality (2026-04-24) — FDR Defense + CHANGELOG Date Monotonicity + terminal_*_state Import Boundary

Drei reine Tripwire-Pins (8 Tests, alle grün lokal):

**A — A/B-Comparison FDR-Defense**
- Neuer Pin [`tests/test_run_ab_comparison_fdr_defense.py`](tests/test_run_ab_comparison_fdr_defense.py):
  AST-walked Strukturschutz für `scripts/run_ab_comparison.py`. Pinnt
  Präsenz von `benjamini_hochberg`/`_family_fdr_layer`-Defs, dass
  `FDR_Q` ein `float`-Literal in (0, 1) bleibt, und dass `compare()`
  den `_family_fdr_layer` aufruft. Verhindert stilles Entkoppeln des
  BH-FDR-Layers (würde unkorrigierte p-Werte ausliefern).

**B — CHANGELOG `[Unreleased]` Date-Monotonicity**
- Neuer Pin [`tests/test_changelog_unreleased_date_monotonicity.py`](tests/test_changelog_unreleased_date_monotonicity.py):
  Companion zum Format-Pin aus PR #133. Datierte Einträge im
  `## [Unreleased]`-Block müssen von oben nach unten chronologisch
  nicht-aufsteigend sein. Catcht Merge-Konflikt-Artefakte (alter
  Eintrag landet versehentlich oben) und Rück-Datierungen.
  Enforcement ab `_ENFORCEMENT_FROM_DATE = "2026-04-22"`; Plan-2.8-
  Planungseinträge (separater Roadmap-Ledger) per Title-Filter
  exempt.

**C — `terminal_*_state.py` Import-Boundary**
- Neuer Pin [`tests/test_terminal_state_import_boundary.py`](tests/test_terminal_state_import_boundary.py):
  State-Layer-Module (`terminal_*_state.py`) dürfen keine non-state
  `terminal_*.py`-Module importieren — schützt die in
  `/memories/repo/terminal-*-state-layer.md` dokumentierte Layering-
  Disziplin und verhindert Zyklen zwischen Feed/UI und State Store.
  `terminal_feed_state.py`'s pre-existierende Kopplungen zu
  `terminal_export`/`terminal_poller`/`terminal_ui_helpers` sind im
  `_IMPORT_ALLOWLIST` mit Begründung dokumentiert; jede *neue*
  Kopplung erfordert explizite Allowlist-Erweiterung.

Pattern: alle drei Pins sind Defense-Pins (defending working
invariants), keine Produktionsänderungen.

### Tests / Quality / Pine (2026-04-24) — Cross-Language Vocab + A/B Discipline + Test Health

Drei pin-Erweiterungen aus dem Backlog von PR #130 (I-2 Folgearbeit
Pine-Schicht, plus zwei kleinere Disziplin-Pins):

**A — Pine ↔ Python Vocab Cross-Check**
- Neuer Pin [`tests/test_pine_python_vocab_cross_check.py`](tests/test_pine_python_vocab_cross_check.py):
  jeder Token in `HERO_TRUST_VOCAB`, `HERO_ACTION_VOCAB`,
  `HERO_SETUP_QUALITY_VOCAB`, `HERO_MARKET_MODE_VOCAB`,
  `HERO_BIAS_VOCAB`, `TRUST_STATE_VALUES` muss als quoted-literal in
  mindestens einer der zugeordneten Pine-Surfaces erscheinen
  (Dashboard / Mobile-Dashboard / Core-Engine).
- Echte Drift gefunden und behoben: `"WATCH"` (HERO_ACTION) und
  `"NEUTRAL"` (HERO_MARKET_MODE) wurden in
  [`SMC_Mobile_Dashboard.pine`](SMC_Mobile_Dashboard.pine) nur als
  default-else-branch gerendert (`"⚪ WATCH"`) — Vocab-Anchor-Kommentare
  hinzugefügt. Ergänzt I-2 aus PR #130 (Python-Side Fingerprint Gate)
  um die Pine-Render-Schicht.

**B — A/B-Comparison Multiple-Hypothesis Discipline (Regression-Pin)**
- Neuer Pin [`tests/test_ab_comparison_multiple_hypothesis_discipline.py`](tests/test_ab_comparison_multiple_hypothesis_discipline.py):
  friert die existierende BH-FDR-Disziplin in
  [`scripts/run_ab_comparison.py`](scripts/run_ab_comparison.py) ein —
  `benjamini_hochberg()` Helper, beide FDR-Layer
  (`_family_fdr_layer`, `_calibration_fdr_layer`),
  `"method": "benjamini_hochberg"` Self-Identification, und jede
  `"p_value"` Field-Emission braucht ein `"adjusted_p_value"`-Sibling.
- Numerische Korrektheit ist bereits durch
  `test_benjamini_hochberg_property.py`,
  `test_run_ab_comparison_fdr.py` und
  `test_run_ab_comparison_calibration_fdr.py` abgedeckt; dieser Pin
  schützt nur vor stillem Refactor-Verlust.

**C — Test-Suite Health Discipline (Regression-Pin)**
- Neuer Pin [`tests/test_test_suite_health_discipline.py`](tests/test_test_suite_health_discipline.py):
  friert den aktuellen gesunden Zustand der Test-Suite ein —
  0 non-strict `xfail` (silent passing wenn Bug behoben) und jeder
  `skip`/`skipif`-Marker mit `reason=` Argument. Marker-Body wird
  paren-balanced über bis zu 12 Zeilen verfolgt, damit multi-line
  `skipif(cond, reason=...)` mit nested parens (`os.environ.get(...)`)
  korrekt erkannt wird. Allowlist `_XFAIL_ALLOWLIST` für legitime
  Ausnahmen (aktuell leer).

**Acceptance / Test-Suite-Beweis**
- Alle 11 neuen Tests grün
  (6 vocab cross-check + 3 ab-comparison + 2 test-health).

**Quervergleich zum Audit-Backlog**
- Verlängert I-2 (Single Source of Truth Vocab Fingerprint, PR #130) in
  die Pine-Render-Schicht.
- Konvertiert eine ursprünglich als "fehlend" markierte FDR-Discipline-
  Lücke in einen Regression-Pin nach Discovery, dass die BH-Korrektur
  bereits implementiert war.

### Tests / Quality / Pine (2026-04-24) — Hero Defaults Coverage + Pine Security Discipline + Trust-State Relationship

Drei kleine, hochpräzise Pins als Erweiterung der Vocab-Triangle aus
PR #130 / #131:

**E — Hero-Defaults Vocab-Coverage**

- Neuer Pin [`tests/test_hero_defaults_vocab_coverage.py`](tests/test_hero_defaults_vocab_coverage.py):
  jeder `DEFAULTS[k]`-Wert in [`scripts/smc_hero_state.py`](scripts/smc_hero_state.py)
  für `HERO_TRUST` / `HERO_SETUP_QUALITY` / `HERO_ACTION` muss Element
  des entsprechenden Vocab-`frozenset` sein. Schließt die dritte Ecke
  des Vocab-Schutz-Dreiecks (Membership-Fingerprint, Pine-Render-
  Coverage, Default-Coverage).

**D — Pine `request.security` Discipline (Regression-Pin)**

- Neuer Pin [`tests/test_pine_request_security_discipline.py`](tests/test_pine_request_security_discipline.py):
  zwei Invarianten für aktive (non-legacy) Pine-Files:
  1. Kein same-symbol+same-TF
     `request.security(syminfo.tickerid, timeframe.period, ...)`
     (Pine-Antipattern: extra security context für no-op).
  2. Jede `request.security()` Call muss `lookahead=` explizit
     spezifizieren (default unterscheidet sich zwischen Pine-Versionen,
     silent future-bar leakage = lookahead-bias bug).
- `request.security_lower_tf` ausgenommen (kein `lookahead=` Argument).
- Discovery: aktive Surface bereits sauber; Pin schützt vor Regression.

**F — Hero ↔ TrustState Relationship-Invariant**

- Neuer Pin [`tests/test_hero_trust_state_relationship.py`](tests/test_hero_trust_state_relationship.py):
  friert die Beziehung zwischen `HERO_TRUST_VOCAB` (Hero-Layer) und der
  `TrustState`-Enum (Product-Trust-Layer) ein:
  - **Shared core** `{healthy, degraded, stale, unavailable}` muss in
    beiden Vocabs vorhanden sein.
  - **Hero-only** `{warmup}` darf nicht in `TrustState` lecken.
  - **TrustState-only** `{watch_only}` darf nicht in `HERO_TRUST_VOCAB`
    lecken.
  - Keine undokumentierten Tokens außerhalb dieser Drei-Partition.

**Acceptance / Test-Suite-Beweis**

- 9/9 neue Tests grün (3 + 2 + 4).

**Discovery-Notes**

- Ursprünglich geplantes F (Pine-Legacy-Move + Inventory-Pin) bereits
  vollständig erledigt durch
  [`tests/test_pine_active_surface_inventory.py`](tests/test_pine_active_surface_inventory.py)
  + [`tests/test_pine_legacy_isolation.py`](tests/test_pine_legacy_isolation.py)
  + [`tests/test_pine_library_version_consistency.py`](tests/test_pine_library_version_consistency.py).
  Pivot auf Relationship-Invariant als nächst-höchstwertigen Pin.
- D ist (analog zu B in PR #131) ein Regression-Guard: aktive Pine-
  Surface war bereits sauber. Audit-Backlog entwickelt sich zu
  "freeze the good state" statt "fix the bad state".

### Tests / Quality / Workflows (2026-04-24) — Audit-Followup Combo (M-1 / M-4 / L-1 / L-2 / I-1 / I-2)

Sechs Punkte aus dem Backlog von
[`docs/reviews/2026-04-24-system-review.md`](docs/reviews/2026-04-24-system-review.md)
in einem PR — alle audit-getrieben, alle pin-geschützt:

**M-1 — `continue-on-error: true` muss Begründung deklarieren**
- Neuer Pin [`tests/test_workflow_continue_on_error_discipline.py`](tests/test_workflow_continue_on_error_discipline.py):
  jeder `continue-on-error: true` Step braucht innerhalb ±5 Zeilen
  einen `# CONTINUE-ON-ERROR-INTENTIONAL: <Begründung>` Marker.
- 12 bestehende Sites in 5 Workflows mit Markern annotiert
  (notification best-effort, optional artifact downloads, advisory
  measurement runs, flaky TV automation). Future silent-skips zwingen
  Reviewer zu expliziter Begründung.

**M-4 — Pine-Resolver-Disziplin**
- Neuer AST-Pin [`tests/test_pine_apply_surface_resolver_discipline.py`](tests/test_pine_apply_surface_resolver_discipline.py):
  jedes `*.pine` String-Literal in `pine_apply_surface_reduction.py`
  muss erstes Argument von `resolve_pine_file(...)` sein (direkt oder
  via for-loop variable). Verhindert direktes `Path("X.pine")` /
  `open("X.pine")` das die Search-Dirs (repo-root + `pine/legacy/`)
  bypassen würde.
- Audit-Retraction: `resolve_pine_file()` deckt `pine/legacy/`
  bereits ab — D-1 v2 physische Migration hat heute schon
  funktioniert. Pin ist defense-in-depth gegen künftige Direkt-Pfad-
  Regression.

**L-1 — terminal_newsapi.py Stub Cross-Reference**
- Module docstring erweitert: explizit auf
  `scripts/smc_newsapi_ai.py` (~750 Zeilen, active path) hingewiesen
  + Audit-Anker `L-1` für grep.
- Neuer Pin [`tests/test_terminal_newsapi_stub_marker.py`](tests/test_terminal_newsapi_stub_marker.py):
  enforces dass die Cross-Reference + der `L-1` Anker in der docstring
  bleiben.

**L-2 — F2 Promotion-Gate "skipped" Visibility**
- `.github/workflows/f2-promotion-gate-daily.yml` skip-step:
  `::notice` → `::warning` (mit Audit-Begründung als Kommentar).
  Jeder skipped Daily-Run zeigt jetzt eine gelbe Banner-Annotation
  im Run-Summary; "stuck on skipped for weeks" Drift wird sichtbar
  ohne externe Counter-Ledger.
- Neuer Pin [`tests/test_workflow_f2_skip_visibility.py`](tests/test_workflow_f2_skip_visibility.py).

**I-1 — Numerical Audit Anchor Pin**
- Neuer Pin [`tests/test_enrichment_value_analysis_audit_anchor.py`](tests/test_enrichment_value_analysis_audit_anchor.py):
  enforces dass der Comment-Anker
  `N-1 (TEMPORAL_NUMERICAL_AUDIT_2026-04-24)` und der Epsilon-Guard
  `abs(self.baseline_mean_pnl) < 1e-12` in
  `scripts/smc_enrichment_value_analysis.py` erhalten bleiben.
  Verhindert dass eine Routine-"Comment cleanup" Pass die
  Audit-Begründung silent dropt.

**I-2 — Central Vocabulary Fingerprint Gate**
- Neuer zentraler Pin [`tests/test_central_vocab_fingerprint_gate.py`](tests/test_central_vocab_fingerprint_gate.py)
  als single-source-of-truth über alle kanonischen Vocabularies:
  - `HERO_TRUST_VOCAB` (5)
  - `HERO_SETUP_QUALITY_VOCAB` (4)
  - `HERO_ACTION_VOCAB` (4)
  - `HERO_DEFAULTS_KEYS` (7)
  - `TRUST_STATE_VALUES` (5)
  - `ACTION_IMPACTS` (4)
- Jede Vocabulary wird zu sortiertem JSON serialisiert + sha256
  truncated → 16-hex Fingerprint. Drift in irgendeiner Vocabulary
  bricht den Pin und zwingt Reviewer zu bewusster Baseline-Bump
  (mit confirm dass downstream Pine/dashboard/alert contracts den
  neuen Token verstehen).
- Cross-check: `TrustState` enum vs. `all_trust_states()` iterator
  müssen exakt übereinstimmen (verhindert vergessenen Iterator-Update).

**Test-Footprint:** +6 neue Test-Files mit zusammen 16 Tests, alle grün.
Drei Source-Edits (`terminal_newsapi.py` docstring,
`f2-promotion-gate-daily.yml` notice→warning, 5 Workflows mit Markern).
Audit-Item M-4 mit Retraction-Notiz: `resolve_pine_file()` deckt das
Szenario bereits ab; Pin bleibt als regression guard.

### Tests / Quality (2026-04-24) — AST-Pin Triple: lru_cache / to_datetime utc / pytest-xdist parametrize Determinismus

Drei reine Tripwire-Pins (kein Verhaltens-Risiko, AST-only) gegen
hochfrequente Bug-Klassen aus PRs #98, #95, #104 (Klassen #4, #25, #29
des SMC System Review Prompts):

- **`tests/test_lru_cache_maxsize_discipline.py`** (3 Tests, Klasse #29):
  jeder `@lru_cache` Decorator muss explizit `maxsize=N` führen — bare
  `@lru_cache()` Default ist unbounded und leakt Memory in Long-Running
  Streamlit/Terminal Sessions (PR #98 / A-2). Baseline pinnt die 3
  bekannten Sites (`smc_newsapi_ai.py` × 2 + `newsstack_fmp/_market_cal.py`).
- **`tests/test_to_datetime_utc_discipline.py`** (3 Tests, Klasse #4):
  jeder `pd.to_datetime(frame["col"])` Call mit Timestamp-Spalte
  (timestamp/ts/ts_event/ts_recv/datetime/...) muss `utc=True` führen.
  Date-only Spalten (trade_date/asof_date/...) sind explizit allowlisted.
  Aktuell 0 Verstöße — Pin verhindert Re-Introduktion (PR #95 / TZ-1/TZ-2).
- **`tests/test_pytest_xdist_parametrize_determinism.py`** (2 Tests,
  Klasse #25): jeder `@pytest.mark.parametrize` darf seine Argument-
  Quelle nicht aus `set(...)` / `dict.keys()` / `os.listdir(...)` /
  `glob.glob(...)` / `Path.iterdir()` / Set-Literal lesen ohne
  `sorted(...)` Wrapper. Verhindert Worker-Collection-Mismatch unter
  `pytest-xdist` (PR #104). Aktuell 0 Verstöße.

**Test footprint:** +8 neue Tests, alle grün. Baseline-Drift-Failures
liefern Auto-Update Recipe in der Failure-Message.

### Fixes & Pins (2026-04-24) — System Review 2026-04-24 Followup (H-1, L-3, M-3)

Adressiert die drei priorisierten Backlog-Items aus
[`docs/reviews/2026-04-24-system-review.md`](docs/reviews/2026-04-24-system-review.md):

**H-1 — `scripts/smc_ob_context_light.py` Empty-OB Subnormal-Robustheit**
- `bull_level == 0.0 and bear_level == 0.0` → `abs(...) < _OB_LEVEL_EPS` (1e-12)
- Neue `_OB_LEVEL_EPS` Konstante zwischen IEEE-754 subnormal range (5e-324)
  und kleinster realer Tick-Größe (1e-2). Defense-in-depth: heute liefert
  Upstream einen Literal-Sentinel, aber Comparison-Form würde silent driften
  wenn das je auf computed-value umgestellt wird.
- 3 neue Regression-Tests in `tests/test_ob_context_light.py`
  (subnormal positive, subnormal negative, sanity-check für 1e-2 als active OB).

**L-3 — Division-Site Baseline-Pin (`tests/test_division_site_baseline.py`)**
- AST-Pin im Stil des `lru_cache` baseline-pin (PR #127): pinnt die exakte
  Anzahl `a / b` Divisionen pro audited file (`smc_core/scoring.py`: 27,
  `smc_core/fvg_quality.py`: 7).
- Jede neue Division zwingt Reviewer zu confirm denominator ist non-zero
  (literal, structural, oder epsilon-guarded) bevor Baseline gebumpt wird.
- 2 neue Tests, beide grün.

**M-3 — Workflow `GH_PAT` Discipline (`tests/test_workflow_gh_pat_discipline.py`)**
- Audit-Retraction: ursprüngliche M-3 Finding-Beschreibung war zu breit —
  `gh issue create/comment` und `gh run list/download` sind mit
  `GITHUB_TOKEN` legitim. Nur `gh pr create/edit/merge`,
  `git push origin bot/*` und `peter-evans/create-pull-request`
  brauchen `GH_PAT` damit fast-gates triggert.
- Neuer Pin walkt alle `.github/workflows/*.yml` und enforces dass jede
  sensitive action `secrets.GH_PAT` in Proximity hat (±100 Zeilen,
  passt für die größten step bodies).
- Pin entdeckte 2 echte Verstöße in `smc-library-refresh.yml:580/586`
  (`gh pr create` + `gh pr merge` für `bot/library-refresh-${GITHUB_RUN_ID}`
  PRs ohne GH_PAT). Fix angewendet: Step "Commit and push changes"
  nutzt jetzt das kanonische
  `${{ secrets.GH_PAT != '' && secrets.GH_PAT || github.token }}` ternary.
- 2 neue Tests, beide grün.

**Test footprint:** +7 neue Tests, alle grün. Zwei Source-Edits
(`smc_ob_context_light.py` + `smc-library-refresh.yml`), beide
audit-driven, beide mit Pin-Schutz gegen Regression.

### Tests / Quality (2026-04-24) — Audit-Followup Pins (workflow continue-on-error / raw write call sites / Pine legacy isolation / Pine active surface inventory)

Vier additive Inventory-Pin-Tests, die die im Audit (PR #123) gefundenen
Observability-Lücken auf konkrete Allowlists herunterbrechen. Pure
stdlib, zero source changes.

- **`tests/test_workflow_continue_on_error_inventory.py`** (~120 LOC,
  4 cases): pinnt die exakten 12 `continue-on-error: true` Vorkommen
  über 5 Workflows (smc-live-newsapi-refresh, smc-library-refresh ×6,
  smc-deeper-integration-gates ×2, plan-2-8-weekly-digest ×3,
  smc-release-gates) auf konkrete Zeilennummern. Schließt M-2 aus dem
  Audit. Failure zwingt zu expliziter Begründung im Allowlist-Kommentar.
  Korrigiert die Audit-Behauptung "nur 2 Workflows" — tatsächlich 5.
- **`tests/test_atomic_write_call_sites.py`** (~165 LOC, 4 cases):
  AST-basierter Sweep findet alle `open(..., "w"/"wb"/"x"/"a")`,
  `Path.open(...)`, `os.fdopen(...)` Schreib-Call-Sites in
  `scripts/`. 14 erlaubte Files mit Begründung in `_ALLOWED_RAW_WRITE_FILES`
  (alle entweder `os.fdopen+os.replace` atomic-Pattern, append-mode
  JSONL, oder one-shot CSV nicht im Pipeline-Konsum). Schließt I-1
  Triage-Frage aus dem Audit (1003 vs 92 war grep-noise; echte Zahl
  ~14). Pin-Test pruned zusätzlich stale Allowlist-Einträge.
- **`tests/test_pine_legacy_isolation.py`** (~155 LOC, 4 cases):
  pinnt die 23 legacy `*.pine` Files unter `pine/legacy/` als exakte
  Inventory, verbietet Re-Introduktion am Repo-Root, und assertet
  dass nur explizit erlaubte Tooling-Files (`smc_bus_manifest.py`,
  `smc_file_lifecycle.py`, `smc_surface_matrix.py`,
  `pine_apply_surface_reduction.py`, `test_usi_lint.py`) legacy-Namen
  referenzieren dürfen. Audit-Item G/H zusammengefasst.
- **`tests/test_pine_active_surface_inventory.py`** (~95 LOC, 4 cases):
  pinnt die 30-File aktive Pine-Oberfläche (17 Root-Orchestratoren +
  5 `pine/skipp_*.pine` Libraries + 8 `SMC++/smc_*.pine` private
  Libraries). Neue `*.pine` am Root zwingt zu expliziter Klassifikation
  (Orchestrator vs Library vs Legacy). Audit-Item H Inventory.

Verifikation: `21 passed in 5.28s` für die 4 neuen Module. Zero source
changes. Pure stdlib (respects ADR-0005).

### Tests / Quality (2026-04-24) — BH property test, Brier/ECE closed-form pin, SPRT boundary precision, CHANGELOG category lint

Four additive, source-untouched test modules tightening the
measurement-runtime contract on top of the PR #120 / #121 schema-pin
+ ADR-0005 work. Pure stdlib, no new runtime imports.

- **`benjamini_hochberg` property test**
  (`tests/test_benjamini_hochberg_property.py`, ~150 LOC, 35 cases):
  pins the BH step-up contract directly on the helper —
  empty-input shape, output-length invariance, monotonicity of
  adjusted p-values along the sorted axis, [0, 1] adjusted range,
  q=0/q=1 edge cases, sorted-prefix structure of the rejection set,
  threshold-separation property, shuffle invariance, and a B&H 1995
  textbook three-p-value worked example. Existing tests covered the
  `digest["fdr"]` payload but not the helper's mathematical
  invariants in isolation.
- **`_metric_brier` / `_metric_ece` closed-form pin**
  (`tests/test_metric_brier_ece_pin.py`, ~135 LOC, 13 cases):
  locks the calibration-metric closed forms against silent
  re-implementation drift. Brier: perfect prediction → 0, fully
  inverted → 1, all-0.5 baseline → 0.25, two-event hand-checked
  average. ECE: perfect calibration → 0, total miscalibration in
  one bucket → 1.0, two-bin weighted average, probability clipping
  on out-of-range inputs, NaN on empty input, [0, 1] bound on
  random fuzz. These metrics feed the calibration-FDR layer
  (`digest["fdr_calibration"]`).
- **`terminal_decision` SPRT boundary-precision pin**
  (`tests/test_terminal_decision_boundary.py`, ~120 LOC, 9 cases):
  computes the exact integer `k` at which the LLR crosses each
  Wald bound for `(n, p0, p1, alpha, beta) = (200|500|1000, 0.5,
  0.6, 0.05, 0.20)` and asserts that the inclusive-boundary
  classification (`llr >= upper_bound` → `accept_h1`,
  `llr <= lower_bound` → `accept_h0`) is preserved to the integer
  step. Plus a closed-form LLR pin
  (`llr = k·ln(p1/p0) + (n-k)·ln((1-p1)/(1-p0))`) at five
  representative `(n, k)` points. Catches the off-by-one
  comparison-operator drift that the four-variant decision pin
  (PR #120) cannot see.
- **CHANGELOG `[Unreleased]` category lint**
  (`tests/test_changelog_format_lint.py`, ~95 LOC, 2 cases): asserts
  that the first `## [...]` versioned heading is `[Unreleased]` and
  that every `###` sub-header inside `[Unreleased]` uses a category
  from the active whitelist (`Added`, `Changed`, `Deprecated`,
  `Removed`, `Fixed`, `Security`, `Documentation`,
  `Tests / Quality`, `Schema Versions`, `Evidence`, `Verification`).
  Date and uniqueness checks are deliberately omitted because the
  existing repo convention legitimately repeats e.g. multiple
  `### Verification` blocks per day and uses date-range headers.

All four modules are pure-stdlib (no scipy/sklearn/pandas) and
respect the ADR-0005 measurement-runtime fence. Total addition:
**62 tests, ~500 LOC, zero source changes**.

### Tests / Quality (2026-04-24) — `_normal_cdf` accuracy pin + SPRT Wald-bounds property test + ADR-0005 pre-commit CLI

Three additive hardening pieces, no source changes to the runtime
itself:

- **`_normal_cdf` accuracy pin**
  (`tests/test_normal_cdf_accuracy_pin.py`): pins
  `scripts.run_ab_comparison._normal_cdf` against 13 reference
  points spanning [-3, 3] to 1e-9 absolute tolerance. The function
  underpins every p-value in `digest['fdr']` and `digest['fdr_calibration']`;
  a polynomial-approximation replacement (Abramowitz & Stegun, etc.)
  would diverge by ~1e-7 and trip the pin. Also pins `_normal_cdf(0)
  == 0.5` exactly, symmetry (`cdf(-x) + cdf(x) == 1`), monotonicity,
  and [0, 1] bounds at finite extremes.
- **SPRT Wald-bounds property test**
  (`tests/test_sprt_wald_bounds_property.py`): pins the closed-form
  Wald-A / Wald-B formulas of `SPRTConfig.upper_bound` /
  `lower_bound` over a 7×6 = 42-point grid of (alpha, beta) pairs
  spanning the validation range (0, 0.5). Also asserts sign
  invariants (upper > 0, lower < 0), strict separation, and
  monotonicity in alpha/beta. A stealth refactor that swaps
  numerator/denominator or substitutes an "equivalent" expression
  would silently invert promote/hold/rollback decisions for the
  SPRT layer.
- **ADR-0005 pre-commit CLI**
  (`scripts/check_adr_0005_pure_stdlib.py`,
  `tests/test_check_adr_0005_pure_stdlib_cli.py`,
  `.pre-commit-config.yaml`): wraps the AST scan from PR #120
  (`tests/test_adr_0005_pure_stdlib_runtime.py`) as a standalone
  CLI and registers it as a pre-commit hook scoped to
  `^scripts/(run_ab_comparison|smc_sprt_stop_rule)\.py$`.
  Re-imports `RUNTIME_FILES` and `BANNED_ROOTS` from the test
  module so the two stay in lock-step (single source of truth).
  Contributors now catch ADR-0005 violations pre-push without
  spinning up the full test suite.

Verification: `251 passed in 1.46s` for the 7 affected test
modules.

### Tests / Quality (2026-04-24) — Schema-pin trilogy + ADR-0005 AST guard + degenerate-branch coverage

Hardens the A/B-comparison digest contract and the ADR-0005
"pure-stdlib measurement runtime" constraint with static, additive
tests (no source changes).

- **SPRT schema-pin** (`tests/test_run_ab_comparison_sprt.py`): pins
  the top-level (`{decision, n, k, hit_rate, llr, wald_upper,
  wald_lower, config, control_n, control_hit_rate}`) and `config`
  sub-block (`{p0, p1, alpha, beta}`) key sets of `digest["sprt"]`
  across all four decision variants (`accept_h1`, `accept_h0`,
  `inconclusive`, `zero_n`). Closes the symmetry gap left by the
  hit-rate FDR pin (#119) and the calibration-FDR pin (#118):
  `digest["sprt"]` was the last advisory layer without a
  stealth-field guard.
- **`_two_proportion_z_pvalue` degenerate gap-fill**
  (`tests/test_run_ab_comparison_fdr.py`): adds the missing
  `n_ctrl=0`-only branch (mirror of the existing `n_treat=0` test)
  and one end-to-end test asserting `_family_fdr_layer` records
  `skipped_reason="degenerate_or_empty"` and excludes the family
  from the BH input list.
- **ADR-0005 enforcement**
  (`tests/test_adr_0005_pure_stdlib_runtime.py`): static `ast`
  parse over `scripts/run_ab_comparison.py` and
  `scripts/smc_sprt_stop_rule.py` asserts no
  `numpy`/`scipy`/`pandas`/`statsmodels`/`sklearn`/`torch`/
  `tensorflow` imports (top-level or `from`-form). Failure message
  tells contributors to supersede ADR-0005 first if the constraint
  is intentionally lifted.

Field add/rename in any of the three pinned blocks must be paired
with a major schema version bump per the
`schema-version-bump-must-be-major-on-field-count-change`
convention.

Verification: `60 passed in 1.10s` for the four affected test
modules.

### Documentation (2026-04-24) — Schema-pin trilogy backfill for #117–#119

Backfills CHANGELOG entries for three S-2 follow-up PRs that landed
without `[Unreleased]` notes:

- **#117** (S-2 calibration-FDR bootstrap): adds the
  `digest["fdr_calibration"]` block with bootstrap-resampled,
  Benjamini-Hochberg-corrected p-values for per-(symbol,timeframe)
  Brier and ECE deltas. Advisory only — does not alter
  Promote/Hold/Rollback.
- **#118** (symmetry guard + schema-pin for `fdr_calibration` +
  ADR-0005): pins the field set of `digest["fdr_calibration"]` and
  formalises the pure-stdlib constraint for the measurement runtime
  in `docs/adr/0005-pure-stdlib-measurement-runtime.md`.
- **#119** (schema-pin for `digest["fdr"]` hit-rate block): mirrors
  #118 for the older hit-rate FDR layer (#102).

### Documentation (2026-04-24) — D-2: SCHEMA_VERSION history consolidated

Pulled `smc_core.schema_version.SCHEMA_VERSION` history out of inline
module comments into the dedicated **Schema Versions** section below
(closes audit-backlog item D-2). Inline comments in
`smc_core/schema_version.py` retain only the **current** version
note + a pointer to this CHANGELOG section.

### Changed (2026-04-23) — Coverage-source omit-list expanded for standalone CLIs

`pyproject.toml::tool.coverage.run.omit` now excludes 7 additional
manual-operator scripts that have no automated test coverage by design
and are not imported by production modules:

- `open_prep/streamlit_monitor.py` (~1472 stmts at 0% covered)
- `scripts/fvg_asia_real_sample.py`
- `scripts/fvg_label_audit_q3.py`
- `scripts/pine_slim.py`
- `scripts/probe_newsapi_feed_cursor.py`
- `scripts/run_smc_e2e_smoke_test.py`
- `scripts/tv_publish_evidence_summary.py`

Same pattern as the prior `streamlit_terminal.py` exclusion (issue #17 /
`/memories/repo/coverage-source-config.md` / commit `df9eb7d2`).
Without the carve-out, total coverage was dragged below the 95%
`fail_under` threshold despite production code being fully covered.
Production-import safety verified before each addition.

### Changed (2026-04-22) — D3 Promotion: FVG quality strict regime

**Major behavioural change.** `smc_core.fvg_quality.score_fvg()` now
defaults to the **strict** weight regime promoted from the D4 audit:

- `WEIGHT_VERSION = "strict_v1_no_hurst"`
- Weights: `gap_size_atr=0.45`, `htf_aligned=0.0735`,
  `distance_to_price_atr=0.45`, `is_full_body=0.0515`, `hurst_50=0.0`
- Directions: all `-1` except `hurst_50=0` (disabled — audit §1.5
  null-signal)
- Score formula: `clamp(0.5 + Σ w·d·(comp − 0.5), 0, 1)`
- **Tier semantics inverted**: under the strict default, HIGH tier
  means "strict-favourable" (small gaps, near-price, no HTF hype) —
  the empirical opposite of the previous lenient regime. Tier
  thresholds (HIGH ≥ 0.70, MEDIUM ≥ 0.50) remain numerically
  unchanged.

`scripts/fvg_quality_recalibration.py` defaults flipped to match:
`label_source="partial_50"`, `signed_weights=True`,
`acceptance_mode="relative"`. `report_version` 1.2 → 2.0.
`LEGACY_WEIGHTS` retained as alias for `LENIENT_WEIGHTS`
(back-compat). New constants `STRICT_WEIGHTS`, `STRICT_DIRECTIONS`
mirror the production-side pinning.

`SMC_Core_Engine.pine::fvg_quality_score` is **NOT** mirror-promoted.
Pine and Python use disjoint feature sets (Pine reads
`fill_current_ratio`, `not filled`, `total_volume>0`; Python reads
`htf_aligned`, `distance_to_price_atr`, `hurst_50`). True mirroring
needs a Pine `FVG`-type extension and is deferred to a separate
phase. Documented in
`/memories/repo/fvg-quality-pine-python-feature-disjunction.md`.

Refs: `docs/FVG_QUALITY_D4_AUDIT.md` §6 (D3-Promotion-Befund + Pine-vs-Python-Disjunktion),
`docs/STRATEGY_2026_Q3.md` §D3+§D4,
`/memories/repo/fvg-quality-d3-promotion-landed.md`.

### Added (2026-11-01) — Plan 2.8 bool-or-list records + pxd + trailing-question-mark lines

- `scripts/plan_2_8_ledger_bool_or_list_only_record_count.py`
  counts ledger records whose every value is a bool or list.
- `scripts/plan_2_8_digest_pxd_file_count.py` counts top-level `.pxd` files.
- `scripts/plan_2_8_weekly_summary_trailing_question_mark_line_count.py`
  counts non-empty lines whose last character is ``?``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-10-31) — Plan 2.8 bool-or-dict records + pyx + leading-question-mark lines

- `scripts/plan_2_8_ledger_bool_or_dict_only_record_count.py`
  counts ledger records whose every value is a bool or dict.
- `scripts/plan_2_8_digest_pyx_file_count.py` counts top-level `.pyx` files.
- `scripts/plan_2_8_weekly_summary_leading_question_mark_line_count.py`
  counts non-empty lines whose first character is ``?``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-10-27) — Plan 2.8 bool-or-list-or-null records + cbl + leading-comma lines

- `scripts/plan_2_8_ledger_bool_or_list_or_null_only_record_count.py`
  counts ledger records whose every value is bool, list, or null.
- `scripts/plan_2_8_digest_cbl_file_count.py` counts top-level `.cbl` files.
- `scripts/plan_2_8_weekly_summary_leading_comma_line_count.py`
  counts non-empty lines whose first character is ``,``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-10-26) — Plan 2.8 bool-or-dict-or-null records + cob + trailing-semicolon lines

- `scripts/plan_2_8_ledger_bool_or_dict_or_null_only_record_count.py`
  counts ledger records whose every value is bool, dict, or null.
- `scripts/plan_2_8_digest_cob_file_count.py` counts top-level `.cob` files.
- `scripts/plan_2_8_weekly_summary_trailing_semicolon_line_count.py`
  counts non-empty lines whose last character is ``;``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-10-25) — Plan 2.8 numeric-or-list-or-null records + hpp + leading-semicolon lines

- `scripts/plan_2_8_ledger_numeric_or_list_or_null_only_record_count.py`
  counts ledger records whose every value is a number, list, or null.
- `scripts/plan_2_8_digest_hpp_file_count.py` counts top-level `.hpp` files.
- `scripts/plan_2_8_weekly_summary_leading_semicolon_line_count.py`
  counts non-empty lines whose first character is ``;``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-10-24) — Plan 2.8 numeric-or-dict-or-null records + mli + trailing-underscore lines

- `scripts/plan_2_8_ledger_numeric_or_dict_or_null_only_record_count.py`
  counts ledger records whose every value is a number, dict, or null.
- `scripts/plan_2_8_digest_mli_file_count.py` counts top-level `.mli` files.
- `scripts/plan_2_8_weekly_summary_trailing_underscore_line_count.py`
  counts non-empty lines whose last character is ``_``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-10-23) — Plan 2.8 dict-or-list-or-bool records + f08 + leading-underscore lines

- `scripts/plan_2_8_ledger_dict_or_list_or_bool_only_record_count.py`
  counts ledger records whose every value is a dict, list, or bool.
- `scripts/plan_2_8_digest_f08_file_count.py` counts top-level `.f08` files.
- `scripts/plan_2_8_weekly_summary_leading_underscore_line_count.py`
  counts non-empty lines whose first character is ``_``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-10-22) — Plan 2.8 only-falsy records + f03 + trailing-tilde lines

- `scripts/plan_2_8_ledger_only_falsy_record_count.py` counts
  non-empty ledger records whose every value is falsy.
- `scripts/plan_2_8_digest_f03_file_count.py` counts top-level `.f03` files.
- `scripts/plan_2_8_weekly_summary_trailing_tilde_line_count.py`
  counts non-empty lines whose last character is ``~``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-10-21) — Plan 2.8 only-truthy records + f95 + leading-tilde lines

- `scripts/plan_2_8_ledger_only_truthy_record_count.py` counts
  non-empty ledger records whose every value is truthy.
- `scripts/plan_2_8_digest_f95_file_count.py` counts top-level `.f95` files.
- `scripts/plan_2_8_weekly_summary_leading_tilde_line_count.py`
  counts non-empty lines whose first character is ``~``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-10-19) — Plan 2.8 empty-list-or-empty-dict records + ado + leading-pipe lines

- `scripts/plan_2_8_ledger_empty_list_or_empty_dict_only_record_count.py`
  counts non-empty ledger records whose every value is an empty list
  or empty ``dict``.
- `scripts/plan_2_8_digest_ado_file_count.py` counts top-level `.ado` files.
- `scripts/plan_2_8_weekly_summary_leading_pipe_line_count.py`
  counts non-empty lines whose first character is ``|``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-10-18) — Plan 2.8 dict-or-empty-list records + do + trailing-backslash lines

- `scripts/plan_2_8_ledger_dict_or_empty_list_only_record_count.py`
  counts non-empty ledger records whose every value is a dict or an
  empty ``list``.
- `scripts/plan_2_8_digest_do_file_count.py` counts top-level `.do` files.
- `scripts/plan_2_8_weekly_summary_trailing_backslash_line_count.py`
  counts non-empty lines whose last character is ``\``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-10-17) — Plan 2.8 list-or-empty-dict records + sas + leading-backslash lines

- `scripts/plan_2_8_ledger_list_or_empty_dict_only_record_count.py`
  counts non-empty ledger records whose every value is a list or an
  empty ``dict``.
- `scripts/plan_2_8_digest_sas_file_count.py` counts top-level `.sas` files.
- `scripts/plan_2_8_weekly_summary_leading_backslash_line_count.py`
  counts non-empty lines whose first character is ``\``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-10-16) — Plan 2.8 empty-dict records + r + trailing-slash lines

- `scripts/plan_2_8_ledger_empty_dict_only_record_count.py` counts
  non-empty ledger records whose every value is an empty ``dict``.
- `scripts/plan_2_8_digest_r_file_count.py` counts top-level `.r` files.
- `scripts/plan_2_8_weekly_summary_trailing_slash_line_count.py`
  counts non-empty lines whose last character is ``/``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-10-15) — Plan 2.8 empty-list records + mm + leading-slash lines

- `scripts/plan_2_8_ledger_empty_list_only_record_count.py` counts
  non-empty ledger records whose every value is an empty ``list``.
- `scripts/plan_2_8_digest_mm_file_count.py` counts top-level `.mm` files.
- `scripts/plan_2_8_weekly_summary_leading_slash_line_count.py`
  counts non-empty lines whose first character is ``/``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-10-12) — Plan 2.8 list/dict/string records + ada + trailing-plus lines

- `scripts/plan_2_8_ledger_list_or_dict_or_string_only_record_count.py`
  counts non-empty ledger records whose every value is ``list``,
  ``dict``, or ``str``.
- `scripts/plan_2_8_digest_ada_file_count.py` counts top-level `.ada`
  files.
- `scripts/plan_2_8_weekly_summary_trailing_plus_line_count.py` counts
  non-empty lines whose last character is ``+``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-10-11) — Plan 2.8 list/string records + pas + leading-plus lines

- `scripts/plan_2_8_ledger_list_or_string_only_record_count.py` counts
  non-empty ledger records whose every value is ``list`` or ``str``.
- `scripts/plan_2_8_digest_pas_file_count.py` counts top-level
  `.pas` files.
- `scripts/plan_2_8_weekly_summary_leading_plus_line_count.py` counts
  non-empty lines whose first character is ``+``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-10-10) — Plan 2.8 dict/string records + vb + trailing-star lines

- `scripts/plan_2_8_ledger_dict_or_string_only_record_count.py` counts
  non-empty ledger records whose every value is ``dict`` or ``str``.
- `scripts/plan_2_8_digest_vb_file_count.py` counts top-level `.vb`
  files.
- `scripts/plan_2_8_weekly_summary_trailing_star_line_count.py` counts
  non-empty lines whose last character is ``*``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-10-09) — Plan 2.8 numeric/bool/null/string records + fsx + leading-star lines

- `scripts/plan_2_8_ledger_numeric_or_bool_or_null_or_string_only_record_count.py`
  counts non-empty ledger records whose every value is ``int``,
  ``float``, ``bool``, ``None``, or ``str``.
- `scripts/plan_2_8_digest_fsx_file_count.py` counts top-level
  `.fsx` files.
- `scripts/plan_2_8_weekly_summary_leading_star_line_count.py` counts
  non-empty lines whose first character is ``*``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-10-08) — Plan 2.8 numeric/bool/string records + fsi + trailing-amp lines

- `scripts/plan_2_8_ledger_numeric_or_bool_or_string_only_record_count.py`
  counts non-empty ledger records whose every value is ``int``,
  ``float``, ``bool``, or ``str``.
- `scripts/plan_2_8_digest_fsi_file_count.py` counts top-level
  `.fsi` files.
- `scripts/plan_2_8_weekly_summary_trailing_amp_line_count.py` counts
  non-empty lines whose last character is ``&``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-10-07) — Plan 2.8 numeric/bool/null records + fs + leading-amp lines

- `scripts/plan_2_8_ledger_numeric_or_bool_or_null_only_record_count.py`
  counts non-empty ledger records whose every value is ``int``,
  ``float``, ``bool``, or ``None``.
- `scripts/plan_2_8_digest_fs_file_count.py` counts top-level
  `.fs` files.
- `scripts/plan_2_8_weekly_summary_leading_amp_line_count.py` counts
  non-empty lines whose first character is ``&``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-10-06) — Plan 2.8 numeric/null/string records + vala + trailing-caret lines

- `scripts/plan_2_8_ledger_numeric_or_null_or_string_only_record_count.py`
  counts non-empty ledger records whose every value is ``int`` (not
  ``bool``), ``float``, ``str``, or ``None``.
- `scripts/plan_2_8_digest_vala_file_count.py` counts top-level
  `.vala` files.
- `scripts/plan_2_8_weekly_summary_trailing_caret_line_count.py`
  counts non-empty lines whose last character is ``^``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-10-05) — Plan 2.8 list/dict/null/string records + zig + leading-caret lines

- `scripts/plan_2_8_ledger_list_or_dict_or_null_or_string_only_record_count.py`
  counts non-empty ledger records whose every value is ``list``,
  ``dict``, ``str``, or ``None``.
- `scripts/plan_2_8_digest_zig_file_count.py` counts top-level `.zig`
  files.
- `scripts/plan_2_8_weekly_summary_leading_caret_line_count.py`
  counts non-empty lines whose first character is ``^``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-10-04) — Plan 2.8 dict/null/string records + nim + trailing-percent lines

- `scripts/plan_2_8_ledger_dict_or_null_or_string_only_record_count.py`
  counts non-empty ledger records whose every value is ``dict``,
  ``str``, or ``None``.
- `scripts/plan_2_8_digest_nim_file_count.py` counts top-level `.nim`
  files.
- `scripts/plan_2_8_weekly_summary_trailing_percent_line_count.py`
  counts non-empty lines whose last character is ``%``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-10-03) — Plan 2.8 list/null/string records + cr + leading-percent lines

- `scripts/plan_2_8_ledger_list_or_null_or_string_only_record_count.py`
  counts non-empty ledger records whose every value is ``list``,
  ``str``, or ``None``.
- `scripts/plan_2_8_digest_cr_file_count.py` counts top-level `.cr`
  files.
- `scripts/plan_2_8_weekly_summary_leading_percent_line_count.py`
  counts non-empty lines whose first character is ``%``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-10-02) — Plan 2.8 dict-only records + clj + trailing-hash lines

- `scripts/plan_2_8_ledger_dict_only_record_count.py` counts non-empty
  ledger records whose every value is a ``dict``.
- `scripts/plan_2_8_digest_clj_file_count.py` counts top-level `.clj`
  files.
- `scripts/plan_2_8_weekly_summary_trailing_hash_line_count.py`
  counts non-empty lines whose last character is ``#``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-10-01) — Plan 2.8 list-only records + jl + leading-hash lines

- `scripts/plan_2_8_ledger_list_only_record_count.py` counts non-empty
  ledger records whose every value is a ``list``.
- `scripts/plan_2_8_digest_jl_file_count.py` counts top-level `.jl`
  files.
- `scripts/plan_2_8_weekly_summary_leading_hash_line_count.py`
  counts non-empty lines whose first character is ``#``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-09-30) — Plan 2.8 list/dict/null records + hs + trailing-at lines

- `scripts/plan_2_8_ledger_list_or_dict_or_null_only_record_count.py`
  counts non-empty ledger records whose every value is ``list``,
  ``dict``, or ``None``.
- `scripts/plan_2_8_digest_hs_file_count.py` counts top-level `.hs`
  files.
- `scripts/plan_2_8_weekly_summary_trailing_at_line_count.py`
  counts non-empty lines whose last character is ``@``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-09-29) — Plan 2.8 zero-float records + erl + leading-at lines

- `scripts/plan_2_8_ledger_zero_float_only_record_count.py`
  counts non-empty ledger records whose every value is exactly the
  float ``0.0`` (excludes ``int`` and ``bool``).
- `scripts/plan_2_8_digest_erl_file_count.py` counts top-level `.erl`
  files.
- `scripts/plan_2_8_weekly_summary_leading_at_line_count.py`
  counts non-empty lines whose first character is ``@``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-09-28) — Plan 2.8 zero-int records + ex + trailing-dollar lines

- `scripts/plan_2_8_ledger_zero_int_only_record_count.py`
  counts non-empty ledger records whose every value is exactly the
  integer ``0`` (excludes ``bool``).
- `scripts/plan_2_8_digest_ex_file_count.py` counts top-level `.ex`
  files.
- `scripts/plan_2_8_weekly_summary_trailing_dollar_line_count.py`
  counts non-empty lines whose last character is ``$``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-09-27) — Plan 2.8 list-or-dict records + elm + leading-dollar lines

- `scripts/plan_2_8_ledger_list_or_dict_only_record_count.py`
  counts non-empty ledger records whose every value is a ``list`` or
  ``dict``.
- `scripts/plan_2_8_digest_elm_file_count.py` counts top-level `.elm`
  files.
- `scripts/plan_2_8_weekly_summary_leading_dollar_line_count.py`
  counts non-empty lines whose first character is ``$``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-09-26) — Plan 2.8 dict-or-null records + groovy + trailing-tab lines

- `scripts/plan_2_8_ledger_dict_or_null_only_record_count.py`
  counts non-empty ledger records whose every value is a ``dict`` or
  ``None``.
- `scripts/plan_2_8_digest_groovy_file_count.py` counts top-level
  `.groovy` files.
- `scripts/plan_2_8_weekly_summary_trailing_tab_line_count.py`
  counts non-empty lines whose last character is a tab.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-09-25) — Plan 2.8 list-or-null records + dart + leading-tab lines

- `scripts/plan_2_8_ledger_list_or_null_only_record_count.py`
  counts non-empty ledger records whose every value is a ``list`` or
  ``None``.
- `scripts/plan_2_8_digest_dart_file_count.py` counts top-level `.dart`
  files.
- `scripts/plan_2_8_weekly_summary_leading_tab_line_count.py`
  counts non-empty lines whose first character is a tab.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-09-24) — Plan 2.8 negative-or-zero float records + pl + trailing-backtick lines

- `scripts/plan_2_8_ledger_negative_or_zero_float_only_record_count.py`
  counts non-empty ledger records whose every value is a non-positive
  ``float`` (excludes ``int`` and ``bool``).
- `scripts/plan_2_8_digest_pl_file_count.py` counts top-level `.pl`
  files.
- `scripts/plan_2_8_weekly_summary_trailing_backtick_line_count.py`
  counts non-empty lines whose last character is `` ` ``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-09-23) — Plan 2.8 positive-or-zero float records + lua + leading-backtick lines

- `scripts/plan_2_8_ledger_positive_or_zero_float_only_record_count.py`
  counts non-empty ledger records whose every value is a non-negative
  ``float`` (excludes ``int`` and ``bool``).
- `scripts/plan_2_8_digest_lua_file_count.py` counts top-level `.lua`
  files.
- `scripts/plan_2_8_weekly_summary_leading_backtick_line_count.py`
  counts non-empty lines whose first character is `` ` ``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-09-22) — Plan 2.8 negative-or-zero int records + scala + trailing-apostrophe lines

- `scripts/plan_2_8_ledger_negative_or_zero_int_only_record_count.py`
  counts non-empty ledger records whose every value is a non-positive
  ``int`` (excluding ``bool``).
- `scripts/plan_2_8_digest_scala_file_count.py` counts top-level
  `.scala` files.
- `scripts/plan_2_8_weekly_summary_trailing_apostrophe_line_count.py`
  counts non-empty lines whose last character is ``'``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-09-21) — Plan 2.8 positive-or-zero int records + rb + leading-apostrophe lines

- `scripts/plan_2_8_ledger_positive_or_zero_int_only_record_count.py`
  counts non-empty ledger records whose every value is a non-negative
  ``int`` (excluding ``bool``).
- `scripts/plan_2_8_digest_rb_file_count.py` counts top-level `.rb`
  files.
- `scripts/plan_2_8_weekly_summary_leading_apostrophe_line_count.py`
  counts non-empty lines whose first character is ``'``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-09-20) — Plan 2.8 numeric-or-bool records + swift + trailing-quote lines

- `scripts/plan_2_8_ledger_numeric_or_bool_only_record_count.py`
  counts non-empty ledger records whose every value is a ``bool``,
  ``int``, or ``float``.
- `scripts/plan_2_8_digest_swift_file_count.py` counts top-level
  `.swift` files.
- `scripts/plan_2_8_weekly_summary_trailing_quote_line_count.py` counts
  non-empty lines whose last character is ``"``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-09-19) — Plan 2.8 numeric-or-string records + kt + leading-quote lines

- `scripts/plan_2_8_ledger_numeric_or_string_only_record_count.py`
  counts non-empty ledger records whose every value is a ``str``,
  ``int``, or ``float`` (excluding ``bool``).
- `scripts/plan_2_8_digest_kt_file_count.py` counts top-level `.kt`
  files.
- `scripts/plan_2_8_weekly_summary_leading_quote_line_count.py` counts
  non-empty lines whose first character is ``"``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-09-18) — Plan 2.8 float-or-string-or-null records + java + trailing-brace lines

- `scripts/plan_2_8_ledger_float_or_string_or_null_record_count.py`
  counts non-empty ledger records whose every value is a ``float``,
  ``str``, or ``None``.
- `scripts/plan_2_8_digest_java_file_count.py` counts top-level `.java`
  files.
- `scripts/plan_2_8_weekly_summary_trailing_brace_line_count.py` counts
  non-empty lines whose last character is ``}``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-09-17) — Plan 2.8 bool-or-string-or-null records + go + leading-brace lines

- `scripts/plan_2_8_ledger_bool_or_string_or_null_record_count.py`
  counts non-empty ledger records whose every value is a ``bool``,
  ``str``, or ``None``.
- `scripts/plan_2_8_digest_go_file_count.py` counts top-level `.go`
  files.
- `scripts/plan_2_8_weekly_summary_leading_brace_line_count.py` counts
  non-empty lines whose first character is ``{``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-09-16) — Plan 2.8 bool-or-int-or-null records + rs + trailing-bracket lines

- `scripts/plan_2_8_ledger_bool_or_int_or_null_record_count.py` counts
  non-empty ledger records whose every value is a ``bool``, ``int``, or
  ``None``.
- `scripts/plan_2_8_digest_rs_file_count.py` counts top-level `.rs`
  files.
- `scripts/plan_2_8_weekly_summary_trailing_bracket_line_count.py`
  counts non-empty lines whose last character is ``]``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-09-15) — Plan 2.8 string-or-int-or-null records + tex + leading-bracket lines

- `scripts/plan_2_8_ledger_string_or_int_or_null_record_count.py` counts
  non-empty ledger records whose every value is ``str``, ``int``
  (excluding ``bool``), or ``None``.
- `scripts/plan_2_8_digest_tex_file_count.py` counts top-level `.tex`
  files.
- `scripts/plan_2_8_weekly_summary_leading_bracket_line_count.py` counts
  non-empty lines whose first character is ``[``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-09-14) — Plan 2.8 nonzero-float records + nix + trailing-paren lines

- `scripts/plan_2_8_ledger_nonzero_float_only_record_count.py` counts
  non-empty ledger records whose every value is a non-zero ``float``.
- `scripts/plan_2_8_digest_nix_file_count.py` counts top-level `.nix`
  files.
- `scripts/plan_2_8_weekly_summary_trailing_paren_line_count.py` counts
  non-empty lines whose last character is ``)``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-09-13) — Plan 2.8 negative-float records + ps1 + leading-paren lines

- `scripts/plan_2_8_ledger_negative_float_only_record_count.py` counts
  non-empty ledger records whose every value is a ``float`` strictly
  less than zero.
- `scripts/plan_2_8_digest_ps1_file_count.py` counts top-level `.ps1`
  files.
- `scripts/plan_2_8_weekly_summary_leading_paren_line_count.py` counts
  non-empty lines whose first character is ``(``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-09-12) — Plan 2.8 positive-float records + bat + leading-punct lines

- `scripts/plan_2_8_ledger_positive_float_only_record_count.py` counts
  non-empty ledger records whose every value is a ``float`` greater
  than zero.
- `scripts/plan_2_8_digest_bat_file_count.py` counts top-level `.bat`
  files.
- `scripts/plan_2_8_weekly_summary_leading_punct_line_count.py` counts
  non-empty lines whose first character is ``. ! ?``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-09-11) — Plan 2.8 string-or-float records + awk + trailing-lowercase lines

- `scripts/plan_2_8_ledger_string_or_float_only_record_count.py` counts
  non-empty ledger records whose every value is a ``str`` or ``float``.
- `scripts/plan_2_8_digest_awk_file_count.py` counts top-level `.awk`
  files.
- `scripts/plan_2_8_weekly_summary_trailing_lowercase_line_count.py`
  counts non-empty lines whose last character is an ASCII lowercase
  letter.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-09-10) — Plan 2.8 float-or-int records + zsh + leading-lowercase lines

- `scripts/plan_2_8_ledger_float_or_int_only_record_count.py` counts
  non-empty ledger records whose every value is a ``float`` or non-bool
  ``int``.
- `scripts/plan_2_8_digest_zsh_file_count.py` counts top-level `.zsh`
  files.
- `scripts/plan_2_8_weekly_summary_leading_lowercase_line_count.py`
  counts non-empty lines whose first character is an ASCII lowercase
  letter.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-09-09) — Plan 2.8 single-char records + bash + trailing-uppercase lines

- `scripts/plan_2_8_ledger_single_char_string_only_record_count.py`
  counts non-empty ledger records whose every value is a length-1
  ``str``.
- `scripts/plan_2_8_digest_bash_file_count.py` counts top-level `.bash`
  files.
- `scripts/plan_2_8_weekly_summary_trailing_uppercase_line_count.py`
  counts non-empty lines whose last character is an ASCII uppercase
  letter.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-09-07) — Plan 2.8 string-or-int records + py + trailing-alpha lines

- `scripts/plan_2_8_ledger_string_or_int_only_record_count.py` counts
  non-empty ledger records whose every value is a ``str`` or non-bool
  ``int``.
- `scripts/plan_2_8_digest_py_file_count.py` counts top-level `.py`
  files.
- `scripts/plan_2_8_weekly_summary_trailing_alpha_line_count.py` counts
  non-empty lines whose last character is an ASCII letter.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-09-06) — Plan 2.8 float-or-null records + sql + leading-alpha lines

- `scripts/plan_2_8_ledger_float_or_null_only_record_count.py` counts
  non-empty ledger records whose every value is a ``float`` or null.
- `scripts/plan_2_8_digest_sql_file_count.py` counts top-level `.sql`
  files.
- `scripts/plan_2_8_weekly_summary_leading_alpha_line_count.py` counts
  non-empty lines whose first character is an ASCII letter.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-09-05) — Plan 2.8 int-or-bool records + sh + trailing-punct lines

- `scripts/plan_2_8_ledger_int_or_bool_only_record_count.py` counts
  non-empty ledger records whose every value is an ``int`` or ``bool``.
- `scripts/plan_2_8_digest_sh_file_count.py` counts top-level `.sh`
  files.
- `scripts/plan_2_8_weekly_summary_trailing_punct_line_count.py` counts
  non-empty lines whose last character is ``. ! ?``.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-09-04) — Plan 2.8 string-or-bool records + dat + trailing-hyphen lines

- `scripts/plan_2_8_ledger_string_or_bool_only_record_count.py` counts
  non-empty ledger records whose every value is a ``str`` or ``bool``.
- `scripts/plan_2_8_digest_dat_file_count.py` counts top-level `.dat`
  files.
- `scripts/plan_2_8_weekly_summary_trailing_hyphen_line_count.py` counts
  non-empty lines whose last character is an ASCII hyphen.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-09-03) — Plan 2.8 numeric-or-null records + tmp + leading-hyphen lines

- `scripts/plan_2_8_ledger_numeric_or_null_only_record_count.py` counts
  non-empty ledger records whose every value is a number or null.
- `scripts/plan_2_8_digest_tmp_file_count.py` counts top-level `.tmp`
  files.
- `scripts/plan_2_8_weekly_summary_leading_hyphen_line_count.py` counts
  non-empty lines whose first character is an ASCII hyphen.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-09-02) — Plan 2.8 nonzero-int records + bak + trailing-digit lines

- `scripts/plan_2_8_ledger_nonzero_int_only_record_count.py` counts
  non-empty ledger records whose every value is a nonzero ``int``.
- `scripts/plan_2_8_digest_bak_file_count.py` counts top-level `.bak`
  files.
- `scripts/plan_2_8_weekly_summary_trailing_digit_line_count.py` counts
  non-empty lines whose last character is an ASCII digit.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-09-01) — Plan 2.8 negative-int records + lock + leading-digit lines

- `scripts/plan_2_8_ledger_negative_int_only_record_count.py` counts
  non-empty ledger records whose every value is a negative ``int``.
- `scripts/plan_2_8_digest_lock_file_count.py` counts top-level `.lock`
  files.
- `scripts/plan_2_8_weekly_summary_leading_digit_line_count.py` counts
  non-empty lines whose first character is an ASCII digit.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-08-31) — Plan 2.8 positive-int records + env + medium lines

- `scripts/plan_2_8_ledger_positive_int_only_record_count.py` counts
  non-empty ledger records whose every value is a positive ``int``.
- `scripts/plan_2_8_digest_env_file_count.py` counts top-level `.env`
  files.
- `scripts/plan_2_8_weekly_summary_medium_line_count.py` counts lines
  whose length is between 10 and 79 characters inclusive.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-08-30) — Plan 2.8 int-or-null records + conf + long lines

- `scripts/plan_2_8_ledger_int_or_null_only_record_count.py` counts
  non-empty ledger records whose every value is either ``int`` or null.
- `scripts/plan_2_8_digest_conf_file_count.py` counts top-level `.conf`
  files.
- `scripts/plan_2_8_weekly_summary_long_line_count.py` counts lines
  whose length is at least 80 characters.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-08-29) — Plan 2.8 bool-or-null records + cfg + short lines

- `scripts/plan_2_8_ledger_bool_or_null_only_record_count.py` counts
  non-empty ledger records whose every value is either ``bool`` or null.
- `scripts/plan_2_8_digest_cfg_file_count.py` counts top-level `.cfg`
  files.
- `scripts/plan_2_8_weekly_summary_short_line_count.py` counts
  non-empty lines whose length is strictly less than 10 characters.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-08-28) — Plan 2.8 string-or-null records + ini + multi-word lines

- `scripts/plan_2_8_ledger_string_or_null_only_record_count.py` counts
  non-empty ledger records whose every value is either ``str`` or null.
- `scripts/plan_2_8_digest_ini_file_count.py` counts top-level `.ini`
  files.
- `scripts/plan_2_8_weekly_summary_multi_word_line_count.py` counts
  lines containing two or more whitespace-separated tokens.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-08-27) — Plan 2.8 numeric-only records + toml + single-word lines

- `scripts/plan_2_8_ledger_numeric_only_record_count.py` counts non-empty
  ledger records whose every value is a plain numeric type (``int`` or
  ``float``, excluding ``bool``).
- `scripts/plan_2_8_digest_toml_file_count.py` counts top-level `.toml`
  files.
- `scripts/plan_2_8_weekly_summary_single_word_line_count.py` counts
  lines containing exactly one whitespace-separated token.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-08-26) — Plan 2.8 heterogeneous-value records + skr + single-char lines

- `scripts/plan_2_8_ledger_heterogeneous_value_record_count.py` counts
  non-empty ledger records whose values span more than one type bucket.
- `scripts/plan_2_8_digest_skr_file_count.py` counts top-level `.skr`
  files.
- `scripts/plan_2_8_weekly_summary_single_char_line_count.py` counts
  lines that are exactly one character long.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-08-25) — Plan 2.8 homogeneous-value records + pkr + space-only lines

- `scripts/plan_2_8_ledger_homogeneous_value_record_count.py` counts
  non-empty ledger records whose every value shares the same type bucket.
- `scripts/plan_2_8_digest_pkr_file_count.py` counts top-level `.pkr`
  files.
- `scripts/plan_2_8_weekly_summary_space_only_line_count.py` counts
  non-empty lines whose every char is an ASCII space (excludes tabs).
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-08-24) — Plan 2.8 float-only records + gpx + digit-or-space lines

- `scripts/plan_2_8_ledger_float_only_record_count.py` counts non-empty
  ledger records whose every value is a plain ``float``.
- `scripts/plan_2_8_digest_gpx_file_count.py` counts top-level `.gpx`
  files.
- `scripts/plan_2_8_weekly_summary_digit_or_space_line_count.py` counts
  non-empty lines whose every char is an ASCII digit or space.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-08-23) — Plan 2.8 int-only records + kbx + letter-or-space lines

- `scripts/plan_2_8_ledger_int_only_record_count.py` counts non-empty
  ledger records whose every value is a plain ``int`` (booleans excluded).
- `scripts/plan_2_8_digest_kbx_file_count.py` counts top-level `.kbx`
  files.
- `scripts/plan_2_8_weekly_summary_letter_or_space_line_count.py`
  counts non-empty lines whose every char is an ASCII letter or space.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-08-22) — Plan 2.8 mixed-value records + asc + printable lines

- `scripts/plan_2_8_ledger_mixed_value_record_count.py` counts ledger
  records that contain both at least one scalar and at least one
  collection value (empty objects excluded).
- `scripts/plan_2_8_digest_asc_file_count.py` counts top-level `.asc`
  files.
- `scripts/plan_2_8_weekly_summary_printable_line_count.py` counts
  non-empty lines whose every character is printable ASCII (0x20-0x7E).
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-08-21) — Plan 2.8 collection-only records + pgp + alnum-only lines

- `scripts/plan_2_8_ledger_collection_only_record_count.py` counts
  ledger records whose every top-level value is a JSON list or object
  (empty objects excluded).
- `scripts/plan_2_8_digest_pgp_file_count.py` counts top-level `.pgp`
  files.
- `scripts/plan_2_8_weekly_summary_alnum_only_line_count.py` counts
  non-empty lines whose every character is an ASCII letter or digit.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-08-20) — Plan 2.8 scalar-only records + gpg + letter-only lines

- `scripts/plan_2_8_ledger_scalar_only_record_count.py` counts ledger
  records whose every top-level value is a JSON scalar (str/num/bool/null;
  empty objects excluded).
- `scripts/plan_2_8_digest_gpg_file_count.py` counts top-level `.gpg`
  files.
- `scripts/plan_2_8_weekly_summary_letter_only_line_count.py` counts
  non-empty lines whose every character is an ASCII letter.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-08-19) — Plan 2.8 object-only records + pub + non-ascii lines

- `scripts/plan_2_8_ledger_object_only_record_count.py` counts ledger
  records whose every top-level value is a JSON object (empty objects
  excluded).
- `scripts/plan_2_8_digest_pub_file_count.py` counts top-level `.pub`
  files.
- `scripts/plan_2_8_weekly_summary_non_ascii_line_count.py` counts
  lines containing at least one non-ASCII character.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-08-18) — Plan 2.8 array-only records + csr + ascii-only lines

- `scripts/plan_2_8_ledger_array_only_record_count.py` counts ledger
  records whose every top-level value is a JSON array (empty objects
  excluded).
- `scripts/plan_2_8_digest_csr_file_count.py` counts top-level `.csr`
  files.
- `scripts/plan_2_8_weekly_summary_ascii_only_line_count.py` counts
  lines whose every character is ASCII (codepoint < 128).
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-08-17) — Plan 2.8 null-only records + p7s + mixed-case lines

- `scripts/plan_2_8_ledger_null_only_record_count.py` counts ledger
  records whose every top-level value is JSON ``null`` (empty objects
  excluded).
- `scripts/plan_2_8_digest_p7s_file_count.py` counts top-level `.p7s`
  files.
- `scripts/plan_2_8_weekly_summary_mixed_case_line_count.py` counts
  lines containing both an ASCII uppercase and lowercase letter.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-08-16) — Plan 2.8 bool-only records + p7m + digit-only lines

- `scripts/plan_2_8_ledger_bool_only_record_count.py` counts ledger
  records whose every top-level value is a bool (empty objects excluded).
- `scripts/plan_2_8_digest_p7m_file_count.py` counts top-level `.p7m`
  files.
- `scripts/plan_2_8_weekly_summary_digit_only_line_count.py` counts
  non-empty lines whose every character is an ASCII digit.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-08-15) — Plan 2.8 number-only records + p7c + lowercase lines

- `scripts/plan_2_8_ledger_number_only_record_count.py` counts ledger
  records whose every top-level value is a number (int or float; bool
  excluded; empty objects excluded).
- `scripts/plan_2_8_digest_p7c_file_count.py` counts top-level `.p7c`
  files.
- `scripts/plan_2_8_weekly_summary_lowercase_line_count.py` counts
  lines containing at least one ASCII lowercase letter.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-08-14) — Plan 2.8 string-only records + p7b + uppercase lines

- `scripts/plan_2_8_ledger_string_only_record_count.py` counts ledger
  records whose every top-level value is a string (excluding empty
  objects).
- `scripts/plan_2_8_digest_p7b_file_count.py` counts top-level `.p7b`
  files.
- `scripts/plan_2_8_weekly_summary_uppercase_line_count.py` counts
  lines containing at least one ASCII uppercase letter.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-08-13) — Plan 2.8 non-dict records + cert + digit lines

- `scripts/plan_2_8_ledger_non_dict_record_count.py` counts ledger
  records whose JSON payload is not an object.
- `scripts/plan_2_8_digest_cert_file_count.py` counts top-level `.cert`
  files.
- `scripts/plan_2_8_weekly_summary_digit_line_count.py` counts lines
  containing at least one ASCII digit.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-08-12) — Plan 2.8 top-key unique + cer + angle-close lines

- `scripts/plan_2_8_ledger_top_key_count_unique.py` reports number of
  distinct top-level key counts seen across ledger records.
- `scripts/plan_2_8_digest_cer_file_count.py` counts top-level `.cer`
  files.
- `scripts/plan_2_8_weekly_summary_angle_close_line_count.py` counts
  lines containing an ASCII `>`.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-08-11) — Plan 2.8 top-key min + pkcs12 + angle-open lines

- `scripts/plan_2_8_ledger_top_key_count_min.py` reports min top-level
  key count across ledger records.
- `scripts/plan_2_8_digest_pkcs12_file_count.py` counts top-level
  `.pkcs12` files.
- `scripts/plan_2_8_weekly_summary_angle_open_line_count.py` counts
  lines containing an ASCII `<`.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-08-10) — Plan 2.8 top-key max + keystore + brace-close lines

- `scripts/plan_2_8_ledger_top_key_count_max.py` reports max top-level
  key count across ledger records.
- `scripts/plan_2_8_digest_keystore_file_count.py` counts top-level
  `.keystore` files.
- `scripts/plan_2_8_weekly_summary_brace_close_line_count.py` counts
  lines containing an ASCII `}`.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-08-09) — Plan 2.8 top-key total + jks + brace-open lines

- `scripts/plan_2_8_ledger_top_key_count_total.py` sums top-level key
  counts across ledger records.
- `scripts/plan_2_8_digest_jks_file_count.py` counts top-level `.jks`
  files.
- `scripts/plan_2_8_weekly_summary_brace_open_line_count.py` counts
  lines containing an ASCII `{`.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-08-08) — Plan 2.8 nonempty records + p12 + bracket-close lines

- `scripts/plan_2_8_ledger_nonempty_record_count.py` counts ledger
  records with at least one top-level key.
- `scripts/plan_2_8_digest_p12_file_count.py` counts top-level `.p12`
  files.
- `scripts/plan_2_8_weekly_summary_bracket_close_line_count.py` counts
  lines containing an ASCII `]`.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-08-07) — Plan 2.8 empty records + pfx + bracket-open lines

- `scripts/plan_2_8_ledger_empty_record_count.py` counts ledger records
  with zero top-level keys.
- `scripts/plan_2_8_digest_pfx_file_count.py` counts top-level `.pfx`
  files.
- `scripts/plan_2_8_weekly_summary_bracket_open_line_count.py` counts
  lines containing an ASCII `[`.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-08-06) — Plan 2.8 odd-key records + der + paren-close lines

- `scripts/plan_2_8_ledger_odd_key_record_count.py` counts ledger
  records whose top-level key count is odd.
- `scripts/plan_2_8_digest_der_file_count.py` counts top-level `.der`
  files.
- `scripts/plan_2_8_weekly_summary_paren_close_line_count.py` counts
  lines containing an ASCII `)`.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-08-05) — Plan 2.8 even-key records + key + paren-open lines

- `scripts/plan_2_8_ledger_even_key_record_count.py` counts ledger
  records whose top-level key count is even (including zero).
- `scripts/plan_2_8_digest_key_file_count.py` counts top-level `.key`
  files.
- `scripts/plan_2_8_weekly_summary_paren_open_line_count.py` counts lines
  containing an ASCII `(`.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-08-04) — Plan 2.8 multi-key records + crt + asterisk lines

- `scripts/plan_2_8_ledger_multi_key_record_count.py` counts ledger
  records that have two or more top-level keys.
- `scripts/plan_2_8_digest_crt_file_count.py` counts top-level `.crt`
  files.
- `scripts/plan_2_8_weekly_summary_asterisk_line_count.py` counts lines
  containing an ASCII `*`.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-08-03) — Plan 2.8 single-key records + pem + hyphen lines

- `scripts/plan_2_8_ledger_single_key_record_count.py` counts ledger
  records that have exactly one top-level key.
- `scripts/plan_2_8_digest_pem_file_count.py` counts top-level `.pem`
  files.
- `scripts/plan_2_8_weekly_summary_hyphen_line_count.py` counts lines
  containing an ASCII `-`.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-08-02) — Plan 2.8 false values + wasm + period lines

- `scripts/plan_2_8_ledger_false_value_count.py` counts top-level boolean
  ``false`` values across ledger JSON-object records.
- `scripts/plan_2_8_digest_wasm_file_count.py` counts top-level `.wasm`
  files.
- `scripts/plan_2_8_weekly_summary_period_line_count.py` counts lines
  containing an ASCII `.`.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-08-01) — Plan 2.8 true values + pyo + comma lines

- `scripts/plan_2_8_ledger_true_value_count.py` counts top-level boolean
  ``true`` values across ledger JSON-object records.
- `scripts/plan_2_8_digest_pyo_file_count.py` counts top-level `.pyo`
  files.
- `scripts/plan_2_8_weekly_summary_comma_line_count.py` counts lines
  containing an ASCII `,`.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-07-31) — Plan 2.8 nested objects + pyc + colon lines

- `scripts/plan_2_8_ledger_nested_object_value_count.py` counts top-level
  dict values that contain at least one nested dict element.
- `scripts/plan_2_8_digest_pyc_file_count.py` counts top-level `.pyc`
  files.
- `scripts/plan_2_8_weekly_summary_colon_line_count.py` counts lines
  containing an ASCII `:`.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-07-30) — Plan 2.8 nested arrays + wim + plus lines

- `scripts/plan_2_8_ledger_nested_array_value_count.py` counts top-level
  list values that contain at least one nested list element.
- `scripts/plan_2_8_digest_wim_file_count.py` counts top-level `.wim`
  files.
- `scripts/plan_2_8_weekly_summary_plus_line_count.py` counts lines
  containing an ASCII `+`.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-07-29) — Plan 2.8 empty objects + ovf + equals lines

- `scripts/plan_2_8_ledger_empty_object_value_count.py` counts top-level
  empty-dict values across ledger JSON-object records.
- `scripts/plan_2_8_digest_ovf_file_count.py` counts top-level `.ovf`
  files.
- `scripts/plan_2_8_weekly_summary_equals_line_count.py` counts lines
  containing an ASCII `=`.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-07-28) — Plan 2.8 empty arrays + ova + underscore lines

- `scripts/plan_2_8_ledger_empty_array_value_count.py` counts top-level
  empty-list values across ledger JSON-object records.
- `scripts/plan_2_8_digest_ova_file_count.py` counts top-level `.ova`
  files.
- `scripts/plan_2_8_weekly_summary_underscore_line_count.py` counts lines
  containing an ASCII `_`.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-07-27) — Plan 2.8 positive numbers + qcow2 + backslash lines

- `scripts/plan_2_8_ledger_positive_number_value_count.py` counts top-level
  numeric values strictly greater than zero (bools excluded) across ledger
  records.
- `scripts/plan_2_8_digest_qcow2_file_count.py` counts top-level `.qcow2`
  files.
- `scripts/plan_2_8_weekly_summary_backslash_line_count.py` counts lines
  containing an ASCII backslash.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-07-26) — Plan 2.8 negative numbers + vmdk + slash lines

- `scripts/plan_2_8_ledger_negative_number_value_count.py` counts top-level
  numeric values strictly less than zero (bools excluded) across ledger
  records.
- `scripts/plan_2_8_digest_vmdk_file_count.py` counts top-level `.vmdk`
  files.
- `scripts/plan_2_8_weekly_summary_slash_line_count.py` counts lines
  containing an ASCII `/`.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-07-25) — Plan 2.8 zero numbers + vhd + backtick lines

- `scripts/plan_2_8_ledger_zero_number_value_count.py` counts top-level
  zero-valued numeric values (bools excluded) across ledger records.
- `scripts/plan_2_8_digest_vhd_file_count.py` counts top-level `.vhd`
  files.
- `scripts/plan_2_8_weekly_summary_backtick_line_count.py` counts lines
  containing an ASCII backtick.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-07-24) — Plan 2.8 empty strings + bin + tilde lines

- `scripts/plan_2_8_ledger_empty_string_value_count.py` counts top-level
  empty-string values across ledger JSON-object records.
- `scripts/plan_2_8_digest_bin_file_count.py` counts top-level `.bin`
  files.
- `scripts/plan_2_8_weekly_summary_tilde_line_count.py` counts lines
  containing an ASCII `~`.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-07-23) — Plan 2.8 float values + img + caret lines

- `scripts/plan_2_8_ledger_float_value_count.py` counts `float` top-level
  values across ledger JSON-object records.
- `scripts/plan_2_8_digest_img_file_count.py` counts top-level `.img` files.
- `scripts/plan_2_8_weekly_summary_caret_line_count.py` counts lines
  containing an ASCII `^`.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-07-22) — Plan 2.8 int values + vpk + percent lines

- `scripts/plan_2_8_ledger_int_value_count.py` counts strict-int top-level
  values across ledger JSON-object records (bools excluded).
- `scripts/plan_2_8_digest_vpk_file_count.py` counts top-level `.vpk` files.
- `scripts/plan_2_8_weekly_summary_percent_line_count.py` counts lines
  containing an ASCII `%`.
- Weekly digest workflow wires three fail-soft compute+upload step pairs.

### Added (2026-07-21) — Plan 2.8 number-field records + pak + dollar lines

- New `scripts/plan_2_8_ledger_number_field_record_count.py` counts
  records containing at least one top-level numeric value.
- New `scripts/plan_2_8_digest_pak_file_count.py` counts top-level
  ``.pak`` files.
- New `scripts/plan_2_8_weekly_summary_dollar_line_count.py` counts
  lines containing at least one ``$``.
- Weekly workflow wires the three new fail-soft step pairs after the
  hash-line upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-07-20) — Plan 2.8 bool-field records + lzh + hash lines

- New `scripts/plan_2_8_ledger_bool_field_record_count.py` counts
  records containing at least one top-level ``bool`` value.
- New `scripts/plan_2_8_digest_lzh_file_count.py` counts top-level
  ``.lzh`` files.
- New `scripts/plan_2_8_weekly_summary_hash_line_count.py` counts
  lines containing at least one ``#``.
- Weekly workflow wires the three new fail-soft step pairs after the
  at-sign-line upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-07-19) — Plan 2.8 string-field records + z + at-sign lines

- New `scripts/plan_2_8_ledger_string_field_record_count.py` counts
  records containing at least one top-level string value.
- New `scripts/plan_2_8_digest_z_file_count.py` counts top-level
  ``.z`` files.
- New `scripts/plan_2_8_weekly_summary_at_sign_line_count.py` counts
  lines containing at least one ``@``.
- Weekly workflow wires the three new fail-soft step pairs after the
  ampersand-line upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-07-18) — Plan 2.8 object-field records + hqx + amp lines

- New `scripts/plan_2_8_ledger_object_field_record_count.py` counts
  records containing at least one top-level ``dict`` value.
- New `scripts/plan_2_8_digest_hqx_file_count.py` counts top-level
  ``.hqx`` files.
- New `scripts/plan_2_8_weekly_summary_ampersand_line_count.py`
  counts lines containing at least one ``&``.
- Weekly workflow wires the three new fail-soft step pairs after the
  pipe-line upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-07-17) — Plan 2.8 array-field records + sit + pipe lines

- New `scripts/plan_2_8_ledger_array_field_record_count.py` counts
  records containing at least one top-level ``list`` value.
- New `scripts/plan_2_8_digest_sit_file_count.py` counts top-level
  ``.sit`` files.
- New `scripts/plan_2_8_weekly_summary_pipe_line_count.py` counts
  lines containing at least one ``|``.
- Weekly workflow wires the three new fail-soft step pairs after the
  exclamation-line upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-07-16) — Plan 2.8 null-field records + zoo + exclam lines

- New `scripts/plan_2_8_ledger_null_field_record_count.py` counts
  records containing at least one top-level ``null`` value.
- New `scripts/plan_2_8_digest_zoo_file_count.py` counts top-level
  ``.zoo`` files.
- New `scripts/plan_2_8_weekly_summary_exclamation_line_count.py`
  counts lines containing at least one ``!``.
- Weekly workflow wires the three new fail-soft step pairs after the
  question-mark-line upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-07-15) — Plan 2.8 object values + ace + question lines

- New `scripts/plan_2_8_ledger_object_value_count.py` counts top-level
  object-typed field values across ledger records.
- New `scripts/plan_2_8_digest_ace_file_count.py` counts top-level
  ``.ace`` files.
- New `scripts/plan_2_8_weekly_summary_question_mark_line_count.py`
  counts lines containing at least one ``?``.
- Weekly workflow wires the three new fail-soft step pairs after the
  semicolon-line upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-07-14) — Plan 2.8 array values + lha + semicolon lines

- New `scripts/plan_2_8_ledger_array_value_count.py` counts top-level
  list-typed field values across ledger records.
- New `scripts/plan_2_8_digest_lha_file_count.py` counts top-level
  ``.lha`` files.
- New `scripts/plan_2_8_weekly_summary_semicolon_line_count.py`
  counts lines containing at least one semicolon.
- Weekly workflow wires the three new fail-soft step pairs after the
  leading-colon upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-07-13) — Plan 2.8 string values + arj + lead-colon

- New `scripts/plan_2_8_ledger_string_value_count.py` counts top-level
  string field values across ledger records.
- New `scripts/plan_2_8_digest_arj_file_count.py` counts top-level
  ``.arj`` files.
- New `scripts/plan_2_8_weekly_summary_leading_colon_count.py` counts
  lines whose first non-whitespace char is ``:``.
- Weekly workflow wires the three new fail-soft step pairs after the
  trailing-colon upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-07-12) — Plan 2.8 number values + cab + trail-colon

- New `scripts/plan_2_8_ledger_number_value_count.py` counts top-level
  numeric field values (ints/floats, excluding bools).
- New `scripts/plan_2_8_digest_cab_file_count.py` counts top-level
  ``.cab`` files.
- New `scripts/plan_2_8_weekly_summary_trailing_colon_count.py` counts
  lines whose rstripped form ends with ``:``.
- Weekly workflow wires the three new fail-soft step pairs after the
  all-caps upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-07-11) — Plan 2.8 bool values + lz + all-caps

- New `scripts/plan_2_8_ledger_bool_value_count.py` counts top-level
  boolean field values across ledger records.
- New `scripts/plan_2_8_digest_lz_file_count.py` counts top-level
  ``.lz`` files.
- New `scripts/plan_2_8_weekly_summary_all_caps_line_count.py` counts
  lines whose letters are all uppercase.
- Weekly workflow wires the three new fail-soft step pairs after the
  tab-line upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-07-10) — Plan 2.8 null values + zst + tab-line

- New `scripts/plan_2_8_ledger_null_value_count.py` counts top-level
  ``null`` field values across ledger records.
- New `scripts/plan_2_8_digest_zst_file_count.py` counts top-level
  ``.zst`` files.
- New `scripts/plan_2_8_weekly_summary_tab_line_count.py` counts lines
  containing ASCII tab characters.
- Weekly workflow wires the three new fail-soft step pairs after the
  comment-line upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-07-09) — Plan 2.8 field keys + rar + comment

- New `scripts/plan_2_8_ledger_field_key_count.py` counts distinct
  top-level field keys across ledger records.
- New `scripts/plan_2_8_digest_rar_file_count.py` counts top-level
  ``.rar`` files.
- New `scripts/plan_2_8_weekly_summary_comment_line_count.py` counts
  Markdown/HTML comment lines.
- Weekly workflow wires the three new fail-soft step pairs after the
  table-separator upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-07-08) — Plan 2.8 unique records + pkg + table-sep

- New `scripts/plan_2_8_ledger_unique_record_count.py` counts unique
  ledger records via canonical JSON key.
- New `scripts/plan_2_8_digest_pkg_file_count.py` counts top-level
  ``.pkg`` files.
- New `scripts/plan_2_8_weekly_summary_table_separator_count.py`
  counts Markdown table separator rows.
- Weekly workflow wires the three new fail-soft step pairs after the
  table-row upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-07-07) — Plan 2.8 json-invalid + ipa + table-row

- New `scripts/plan_2_8_ledger_json_invalid_count.py` counts ledger
  entries that fail to parse as JSON.
- New `scripts/plan_2_8_digest_ipa_file_count.py` counts top-level
  ``.ipa`` files.
- New `scripts/plan_2_8_weekly_summary_table_row_count.py` counts
  Markdown table rows (header + data; separator excluded).
- Weekly workflow wires the three new fail-soft step pairs after the
  blockquote upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-07-06) — Plan 2.8 json-valid + apk + blockquote

- New `scripts/plan_2_8_ledger_json_valid_count.py` counts ledger
  entries that parse as valid JSON.
- New `scripts/plan_2_8_digest_apk_file_count.py` counts top-level
  ``.apk`` files.
- New `scripts/plan_2_8_weekly_summary_blockquote_line_count.py`
  counts Markdown blockquote lines.
- Weekly workflow wires the three new fail-soft step pairs after the
  horizontal-rule upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-07-05) — Plan 2.8 duplicate record + msi + hr-line

- New `scripts/plan_2_8_ledger_duplicate_record_count.py` counts
  duplicate records via canonical JSON key.
- New `scripts/plan_2_8_digest_msi_file_count.py` counts top-level
  ``.msi`` files.
- New `scripts/plan_2_8_weekly_summary_horizontal_rule_count.py`
  counts Markdown horizontal-rule lines.
- Weekly workflow wires the three new steps after the fenced-code
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-07-04) — Plan 2.8 schema version + rpm + fenced-code

- New `scripts/plan_2_8_ledger_schema_version_count.py` counts
  distinct schema_version values observed in ledger records.
- New `scripts/plan_2_8_digest_rpm_file_count.py` counts top-level
  ``.rpm`` files.
- New `scripts/plan_2_8_weekly_summary_fenced_code_block_count.py`
  counts Markdown fenced code blocks.
- Weekly workflow wires the three new steps after the numbered-line
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-07-03) — Plan 2.8 nonblank line + deb + numbered-line

- New `scripts/plan_2_8_ledger_nonblank_line_count.py` counts
  non-blank ledger lines.
- New `scripts/plan_2_8_digest_deb_file_count.py` counts top-level
  ``.deb`` files.
- New `scripts/plan_2_8_weekly_summary_numbered_line_count.py`
  counts Markdown ordered-list numbered lines.
- Weekly workflow wires the three new steps after the bullet-line
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-07-02) — Plan 2.8 bytes-per-line mean + exe + bullet-line

- New `scripts/plan_2_8_ledger_byte_size_per_line_mean.py` reports
  the mean byte length of non-blank ledger lines.
- New `scripts/plan_2_8_digest_exe_file_count.py` counts top-level
  ``.exe`` files.
- New `scripts/plan_2_8_weekly_summary_bullet_line_count.py` counts
  Markdown unordered-list bullet lines.
- Weekly workflow wires the three new steps after the empty-line
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-07-01) — Plan 2.8 total bytes + dmg + empty-line

- New `scripts/plan_2_8_ledger_total_byte_size.py` reports the raw
  byte size of the ledger file.
- New `scripts/plan_2_8_digest_dmg_file_count.py` counts top-level
  ``.dmg`` files.
- New `scripts/plan_2_8_weekly_summary_empty_line_count.py` counts
  strictly-empty lines in the weekly summary.
- Weekly workflow wires the three new steps after the
  whitespace-only line upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-30) — Plan 2.8 last record + iso + whitespace-only

- New `scripts/plan_2_8_ledger_last_record_status.py` reports the
  status of the last valid ledger record.
- New `scripts/plan_2_8_digest_iso_file_count.py` counts top-level
  ``.iso`` files.
- New `scripts/plan_2_8_weekly_summary_whitespace_only_line_count.py`
  counts non-empty lines that contain only whitespace.
- Weekly workflow wires the three new steps after the trailing-space
  line upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-29) — Plan 2.8 first record + xvid + trailing-space

- New `scripts/plan_2_8_ledger_first_record_status.py` reports the
  status of the first valid ledger record.
- New `scripts/plan_2_8_digest_xvid_file_count.py` counts top-level
  ``.xvid`` files.
- New `scripts/plan_2_8_weekly_summary_trailing_space_line_count.py`
  counts lines ending with space or tab.
- Weekly workflow wires the three new steps after the leading-space
  line upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-28) — Plan 2.8 status mode + divx + leading-space

- New `scripts/plan_2_8_ledger_status_mode_count.py` reports the
  frequency of the most-common status value.
- New `scripts/plan_2_8_digest_divx_file_count.py` counts top-level
  ``.divx`` files.
- New `scripts/plan_2_8_weekly_summary_leading_space_line_count.py`
  counts lines starting with a space character.
- Weekly workflow wires the three new steps after the indent
  line upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-27) — Plan 2.8 invalid status + ts + indent-line

- New `scripts/plan_2_8_ledger_invalid_status_count.py` counts
  records whose ``status`` is not in the canonical four values.
- New `scripts/plan_2_8_digest_ts_file_count.py` counts top-level
  ``.ts`` files.
- New `scripts/plan_2_8_weekly_summary_indent_line_count.py` counts
  lines starting with space or tab.
- Weekly workflow wires the three new steps after the line
  separator upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-26) — Plan 2.8 captured-at missing + vob + line-separator

- New `scripts/plan_2_8_ledger_captured_at_missing_count.py` counts
  records where ``captured_at`` is missing or empty.
- New `scripts/plan_2_8_digest_vob_file_count.py` counts top-level
  ``.vob`` files.
- New `scripts/plan_2_8_weekly_summary_line_separator_char_count.py`
  counts U+2028 / U+2029 characters in the weekly summary.
- Weekly workflow wires the three new steps after the zero-width
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-25) — Plan 2.8 captured-at present + mxf + zero-width

- New `scripts/plan_2_8_ledger_captured_at_present_count.py` counts
  records that carry a non-empty ``captured_at`` string.
- New `scripts/plan_2_8_digest_mxf_file_count.py` counts top-level
  ``.mxf`` files.
- New `scripts/plan_2_8_weekly_summary_zero_width_char_count.py`
  counts zero-width characters (U+200B / U+200C / U+200D).
- Weekly workflow wires the three new steps after the bom upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-24) — Plan 2.8 unique status + m2ts + bom

- New `scripts/plan_2_8_ledger_unique_status_count.py` counts
  distinct statuses observed in the ledger.
- New `scripts/plan_2_8_digest_m2ts_file_count.py` counts top-level
  ``.m2ts`` files.
- New `scripts/plan_2_8_weekly_summary_bom_char_count.py` counts
  U+FEFF BOM characters in the weekly summary.
- Weekly workflow wires the three new steps after the ascii
  alnum upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-23) — Plan 2.8 unknown span + asf + ascii-alnum

- New `scripts/plan_2_8_ledger_unknown_first_last_index_span.py`
  reports the index span between the first and last unknown records.
- New `scripts/plan_2_8_digest_asf_file_count.py` counts top-level
  ``.asf`` files.
- New `scripts/plan_2_8_weekly_summary_ascii_alnum_char_count.py`
  counts ASCII alphanumerics (A–Z, a–z, 0–9).
- Weekly workflow wires the three new steps after the ascii
  hexdigit upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-22) — Plan 2.8 red span + rm + ascii-hexdigit

- New `scripts/plan_2_8_ledger_red_first_last_index_span.py`
  reports the index span between the first and last red records.
- New `scripts/plan_2_8_digest_rm_file_count.py` counts top-level
  ``.rm`` files.
- New `scripts/plan_2_8_weekly_summary_ascii_hexdigit_char_count.py`
  counts ASCII hexdigits (0–9, a–f, A–F).
- Weekly workflow wires the three new steps after the ascii
  letter upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-21) — Plan 2.8 amber span + 3gp + ascii-letter

- New `scripts/plan_2_8_ledger_amber_first_last_index_span.py`
  reports the index span between the first and last amber records.
- New `scripts/plan_2_8_digest_threegp_file_count.py` counts
  top-level ``.3gp`` files.
- New `scripts/plan_2_8_weekly_summary_ascii_letter_char_count.py`
  counts ASCII letters (A–Z, a–z).
- Weekly workflow wires the three new steps after the ascii
  control upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-20) — Plan 2.8 green span + m4v + ascii-control

- New `scripts/plan_2_8_ledger_green_first_last_index_span.py`
  reports the index span between the first and last green records.
- New `scripts/plan_2_8_digest_m4v_file_count.py` counts top-level
  ``.m4v`` files.
- New `scripts/plan_2_8_weekly_summary_ascii_control_char_count.py`
  counts ASCII control characters (``< 0x20`` or ``0x7F``).
- Weekly workflow wires the three new steps after the ascii
  printable upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-19) — Plan 2.8 unknown streak-count + mpg + ascii-printable

- New `scripts/plan_2_8_ledger_unknown_streak_count.py` counts
  distinct runs of unknown statuses.
- New `scripts/plan_2_8_digest_mpg_file_count.py` counts
  top-level ``.mpg`` files.
- New `scripts/plan_2_8_weekly_summary_ascii_printable_char_count.py`
  counts ASCII printable characters (0x20–0x7E).
- Weekly workflow wires the three new steps after the space char
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-18) — Plan 2.8 red streak-count + flv + space

- New `scripts/plan_2_8_ledger_red_streak_count.py` counts
  distinct runs of red statuses.
- New `scripts/plan_2_8_digest_flv_file_count.py` counts
  top-level ``.flv`` files.
- New `scripts/plan_2_8_weekly_summary_space_char_count.py`
  counts ASCII space characters in the summary.
- Weekly workflow wires the three new steps after the null-byte
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-17) — Plan 2.8 amber streak-count + wmv + null-byte

- New `scripts/plan_2_8_ledger_amber_streak_count.py` counts
  distinct runs of amber statuses.
- New `scripts/plan_2_8_digest_wmv_file_count.py` counts
  top-level ``.wmv`` files.
- New `scripts/plan_2_8_weekly_summary_null_byte_char_count.py`
  counts ``\x00`` bytes in the summary.
- Weekly workflow wires the three new steps after the vertical-tab
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-16) — Plan 2.8 green streak-count + avi + vertical-tab

- New `scripts/plan_2_8_ledger_green_streak_count.py` counts
  distinct runs of green statuses.
- New `scripts/plan_2_8_digest_avi_file_count.py` counts
  top-level ``.avi`` files.
- New `scripts/plan_2_8_weekly_summary_vertical_tab_char_count.py`
  counts ``\v`` bytes in the summary.
- Weekly workflow wires the three new steps after the form-feed
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-15) — Plan 2.8 unknown max + mkv + form-feed

- New `scripts/plan_2_8_ledger_unknown_index_max.py` reports the
  maximum index of an unknown status (-1 if none).
- New `scripts/plan_2_8_digest_mkv_file_count.py` counts
  top-level ``.mkv`` files.
- New `scripts/plan_2_8_weekly_summary_form_feed_char_count.py`
  counts ``\f`` bytes in the summary.
- Weekly workflow wires the three new steps after the carriage
  return upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-14) — Plan 2.8 red max + webm + carriage-return

- New `scripts/plan_2_8_ledger_red_index_max.py` reports the
  maximum index of a red status (-1 if none).
- New `scripts/plan_2_8_digest_webm_file_count.py` counts
  top-level ``.webm`` files.
- New `scripts/plan_2_8_weekly_summary_carriage_return_char_count.py`
  counts ``\r`` bytes in the summary.
- Weekly workflow wires the three new steps after the newline char
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-13) — Plan 2.8 amber max + mov + newline

- New `scripts/plan_2_8_ledger_amber_index_max.py` reports the
  maximum index of an amber status (-1 if none).
- New `scripts/plan_2_8_digest_mov_file_count.py` counts
  top-level ``.mov`` files.
- New `scripts/plan_2_8_weekly_summary_newline_char_count.py`
  counts ``\n`` characters in the summary.
- Weekly workflow wires the three new steps after the ``}`` char
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-12) — Plan 2.8 green max + mp4 + brace-close

- New `scripts/plan_2_8_ledger_green_index_max.py` reports the
  maximum index of a green status (-1 if none).
- New `scripts/plan_2_8_digest_mp4_file_count.py` counts
  top-level ``.mp4`` files.
- New `scripts/plan_2_8_weekly_summary_brace_close_char_count.py`
  counts ``}`` characters in the summary.
- Weekly workflow wires the three new steps after the ``{`` char
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-11) — Plan 2.8 unknown min + flac + brace-open

- New `scripts/plan_2_8_ledger_unknown_index_min.py` reports the
  minimum index of an unknown status (-1 if none).
- New `scripts/plan_2_8_digest_flac_file_count.py` counts
  top-level ``.flac`` files.
- New `scripts/plan_2_8_weekly_summary_brace_open_char_count.py`
  counts ``{`` characters in the summary.
- Weekly workflow wires the three new steps after the ``]`` char
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-10) — Plan 2.8 red min + ogg + bracket-close

- New `scripts/plan_2_8_ledger_red_index_min.py` reports the
  minimum index of a red status (-1 if none).
- New `scripts/plan_2_8_digest_ogg_file_count.py` counts
  top-level ``.ogg`` files.
- New `scripts/plan_2_8_weekly_summary_bracket_close_char_count.py`
  counts ``]`` characters in the summary.
- Weekly workflow wires the three new steps after the ``[`` char
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-09) — Plan 2.8 amber min + wav + bracket-open

- New `scripts/plan_2_8_ledger_amber_index_min.py` reports the
  minimum index of an amber status (-1 if none).
- New `scripts/plan_2_8_digest_wav_file_count.py` counts
  top-level ``.wav`` files.
- New `scripts/plan_2_8_weekly_summary_bracket_open_char_count.py`
  counts ``[`` characters in the summary.
- Weekly workflow wires the three new steps after the ``)`` char
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-08) — Plan 2.8 green min + mp3 + paren-close

- New `scripts/plan_2_8_ledger_green_index_min.py` reports the
  minimum index of a green status (-1 if none).
- New `scripts/plan_2_8_digest_mp3_file_count.py` counts top-level
  ``.mp3`` files.
- New `scripts/plan_2_8_weekly_summary_paren_close_char_count.py`
  counts ``)`` characters in the summary.
- Weekly workflow wires the three new steps after the ``(`` char
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-07) — Plan 2.8 unknown variance + raw + paren-open

- New `scripts/plan_2_8_ledger_unknown_index_variance.py` reports
  the population variance of unknown indices.
- New `scripts/plan_2_8_digest_raw_file_count.py` counts
  top-level ``.raw`` files.
- New `scripts/plan_2_8_weekly_summary_paren_open_char_count.py`
  counts ``(`` characters in the summary.
- Weekly workflow wires the three new steps after the ``>`` char
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-06) — Plan 2.8 red variance + psd + gt

- New `scripts/plan_2_8_ledger_red_index_variance.py` reports the
  population variance of red indices.
- New `scripts/plan_2_8_digest_psd_file_count.py` counts top-level
  ``.psd`` files.
- New `scripts/plan_2_8_weekly_summary_gt_char_count.py` counts
  ``>`` characters in the summary.
- Weekly workflow wires the three new steps after the ``<`` char
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-05) — Plan 2.8 amber variance + avif + lt

- New `scripts/plan_2_8_ledger_amber_index_variance.py` reports
  the population variance of amber indices.
- New `scripts/plan_2_8_digest_avif_file_count.py` counts
  top-level ``.avif`` files.
- New `scripts/plan_2_8_weekly_summary_lt_char_count.py` counts
  ``<`` characters in the summary.
- Weekly workflow wires the three new steps after the percent
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-04) — Plan 2.8 green variance + heic + percent

- New `scripts/plan_2_8_ledger_green_index_variance.py` reports
  the population variance of green indices.
- New `scripts/plan_2_8_digest_heic_file_count.py` counts
  top-level ``.heic`` files.
- New `scripts/plan_2_8_weekly_summary_percent_char_count.py`
  counts ``%`` characters in the summary.
- Weekly workflow wires the three new steps after the ampersand
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-03) — Plan 2.8 unknown stddev + tif + ampersand

- New `scripts/plan_2_8_ledger_unknown_index_stddev.py` reports
  the population stddev of unknown indices.
- New `scripts/plan_2_8_digest_tif_file_count.py` counts top-level
  ``.tif``/``.tiff`` files.
- New `scripts/plan_2_8_weekly_summary_ampersand_char_count.py`
  counts ``&`` characters in the summary.
- Weekly workflow wires the three new steps after the ``@`` char
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-02) — Plan 2.8 red stddev + bmp + at

- New `scripts/plan_2_8_ledger_red_index_stddev.py` reports the
  population stddev of red indices.
- New `scripts/plan_2_8_digest_bmp_file_count.py` counts top-level
  ``.bmp`` files.
- New `scripts/plan_2_8_weekly_summary_at_char_count.py` counts
  ``@`` characters in the summary.
- Weekly workflow wires the three new steps after the dollar
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-06-01) — Plan 2.8 amber stddev + ico + dollar

- New `scripts/plan_2_8_ledger_amber_index_stddev.py` reports the
  population stddev of amber indices.
- New `scripts/plan_2_8_digest_ico_file_count.py` counts top-level
  ``.ico`` files.
- New `scripts/plan_2_8_weekly_summary_dollar_char_count.py`
  counts ``$`` characters in the summary.
- Weekly workflow wires the three new steps after the grave
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-31) — Plan 2.8 green stddev + webp + grave

- New `scripts/plan_2_8_ledger_green_index_stddev.py` reports the
  population stddev of green indices.
- New `scripts/plan_2_8_digest_webp_file_count.py` counts
  top-level ``.webp`` files.
- New `scripts/plan_2_8_weekly_summary_grave_char_count.py` counts
  grave accent characters in the summary.
- Weekly workflow wires the three new steps after the tilde
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-30) — Plan 2.8 unknown median + jpg + tilde

- New `scripts/plan_2_8_ledger_unknown_index_median.py` reports
  the median index of unknown records.
- New `scripts/plan_2_8_digest_jpg_file_count.py` counts top-level
  ``.jpg``/``.jpeg`` files.
- New `scripts/plan_2_8_weekly_summary_tilde_char_count.py` counts
  ``~`` characters in the summary.
- Weekly workflow wires the three new steps after the caret
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-29) — Plan 2.8 red median + gif + caret

- New `scripts/plan_2_8_ledger_red_index_median.py` reports the
  median index of red records.
- New `scripts/plan_2_8_digest_gif_file_count.py` counts top-level
  ``.gif`` files.
- New `scripts/plan_2_8_weekly_summary_caret_char_count.py` counts
  ``^`` characters in the summary.
- Weekly workflow wires the three new steps after the backslash
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-28) — Plan 2.8 amber median + svg + backslash

- New `scripts/plan_2_8_ledger_amber_index_median.py` reports the
  median index of amber records.
- New `scripts/plan_2_8_digest_svg_file_count.py` counts top-level
  ``.svg`` files.
- New `scripts/plan_2_8_weekly_summary_backslash_char_count.py`
  counts ``\`` characters in the summary.
- Weekly workflow wires the three new steps after the slash
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-27) — Plan 2.8 green median + pdf + slash

- New `scripts/plan_2_8_ledger_green_index_median.py` reports the
  median index of green records.
- New `scripts/plan_2_8_digest_pdf_file_count.py` counts top-level
  ``.pdf`` files.
- New `scripts/plan_2_8_weekly_summary_slash_char_count.py` counts
  ``/`` characters in the summary.
- Weekly workflow wires the three new steps after the asterisk
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-26) — Plan 2.8 transition rate + xz + asterisk

- New `scripts/plan_2_8_ledger_status_transition_rate.py` reports
  the fraction of pairwise status transitions.
- New `scripts/plan_2_8_digest_xz_file_count.py` counts top-level
  ``.xz`` files.
- New `scripts/plan_2_8_weekly_summary_asterisk_char_count.py`
  counts ``*`` characters in the summary.
- Weekly workflow wires the three new steps after the equal-count
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-25) — Plan 2.8 last transition + bz2 + equal

- New `scripts/plan_2_8_ledger_last_transition_index.py` surfaces
  the last status change index.
- New `scripts/plan_2_8_digest_bz2_file_count.py` counts top-level
  ``.bz2`` files.
- New `scripts/plan_2_8_weekly_summary_equal_char_count.py` counts
  ``=`` characters in the summary.
- Weekly workflow wires the three new steps after the minus-count
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-24) — Plan 2.8 first transition + gz + minus

- New `scripts/plan_2_8_ledger_first_transition_index.py` surfaces
  the first status change index.
- New `scripts/plan_2_8_digest_gz_file_count.py` counts top-level
  ``.gz`` files.
- New `scripts/plan_2_8_weekly_summary_minus_char_count.py` counts
  ``-`` characters in the summary.
- Weekly workflow wires the three new steps after the plus-count
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-23) — Plan 2.8 status transitions + tar files + plus

- New `scripts/plan_2_8_ledger_status_transition_count.py` counts
  adjacent status transitions in the ledger.
- New `scripts/plan_2_8_digest_tar_file_count.py` counts top-level
  ``.tar``/``.tgz`` files.
- New `scripts/plan_2_8_weekly_summary_plus_char_count.py` counts
  ``+`` characters in the summary.
- Weekly workflow wires the three new steps after the
  underscore-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-22) — Plan 2.8 unknown index mean + zip files + underscore

- New `scripts/plan_2_8_ledger_unknown_index_mean.py` reports the
  arithmetic mean of unknown observation indices.
- New `scripts/plan_2_8_digest_zip_file_count.py` counts top-level
  ``.zip`` files.
- New `scripts/plan_2_8_weekly_summary_underscore_char_count.py`
  counts ``_`` characters in the summary.
- Weekly workflow wires the three new steps after the pipe-count
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-21) — Plan 2.8 red index mean + html files + pipe

- New `scripts/plan_2_8_ledger_red_index_mean.py` reports the
  arithmetic mean of red observation indices.
- New `scripts/plan_2_8_digest_html_file_count.py` counts top-level
  ``.html``/``.htm`` files.
- New `scripts/plan_2_8_weekly_summary_pipe_char_count.py` counts
  ``|`` characters in the summary.
- Weekly workflow wires the three new steps after the
  apostrophe-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-20) — Plan 2.8 amber index mean + xml files + apostrophe

- New `scripts/plan_2_8_ledger_amber_index_mean.py` reports the
  arithmetic mean of amber observation indices.
- New `scripts/plan_2_8_digest_xml_file_count.py` counts top-level
  ``.xml`` files.
- New `scripts/plan_2_8_weekly_summary_apostrophe_char_count.py`
  counts ASCII single-quote characters in the summary.
- Weekly workflow wires the three new steps after the quote-count
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-19) — Plan 2.8 green index mean + log files + quote

- New `scripts/plan_2_8_ledger_green_index_mean.py` reports the
  arithmetic mean of green observation indices.
- New `scripts/plan_2_8_digest_log_file_count.py` counts top-level
  ``.log`` files.
- New `scripts/plan_2_8_weekly_summary_quote_char_count.py` counts
  ASCII double-quote characters in the summary.
- Weekly workflow wires the three new steps after the colon-count
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-18) — Plan 2.8 last unknown + tsv files + colon

- New `scripts/plan_2_8_ledger_last_unknown_index.py` reports the
  zero-based index of the most recent unknown observation.
- New `scripts/plan_2_8_digest_tsv_file_count.py` counts top-level
  ``.tsv`` files.
- New `scripts/plan_2_8_weekly_summary_colon_char_count.py` counts
  ``:`` characters in the summary.
- Weekly workflow wires the three new steps after the
  semicolon-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-17) — Plan 2.8 last red + csv files + semicolon

- New `scripts/plan_2_8_ledger_last_red_index.py` reports the
  zero-based index of the most recent red observation.
- New `scripts/plan_2_8_digest_csv_file_count.py` counts top-level
  ``.csv`` files.
- New `scripts/plan_2_8_weekly_summary_semicolon_char_count.py`
  counts ``;`` characters in the summary.
- Weekly workflow wires the three new steps after the comma-count
  upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-16) — Plan 2.8 last amber + png files + comma

- New `scripts/plan_2_8_ledger_last_amber_index.py` reports the
  zero-based index of the most recent amber observation.
- New `scripts/plan_2_8_digest_png_file_count.py` counts top-level
  ``.png`` files.
- New `scripts/plan_2_8_weekly_summary_comma_char_count.py` counts
  ``,`` characters in the summary.
- Weekly workflow wires the three new steps after the
  exclamation-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-15) — Plan 2.8 last green + yml files + exclamation

- New `scripts/plan_2_8_ledger_last_green_index.py` reports the
  zero-based index of the most recent green observation.
- New `scripts/plan_2_8_digest_yml_file_count.py` counts top-level
  ``.yml``/``.yaml`` files.
- New `scripts/plan_2_8_weekly_summary_exclamation_char_count.py`
  counts ``!`` characters in the summary.
- Weekly workflow wires the three new steps after the
  question-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-14) — Plan 2.8 first unknown + jsonl files + question

- New `scripts/plan_2_8_ledger_first_unknown_index.py` reports the
  zero-based index of the first unknown observation.
- New `scripts/plan_2_8_digest_jsonl_file_count.py` reports the
  count of top-level ``.jsonl`` files.
- New `scripts/plan_2_8_weekly_summary_question_char_count.py`
  counts ``?`` characters in the summary.
- Weekly workflow wires the three new steps after the
  sentence-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-14) — Plan 2.8 first red + txt files + sentences

- New `scripts/plan_2_8_ledger_first_red_index.py` reports the
  zero-based index of the first red observation.
- New `scripts/plan_2_8_digest_txt_file_count.py` reports the
  count of top-level ``.txt`` files.
- New `scripts/plan_2_8_weekly_summary_sentence_count.py`
  counts sentence terminators in the summary.
- Weekly workflow wires the three new steps after the
  non-ascii-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-14) — Plan 2.8 first amber + json files + non-ascii

- New `scripts/plan_2_8_ledger_first_amber_index.py` reports the
  zero-based index of the first amber observation.
- New `scripts/plan_2_8_digest_json_file_count.py` reports the
  count of top-level ``.json`` files.
- New `scripts/plan_2_8_weekly_summary_non_ascii_char_count.py`
  counts code points with ord > 127 in the summary.
- Weekly workflow wires the three new steps after the
  hash-char upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-14) — Plan 2.8 first green + md files + hash chars

- New `scripts/plan_2_8_ledger_first_green_index.py` reports the
  zero-based index of the first green observation.
- New `scripts/plan_2_8_digest_md_file_count.py` reports the
  count of top-level ``.md`` files.
- New `scripts/plan_2_8_weekly_summary_hash_char_count.py`
  counts ``#`` characters in the summary.
- Weekly workflow wires the three new steps after the
  tab-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-14) — Plan 2.8 unknown streak + nonempty files + tabs

- New `scripts/plan_2_8_ledger_unknown_streak_max.py` reports the
  longest consecutive unknown run.
- New `scripts/plan_2_8_digest_nonempty_file_count.py` reports the
  count of top-level files with size > 0.
- New `scripts/plan_2_8_weekly_summary_tab_char_count.py` counts
  ASCII tab characters in the summary.
- Weekly workflow wires the three new steps after the
  whitespace-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-14) — Plan 2.8 green streak + smallest file + whitespace

- New `scripts/plan_2_8_ledger_green_streak_max.py` reports the
  longest consecutive green run.
- New `scripts/plan_2_8_digest_smallest_file_size.py` reports the
  byte size of the smallest top-level file.
- New `scripts/plan_2_8_weekly_summary_whitespace_char_count.py`
  counts ASCII whitespace characters in the summary.
- Weekly workflow wires the three new steps after the
  lowercase-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-14) — Plan 2.8 red streak + largest file + lowercase

- New `scripts/plan_2_8_ledger_red_streak_max.py` reports the
  longest consecutive red run.
- New `scripts/plan_2_8_digest_largest_file_size.py` reports the
  byte size of the largest top-level file.
- New `scripts/plan_2_8_weekly_summary_lowercase_letter_count.py`
  counts ASCII lowercase letters in the summary.
- Weekly workflow wires the three new steps after the
  uppercase-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-14) — Plan 2.8 amber streak + size variance + uppercase

- New `scripts/plan_2_8_ledger_amber_streak_max.py` reports the
  longest consecutive amber run.
- New `scripts/plan_2_8_digest_file_size_variance.py` reports
  the population variance of top-level file sizes.
- New `scripts/plan_2_8_weekly_summary_uppercase_letter_count.py`
  counts ASCII uppercase letters in the summary.
- Weekly workflow wires the three new steps after the
  vowel-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-14) — Plan 2.8 record byte mean + total bytes + vowels

- New `scripts/plan_2_8_ledger_record_byte_size_mean.py` reports
  mean UTF-8 byte length of non-blank ledger lines.
- New `scripts/plan_2_8_digest_total_byte_size.py` reports the
  total byte size of top-level regular files.
- New `scripts/plan_2_8_weekly_summary_vowel_count.py` counts
  ASCII vowels in the summary file.
- Weekly workflow wires the three new steps after the
  checkbox-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-05-14) — Plan 2.8 obs-per-day + size mean + checkboxes

- New `scripts/plan_2_8_ledger_observations_per_day_mean.py`
  reports mean observations per distinct day.
- New `scripts/plan_2_8_digest_file_size_mean.py` reports
  the arithmetic mean of top-level regular-file sizes.
- New `scripts/plan_2_8_weekly_summary_checkbox_count.py`
  counts GFM task-list checkbox lines.
- Weekly workflow wires the three new steps after the
  backtick-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-05-13) — Plan 2.8 unique days + total lines + backticks

- New `scripts/plan_2_8_ledger_unique_days.py` reports the
  count of distinct YYYY-MM-DD prefixes.
- New `scripts/plan_2_8_digest_total_line_count.py` sums
  lines across top-level text files.
- New `scripts/plan_2_8_weekly_summary_backtick_count.py`
  counts backtick characters in the summary.
- Weekly workflow wires the three new steps after the
  heading-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-05-12) — Plan 2.8 ledger blanks + writable frac + headings

- New `scripts/plan_2_8_ledger_blank_line_count.py` counts
  whitespace-only lines in the ledger.
- New `scripts/plan_2_8_digest_writable_fraction.py` reports
  writable file share among top-level regular files.
- New `scripts/plan_2_8_weekly_summary_heading_count.py`
  counts ATX headings in the summary file.
- Weekly workflow wires the three new steps after the
  avg-word-length upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-05-11) — Plan 2.8 malformed + readable frac + avg word

- New `scripts/plan_2_8_ledger_malformed_count.py` counts
  non-JSON ledger lines.
- New `scripts/plan_2_8_digest_readable_fraction.py` reports
  readable file fraction among top-level regular files.
- New `scripts/plan_2_8_weekly_summary_avg_word_length.py`
  reports mean whitespace token length.
- Weekly workflow wires the three new steps after the
  longest-word upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-05-10) — Plan 2.8 last obs + size median + longest word

- New `scripts/plan_2_8_ledger_last_observation.py` reports
  the last ``captured_at`` string across valid records.
- New `scripts/plan_2_8_digest_file_size_median.py` reports
  the median of top-level regular-file sizes.
- New `scripts/plan_2_8_weekly_summary_longest_word.py``
  reports the longest whitespace token.
- Weekly workflow wires the three new steps after the
  trailing-whitespace-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-05-09) — Plan 2.8 first obs + missing files + trailing ws

- New `scripts/plan_2_8_ledger_first_observation.py` reports
  the ``captured_at`` of the first valid ledger record.
- New `scripts/plan_2_8_digest_missing_files.py` flags which
  canonical digest files are missing from the output dir.
- New `scripts/plan_2_8_weekly_summary_trailing_whitespace_count.py`
  counts lines ending with space or tab.
- Weekly workflow wires the three new steps after the
  unique-word-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-05-08) — Plan 2.8 status entropy + size range + unique words

- New `scripts/plan_2_8_ledger_status_entropy.py` reports the
  Shannon entropy (base 2) of the status distribution.
- New `scripts/plan_2_8_digest_file_size_range.py` reports
  ``max - min`` of top-level regular-file sizes.
- New `scripts/plan_2_8_weekly_summary_unique_word_count.py``
  reports the count of distinct case-folded tokens.
- Weekly workflow wires the three new steps after the
  line-length-stddev upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-05-07) — Plan 2.8 green ratio + size stddev + line stddev

- New `scripts/plan_2_8_ledger_green_ratio.py` reports the
  share of valid observations recorded as ``green``.
- New `scripts/plan_2_8_digest_file_size_stddev.py` reports
  the population stddev of top-level regular-file sizes.
- New `scripts/plan_2_8_weekly_summary_line_length_stddev.py``
  reports the population stddev of line lengths.
- Weekly workflow wires the three new steps after the
  max-line-length upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-05-06) — Plan 2.8 coverage + min size + max line

- New `scripts/plan_2_8_ledger_status_coverage.py` reports
  fraction of canonical statuses observed.
- New `scripts/plan_2_8_digest_min_file_size.py` reports
  smallest top-level regular-file size.
- New `scripts/plan_2_8_weekly_summary_max_line_length.py`
  reports the longest line in the summary.
- Weekly workflow wires the three new steps after the
  median-line-length upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-05-05) — Plan 2.8 set size + max size + median line

- New `scripts/plan_2_8_ledger_status_set_size.py` reports
  the count of distinct canonical statuses observed.
- New `scripts/plan_2_8_digest_max_file_size.py` reports
  the largest top-level regular-file size.
- New `scripts/plan_2_8_weekly_summary_median_line_length.py`
  reports median line length across the summary.
- Weekly workflow wires the three new steps after the
  mean-line-length upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-05-04) — Plan 2.8 most common + executable + mean line

- New `scripts/plan_2_8_ledger_most_common_status.py` reports
  the most common canonical status.
- New `scripts/plan_2_8_digest_executable_file_count.py`
  counts executable top-level regular files.
- New `scripts/plan_2_8_weekly_summary_mean_line_length.py`
  reports mean line length across all lines.
- Weekly workflow wires the three new steps after the
  first-line-length upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-05-03) — Plan 2.8 rarest + writable + first-line

- New `scripts/plan_2_8_ledger_rarest_status.py` reports
  the rarest canonical status.
- New `scripts/plan_2_8_digest_writable_file_count.py`
  counts writable top-level regular files.
- New `scripts/plan_2_8_weekly_summary_first_line_length.py`
  reports length of first non-blank line.
- Weekly workflow wires the three new steps after the
  last-line-length upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-05-02) — Plan 2.8 per-status observations + readable + last-line

- New `scripts/plan_2_8_ledger_observations_by_status.py`
  reports observation counts split by canonical status.
- New `scripts/plan_2_8_digest_readable_file_count.py`
  counts readable top-level regular files.
- New `scripts/plan_2_8_weekly_summary_last_line_length.py`
  reports length of last non-blank line.
- Weekly workflow wires the three new steps after the
  starts-with-heading upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-05-01) — Plan 2.8 observations + binary + heading

- New `scripts/plan_2_8_ledger_observation_count.py` reports
  total valid status observations.
- New `scripts/plan_2_8_digest_binary_file_count.py` counts
  top-level files containing NUL bytes.
- New `scripts/plan_2_8_weekly_summary_starts_with_heading.py`
  probes whether the summary starts with an H1 line.
- Weekly workflow wires the three new steps after the
  trailing-newline upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-30) — Plan 2.8 variance + regular files + trailing NL

- New `scripts/plan_2_8_ledger_run_length_variance.py`
  reports population variance of run lengths.
- New `scripts/plan_2_8_digest_regular_file_count.py`
  counts top-level regular-file entries.
- New `scripts/plan_2_8_weekly_summary_trailing_newline.py`
  probes whether the summary ends with a newline.
- Weekly workflow wires the three new steps after the
  crlf-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-29) — Plan 2.8 iqr + directories + crlf

- New `scripts/plan_2_8_ledger_run_length_iqr.py` reports
  interquartile range of status run lengths.
- New `scripts/plan_2_8_digest_directory_count.py` counts
  top-level directory entries.
- New `scripts/plan_2_8_weekly_summary_crlf_count.py` counts
  CRLF sequences in the weekly summary body.
- Weekly workflow wires the three new steps after the
  cr-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-28) — Plan 2.8 total per status + symlinks + CR

- New `scripts/plan_2_8_ledger_total_run_length_per_status.py`
  reports total observations per canonical status.
- New `scripts/plan_2_8_digest_symlink_count.py`
  counts top-level symlink entries.
- New `scripts/plan_2_8_weekly_summary_cr_count.py`
  counts CR (``\r``) characters in the weekly summary.
- Weekly workflow wires the three new steps after the
  newline-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-28) — Plan 2.8 median per status + unique ext + newlines

- New `scripts/plan_2_8_ledger_median_run_length_per_status.py`
  reports median run length per canonical status.
- New `scripts/plan_2_8_digest_unique_extension_count.py`
  reports count of distinct top-level extensions.
- New `scripts/plan_2_8_weekly_summary_newline_count.py`
  counts LF characters in the weekly summary body.
- Weekly workflow wires the three new steps after the
  tab-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-28) — Plan 2.8 min per status + alpha + tabs

- New `scripts/plan_2_8_ledger_min_run_length_per_status.py`
  reports the shortest run length per canonical status.
- New `scripts/plan_2_8_digest_alpha_basename_count.py`
  counts top-level files whose stem is letters only.
- New `scripts/plan_2_8_weekly_summary_tab_count.py`
  counts tab (U+0009) characters in the weekly summary.
- Weekly workflow wires the three new steps after the
  space-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-28) — Plan 2.8 max per status + numeric + spaces

- New `scripts/plan_2_8_ledger_max_run_length_per_status.py`
  reports the longest run length per canonical status.
- New `scripts/plan_2_8_digest_numeric_basename_count.py`
  counts top-level files whose stem is digits only.
- New `scripts/plan_2_8_weekly_summary_space_count.py`
  counts ASCII U+0020 space characters.
- Weekly workflow wires the three new steps after the
  punctuation-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-28) — Plan 2.8 mean per status + hidden + punctuation

- New `scripts/plan_2_8_ledger_mean_run_length_per_status.py`
  reports mean run length broken down by canonical status.
- New `scripts/plan_2_8_digest_hidden_file_count.py`
  counts top-level files whose basename starts with '.'.
- New `scripts/plan_2_8_weekly_summary_punctuation_count.py`
  counts ASCII punctuation characters in the weekly summary.
- Weekly workflow wires the three new steps after the
  letter-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-28) — Plan 2.8 run-length range + lowercase + letters

- New `scripts/plan_2_8_ledger_run_length_range.py`
  reports the max-minus-min of status run lengths.
- New `scripts/plan_2_8_digest_lowercase_filename_count.py`
  counts top-level files with no uppercase ASCII letters.
- New `scripts/plan_2_8_weekly_summary_letter_count.py`
  counts ASCII letter characters in the weekly summary.
- Weekly workflow wires the three new steps after the
  digit-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-28) — Plan 2.8 shortest run + uppercase + digits

- New `scripts/plan_2_8_ledger_shortest_run.py`
  reports the minimum status run length.
- New `scripts/plan_2_8_digest_uppercase_filename_count.py`
  counts top-level files with uppercase ASCII letters.
- New `scripts/plan_2_8_weekly_summary_digit_count.py`
  counts ASCII digit characters in the weekly summary.
- Weekly workflow wires the three new steps after the
  whitespace-ratio upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-28) — Plan 2.8 stddev run + ext counts + whitespace

- New `scripts/plan_2_8_ledger_stddev_run_length.py`
  reports the population stddev of status run lengths.
- New `scripts/plan_2_8_digest_file_count_by_ext.py`
  reports file counts per top-level extension.
- New `scripts/plan_2_8_weekly_summary_whitespace_ratio.py`
  reports whitespace share of the weekly summary body.
- Weekly workflow wires the three new steps after the
  non-blank-line upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-28) — Plan 2.8 median run + empty file + non-blank

- New `scripts/plan_2_8_ledger_median_run_length.py`
  reports the median length of consecutive status runs.
- New `scripts/plan_2_8_digest_empty_file_count.py`
  reports the number of zero-byte artifact files.
- New `scripts/plan_2_8_weekly_summary_non_blank_line_count.py`
  counts lines containing any non-whitespace character.
- Weekly workflow wires the three new steps after the
  blank-line upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-28) — Plan 2.8 avg run length + non-empty + blank-line

- New `scripts/plan_2_8_ledger_avg_run_length.py` reports
  the mean length of consecutive status runs.
- New `scripts/plan_2_8_digest_non_empty_file_count.py`
  reports the number of top-level artifact files with
  size greater than zero.
- New `scripts/plan_2_8_weekly_summary_blank_line_count.py`
  counts whitespace-only lines in the weekly summary.
- Weekly workflow wires the three new steps after the
  diff-fence upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-28) — Plan 2.8 run min + total size + diff-fence

- New `scripts/plan_2_8_ledger_status_run_min.py` reports
  the shortest consecutive status run.
- New `scripts/plan_2_8_digest_total_size.py` reports the
  total byte size across top-level artifact files.
- New `scripts/plan_2_8_weekly_summary_diff_fence_count.py`
  counts fenced code blocks whose info-string is
  ``diff``/``patch``.
- Weekly workflow wires the three new steps after the
  json-fence upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-28) — Plan 2.8 run max + avg size + json-fence

- New `scripts/plan_2_8_ledger_status_run_max.py`
  reports the longest consecutive status run.
- New `scripts/plan_2_8_digest_avg_size.py` reports
  mean bytes per file across the artifact directory.
- New `scripts/plan_2_8_weekly_summary_json_fence_count.py`
  counts fenced code blocks whose info-string is
  ``json``/``json5``/``jsonc``.
- Weekly workflow wires the three new steps after the
  yaml-fence upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-28) — Plan 2.8 run summary + shortest filename + yaml-fence

- New `scripts/plan_2_8_ledger_status_run_summary.py`
  enumerates every consecutive status run with start,
  end, and length.
- New `scripts/plan_2_8_digest_shortest_filename.py`
  reports the top-level file with the shortest basename.
- New `scripts/plan_2_8_weekly_summary_yaml_fence_count.py`
  counts fenced code blocks whose info-string is
  ``yaml``/``yml``.
- Weekly workflow wires the three new steps after the
  python-fence upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-28) — Plan 2.8 run count + longest filename + python-fence

- New `scripts/plan_2_8_ledger_status_run_count.py`
  reports the total number of distinct consecutive
  status runs.
- New `scripts/plan_2_8_digest_longest_filename.py`
  reports the top-level file with the longest basename.
- New `scripts/plan_2_8_weekly_summary_python_fence_count.py`
  counts fenced code blocks whose info-string is
  ``python``/``py``/``python3``.
- Weekly workflow wires the three new steps after the
  shell-fence upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-28) — Plan 2.8 status first/last + basename length + shell-fence

- New `scripts/plan_2_8_ledger_status_first_last.py`
  reports the first and last timestamp per observed
  ledger status.
- New `scripts/plan_2_8_digest_basename_length_stats.py`
  reports min/max/mean of file-basename lengths across
  the top-level artifact directory.
- New `scripts/plan_2_8_weekly_summary_shell_fence_count.py`
  counts fenced code blocks whose info-string is
  ``sh``/``bash``/``zsh``/``shell``.
- Weekly workflow wires the three new steps after the
  emoji-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-28) — Plan 2.8 last unknown + line counts + emoji count

- New `scripts/plan_2_8_ledger_last_unknown.py` reports
  the timestamp of the most recent unknown ledger record.
- New `scripts/plan_2_8_digest_line_counts.py` reports
  per-file newline-based line counts plus a grand total.
- New `scripts/plan_2_8_weekly_summary_emoji_count.py`
  counts ``:emoji:`` shortcodes while excluding fenced
  blocks and inline code.
- Weekly workflow wires the three new steps after the
  autolink-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-28) — Plan 2.8 last amber + word count + autolink count

- New `scripts/plan_2_8_ledger_last_amber.py` reports the
  timestamp of the most recent amber ledger record.
- New `scripts/plan_2_8_digest_word_count.py` reports the
  total word count across all artifact files plus a
  per-file breakdown sorted by name.
- New `scripts/plan_2_8_weekly_summary_autolink_count.py`
  counts ``<https:…>``/``<http:…>``/``<mailto:…>`` auto
  links while excluding fenced blocks and inline code.
- Weekly workflow wires the three new steps after the
  HTML-tag-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-27) — Plan 2.8 last red + per-ext bytes + HTML tag count

- New `scripts/plan_2_8_ledger_last_red.py` reports the
  timestamp of the most recent red ledger record.
- New `scripts/plan_2_8_digest_per_ext_bytes.py` reports
  total bytes per file extension (``(none)`` bucket for
  suffix-less files), sorted by bytes descending.
- New `scripts/plan_2_8_weekly_summary_html_tag_count.py`
  counts raw HTML tag occurrences while excluding fenced
  blocks, inline code, and HTML comments.
- Weekly workflow wires the three new steps after the
  reference-defs upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-26) — Plan 2.8 first unknown + mtime span + reference defs

- New `scripts/plan_2_8_ledger_first_unknown.py` reports the
  timestamp of the earliest unknown ledger record.
- New `scripts/plan_2_8_digest_mtime_span.py` reports the
  oldest→newest mtime span in hours across artifact files.
- New `scripts/plan_2_8_weekly_summary_reference_defs.py`
  counts Markdown link reference definitions (``[label]:
  url``), returning a sorted label list; fenced blocks are
  excluded.
- Weekly workflow wires the three new steps after the
  strikethrough-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-25) — Plan 2.8 first amber + median mtime + strikethrough count

- New `scripts/plan_2_8_ledger_first_amber.py` reports the
  timestamp of the earliest amber ledger record.
- New `scripts/plan_2_8_digest_median_mtime.py` reports the
  median mtime across top-level artifact files (lower
  middle for even counts).
- New `scripts/plan_2_8_weekly_summary_strikethrough_count.py`
  counts ``~~text~~`` spans while excluding fenced blocks
  and inline code.
- Weekly workflow wires the three new steps after the
  bold-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-24) — Plan 2.8 first red + newest file + bold count

- New `scripts/plan_2_8_ledger_first_red.py` reports the
  timestamp of the earliest red ledger record.
- New `scripts/plan_2_8_digest_newest_file.py` reports the
  single newest artifact-directory file by mtime.
- New `scripts/plan_2_8_weekly_summary_bold_count.py` counts
  ``**bold**`` and ``__bold__`` strong-emphasis spans while
  excluding fenced blocks and inline code.
- Weekly workflow wires the three new steps after the
  footnote-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-23) — Plan 2.8 green streak history + oldest file + footnote count

- New `scripts/plan_2_8_ledger_green_streak_history.py` lists
  all past green-streak segments in chronological order with
  length and duration-in-hours per segment.
- New `scripts/plan_2_8_digest_oldest_file.py` reports the
  single oldest artifact-directory file by mtime (subdirs
  ignored).
- New `scripts/plan_2_8_weekly_summary_footnote_count.py`
  counts Markdown footnote references and definitions while
  excluding fenced code blocks.
- Weekly workflow wires the three new steps after the
  longest-line upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-22) — Plan 2.8 longest gap + duplicate sizes + longest line

- New `scripts/plan_2_8_ledger_longest_gap.py` reports the
  longest gap in hours between consecutive captures plus the
  boundary timestamps; ``--fail-above-hours`` for CI.
- New `scripts/plan_2_8_digest_duplicate_sizes.py` groups
  artifact files by identical byte size to surface suspect
  duplicates; ``--fail-on-duplicates`` for CI.
- New `scripts/plan_2_8_weekly_summary_longest_line.py`
  reports the longest line length and its 1-based line
  number; ``--fail-above-length`` for CI.
- Weekly workflow wires the three new steps after the
  sha256 upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-21) — Plan 2.8 captures per day + tiny files + summary sha256

- New `scripts/plan_2_8_ledger_captures_per_day.py` groups
  ledger records by UTC date and reports per-day capture
  counts; malformed timestamps and invalid statuses are
  skipped; days sorted ascending.
- New `scripts/plan_2_8_digest_tiny_files.py` lists artifact
  files below a configurable byte threshold (default 100B);
  boundary is exclusive; subdirs ignored;
  ``--fail-on-tiny`` for CI.
- New `scripts/plan_2_8_weekly_summary_sha256.py` computes a
  stable SHA256 fingerprint of the full weekly summary along
  with size and line counts.
- Weekly workflow wires the three new steps after the
  ordered-list-count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-04-21) — Plan 2.8 oldest captured_at + top ext + ordered list count

- New `scripts/plan_2_8_ledger_oldest_captured_at.py` reports
  the earliest ``captured_at`` in the ledger and its age in
  hours relative to ``--now`` (``--fail-below-hours``).
- New `scripts/plan_2_8_digest_ext_top.py` reports the most
  common file extension in the artifact dir (ties broken
  alphabetically, no-ext grouped); ``--fail-below-count``.
- New `scripts/plan_2_8_weekly_summary_ordered_list_count.py`
  counts ordered list items (``1.`` or ``1)``) in the weekly
  summary (fenced code excluded).
- Weekly workflow wires the three new steps after the list
  count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-21) — Plan 2.8 latest captured_at + smallest file + list count

- New `scripts/plan_2_8_ledger_latest_captured_at.py` reports
  the most recent ``captured_at`` timestamp (status-agnostic)
  and its age in hours relative to ``--now``
  (``--fail-above-hours`` for CI).
- New `scripts/plan_2_8_digest_smallest_file.py` reports the
  smallest non-empty file in the artifact dir (ties broken
  by name); ``--fail-below-bytes`` for CI.
- New `scripts/plan_2_8_weekly_summary_list_count.py` counts
  unordered list items (``-`` or ``*``) in the weekly
  summary (horizontal rules and fenced code excluded).
- Weekly workflow wires the three new steps after the link
  count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-21) — Plan 2.8 first green age + largest file + link count

- New `scripts/plan_2_8_ledger_first_green_age.py` reports
  hours since the first green ledger capture relative to
  ``--now`` (``--fail-below-hours`` for CI).
- New `scripts/plan_2_8_digest_largest_file.py` reports the
  largest artifact file by byte size (ties broken by name).
- New `scripts/plan_2_8_weekly_summary_link_count.py` counts
  Markdown inline links ``[text](url)`` and their distinct
  targets (images and fenced code excluded).
- Weekly workflow wires the three new steps after the table
  count upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-21) — Plan 2.8 unique statuses + size sum + table count

- New `scripts/plan_2_8_ledger_unique_statuses.py` lists the
  distinct valid statuses seen in the ledger with per-status
  counts (``--fail-below-count`` for CI).
- New `scripts/plan_2_8_digest_size_sum.py` reports the total
  byte size of artifact-dir files (``--fail-above-bytes``).
- New `scripts/plan_2_8_weekly_summary_table_count.py` counts
  Markdown pipe-tables in the weekly summary (fenced code
  excluded).
- Weekly workflow wires the three new steps after the
  inline-code upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-21) — Plan 2.8 median gap + empty ratio + inline-code count

- New `scripts/plan_2_8_ledger_median_gap.py` reports the
  median gap in hours between consecutive ledger captures
  (``--fail-above-hours`` for CI).
- New `scripts/plan_2_8_digest_empty_ratio.py` reports the
  share of zero-byte files in the artifact directory
  (``--fail-above-ratio`` for CI).
- New `scripts/plan_2_8_weekly_summary_inline_code_count.py`
  counts single-backtick inline-code spans in the weekly
  summary (fenced code excluded).
- Weekly workflow wires the three new steps after the
  horizontal-rule upload.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six
  new script+test pairs.

### Added (2026-04-21) — Plan 2.8 unknown ratio + empty files + hr count

- New `scripts/plan_2_8_ledger_unknown_ratio.py` mirrors the
  red/amber/green ratio helpers for ``unknown`` records;
  ``--fail-above-ratio`` for CI.
- New `scripts/plan_2_8_digest_empty_files.py` lists
  zero-byte files (sorted by name) with ``--fail-on-empty``
  for CI.
- New `scripts/plan_2_8_weekly_summary_hr_count.py` counts
  Markdown horizontal-rule lines (``---``/``___``/``***``
  with three or more identical characters) outside fenced
  code blocks.
- Weekly workflow wires the three new steps after blockquote
  count.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-04-21) — Plan 2.8 red ratio + file age stats + blockquote count

- New `scripts/plan_2_8_ledger_red_ratio.py` mirrors the
  amber-ratio helper for red records; includes
  ``--fail-above-ratio`` for CI.
- New `scripts/plan_2_8_digest_file_age_stats.py` reports
  min/mean/max file age (seconds since mtime) for the
  artifact dir; negative ages are clamped to zero; subdirs
  ignored; ``now_ts`` injection keeps tests deterministic.
- New `scripts/plan_2_8_weekly_summary_blockquote_count.py`
  counts blockquote lines and distinct blockquote blocks
  outside fenced code blocks.
- Weekly workflow wires the three new steps after heading
  hierarchy.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-04-21) — Plan 2.8 amber ratio + name length stats + heading hierarchy

- New `scripts/plan_2_8_ledger_amber_ratio.py` mirrors the
  green-ratio helper for amber records; includes
  ``--fail-above-ratio`` for CI alerts.
- New `scripts/plan_2_8_digest_name_length_stats.py` reports
  min/mean/max filename lengths; subdirs ignored; empty dirs
  return zeros.
- New `scripts/plan_2_8_weekly_summary_heading_hierarchy.py`
  counts ATX headings per level (H1-H6) outside fenced code
  blocks and reports the deepest level seen.
- Weekly workflow wires the three new steps after paragraph
  stats.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-04-21) — Plan 2.8 distinct days + extension coverage + paragraph stats

- New `scripts/plan_2_8_ledger_distinct_days.py` counts
  distinct UTC days present in the ledger; malformed
  timestamps and invalid statuses are skipped; days list is
  sorted.
- New `scripts/plan_2_8_digest_extension_coverage.py` reports
  how many artifact files carry a suffix and the coverage
  ratio; subdirectories ignored.
- New `scripts/plan_2_8_weekly_summary_paragraph_stats.py`
  counts paragraph runs (contiguous non-blank lines separated
  by blank lines) and reports the mean lines/paragraph;
  fenced-code markers are excluded to avoid inflating
  paragraph counts.
- Weekly workflow wires the three new steps after image
  count.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-04-21) — Plan 2.8 status streaks + oldest/newest + image count

- New `scripts/plan_2_8_ledger_status_streaks.py` reports the
  current tail-end status streak (status, length, start_at,
  end_at); ``{"found": false}`` when no valid records.
- New `scripts/plan_2_8_digest_oldest_newest.py` reports the
  oldest and newest files in the artifact dir by mtime; ties
  broken on name ascending; subdirs ignored.
- New `scripts/plan_2_8_weekly_summary_image_count.py` counts
  ``![alt](src)`` image tags outside fenced code blocks and
  reports both total and distinct src counts.
- Weekly workflow wires the three new steps after emphasis
  count.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-04-21) — Plan 2.8 recent green ratio + median size + emphasis count

- New `scripts/plan_2_8_ledger_recent_green_ratio.py` reports
  the green-share ratio over the trailing N ledger records
  (``None`` when the window is empty); ``--fail-below-ratio``
  for CI.
- New `scripts/plan_2_8_digest_median_size.py` reports the
  median file size across the artifact dir; subdirs ignored.
- New `scripts/plan_2_8_weekly_summary_emphasis_count.py`
  counts bold (``**...**``) and italic (``*...*`` or
  ``_..._``) spans outside fenced code blocks; bold markers
  stripped before italic scan to avoid double-counting.
- Weekly workflow wires the three new steps after tables
  count.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-04-21) — Plan 2.8 last-N summary + mean size + tables count

- New `scripts/plan_2_8_ledger_last_n_summary.py` reports
  status counts within the trailing N ledger records;
  `--last-n 0` means all records.
- New `scripts/plan_2_8_digest_mean_size.py` reports the
  arithmetic mean (rounded 2dp) of artifact-dir file sizes
  alongside file_count and total_bytes; subdirectories
  ignored.
- New `scripts/plan_2_8_weekly_summary_tables_count.py`
  counts pipe-table blocks in the weekly summary (contiguous
  runs of two or more `|`-prefixed lines); content inside
  fenced code blocks excluded; single `|` lines are not
  counted as tables.
- Weekly workflow wires last-N, mean-size, and tables-count
  steps after list-stats.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-04-21) — Plan 2.8 longest run + size histogram + list stats

- New `scripts/plan_2_8_ledger_longest_run.py` reports the
  longest consecutive run of each status in the ledger with
  start/end timestamps; statuses that never appear return
  length 0.
- New `scripts/plan_2_8_digest_size_histogram.py` buckets
  artifact files into five fixed size ranges (<1KB, 1-10KB,
  10-100KB, 100KB-1MB, >=1MB); boundary at 1024 bytes moves
  to the 1-10KB bucket.
- New `scripts/plan_2_8_weekly_summary_list_stats.py` counts
  bullet (`-`/`*`) vs numbered (`N.`) list items in the
  summary, skipping content inside fenced code blocks.
- Weekly workflow wires longest-run, size-histogram, and
  list-stats steps after link-check.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-04-21) — Plan 2.8 run length + smallest files + link check

- New `scripts/plan_2_8_ledger_status_run_length.py`
  run-length-encodes the ledger status series into segments
  of `{status, length, start_at, end_at}`.
- New `scripts/plan_2_8_digest_smallest_files.py` mirrors
  largest_files but lists the bottom-N by size; subdirectories
  ignored.
- New `scripts/plan_2_8_weekly_summary_link_check.py` parses
  `[text](target)` links and flags fragment-only links without
  a matching heading anchor (GitHub-style slug); duplicate
  missing fragments deduplicated;
  `--fail-on-missing-fragments` gates CI.
- Weekly workflow wires run-length, smallest-files, and
  link-check steps after code-blocks.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-04-21) — Plan 2.8 first flip + largest files + code blocks

- New `scripts/plan_2_8_ledger_first_flip.py` mirrors
  latest_flip but reports the earliest status transition in
  the ledger; returns `{"found": false}` when none exists.
- New `scripts/plan_2_8_digest_largest_files.py` lists the
  top-N largest files in the artifact directory (descending;
  ties broken by name); `--top-n 0` returns all;
  subdirectories ignored.
- New `scripts/plan_2_8_weekly_summary_code_blocks.py` counts
  fenced code blocks in the weekly summary; reports
  `unbalanced: true` when the final fence is unterminated;
  `--fail-on-unbalanced` gates CI.
- Weekly workflow wires first-flip, largest-files, and
  code-blocks steps after word-count.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-04-21) — Plan 2.8 latest flip + filetype breakdown + word count

- New `scripts/plan_2_8_ledger_latest_flip.py` reports the
  most-recent status transition (from/to + captured_at) in the
  ledger; returns `{"found": false}` when no flip exists.
- New `scripts/plan_2_8_digest_filetype_breakdown.py` groups
  artifact files by lowercase extension (`""` bucket for files
  without an extension) and reports count + total bytes per
  group; subdirectories ignored.
- New `scripts/plan_2_8_weekly_summary_word_count.py` counts
  words, chars, non-whitespace chars, and lines in the weekly
  summary file; `--fail-below-words N` gates CI.
- Weekly workflow wires latest-flip, filetype-breakdown, and
  word-count steps after summary-preview.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-04-21) — Plan 2.8 transition matrix + hash inventory + summary preview

- New `scripts/plan_2_8_ledger_transition_matrix.py` builds a
  4x4 NxN status-transition matrix (green/amber/red/unknown)
  from consecutive ledger records; only counts distinct
  from->to pairs and reports `total_transitions`.
- New `scripts/plan_2_8_digest_hash_inventory.py` computes a
  SHA256 for every regular file in the artifact directory
  (subdirectories ignored) for drift detection; deterministic
  across calls.
- New `scripts/plan_2_8_weekly_summary_preview.py` emits the
  first N lines of `weekly_summary.md` as a fenced block with
  `_empty_` placeholder when the summary is empty; negative
  `--max-lines` is clamped to zero.
- Weekly workflow wires transition-matrix, hash-inventory, and
  summary-preview steps after gap-detector.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-04-21) — Plan 2.8 weekday histogram + summary index + gap detector

- New `scripts/plan_2_8_ledger_weekday_histogram.py` buckets
  records per UTC weekday (Mon=0..Sun=6) with name-friendly md
  rendering; reports empty_weekdays list; `--fail-on-empty-weekdays N`
  gates CI.
- New `scripts/plan_2_8_digest_summary_index.py` walks an
  artifact directory and builds a `.md` manifest with per-file
  size and first `# ` heading (falls back to filename); non-md
  files and subdirectories are ignored.
- New `scripts/plan_2_8_ledger_gap_detector.py` reports gaps
  between consecutive `captured_at` timestamps exceeding
  `--threshold-hours` (default 24); `--fail-on-gaps` gates CI;
  boundary (exactly threshold) is not flagged.
- Weekly workflow wires weekday-histogram, summary-index, and
  gap-detector steps after required-sections.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-04-21) — Plan 2.8 hour histogram + stale report + required sections

- New `scripts/plan_2_8_ledger_hour_histogram.py` buckets
  records by UTC hour-of-day (0..23); reports empty_hours list;
  `--fail-on-empty-hours N` gates CI.
- New `scripts/plan_2_8_digest_stale_report.py` classifies
  artifacts as fresh / warn / stale with configurable
  `--warn-days` and `--stale-days` thresholds; subdirectories
  are ignored; `--fail-on-stale` gates CI.
- New `scripts/plan_2_8_weekly_summary_required_sections.py`
  asserts `DEFAULT_REQUIRED` level-2 headings are present in
  `weekly_summary.md`; `--fail-on-missing` gates CI.
- Weekly workflow wires hour-histogram, stale-report
  (warn=7/stale=14), and required-sections steps after TOC
  checksum; each uploads its output as a retained artifact.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-04-21) — Plan 2.8 status share + missing + TOC checksum

- New `scripts/plan_2_8_ledger_status_share.py` computes
  share-of-time per valid status across the full ledger;
  percentages rounded to 2dp; `--fail-below-green` gates CI.
- New `scripts/plan_2_8_digest_missing_artifacts.py` compares
  filenames in the digest dir against a pinned `REQUIRED` tuple
  (31 entries) and reports missing + extra files;
  subdirectories are not counted; `--fail-on-missing` gates CI.
- New `scripts/plan_2_8_weekly_summary_toc_checksum.py`
  extracts the `## Contents` block from `weekly_summary.md`,
  normalises line endings, strips leading/trailing blanks, and
  emits a stable SHA256 so silent TOC drift is detectable.
- Weekly workflow wires status-share, missing-artifacts, and
  TOC-checksum steps after heading-order.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-04-21) — Plan 2.8 best day + size trend + heading order

- New `scripts/plan_2_8_ledger_best_day.py` mirrors worst-day
  and flags the UTC date with the most green records; ties
  break by earliest date.
- New `scripts/plan_2_8_digest_size_trend.py` compares total
  bytes in two artifact directories (prior vs current) and
  reports delta_bytes and delta_pct (`None` when prior=0);
  `--fail-on-drop-pct` gates CI on sudden shrinkage;
  subdirectories are not counted.
- New `scripts/plan_2_8_weekly_summary_heading_order.py`
  validates that `##` headings in `weekly_summary.md` appear in
  `DEFAULT_ORDER` and reports missing, extra, and misorder;
  `--fail-on-misorder` gates CI.
- Weekly workflow wires best-day, size-trend (reuses the
  prior-catalog download dir), and heading-order steps after
  section-stats.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-04-21) — Plan 2.8 worst day + catalog diff + section stats

- New `scripts/plan_2_8_ledger_worst_day.py` groups ledger
  records by UTC date and flags the date with the most
  non-green (amber+red) records; ties break by earliest date.
- New `scripts/plan_2_8_digest_catalog_diff.py` compares two
  artifact-catalog JSON outputs and reports added_known,
  added_unknown, dropped, known→unknown, and unknown→known;
  `--fail-on-unknown-growth` gates CI.
- New `scripts/plan_2_8_weekly_summary_section_stats.py`
  reports per-`##`-section line and word counts of
  `weekly_summary.md` with an empty-section list; H1 headings
  and pre-first-section content are ignored.
- Weekly workflow wires worst-day, catalog-diff (with prior
  catalog downloaded via download-artifact; falls back to the
  current catalog when no prior exists), and section-stats
  steps; each uploads its output as a retained artifact.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-04-21) — Plan 2.8 streak now + artifact age + month summary

- New `scripts/plan_2_8_ledger_streak_now.py` computes the
  trailing (current) streak of the latest status and its
  `started_at` timestamp; emits markdown or JSON.
- New `scripts/plan_2_8_digest_artifact_age.py` scans the
  digest artifact directory and reports per-file size, mtime,
  and age-in-days relative to now; subdirectories are ignored;
  `--fail-on-older-than DAYS` gates CI on staleness.
- New `scripts/plan_2_8_ledger_month_summary.py` groups ledger
  records by calendar month (`YYYY-MM`) and reports per-status
  counts plus a total; invalid statuses/timestamps are tallied
  under `skipped`.
- Weekly workflow wires streak-now, artifact-age, and
  month-summary steps after the TOC step; each uploads its
  output as a retained artifact.
- `scripts/plan_2_8_status.py` Phase 1 anchors pin the six new
  script+test pairs.

### Added (2026-04-21) — Plan 2.8 status today + recent changes + TOC-only

- New `scripts/plan_2_8_ledger_status_today.py` returns the
  ledger record captured on a target UTC date (defaults to
  today); when multiple records match the day, the latest is
  returned. Invalid ISO dates and missing ledgers fail cleanly.
- New `scripts/plan_2_8_digest_recent_changes.py` walks the
  ledger and returns only *transitions* (status-change records);
  synthesises no initial entry. `--limit N` keeps the tail.
- New `scripts/plan_2_8_weekly_summary_toc_only.py` extracts
  just the `## Contents` block from `weekly_summary.md` and
  emits it as a standalone artifact; weekly wires this into
  `$GITHUB_STEP_SUMMARY` so the run page shows the TOC inline.
- Weekly digest wires all three steps; each uploads a 365-day
  retention artifact.

### Added (2026-04-21) — Plan 2.8 flap rate + trend threshold + artifact catalog

- New `scripts/plan_2_8_ledger_flap_rate.py` counts status
  transitions grouped by ISO week of the later record and
  reports total flips, weeks covered, and the average
  flips-per-week. `--fail-on-flips` turns any observed flip
  into rc=1.
- New `scripts/plan_2_8_trend_threshold_alert.py` reads
  `trend.json` and raises rc=1 (when `--fail-below` is set) if
  the most recent week's green % is strictly below the
  threshold; empty weeks list also fails.
- New `scripts/plan_2_8_digest_artifact_catalog.py` walks the
  digest artifact directory and emits a catalog classifying
  each file as `known` (with a short description) or `unknown`
  so stray outputs surface immediately. Subdirectories are
  ignored.
- Weekly digest wires flap rate, trend-threshold alert, and
  artifact catalog; also emits `trend.json` alongside `trend.md`
  so the threshold alert has a JSON input.

### Added (2026-04-21) — Plan 2.8 metadata diff + weekly trend + link check

- New `scripts/plan_2_8_metadata_diff.py` compares current
  `metadata.json` against a prior copy (downloaded via
  `dawidd6/action-download-artifact@v6`) and reports python
  version change, script-count delta, and per-script size
  deltas (added / removed / changed). Malformed or missing
  prior is treated as an empty baseline.
- New `scripts/plan_2_8_ledger_trend.py` buckets ledger records
  by ISO week and reports per-week totals, green counts, and
  green % (2dp) as JSON or a small markdown table.
- New `scripts/plan_2_8_weekly_summary_linkcheck.py` scans
  `weekly_summary.md` for internal anchor links and flags any
  that point at missing headings; `--fail-on-broken` turns
  broken links into rc=1.
- Weekly digest wires prior-metadata download, metadata diff,
  trend, and link check; artifacts uploaded with 365-day
  retention.

### Added (2026-04-21) — Plan 2.8 latest status + longest streak + digest metadata

- New `scripts/plan_2_8_ledger_latest_status.py` emits a tiny
  artifact with the most recent valid-status record (status +
  captured_at + run_url); empty or all-invalid ledgers yield
  `status = "unknown"`.
- New `scripts/plan_2_8_ledger_longest_streak.py` reports the
  longest consecutive run of each status (green / amber / red /
  unknown) with start/end captured_at and length. Records with
  invalid statuses are dropped before streak computation.
- New `scripts/plan_2_8_digest_metadata.py` captures
  generator-side metadata (python version, platform, UTC
  captured_at, size+mtime of each `plan_2_8_*.py`) so weekly
  outputs are self-describing.
- Weekly digest uploads the new `latest_status.json` and
  `metadata.json` artifacts.

### Added (2026-04-21) — Plan 2.8 ledger uptime % + file manifest + weekly summary index

- New `scripts/plan_2_8_ledger_uptime_pct.py` computes green
  uptime as a percentage over the last N weeks, using the most
  recent record before the cutoff as a window anchor so partial
  spans aren't dropped.
- New `scripts/plan_2_8_digest_file_manifest.py` walks
  `scripts/plan_2_8_*.py` and `tests/test_plan_2_8_*.py` and
  reports orphan scripts and orphan tests (self and
  `plan_2_8_status.py` are excluded from the scan).
- New `scripts/plan_2_8_weekly_summary_index.py` aggregates the
  weekly markdown reports (summary, flip-alert, downtime,
  size-budget, archive-index, index-diff) into a single
  `weekly_summary.md` with a table of contents; missing inputs
  become `_(missing)_` placeholders so the output always has the
  full section skeleton.
- Weekly digest uploads the new `uptime.md` and
  `weekly_summary.md` artifacts.

### Added (2026-04-21) — Plan 2.8 ledger downtime + weekly rollup + index diff

- New `scripts/plan_2_8_ledger_downtime.py` sums non-green
  durations (amber / red / unknown) between consecutive ledger
  entries. Trailing intervals are not counted.
- New `scripts/plan_2_8_ledger_weekly_rollup.py` produces a
  compact per-week rollup (status counts, flips, latest status).
- New `scripts/plan_2_8_digest_index_compare.py` diffs the
  current weekly `index.json` against the prior run's copy
  (downloaded via `dawidd6/action-download-artifact@v6`) and
  reports added / removed / size-changed files.
- Weekly digest wires downtime, prior-index download, and the
  index diff; three new uploads: `plan-2-8-ledger-downtime`,
  `plan-2-8-weekly-index-diff`.
- +42 tests plus two weekly-workflow pin-tests.

### Added (2026-04-21) — Plan 2.8 checksum verifier + status matrix + size budget

- New `scripts/plan_2_8_checksum_verify.py` verifies a
  `checksums.json` manifest against a directory, reporting
  missing/mismatched/extra files with opt-in failure on each.
- New `scripts/plan_2_8_ledger_status_matrix.py` builds a
  `from→to` status transition matrix over the ledger (invalid /
  non-string statuses break the chain so they never fabricate
  transitions).
- New `scripts/plan_2_8_digest_size_budget.py` enforces a per-file
  byte budget (default 1 MiB) on the weekly artifact directory;
  supports `--fail-on-breach` for CI.
- Weekly digest now emits and uploads the size-budget report.
- +41 tests covering verification/matrix/budget; one
  weekly-workflow pin-test.

### Added (2026-04-21) — Plan 2.8 ledger stats + artifact checksums + archive index

- New `scripts/plan_2_8_ledger_stats_json.py` buckets the status
  ledger per ISO year-week (default) or per calendar month and
  reports status counts per bucket, plus a skipped tally for
  malformed records.
- New `scripts/plan_2_8_artifact_checksum.py` computes SHA-256
  for every file in the weekly artifact directory and emits both
  `checksums.json` and `checksums.md`, with `--skip` support so
  the checksum files themselves are excluded from the next run.
- New `scripts/plan_2_8_digest_archive_index.py` indexes the
  digest-archive directory, reporting file count + total size
  per snapshot sub-directory.
- Weekly digest now publishes `plan-2-8-artifact-checksums` and
  `plan-2-8-digest-archive-index` (the latter is fail-soft when
  the archive dir is absent).
- +36 tests covering per-week/per-month bucketing, checksum
  computation, archive scanning; two weekly-workflow pin-tests.

### Added (2026-04-21) — Plan 2.8 status flip alert + ledger CSV export + ledger validator

- New `scripts/plan_2_8_status_flip_alert.py` detects status
  transitions in the last N weeks of the ledger (default 12) and
  emits a markdown alert (or JSON), with optional
  `--fail-on-flip`.
- New `scripts/plan_2_8_ledger_csv_export.py` converts the
  JSONL ledger to CSV (mirrors the `plan_2_8_history_export.py`
  shape), default fields `captured_at,status,run_url`.
- New `scripts/plan_2_8_ledger_validate.py` validates every
  ledger record (`captured_at` ISO-parseable, `status` in the
  allowed set), reports invalid lines with reason, supports
  `--fail-on-invalid`.
- Weekly digest now emits the flip alert and CSV alongside the
  ledger summary; two new uploads: `plan-2-8-status-flip-alert`,
  `plan-2-8-ledger-csv`.
- +42 tests covering flip detection, CSV rendering, and
  validator checks; two weekly-workflow pin-tests.

### Added (2026-04-21) — Plan 2.8 ledger prune + run stamp + weekly artifact index

- New `scripts/plan_2_8_status_ledger_prune.py` trims the status
  ledger to the last N records (default 104, ~2 years of weekly
  runs) via an atomic `tempfile` + `os.replace` rewrite. Blank and
  malformed lines are dropped.
- New `scripts/plan_2_8_run_stamp.py` writes a self-describing
  JSON stamp (`run_id`, `run_url`, `sha`, `ref`, `actor`,
  `captured_at`) with `GITHUB_*` env fallback.
- New `scripts/plan_2_8_weekly_index.py` scans the weekly artifact
  directory and emits `index.md` + `index.json` listing every
  produced artifact with its size.
- Weekly digest now prunes the ledger, emits the run stamp, and
  publishes the artifact index (also appended to the job summary).
  Three new uploads: `plan-2-8-run-stamp`, `plan-2-8-weekly-index`.
- +27 tests covering prune/index/stamp helpers plus three
  weekly-workflow pin-tests.

### Added (2026-04-21) — Plan 2.8 status ledger append + summariser

- New `scripts/plan_2_8_status_ledger.py` appends a single
  JSONL observation (`captured_at`, `status`, optional
  `run_url`) each week, carrying over the prior weekly
  artifact by downloading `plan-2-8-status-ledger` via
  `dawidd6/action-download-artifact@v6` with
  `name_is_regexp: true`. Handles both status-snapshot and
  bare health-rollup payloads. +14 tests with weekly-workflow
  pin-tests for download + append + upload steps.
- New `scripts/plan_2_8_status_ledger_summarize.py` summarises
  the ledger into `{counts, total, pct_green, current_status,
  current_streak, last_flip}`, tolerating blank and malformed
  lines. Supports md/json output. +14 tests including a
  weekly-workflow pin-test.
- Weekly digest chains download→append→upload→summary, attaches
  the summary to the job summary, and uploads both the ledger
  and its summary (365d).
- Status anchors, runbook, and CHANGELOG refreshed.

### Added (2026-04-21) — Plan 2.8 alert trend gate + digest-vs-coverage projection + runbook section check

- New `scripts/plan_2_8_alert_trend_gate.py` turns the trend JSON
  into a soft gate with configurable thresholds
  (`--max-rising`, `--max-new`, `--max-falling`). Produces an md
  summary plus JSON, supports `--fail-on-breach`, and defends
  against bool-masquerading-as-int counts. +16 tests with a
  weekly-workflow pin-test (thresholds: rising≤5, new≤10).
- New `scripts/plan_2_8_digest_to_coverage.py` projects the
  weekly digest's alerts onto the coverage slice by
  `(tf, family)` and reports alerts-without-coverage,
  coverage-without-alerts, and their intersection. Accepts
  coverage either as an `{entries:[...]}` object or a bare list.
  `--fail-on-gap` for CI gating. +15 tests, one weekly-workflow
  pin-test.
- New `scripts/plan_2_8_runbook_sections.py` verifies the
  rollout runbook contains all canonical level-2 headings
  (default set pinned to existing "Phase timeline (addendum §6)",
  "Daily automation", "Status quick-check"). Skips fenced
  blocks. `--fail-on-missing` for CI gating. +16 tests
  including a real-runbook sweep and weekly pin-test.
- Weekly digest now runs all three steps after the alert trend
  step, appends each to the job summary, and uploads
  `plan-2-8-alert-trend-gate`, `plan-2-8-digest-vs-coverage`,
  and `plan-2-8-runbook-sections` (365d).
- Status anchors, runbook, and CHANGELOG refreshed.

### Added (2026-04-21) — Plan 2.8 README badge markdown + alert trend aggregator

- New `scripts/plan_2_8_badge_markdown.py` emits a README-ready
  single-line markdown image linking to the Plan 2.8 shields.io
  endpoint badge, optionally wrapped in a click-through link.
  URL-encodes the endpoint URL and guards the label against
  stray `]`. +11 tests including a weekly-workflow pin-test.
- New `scripts/plan_2_8_alert_trend.py` ingests the latest two
  files from the Plan 2.8 digest archive and emits a per-
  `(tf, family)` trend record: latest/prev events and
  hit-rate, deltas, and a direction tag (`rising`, `falling`,
  `flat`, `new`, `gone`). Tolerant of malformed or missing
  archives. +17 tests including a weekly-workflow pin-test.
- Weekly digest now uploads `plan-2-8-badge-markdown` and
  `plan-2-8-alert-trend` (both retained 365 days) and appends the
  trend report to the job summary.
- Status anchors, runbook, and CHANGELOG refreshed.

### Added (2026-04-21) — Plan 2.8 digest schema validator + shields.io status badge

- New `scripts/plan_2_8_digest_schema.py` validates the weekly
  digest JSON against a lightweight, dependency-free schema
  (required top-level keys + per-alert field types; unknown keys
  tolerated). Supports md/json output and `--fail-on-invalid`.
  +18 tests including a bool-as-int rejection guard and a
  weekly-workflow pin-test.
- New `scripts/plan_2_8_runcard_badge.py` emits a shields.io
  endpoint-badge JSON (`schemaVersion: 1`) from either the
  status snapshot or a bare rollout-health JSON. Maps
  green/amber/red to brightgreen/yellow/red; any other value to
  lightgrey. +14 tests with a weekly-workflow pin-test.
- Weekly digest now runs both checks after the manifest diff,
  appends the schema report to the job summary, and uploads
  `plan-2-8-digest-schema-report` + `plan-2-8-status-badge`
  (both retained 365 days).
- Status anchors, runbook, and CHANGELOG refreshed.

### Added (2026-04-21) — Plan 2.8 weekly snooze-expiry + script manifest + manifest diff wiring

- Weekly digest now surfaces a snooze-expiry report
  (`plan_2_8_snooze_expiry_report.py`) as both a job-summary
  section and `plan-2-8-snooze-expiry` artifact.
- Weekly digest runs `plan_2_8_manifest.py` (static scan of
  `scripts/plan_2_8_*.py` ↔ `tests/test_plan_2_8_*.py`) and
  uploads `plan-2-8-manifest`.
- New `scripts/plan_2_8_manifest_diff.py` diffs the prior weekly
  manifest against the current one, reporting
  `added_scripts`, `removed_scripts`, `newly_testless`,
  `newly_tested`, and per-script CLI flag deltas (as md/json).
  Wired into weekly digest, downloading the prior manifest via
  `dawidd6/action-download-artifact@v6` with
  `name_is_regexp: true`. Uploads `plan-2-8-manifest-diff`.
  Supports `--fail-on-regression` for CI gates. +17 tests,
  including two weekly-workflow pin-tests.
- Status anchors, runbook, and CHANGELOG refreshed.

### Added (2026-04-21) — Plan 2.8 weekly history CSV + runbook link-check wiring + snooze expiry + manifest

- Weekly digest workflow now (a) exports the last-365-day history
  as `plan-2-8-history-csv` via `plan_2_8_history_export.py`, and
  (b) runs `plan_2_8_runbook_link_check.py` against the rollout
  runbook, appending its markdown report to the job summary.
  Both steps are fail-soft and skip gracefully when inputs are
  missing.
- New `scripts/plan_2_8_snooze_expiry_report.py` categorises every
  entry in `configs/plan_2_8_snoozes.json` as expired, expiring,
  active, permanent, or malformed against a configurable horizon
  (`--within-days`). Supports md/json output and a
  `--fail-on-expired` guard for CI. +16 tests including two
  weekly-workflow pin-tests.
- New `scripts/plan_2_8_manifest.py` statically scans
  `scripts/plan_2_8_*.py` and `tests/test_plan_2_8_*.py`, pairing
  each script with its companion test and extracting CLI flags via
  a regex probe (no exec). Includes a `--fail-on-missing-test`
  guard so CI can assert that the Plan 2.8 test surface stays
  complete. +13 tests, one sweeping the real repo.
- Status anchors, runbook, and CHANGELOG refreshed.

### Added (2026-04-21) — Plan 2.8 compact status-runcard step + history CSV export + runbook link check

- Weekly digest workflow now runs the compact status runcard
  (`plan_2_8_runcard_from_status.py`) after the digest archive
  and uploads it as `plan-2-8-status-runcard` (365d).
- New `scripts/plan_2_8_history_export.py` converts
  `plan_2_8_history.jsonl` to CSV with a stable 7-column schema
  (`captured_at, scoring_root, tf, family, events, hit_rate_pct,
  delta_pp`). Supports `--lookback-days` and `--fields` override.
  Malformed/blank lines tolerated. +10 tests.
- New `scripts/plan_2_8_runbook_link_check.py` verifies intra-doc
  anchor links in `docs/plan_2_8_rollout_runbook.md` using the
  same slug algorithm as the TOC helper. Ignores external and
  cross-file links, skips fenced code. `--fail-on-broken` for CI.
  +13 tests including a real-runbook sweep and weekly workflow
  pin-test.
- Status anchors, runbook, and CHANGELOG refreshed.

### Added (2026-04-21) — Plan 2.8 weekly archive+compare + compact status runcard + history prune

- Weekly digest workflow now downloads the prior
  `plan-2-8-digest-archive` artifact, archives the fresh
  `digest.json` under its `captured_at` date, and when at least
  two dated archives exist compares them via
  `plan_2_8_digest_compare.py`; results are appended to the step
  summary and the rotating archive is re-uploaded (365d).
- New `scripts/plan_2_8_runcard_from_status.py` renders a slim
  one-page status runcard from machine-readable JSON
  (`status_snapshot.json`, `runcard_index.json`, `health.json`).
  Missing inputs render as `n/a` / unknown. +9 tests plus 2
  workflow pin-tests for archive+compare wiring.
- New `scripts/plan_2_8_history_prune.py` prunes
  `plan_2_8_history.jsonl` to the last N days (default 365),
  atomic rewrite, `--dry-run`, `--drop-undated`, `--output`.
  Malformed JSON lines are counted, blank lines ignored. +10
  tests.
- Status anchors, runbook, and CHANGELOG refreshed.

### Added (2026-04-21) — Plan 2.8 weekly snapshot + TOC steps + digest archive helper

- Weekly digest workflow now writes a `runbook_toc.md/json` via
  `plan_2_8_runbook_toc.py`, a one-line `status_snapshot.json`
  plus md via `plan_2_8_status_snapshot.py`, and uploads the
  status snapshot as `plan-2-8-status-snapshot` (365d retention).
- New `scripts/plan_2_8_digest_archive.py`: copies the current
  `digest.json` into a rotating archive keyed by `captured_at`
  (YYYY-MM-DD). Supports a `--fallback-date`, `--keep` count-based
  rotation, and `--emit-latest-two` for chaining into the digest
  comparator. Same-date writes overwrite in place. +12 tests,
  including two weekly workflow pin-tests.
- Status anchors, runbook, and CHANGELOG refreshed.

### Added (2026-04-21) — Plan 2.8 weekly heatmap step + runbook TOC + status snapshot

- Weekly digest workflow now runs the 90-day alert-history heatmap
  (`plan_2_8_alert_history_heatmap.py`) after the CHANGELOG slice
  step, appending its md to the GitHub step summary.
- New `scripts/plan_2_8_runbook_toc.py` emits a table-of-contents
  sidebar for `docs/plan_2_8_rollout_runbook.md`. Ignores fenced
  code blocks; disambiguates duplicate slugs. md/json output,
  tunable level range. +10 tests.
- New `scripts/plan_2_8_status_snapshot.py` collapses
  `health.json`, `runcard_index.json`, `coverage.json`, and
  `digest.json` into a one-line JSON suitable for dashboards. md
  render shows status/score/alerts/coverage/runcard presence.
  Tolerates missing or malformed inputs. +10 tests (including
  weekly heatmap pin-test).
- Status anchors, runbook, and CHANGELOG refreshed.

### Added (2026-04-21) — Plan 2.8 runcard index + CHANGELOG slice step + digest compare + heatmap

- Weekly digest workflow now runs `plan_2_8_runcard_index.py`
  (md+json) after the runcard upload, and emits a 14-day
  `plan_2_8_changelog_digest.py` slice to the step summary.
- New `scripts/plan_2_8_digest_compare.py`: diff two digest.json
  snapshots on `(tf, family)` identity, report added/removed/
  persistent alerts with md/json output and `--fail-on-added`
  gate. +9 tests plus 2 workflow pin-tests.
- New `scripts/plan_2_8_alert_history_heatmap.py`: weekday x
  `tf/family` heatmap of the alert history, with optional
  `--lookback-days`, tolerant of bad timestamps and malformed
  JSONL lines. +11 tests.
- Status anchors, runbook, and CHANGELOG refreshed.

### Added (2026-04-21) — Plan 2.8 health step + CHANGELOG slice + runcard index

- Weekly digest workflow runs the rollout-health aggregator after
  coverage+stability and now also emits `coverage.json` and
  `stability.json` so the aggregator has structured inputs. Health
  md is appended to `GITHUB_STEP_SUMMARY`; no fail-on-red in CI.
- New `scripts/plan_2_8_changelog_digest.py` scrapes dated `Added/
  Changed/Fixed/Removed (YYYY-MM-DD) - title` entries from
  `CHANGELOG.md` and renders md/json for status sidebars. Supports
  `--lookback-days` and `--limit`. +10 tests.
- New `scripts/plan_2_8_runcard_index.py` scans the digest artifact
  dir, reports which runcard sections are present/missing/empty,
  renders md/json, and supports `--min-present` for CI gates. +12
  tests including section-map lockstep with
  `plan_2_8_weekly_runcard.SECTION_MAP`.
- Status anchors, runbook, and CHANGELOG refreshed.

### Added (2026-04-21) — Plan 2.8 weekly runcard step + monthly ADR queue + rollout health

- Weekly digest workflow now emits a consolidated operator runcard
  (digest + coverage + stability + lint + history summary) and
  uploads it as the `plan-2-8-weekly-runcard` artifact (180d).
- Monthly digest workflow appends a deferred-ADR queue section
  sourced from `docs/DECISIONS.md` via the new ADR queue helper.
- New `scripts/plan_2_8_health.py` aggregator collapses the per-axis
  JSON payloads (digest / coverage / stability) into a single
  0..1 score + `green|amber|red` status + findings list. Supports
  md/json output, `--fail-on-red`, and tolerates missing inputs.
  +15 tests including weekly/monthly workflow pin-tests.
- Status anchors, runbook, and CHANGELOG refreshed.

### Added (2026-04-21) — Plan 2.8 history backfill + ADR queue + weekly runcard

- `scripts/plan_2_8_history_backfill.py`: merge two history JSONLs
  de-duped on `(captured_at, scoring_root)`, atomic write via
  tempfile, `--dry-run` for safe preview. Chronological sort
  tolerates unparseable timestamps. +9 tests.
- `scripts/plan_2_8_adr_queue.py`: parse `docs/DECISIONS.md`,
  extract date/slug/status/decision-summary, filter by
  `accepted`/`deferred`/`superseded`, render md/json/text. +12 tests.
- `scripts/plan_2_8_weekly_runcard.py`: fold per-step digest
  artifacts (digest/issue/snooze_lint/diff/movers/coverage/
  stability/alert_history_summary) into a single operator runcard
  md. Missing or empty sections are silently skipped. +10 tests.
- Status anchors, runbook, and CHANGELOG refreshed.

### Added (2026-04-21) — Plan 2.8 snooze-lint + weekly alert-history summary step

- `scripts/plan_2_8_snooze_lint.py`: validate
  `configs/plan_2_8_snoozes.json` — flags missing `tf`, stale
  entries (expired `expires`), unparseable timestamps, duplicate
  `(tf, family)` pairs. Supports `--warn-only` for advisory CI use.
  +13 tests.
- Weekly digest workflow runs `snooze_lint` in warn-only mode
  *before* applying the snooze so operators see issues in the run
  summary without breaking the digest. +1 pin-test.
- Weekly digest workflow now also runs
  `plan_2_8_alert_history_summary.py` on the rolling
  `alert_history.jsonl` (90-day window) after the upload step and
  streams the ranked table into the run summary. +1 pin-test.
- Status anchors, runbook, and CHANGELOG refreshed.

### Added (2026-04-21) — Plan 2.8 alert-history wiring + monthly rollup + summary CLI

- Weekly digest workflow now appends fired alerts to a long-running
  `alert_history.jsonl` via `scripts/plan_2_8_alert_history.py` and
  publishes it as the `plan-2-8-alert-history` artifact (365-day
  retention). +2 pin-tests.
- Monthly digest workflow now streams the 8-week rolling HR trend
  from `scripts/plan_2_8_digest_rollup.py` into the run summary.
  +1 pin-test.
- `scripts/plan_2_8_alert_history_summary.py`: read the alert log
  and rank TF×family slices by frequency within a lookback window,
  with `last_delta_pp` + `max_abs_delta_pp` context. +9 tests.
- Status anchors, runbook, and CHANGELOG refreshed.

### Added (2026-04-21) — Plan 2.8 weekly stability step + alert history + rolling HR trend

- Weekly digest workflow now streams a fail-soft
  `Plan 2.8 slice stability (last 8 snapshots)` section into the run
  summary right after slice coverage. +1 pin-test.
- `scripts/plan_2_8_alert_history.py`: append fired drift alerts to
  a long-running JSONL log, de-duped on `(captured_at, tf, family)`
  for replay safety. Atomic rewrite-through-tempfile. Accepts both
  list-shaped and digest-shaped payloads. +8 tests.
- `scripts/plan_2_8_digest_rollup.py`: N-week rolling HR trend per
  slice with sparkline rendering. ISO-week bucketing (latest
  snapshot wins within a week). +10 tests.
- Status anchors, runbook, and CHANGELOG refreshed.

### Added (2026-04-21) — Plan 2.8 weekly coverage step + snooze admin + stability metric

- Weekly digest workflow now streams a fail-soft
  `Plan 2.8 slice coverage` section into the run summary,
  consuming `scripts/plan_2_8_coverage.py` against the latest
  rolling-bench history. +1 pin-test.
- `scripts/plan_2_8_snooze_admin.py`: operator CLI for the
  drift-alert snooze config — `add` / `list` / `expire` / `rm`.
  Atomic writes preserve the `_comment` scaffold; `list --active`
  filters on `expires`. +10 tests.
- `scripts/plan_2_8_history_stability.py`: per-slice HR stddev over
  the last N snapshots. Flags slices jittering beyond a configurable
  threshold with a `--fail-on-unstable` gate. +11 tests.
- Status anchors, runbook, and CHANGELOG refreshed.

### Added (2026-04-21) — Plan 2.8 snooze config + monthly digest + coverage helper

- `configs/plan_2_8_snoozes.json`: operator-managed drift-alert
  snooze list (empty by default). Weekly digest workflow now loads
  it, re-renders the digest via `plan_2_8_alert_snooze.py`, and
  resolves final `has_alerts` from the filtered result so suppressed
  slices never open/reopen GitHub issues.
- `.github/workflows/plan-2-8-weekly-digest.yml`: new `snoozed`
  pass-through pipeline — `digest` step emits a JSON digest, new
  `snooze` step applies config if present, new `resolve_alerts` step
  sets the final `has_alerts` output consumed by the open/close
  steps.
- `.github/workflows/plan-2-8-monthly-digest.yml`: schedule
  `0 13 1 * *` + dispatch. Runs the trend digest at 30d lookback and
  top-movers with `--top-n 10`. 365-day artifact retention.
- `scripts/plan_2_8_coverage.py`: report TF×family slices in the
  latest snapshot that are below `min_events`. Optional
  `--fail-on-under` for hard CI gating.
- `scripts/plan_2_8_status.py`: Phase 1 anchors include the snooze
  config, coverage helper, and monthly workflow + tests.
- Docs: runbook notes the weekly snooze behaviour and adds sections
  for monthly digest and slice coverage; pin-test inventory
  refreshed.
- Tests: +10 coverage, +7 monthly workflow, +3 weekly digest wiring
  (20 new).

### Added (2026-04-21) — Plan 2.8 alert snooze + top movers

- `scripts/plan_2_8_alert_snooze.py`: filter a trend-digest JSON
  against a snooze config. Supports tf-only / tf+family matching,
  optional ISO `expires`, invalid-timestamp safety (treated as
  inactive). Does not mutate input; records the suppressed alerts
  under a new `snoozed` key for triage.
- `scripts/plan_2_8_top_movers.py`: rank TF×family slices by
  `|delta_pp|` across a configurable lookback window. Honors
  `min_events` floor; renders both "gainers" and "losers" tables.
- `.github/workflows/plan-2-8-weekly-digest.yml`: new fail-soft
  "Plan 2.8 top movers (30-day window)" step streams the table into
  the run summary below the existing snapshot diff.
- `scripts/plan_2_8_status.py`: Phase 1 anchors include the two
  new helpers + their test files.
- Docs: runbook gains a top-movers / alert-snooze section; pin-test
  inventory refreshed.
- Tests: +10 alert-snooze, +11 top-movers, +1 weekly workflow step
  pin-test (22 new).

### Added (2026-04-21) — Plan 2.8 snapshot diff + drift-alert auto-close

- `scripts/plan_2_8_history_diff.py`: diff any two snapshots in the
  history JSONL (by captured_at or index). Emits per-TF and per-
  TF×family HR-delta tables. Markdown/JSON output. Defaults to the
  last two rows for quick "what changed since yesterday".
- `.github/workflows/plan-2-8-weekly-digest.yml`: new
  "Close drift-alert issues when alerts cleared" step — when the
  digest reports zero comparable slices over threshold, any still-
  open `plan-2.8,drift-alert` issues are auto-commented + closed.
  Additional fail-soft step runs the snapshot-diff helper on the
  last two rows and streams the table into the run summary.
- `scripts/plan_2_8_status.py`: Phase 1 anchors include the diff
  helper + its test file.
- Docs: runbook gains an auto-close paragraph and an ad-hoc
  snapshot-diff section; pin-test inventory refreshed.
- Tests: +9 history-diff, +2 weekly-digest auto-close wiring, +1
  history-diff workflow step (12 new).

### Added (2026-04-21) — Plan 2.8 history validate + drift-alert dedup + run-url

- `scripts/plan_2_8_history_validate.py`: non-destructive integrity
  check (well-formed JSON, parseable `captured_at`, no duplicate
  `(captured_at, scoring_root)` keys, `per_tf` shape). CLI exits
  non-zero on validation hits, can write a JSON report.
- `.github/workflows/smc-measurement-benchmark-rolling.yml`: new
  fail-soft "Plan 2.8 history validate" step after the rotate step.
  Uploads `plan_2_8_history_validate.json` and streams the report
  into the run summary.
- `scripts/plan_2_8_trend_digest.py`: `render_issue_body()` now
  accepts an optional `run_url` and the CLI gains `--run-url` so the
  weekly workflow can stamp the run link into the issue body.
- `.github/workflows/plan-2-8-weekly-digest.yml`: drift-alert step
  re-renders the issue body with the workflow-run URL footer, then
  de-dups via `gh issue list --label plan-2.8 --label drift-alert
  --state open` — comments on an existing open thread instead of
  spawning a new issue every week the alert persists.
- `scripts/plan_2_8_status.py`: Phase 1 anchors extended with the
  validator and its pin-tests.
- Docs: runbook gains a history-validate paragraph and an updated
  drift-alert auto-issue note describing the de-dup behaviour. Pin-
  test inventory refreshed.
- Tests: +11 history-validate, +5 rolling-bench validate wiring,
  +3 issue-body run_url, +2 weekly de-dup wiring (21 new).

### Added (2026-04-21) — Plan 2.8 drift-alert auto-issue + history rotation

- `scripts/plan_2_8_trend_digest.py`: new `render_issue_body()` +
  `has_alerts()` helpers plus `--format issue` / `--alerts-file` CLI
  flags so the weekly workflow can emit a compact GitHub-issue body
  alongside the existing markdown digest.
- `.github/workflows/plan-2-8-weekly-digest.yml`: after rendering
  the digest, also writes `issue_body.md` + `alerts.json`, surfaces
  `has_alerts` as a step output, and opens a `plan-2.8,drift-alert`
  labelled issue via `gh issue create` when the flag is `True`. New
  scoped `permissions: issues: write`.
- `scripts/plan_2_8_history_rotate.py`: size-bound the rolling
  history JSONL by `--max-rows` and/or `--max-age-days`. Atomic
  rewrite, keeps a `.bak`, fail-soft rollback on write errors,
  corrupt-line preservation (opt-in drop).
- `.github/workflows/smc-measurement-benchmark-rolling.yml`: new
  "Plan 2.8 history rotate" fail-soft step after the archive step,
  capped at 366 snapshots / 400 days by default.
- `scripts/plan_2_8_status.py`: Phase 1 anchors extended with the
  rotate helper + its pin-test + the digest-issue renderer + the
  weekly issue-wiring pin-test.
- Docs: runbook gains history-rotation and drift-alert auto-issue
  sections; pin-test inventory refreshed.
- Tests: +8 digest-issue body, +5 weekly issue wiring, +11 history
  rotate, +4 rolling-bench rotate wiring (28 new).

### Added (2026-04-21) — Plan 2.8 trend digest end-to-end

- `scripts/plan_2_8_trend_digest.py`: pure-stdlib weekly digest
  renderer over the JSONL history. Picks `(prev, latest)` endpoints
  using the newest snapshot still satisfying `lookback_days`, then
  reports per-TF and per-TF×family HR drift. A `comparable` flag is
  set only when both endpoints have ≥`min_events` events; alerts
  fire only on comparable slices whose absolute drift ≥
  `alert_threshold_pp`. Three named statuses: `empty`, `warmup`
  (history younger than the window), `ok`.
- `.github/workflows/smc-measurement-benchmark-rolling.yml`: new
  always() "Plan 2.8 history archive (snapshot append)" step
  slotted between the rollup step and the artifact upload. Calls
  `scripts/plan_2_8_history_archive.py` to fold the daily rollup
  into `${out_dir}/plan_2_8_history.jsonl` so the file is uploaded
  as part of the standard rolling-bench bundle. Fail-soft: missing
  rollup or write hiccup must not affect the benchmark outcome.
- `.github/workflows/plan-2-8-weekly-digest.yml`: Mondays at 12:00
  UTC. Downloads the most recent `smc-measurement-benchmark-rolling-*`
  artifact via `dawidd6/action-download-artifact@v6`, locates the
  history JSONL, runs the digest renderer with operator-tunable
  knobs (`lookback_days`, `min_events`, `alert_threshold_pp`),
  streams the markdown into `$GITHUB_STEP_SUMMARY`, and uploads it
  as the `plan-2-8-weekly-digest` artifact (90-day retention).
- `scripts/plan_2_8_status.py`: Phase-1 anchor list expanded with
  the new history-wiring pin-test, the digest script, and the
  weekly-digest workflow file.
- `docs/plan_2_8_rollout_runbook.md`: "Trend history" section
  updated to reflect that the daily rolling-bench now writes the
  history file automatically; new "Weekly trend digest" section
  documents the workflow + knobs + ad-hoc local invocation.
- Pin-tests:
  - `tests/test_plan_2_8_trend_digest.py` (12 tests — empty/warmup
    statuses, oldest-snapshot-satisfying-lookback selection,
    per-TF + per-family drift math, alert emission above threshold,
    no alert below threshold, `comparable=False` when min-events
    unmet (silences alerts), markdown for warmup skips tables, ok
    markdown has all sections, **end-to-end archive→digest** chain
    pinning the schema contract, CLI write, CLI error path).
  - `tests/test_plan_2_8_rolling_workflow_history_wiring.py` (5
    tests — step present + always(), order
    `rollup < archive < upload`, archiver invoked with rollup +
    history paths, history written inside `out_dir` for upload,
    fail-soft with `set +e` and existence guard).
  - `tests/test_plan_2_8_weekly_digest_workflow.py` (6 tests — file
    exists, Monday 12:00 UTC schedule + dispatch, default knob
    values match the digest defaults, digest step wires all flags
    and streams summary, artifact uploaded with `if: always()` and
    ≥90-day retention, download step targets the
    smc-measurement-benchmark-rolling workflow with
    `name_is_regexp: true`).

### Added (2026-04-21) — Plan 2.8 daily heartbeat + history + ADR-body renderer

- `.github/workflows/plan-2-8-status-daily.yml`: daily 06:15 UTC
  heartbeat that runs `scripts/plan_2_8_status.py`. Streams the
  markdown report into `$GITHUB_STEP_SUMMARY`, uploads it as the
  `plan-2-8-status-report` artifact (30-day retention), and fails
  the workflow only when a *required* anchor goes missing.
- `scripts/plan_2_8_history_archive.py`: idempotent JSONL archiver
  that projects each daily `plan_2_8_tf_family_rollup.json` into a
  compact per-TF×family snapshot (`captured_at`, `scoring_root`,
  `files_scanned`, `per_tf`) and appends it to a long-running
  history file. Dedup key = `(captured_at, scoring_root)`. Tolerates
  pre-existing corrupt lines without overwriting them.
- `scripts/plan_2_8_q4_gate_evaluator.py`: new
  `render_adr_body(verdict)` plus `--format adr` CLI choice. Emits a
  four-section ADR skeleton (`## Decision`, `## Alternatives
  considered`, `## Consequences`, `## Evidence`) with the actual gate
  numbers in-line, ready to pipe straight into
  `scripts/append_adr.py --alternatives-file …` for the W13
  decision record. Pass/fail branches each enumerate the
  corresponding rejected alternatives.
- `docs/plan_2_8_rollout_runbook.md`: new "Trend history" section
  with the archiver CLI snippet, expanded "Status quick-check"
  pointing at the new daily workflow, and the W13 ADR step rewritten
  to use `--format adr | append_adr.py --alternatives-file`.
- Pin-tests:
  - `tests/test_plan_2_8_status_daily_workflow.py` (5 tests — file
    exists, `schedule` + `workflow_dispatch` triggers, `15 6 * * *`
    cron, status step wires script + summary streaming, artifact
    uploaded with `if: always()`).
  - `tests/test_plan_2_8_history_archive.py` (7 tests — append
    writes JSONL with projection, idempotence on key, dedup key
    includes `scoring_root`, tolerates corrupt existing lines,
    creates parent directories, CLI write+dedup, CLI error path).
  - `tests/test_plan_2_8_q4_gate_evaluator_adr_body.py` (6 tests —
    all four ADR sections present, pass-path promotes 2H, fail-path
    rejects with failed gate name listed, evidence cites all three
    gates, Brier numbers formatted with sign, CLI `--format adr`
    emits the decision block).

### Added (2026-04-21) — Plan 2.8 Phase 2 bundle builder + status helper

- `scripts/plan_2_8_q4_gate_bundle_builder.py`: pure-stdlib builder
  that projects two `plan_2_8_tf_family_rollup.json` manifests (one
  per A/B arm) plus operator-supplied Brier scores into the bundle
  schema consumed by `plan_2_8_q4_gate_evaluator.py`. Bucket keys =
  `"<tf>/<family>"` from the intersection of TF×family slices in
  both rollups; deterministic ordering. Optional `--bucket
  tf/family` flag (repeatable) restricts the set. `n_events`
  reported per bucket is the candidate-arm count, matching addendum
  §3.2 G3 which gates on treatment-arm exposure. Refuses to
  fabricate Brier values.
- `scripts/plan_2_8_status.py`: read-only walker that scans the
  Phase 0–3 expected anchors (scripts, workflows, docs, pin-tests)
  and emits a markdown / JSON status report. Required-anchor
  failures exit `1`; optional-anchor absence is reported as
  `optional-missing` and does not fail.
- `docs/plan_2_8_rollout_runbook.md`: phase-2 row bumped from
  `in-flight` to `scaffolded` with link to the new builder; new
  "Phase 2 bundle assembly" section with concrete CLI snippet; new
  "Status quick-check" section.
- Pin-tests:
  - `tests/test_plan_2_8_q4_gate_bundle_builder.py` (9 tests —
    bucket intersection + sort order, Brier + sources passthrough,
    `--bucket` filter preserves order, malformed/missing bucket
    rejection, **end-to-end builder→evaluator pass-path**, **end-to-end
    builder→evaluator G3-fail-path** pinning the schema contract
    between the two scripts, CLI write, CLI error path).
  - `tests/test_plan_2_8_status.py` (8 tests — phases 0–3 covered,
    real-repo passes, empty-repo flags every required anchor as
    missing, optional anchors flagged softly, markdown structure,
    CLI happy path / failure path / `--output` writes).

### Added (2026-04-21) — Plan 2.8 Phase-2/3 operator surface

- `.github/workflows/plan-2-8-q4-gate-dryrun.yml`: new manual-only
  (`workflow_dispatch`) W13 dry-run workflow. Inputs: `bundle_path`
  plus all four threshold knobs (`uplift_min_pp`,
  `uplift_min_buckets`, `brier_max_regression`,
  `min_events_per_bucket`) defaulted to the addendum values
  (`0.03` / `2` / `0.02` / `30`). Streams the verdict markdown into
  `$GITHUB_STEP_SUMMARY` and uploads the JSON as the
  `plan-2-8-q4-gate-verdict` artifact (90-day retention).
- `scripts/append_adr.py`: ADR appender helper enforcing the
  canonical shape (Context / Decision / Alternatives considered /
  Consequences / Evidence / Status), with date validation,
  status whitelist (`accepted` / `deferred` / `superseded by ...`),
  `--dry-run`, and file-based `--context-file` /
  `--alternatives-file` inputs for longer sections. Enables the W13
  ADR workflow the rollout runbook describes.
- `docs/plan_2_8_rollout_runbook.md`: operator-facing rollout
  runbook: phase timeline (0/1 done, 2 in-flight, 3 scheduled), the
  daily rolling-bench automation pointer, the W13 Q4-gate
  review checklist with a concrete bundle example, the three-gate
  summary table, the shipped pin-test inventory, and the
  "Phase 2 not ready by W12" deferral escalation.
- Pin-tests:
  - `tests/test_plan_2_8_q4_gate_workflow.py` (6 tests — file exists,
    `workflow_dispatch`-only trigger, all five inputs present, default
    thresholds match the addendum, evaluator step wires all knobs and
    streams summary, artifact uploaded with `if: always()`).
  - `tests/test_append_adr.py` (11 tests — render required
    subsections, header shape, date/slug/decision validation, status
    whitelist, empty-alternatives placeholder, append ordering,
    `## Entries` section required, CLI dry-run, CLI write, CLI error
    exit code).
  - `tests/test_plan_2_8_rollout_runbook.py` (6 tests — title, three
    gates documented with thresholds, cross-references to shipped
    tooling, four-phase table, Phase 0/1 marked done, default
    constants cited verbatim).

### Added (2026-04-21) — docs/DECISIONS.md ADR scaffolding

- `docs/DECISIONS.md`: new append-only architectural decision log
  with canonical ADR format (Context / Decision / Alternatives
  considered / Consequences / Evidence / Status). First entry:
  **2026-04-21 — 3-layer HTF trend stack over Flux-style 7-TF
  bias**, closing the Plan 2.8 addendum §7 risk-mitigation ask for
  a canonical reject-reason location. The entry enumerates all
  three rejected alternatives (Flux 7-TF, 4th intraday layer /
  30m vs 2H, sub-minute LTF) and cross-references the pin-tests
  and the Q4-gate evaluator that would re-open the deferred 2H
  branch.
- `tests/test_docs_decisions_adr.py`: 6 structural pin-tests
  (file exists, required subsections, Plan 2.8 ADR present, ADR
  cross-references addendum + all four pin-tests + Q4 evaluator,
  all three rejected alternatives listed, `Status. accepted.`).

### Added (2026-04-21) — Plan 2.8 §3.2 Q4-Gate evaluator

- `scripts/plan_2_8_q4_gate_evaluator.py`: pure evaluator for the
  three cumulative Q4 gates the addendum §3.2 requires before any
  4th-trend-layer (2H) promotion:
    - **G1 uplift**: >= 3pp HR uplift in >= 2 of the tested context
      buckets (`uplift_min_pp`, `uplift_min_buckets` configurable);
    - **G2 Brier**: brier_candidate - brier_baseline <= 0.02
      (`brier_max_regression` configurable);
    - **G3 min-events**: every bucket carries >= 30 events after
      promotion (`min_events_per_bucket` configurable, Blasiok &
      Nakkiran 2023 smECE floor).
  Consumes a minimal JSON bundle (`buckets[]` + `brier_baseline` +
  `brier_candidate`) so it can plug into any A/B framework. Emits a
  schema_version=1 verdict with `overall: pass|fail`, per-gate
  reasons, per-bucket breakdown. CLI: `--bundle`, `--output`,
  `--format md|json`, `--quiet`, plus tuning knobs for each
  threshold. Mutates nothing — W13 operators can dry-run before
  acting. 13 tests.

### Changed (2026-04-21) — Plan 2.8 rollup wired into rolling benchmark workflow

- `.github/workflows/smc-measurement-benchmark-rolling.yml`: new
  `always()` step "Plan 2.8 Phase 1 per-TF family rollup" slotted
  between the FVG label audit and the artifact upload. Runs
  `scripts/plan_2_8_tf_family_rollup.py` against the day's
  scoring-artifact tree with the expanded `5m,15m,1H,4H` TF list,
  writes `plan_2_8_tf_family_rollup.json` into the benchmark output
  dir (automatically picked up by the existing directory-level
  upload), and streams the Markdown view to `$GITHUB_STEP_SUMMARY`
  so operators can eyeball the two Phase-E2 verdicts (FVG 5m vs
  15m+1H baseline, BOS 4H vs 15m+1H baseline) on every daily run.
  Fail-soft (`set +e` + trailing `true`) so a rollup hiccup cannot
  mask the benchmark outcome.
- `tests/test_plan_2_8_rolling_workflow_rollup_wiring.py`: 6
  structural pin-tests (step present, order
  `audit < rollup < upload`, all four TFs passed, markdown streams
  to step summary, fail-soft, manifest lands in upload path).

### Added (2026-04-21) — Plan 2.8 Phase 1 per-TF family rollup + E2 verdict

- `scripts/plan_2_8_tf_family_rollup.py`: aggregates
  `scoring_<symbol>_<tf>.json` artifacts under a measurement-benchmark
  root into per-TF event counts, per-TF hit rates, per-TF x per-family
  hit rates, and two Phase-E2 verdicts mandated by the addendum
  (W8 deliverable):
    - `fvg_ttf_5m_vs_baseline`: FVG hit-rate on 5m vs the merged
      15m+1H baseline (tests the TTF-artefact hypothesis D3).
    - `bos_stability_4h_vs_baseline`: BOS hit-rate on 4H vs the
      merged 15m+1H baseline (tests the 4H swing-stability claim).
  Both verdicts report `insufficient_data` when either side carries
  < 30 events, so downstream automation cannot act on noise. Schema
  version 1. CLI: `--scoring-root`, `--timeframes`, `--output`,
  `--format md|json`, `--quiet`. Tolerates unreadable files and
  flags unknown timeframes. 12 tests.

### Added (2026-04-21) — Plan 2.8 S3.1 per-TF partitioning pin-test

- `tests/test_plan_2_8_s3_1_per_tf_partitioning.py`: 4 structural
  tests pinning that `_path_token` is stable under the exact
  `RELEASE_REFERENCE_TIMEFRAMES` strings (`"5m"`, `"15m"`, `"1H"`,
  `"4H"`), that `_pair_output_dir` partitions all four TFs into
  distinct directories under the symbol root (no collisions), and
  that per-symbol separation is preserved. Addendum 2.8 Phase 1
  deliverable: without this guard a regression could silently merge
  5m + 15m events into the same scoring bucket and break per-chart_tf
  calibration right at the layer the addendum is designed to
  strengthen.

### Changed (2026-04-21) — Plan 2.8 S0 Pine MTF-stack tooltips

- `SMC_Core_Engine.pine`: the three `Trend TF N` inputs (group
  `7. Advanced - Higher Timeframe Trend`) now carry explicit
  tooltips that document the intentional ICT-standard 3-layer
  hierarchy (4H / 1D / 1W), the factor-~4 spacing, the adaptive
  IPDA dach-TF above layer 3, and the calibration caveat for
  non-default custom TFs. Also added a comment block referencing
  `docs/smc_improvement_plan_addendum_2_8_mtf_scope_2026-04-21.md`
  so future readers can trace the "3 layers, not 7" decision.
- `tests/test_plan_2_8_s0_pine_trend_tf_tooltips.py`: 4 structural
  pin-tests (3-layer mention on TF1, calibration caveat on TF2,
  IPDA + `select_ipda_htf` reference on TF3, all three have
  non-empty tooltips).

### Changed (2026-04-21) — Plan 2.8 S3.1 Chart-TF expansion (5m + 4H added)

- `scripts/run_smc_measurement_benchmark.py`: default `--timeframes`
  expanded from `RELEASE_REFERENCE_TIMEFRAMES[1:3]` (15m, 1H) to
  the full `RELEASE_REFERENCE_TIMEFRAMES` tuple (5m, 15m, 1H, 4H).
  No code change elsewhere — `RELEASE_REFERENCE_TIMEFRAMES` already
  carried all four TFs; only the rolling-benchmark default was
  clamped to the 2-TF slice.
- `.github/workflows/smc-measurement-benchmark-rolling.yml`:
  `workflow_dispatch` `timeframes` input default + run-step shell
  fallback both moved from `15m,1H` to `5m,15m,1H,4H`. The rolling
  benchmark is what feeds F2's daily dual-arm artifact dirs, so the
  expansion propagates automatically into Phase-E2 event collection
  (5m for FVG TTF hypothesis, 4H for BOS swing stability).
- `tests/test_plan_2_8_s3_1_chart_tf_expansion.py`: 4 pin-tests —
  `RELEASE_REFERENCE_TIMEFRAMES == ("5m","15m","1H","4H")`, CLI
  default covers all four, workflow-input default covers all four,
  shell fallback covers all four and no stray `"15m,1H"` literals
  remain.

Rationale: Plan 2.8 §3.1 GO — event density ~3x on 5m (statistical
belastbarkeit for per-context quality filter), 4H proof-point for
BOS family stability, marketing anchor "kalibriert auf 5m/15m/1H/4H"
vs. legacy "15m/1H". Cost: CI config only, benchmark runtime ~2x.

### Changed (2026-04-21) — daily workflow wires runbook + archive cleanup

- `.github/workflows/f2-promotion-gate-daily.yml`: two new
  `always()` steps slotted between the status snapshot and the
  upload — "Operator runbook (consolidated)" streams the
  `f2_runbook.py --format md` output to `$GITHUB_STEP_SUMMARY`
  (status + 7-day digest + ring tail) and "Prune stale archive
  entries (>90d)" runs `f2_cleanup_archives.py` with a 90-day
  retention policy and an audit journal. Both tolerate failure so
  the gate's `rc` stays the primary signal. Upload bundle now
  carries `runbook.json`, `cleanup_archives.json`, and
  `cleanup_archives_journal.jsonl`.
- `tests/test_f2_workflow_yaml_contract.py`: pin-tests extended to
  assert (a) step order
  `annotate < summary < status < runbook < cleanup < upload`,
  (b) both new steps run on `always()` with `set +e` + trailing
  `true`, (c) bundle includes the new files (10 tests, was 9).

### Added (2026-04-21) — consolidated F2 operator runbook

- `scripts/f2_runbook.py`: one-shot report combining
  `build_status()` + `build_digest()` + latest rollback-history ring
  tail into a pasteable Markdown document (Status / Weekly digest /
  Recent ring sections). Also exposes public `build_runbook()` and
  `render_markdown()` APIs. Supports `--format md|json`,
  `--window-days`, `--ring-tail`, `--output`, `--quiet`. Schema
  version 1. Long ring reasons truncated to keep the table
  pasteable. 10 tests.
- `tests/test_f2_helpers_convergence.py`: added `f2_runbook` to
  `F2_HELPERS` (28 tests, was 26).

### Added (2026-04-21) — F2 archive retention helper

- `scripts/f2_cleanup_archives.py`: prunes
  `contextual_calibration.archive/*.json` entries whose embedded
  `YYYY-MM-DDTHH-MM-SSZ` suffix is older than `--max-age-days`
  (default 90). Skips files without a parseable timestamp. Appends
  structured manifest (schema_version=1) to
  `artifacts/ci/f2/cleanup_archives_journal.jsonl` on real runs;
  `--dry-run` previews without unlinking or journalling. Tolerates
  missing archive dirs. CLI supports `--output`/`--quiet` for CI
  use. 12 tests.
- `tests/test_f2_helpers_convergence.py`: added
  `f2_cleanup_archives` to `F2_HELPERS` (26 tests, was 24).

### Added (2026-04-21) — local dry-run simulator for the F2 chain

- `scripts/f2_simulate_chain.py`: walks the full §2.4 G2 rollback
  chain locally against synthetic fixtures — seeds a spec +
  production artifact, writes N day reports, runs
  append → render-issue → revert → rotate → summarize → inspect →
  weekly-digest, and persists a `simulation_manifest.json`
  (schema_version=1) with the narrative + every intermediate record.
  Default fixture = 2 clean days + worse day + rollback day. Custom
  `days` list supported for no-rollback walks. No network, no CI.
  `--quiet` prints only the manifest path for scripting. 8 tests.
- `tests/test_f2_helpers_convergence.py`: added `f2_simulate_chain`
  to the parametrized `F2_HELPERS` list (24 tests, was 22).

### Added (2026-04-21) — f2-weekly-digest workflow (Monday 11 UTC)

- `.github/workflows/f2-weekly-digest.yml`: new scheduled workflow
  that runs `scripts/f2_weekly_digest.py` every Monday 11:00 UTC
  (after the 10:00 UTC daily gate), writes
  `artifacts/ci/f2/weekly_digest.json`, and appends the Markdown
  timeline table to `$GITHUB_STEP_SUMMARY`. Read-only permissions
  (no Issue-ping). Uploads as a 180-day artifact so the rolled-up
  view covers the §2.4 G3 30-day SPRT window plus historical
  context. Fail-soft: no reports dir yet → exits green with a
  `::notice` skip.
- `tests/test_f2_weekly_digest_workflow_contract.py`: structural
  pin-test for the new workflow (6 invariants: name, Monday 11 UTC
  cron, `workflow_dispatch.inputs.window_days`, `contents: read`
  permissions only, helper + reports-dir + md-format flag present,
  upload retention 180 days).

### Added (2026-04-21) — Q3/Q4 Plan §2.4 G3 weekly digest helper

- `scripts/f2_weekly_digest.py`: rolls up the last N days of
  `f2_promotion_gate_<DATE>.json` reports into a single JSON digest
  (schema_version=1) — per-day timeline with brier delta + SPRT n/k,
  decision counters, SPRT-decision counters, trailing
  `consecutive_worse` / `consecutive_better` runs. `--format md` emits
  a Markdown timeline table suitable for the 30-day SPRT window
  operator review. Default window 7 days; `--window-days` overrides.
  Tolerates unreadable report files and non-matching filenames. 16
  tests.
- `tests/test_f2_helpers_convergence.py`: added the new module to the
  parametrized `F2_HELPERS` list (22 tests, was 20).

### Added (2026-04-21) — Markdown render mode for status inspector

- `scripts/f2_inspect_status.py`: new `render_markdown(status)` helper
  + `--format md` CLI flag. Emits a compact operator-readable Markdown
  block (Artifact / Revert Journal / Promote Journal / Latest report
  sections) so the inspector is usable from the terminal without
  piping through `jq`. JSON output unchanged when `--format` is
  omitted; `--quiet` still wins over `--format` for stdout. 3 new
  tests (23 total).

### Added (2026-04-21) — F2 helpers convergence-pin tests

- `tests/test_f2_helpers_convergence.py`: cross-cutting invariants for
  the 8 F2 helpers — every script exposes a callable `main()`, every
  CLI accepts `--help` and exits 0 with `usage:` text, revert+promote
  share `ARCHIVE_SUBDIR_DEFAULT='contextual_calibration.archive'`,
  both journals live under `artifacts/ci/f2/` (and are distinct files
  so they cannot clobber each other), `SUMMARY_SCHEMA_VERSION` and
  `STATUS_SCHEMA_VERSION` are positive integers, and the
  `f2-rollback` Issue label stays pinned (also referenced verbatim in
  the workflow YAML). 20 tests, ~1.4 s.

### Added (2026-04-21) — `--quiet` one-line summary for status inspector

- `scripts/f2_inspect_status.py`: new `render_one_line(status)` helper
  + `--quiet` CLI flag. Compresses the digest to
  `f2[<experiment>] artifact=<status> revert=<n> promote=<n> latest=<date>:<decision>`
  for shell pipelines and CI annotations. `--output` still writes the
  full JSON; `--quiet` only changes stdout. 4 new tests (20 total).
- `.github/workflows/f2-promotion-gate-daily.yml`: status-snapshot step
  now also emits a `::notice title=f2-contextual-arm::<one-line>`
  annotation so the daily run state is visible in the workflow log
  header without scrolling into the fenced JSON block.

### Changed (2026-04-21) — wire status inspector into daily workflow

- `.github/workflows/f2-promotion-gate-daily.yml`: new `if: always()`
  "Contextual arm status snapshot" step runs `f2_inspect_status.py`
  after the history summary, writes `artifacts/ci/f2/status_snapshot.json`
  and appends a fenced JSON block to `$GITHUB_STEP_SUMMARY`. Failure
  tolerated with `|| true` so it cannot mask the gate's exit code.
  Upload bundle now also carries `promote_journal.jsonl` and
  `status_snapshot.json`.
- `tests/test_f2_workflow_yaml_contract.py`: pinned the new step in
  the ordering invariant (annotate < summary < status < upload),
  pinned `always()` on the new step, and pinned the two new upload
  paths.
- `tests/test_f2_pipeline_e2e.py`: end-to-end now also calls the
  inspector after the rotate step, asserting that artifact status,
  revert-history length, journal counters, and latest report all
  agree.

### Added (2026-04-21) — Q3/Q4 Plan §2.3 F2 + §2.4 G2 status inspector

- `scripts/f2_inspect_status.py`: read-only operator inspector that
  fuses the live treatment artifact, both journals (revert + promote),
  and the latest promotion-gate report into a single JSON digest. Pins
  schema_version=1. Includes per-action counts + bounded `tail`
  (default 5) for each journal, the artifact's current status with
  inline `revert_history`/`promote_history` lengths, and the latest
  report's date/decision/SPRT terminal block. Tolerates corrupt
  artifact JSON, corrupt journal lines, missing reports dir, and a
  spec without `arms.treatment.calibration_artifact`. 16 tests.

### Added (2026-04-21) — Q3/Q4 Plan §2.3 F2 ``on_promote`` operator helper

- `scripts/f2_promote_contextual_weights.py`: symmetric counterpart to
  the auto-revert helper. Operator-driven (the spec's `on_promote`
  action list is intentionally a manual follow-up after a clean SPRT
  `accept_h1` plus a clean rollback ring). Refuses unless the supplied
  promotion-gate report has `decision == 'promote'` (or `--force`).
  Archives the live shadow artifact to
  `contextual_calibration.archive/<stem>_<UTC-ISO>.json`, rewrites the
  live file with `status=production` and an appended `promote_history`
  entry, and journals every run to `artifacts/ci/f2/promote_journal.jsonl`.
  Atomic writes, idempotent (re-runs after promotion are no-ops). 16 tests.

### Added (2026-04-21) — Q3/Q4 Plan §2.4 G2 workflow contract test

- `tests/test_f2_workflow_yaml_contract.py`: structural pin-test for
  `.github/workflows/f2-promotion-gate-daily.yml`. Asserts step ordering
  (gate → append → issue → revert → annotate → summary → upload), the
  `if:` conditional gates (rc=='0' guards append, rc=='2' guards
  issue+revert, `always()` runs annotate/summary), `permissions:
  issues: write`, the 10:00 UTC daily cron, and that the upload bundle
  carries both `revert_journal.jsonl` and the
  `contextual_calibration.archive/**` tree.

### Added (2026-04-21) — Q3/Q4 Plan §2.3 F2 + §2.4 G2 end-to-end test

- `tests/test_f2_pipeline_e2e.py`: e2e regression test wiring all 5 operator-facing F2
  helpers together against synthetic fixtures (append → render-issue → revert → rotate →
  summarize). Covers the two-clean-days-then-rollback walkthrough plus revert idempotency
  on a re-run. Pure-Python, no benchmark I/O. Guards every helper in one place.

### Added (2026-04-21) — Q3/Q4 Plan §2.4 G2 automatic Revert

- **F2 contextual-weights auto-revert:** New
  `scripts/f2_revert_contextual_weights.py` closes the explicit
  "automatic Revert" half of the §2.4 G2 rule (the Issue-Ping half
  shipped in `2c284591`). Reads the F2 spec + the most recent
  promotion-gate report, validates `decision == 'rollback'` (refuses
  to demote any other decision unless `--force`), archives the live
  treatment calibration JSON to
  `artifacts/ci/f2/contextual_calibration.archive/<stem>_<UTC-ISO>.json`,
  rewrites the live file with `status=shadow`, and appends a
  `revert_history` entry that records the from-status, report path,
  decision, and archive location. Always appends a JSONL line to
  `artifacts/ci/f2/revert_journal.jsonl` (even on no-op paths) so
  the audit trail is complete. Atomic writes via tempfile +
  `os.replace`. Idempotent; no network. CLI exit codes: `0` on
  success / no-op, `1` on missing spec/report/artifact-field /
  malformed JSON / wrong decision without `--force`. 15 new tests;
  total green across the F2/SPRT/AB chain now 155.
- **Workflow auto-revert wiring:** Updated
  `.github/workflows/f2-promotion-gate-daily.yml` with a new
  "Auto-revert contextual calibration (§2.4 G2)" step that runs
  only on `steps.gate.outputs.rc == '2'`, after the Issue-Ping
  step. Failure is tolerated (`true` after `set +e`) so the
  workflow's own rc=2 stays the primary signal. The journal file
  and archive directory are added to the upload-artifact bundle.
- **Issue body runbook updated:** Step 2 of the rollback Issue
  body now reflects that the contextual JSON has *already* been
  demoted automatically; operators are pointed at the journal +
  archive instead of being asked to demote by hand.

### Added (2026-04-21) — Q3/Q4 Plan §2.3 F2 daily-history summarizer

- **F2 history summarizer:** New `scripts/f2_summarize_history.py`
  closes out the F2 operator toolset (append / rotate / render-issue /
  **summarize**). Reads
  `artifacts/ci/f2/rollback_history.json` (treatment − control
  `calibrated_brier` deltas) and optionally a directory of
  `f2_promotion_gate_*.json` reports, then emits a small
  `schema_version=1` digest with: history length / last delta /
  trailing-mean trend (default 30-day window) / consecutive worse
  vs better counts (matching the §2.4 G2 rollback rule), per-decision
  counts (`promote/hold/rollback/insufficient_data`), the latest
  report path + date + decision, and the verbatim latest SPRT
  terminal block. Pure-Python, deterministic, no network. Useful as
  input for a future Pine HUD row or weekly Slack digest. CLI exit
  codes: `0` on success, `1` on `--trend-window<1` or non-list
  history. 16 new tests; 140 total green across the F2/SPRT/AB chain.
- **Workflow wiring:** Updated
  `.github/workflows/f2-promotion-gate-daily.yml` to invoke the
  summarizer as an `if: always()` step (skip / rollback / config
  error all surface a digest). Writes
  `artifacts/ci/f2/history_summary.json` (now also in the uploaded
  artifact bundle) and appends a fenced JSON block to
  `$GITHUB_STEP_SUMMARY` so the Actions tab shows current pipeline
  state at a glance. Failure of this step is tolerated (`|| true`)
  so it can never mask the gate's exit code.

### Added (2026-04-21) — Q3/Q4 Plan §2.4 G2 GitHub-Issue-Ping

- **F2 rollback Issue renderer:** New
  `scripts/f2_render_rollback_issue.py` deterministically produces an
  Issue title (`[F2 rollback] <decision> on <date>`) and full
  Markdown body from a promotion-gate JSON report. Body includes the
  KPI-delta table, SPRT terminal block, rollback-window history, a
  link to the failing workflow run, the report path, and an operator
  runbook that explicitly points at
  `scripts/f2_rotate_rollback_history.py` for the post-review reset.
  Stable label: `f2-rollback`. CLI exit codes: `0` on success, `1`
  on missing/malformed report. 11 new tests; 124 total green across
  the F2/SPRT/AB chain.
- **Workflow ping wiring:** Updated
  `.github/workflows/f2-promotion-gate-daily.yml`:
  - Added `permissions: issues: write` (alongside existing
    `contents: read`) so the job can file rollback Issues.
  - New "Open rollback Issue" step runs only when
    `steps.gate.outputs.rc == '2'`. Uses `gh issue list` + label
    `f2-rollback` to dedupe: comments on the existing open Issue if
    one is already filed, otherwise opens a fresh one with
    `gh issue create --label f2-rollback`. The gate step's exit
    code 2 still surfaces as a workflow failure (CI red), as
    required by §2.4 G2.

### Added (2026-04-21) — Q3/Q4 Plan §2.4 G2 rollback-history rotate helper

- **F2 rollback-history rotate/reset helper:** New
  `scripts/f2_rotate_rollback_history.py`, an operator-callable
  companion to `f2_append_rollback_history.py`. After a rollback
  decision (gate exit code 2) and the manual review checklist, the
  daily ring at `artifacts/ci/f2/rollback_history.json` MUST be
  reset so the next day's gate does not immediately re-fire on
  stale history. The helper archives the live file to
  `artifacts/ci/f2/rollback_history.archive/<UTC-ISO>.json` (or a
  caller-supplied `--archive-dir`) and replaces it with `[]` (or a
  caller-supplied `--seed` JSON list). Atomic write via tempfile +
  `os.replace`. `--allow-empty` lets operators bootstrap a fresh
  ring when the live file does not yet exist. Refuses archive-name
  collisions to preserve the audit trail. CLI exit codes: `0` on
  success, `1` on configuration error. 13 new tests; 113 total
  green across the F2/SPRT/AB chain.

### Added (2026-04-21) — Q3/Q4 Plan §2.4 G2 rollback-history feedback loop

- **F2 rollback-history append helper:** New
  `scripts/f2_append_rollback_history.py` reads the daily promotion-
  gate JSON report and appends the `calibrated_brier` `delta`
  (treatment − control) to a bounded JSON ring at
  `artifacts/ci/f2/rollback_history.json` (default `--max-len 30`,
  configurable). Atomic write via tempfile + `os.replace`. CLI exit
  codes: `0` on success, `1` on missing report / malformed JSON /
  missing metric. 12 new tests; 100 total green across the
  F2/SPRT/AB chain.
- **F2 daily workflow wiring:** Updated
  `.github/workflows/f2-promotion-gate-daily.yml` to invoke the
  helper after a green gate run (`steps.gate.outputs.rc == '0'`)
  and include `artifacts/ci/f2/rollback_history.json` in the
  uploaded artifact bundle. Skipped when the gate already exited
  with `rc=2` (rollback) so the next manual review owns the reset.
  Closes the loop: the file the helper produces is exactly the
  `--rollback-history` input the next day's gate consumes.

### Added (2026-04-21) — Q3/Q4 Plan §2.3 F2 daily workflow

- **F2 promotion-gate daily workflow (plan §2.3 F2 + §2.4 G3):** New
  `.github/workflows/f2-promotion-gate-daily.yml` wraps
  `scripts/f2_run_promotion_gate.py` into a daily cron at 10:00 UTC
  (after the rolling-benchmark at 07:30 and feature-importance at
  09:00 so dual-arm artifact dirs are in place). Locates
  `artifacts/ci/f2/{static_global_weights,contextual_weights}/<DATE>`,
  runs the orchestrator with the shipping spec and optional rollback
  history, uploads `artifacts/reports/f2_promotion_gate_<DATE>.json`
  for 60 days. Fail-soft when arms are not yet produced
  (`status=skipped`, exit 0) so the 30-day window countdown keeps
  ticking. Exit-code policy: `0` on promote/hold/insufficient_data,
  `2` on rollback (CI red → GitHub-Issue-Ping per §2.4 G2), `1` on
  config error. Permissions: `contents: read` only — the workflow
  never mutates production calibration; promotion is a separate
  manual follow-up driven by the spec's `on_promote` action list.

### Added (2026-04-21) — Q3/Q4 Plan §2.3 F2 promotion-gate orchestrator

- **F2 promotion-gate CLI orchestrator (plan §2.3 F2 + §2.4 G3):** New
  `scripts/f2_run_promotion_gate.py` is a single CLI entry point that
  ties `run_ab_comparison.compare()` to
  `f2_experiment_spec.evaluate_promotion()`. Inputs: `--spec`,
  `--control-dir`, `--treatment-dir`, optional `--rollback-history`
  and `--output`. Output: schema-pinned (`schema_version=1`) JSON
  carrying the `{promote, hold, rollback, insufficient_data}`
  decision, the SPRT terminal report, the KPI deltas, the
  rollback-gate evaluation and the resolved action list. Exit codes:
  `0` on promote/hold/insufficient_data, `1` on configuration error,
  `2` on rollback (CI signal for the §2.4 G2 GitHub-Issue-Ping rule).
  Includes the unit-conversion fix in `_pair_dicts`:
  `PairReport.hit_rate` is a 0..1 fraction on disk but the SPRT
  wiring expects 0..100 percent, so the adapter multiplies by 100 to
  keep the convention consistent across the pipeline. 8 new tests
  (88 total green across the full F2/SPRT/AB chain).

### Added (2026-04-21) — Q3/Q4 Plan §2.3 F2 contextual promotion gate

- **F2 contextual promotion spec + gate evaluator (plan §2.3 F2 +
  §2.4 G3):** New `artifacts/experiments/f2_contextual_promotion.json`
  (schema_version=1) registers the experiment: control =
  `zone_priority_calibration.json` (static global weights), treatment
  = `zone_priority_contextual_calibration.json` (contextual + FVG
  quality score), SPRT config (p0=0.55, p1=0.60, α=0.05, β=0.20,
  max_n=600), rollback gate (2 consecutive worse runs on
  `calibrated_brier`), promotion gate (SPRT H1 + KPI deltas + rollback
  status) with `on_promote`/`on_reject` action lists, and data_window
  (≥30 days, ≥600 events per arm). New `scripts/f2_experiment_spec.py`
  exposes `load_f2_spec()`, `evaluate_rollback()` and
  `evaluate_promotion(digest, spec, daily_deltas)` returning one of
  `{promote, hold, rollback, insufficient_data}` directly from the
  `run_ab_comparison` digest. 16 new tests covering loader
  validation, all rollback-gate edge cases, and all five promotion
  decision branches. The F2 promotion gate is now operationally
  complete; only wall-clock blocker remains (30-day window once the
  contextual arm is wired into the rolling workflow).

### Added (2026-04-21) — Q3/Q4 Plan §2.4 G3 SPRT wired into A/B comparison

- **G3/F2 SPRT in `run_ab_comparison.py` (plan §2.4 G3):** New
  `terminal_decision(n, k, config)` helper in
  `scripts/smc_sprt_stop_rule.py` runs a closed-form aggregate Wald
  SPRT (LLR = `k·ln(p1/p0) + (n-k)·ln((1-p1)/(1-p0))`) against the
  lifetime baseline (p0=0.55, p1=0.60, α=0.05, β=0.20). Order-
  independent, the right call site for post-hoc analysis of fixed-
  window A/B benchmarks (plan: "SPRT *or* fixes N"). `compare()`
  output now carries a `sprt` block and `render_comparison()` emits
  a `## SPRT Stop-Rule (G3/F2)` markdown section with the terminal
  decision, totals, LLR vs Wald bounds and the resolved config.
  F2 promotion gate now consumes the SPRT terminal decision directly
  from `artifacts/reports/ab_comparison.json` on the next G3 30-day
  window completion. 12 new tests; 52 total green across SPRT module
  + comparison wiring.

### Added (2026-04-21) — Q3/Q4 Plan §2.4 G3 SPRT stop-rule

- **G3 / F2 SPRT stop-rule (plan §2.4 G3):** New
  `scripts/smc_sprt_stop_rule.py` implements one-sided two-hypothesis
  Wald SPRT on a single arm's binary outcomes (H0: p = p0 baseline,
  H1: p = p1 target). Pure Python (`math.log` only); no numpy/scipy
  dependency. `SPRTConfig` validates `p1 > p0`, error rates in
  (0, 0.5), `max_n >= 1`. `decide()` returns
  `{accept_h0, accept_h1, continue, max_n_reached}` so the gate
  cannot loop forever in CI. `evaluate_paired()` provides the
  McNemar-style discordant-pair filter for paired (control,
  treatment) tuples. CLI emits a schema-pinned `schema_version=1`
  report with `decision`, `n`, `k`, `hit_rate`, `llr`, Wald bounds
  and the resolved config. Unblocks F2 contextual-promotion gate
  (`docs/f2_contextual_promotion_decision_2026-04-21.md` step 3)
  and G3 30-day A/B once arms are wired into the rolling benchmark.
  17 new tests (incl. deterministic Monte-Carlo H1-truth check at
  ≥70 % acceptance rate).

### Added (2026-04-21) — Q3/Q4 Plan Amendment A1 (D4 + D2 + G1 closeout)

- **A1.A — Per-Event Ledger (plan §A1.A):** New `smc_core/event_ledger.py`
  reads/writes `events_<sym>_<tf>.jsonl` records carrying ScoredEvent
  fields plus the new `features` dict. Schema-pinned with round-trip
  tests; consumed by D4 recalibration and FI-drift downstream.
- **A1.B — D4 FVG-Quality Recalibration Script
  (plan §A1.B):** New `scripts/fvg_quality_recalibration.py` produces
  `artifacts/reports/fvg_quality_calibration_shadow.json`. Pure-Python
  L2 logistic regression (no numpy/scipy/sklearn dep), weights capped
  to [0.05, 0.40] then re-normalised to sum 1.0. Acceptance gate
  codified: top-quartile HR ≥ 0.70, bottom-quartile HR ≤ 0.55,
  Spearman ≥ 0.20. Fail-soft semantics distinguish
  `insufficient_features` vs `insufficient_events`. Shadow-only;
  production `fvg_quality_calibration.json` is not mutated.
- **A1.C — D2 Tri-Axis FVG Pine Codegen (plan §A1.C):** New
  `smc_core/fvg_pine_emit.py` consumes `stratified_fvg_report()` JSON
  and emits a deterministic Pine v5 const block of
  `FVG_HEALTH_<SESSION>_<VOL>` + `_STATUS` (OK / WARN / WEAK / INSUF
  on HR thresholds 0.70 / 0.55). Insufficient buckets render as
  `"insufficient (n=N)"`. Wiring into `SMC_Core_Engine.pine` is the
  remaining manual step (compile-only preflight).
- **A1.D — G1 Baseline Seed Workflow (plan §A1.D):** New
  `.github/workflows/smc-baseline-seed-rolling.yml` runs the daily
  baseline-seed reproducibility check against the 20-symbol universe
  and writes to `artifacts/ci/baseline_seed_rolling/YYYY-MM-DD/`.
  Acceptance memo unblocks after 5 consecutive weekday green runs.
- **D4 enricher (chains A1.B):** `ScoredEvent` gained
  `features: dict[str, Any]` (frozen-safe via `field(default_factory=
  dict)`). `smc_integration/measurement_evidence._score_zone_event`
  now populates the five A1.B feature keys (`gap_size_atr`,
  `htf_aligned`, `distance_to_price_atr`, `is_full_body`, `hurst_50`)
  for the FVG family via new `_atr_at` (Wilder ATR) and
  `_fvg_hurst_50` (delegating to `smc_core.fvg_quality.rolling_hurst`)
  helpers. Missing ATR / Hurst → key omitted (no zero-fill, so
  `insufficient_features` detection stays accurate). End-to-end chain
  `_score_zone_event → ScoredEvent.features → event_ledger →
  recalibration shadow JSON` now closes on the next CI rolling run.

### Added (2026-04-21) — Q3/Q4 Plan Phase E + F1 + E4

- **E1 — Symbol-Expansion (plan §2.2):** Recurring measurement-benchmark
  workflow universe extended from 12 → 20 symbols (adds GOOGL, META,
  NVDA, TSLA, V, UNH, HD, CVX, COP, OXY, BAC, GS, MS). All three preset
  cohorts (Tech-Megacap, Financials, Energy) now covered.
- **E2 — Timeframe-Expansion (plan §2.2):** 5m and 4H added alongside
  existing 15m/1H. Workflow now produces 80 (sym × tf) artifact dirs.
- **E3 — Rolling Benchmark (plan §2.2):** New
  `.github/workflows/smc-measurement-benchmark-rolling.yml` runs the
  20-sym universe daily at 07:30 UTC, writes to dated sub-dirs
  (`artifacts/ci/measurement_benchmark_rolling/YYYY-MM-DD/`), and
  retains 30 days. Includes per-day zone-priority calibration (with
  smECE) + FVG label audit. Purely observational; does not mutate
  checked-in lifetime corpus or production calibration.
- **E4 — FI Ranking-Drift Alert (plan §2.2):**
  `open_prep/feature_importance_report.py` now reads the previous
  `latest.json` before overwriting and attaches a `ranking_drift` block
  to the new record (status ∈ {ok, warn, unknown}, max_position_delta,
  drifted_features). Drifted = top-10 position shift > 3. Features
  dropping out of top-10 count as position N+1 so silent churn cannot
  hide drift. Advisory signal; CLI prints the drifted feature rows.
- **F1 — Testable Calibration alongside ECE (plan §2.3):**
  `scripts/smc_zone_priority_calibration.py` reconstructs corpus-level
  (pred, outcome) arrays from `calibration.bins` in every
  `scoring_*.json` and emits `testable_calibration` with binned ECE
  (n=10), smECE (Błasiok & Nakkiran 2023, kernel) and dCE upper bound
  (Rossellini et al. 2025). smECE is the primary F1 promotion-gate
  input; ECE kept for back-compat. Project-root `sys.path` fallback so
  the `smc_core` import works from CLI invocation.

### Added (2026-04-20)

- **Phase H — Pine Consumer Maturity:**
  - **Calibration Confidence Indicator** — new `[ Calibration Confidence ]` section in Dashboard Audit View (rows 23–25) showing top-family calibration weight with tier label (high/good/ok/low) and composite confidence across all 4 families. Zone Priority + Calibration exports (`ZONE_CAL_OB/FVG/BOS/SWEEP` + Phase F contextual variants) added to the live generated library.
  - **Per-Family Win Rates** — new `[ Per-Family Performance ]` section in Dashboard Audit View (rows 26–30) showing OB, FVG, BOS, SWEEP individually with calibrated historical performance weight as percentage and color-coded confidence tier.
  - **FVG Health Warning** — composite health score (0–100) derived from `FVG_FRESH`, `FVG_INVALIDATED`, `FVG_FILL_PCT`, `FVG_MATURITY_LEVEL`, `FVG_NET_IMBALANCE`. New `[ FVG Health ]` section in Audit View (rows 31–33) with status + conditional warning. New `✅/⚠ FVG Health` checklist item in Explain mode. Warnings for invalidated FVGs, heavily filled zones (≥75%), and weak health.

- **Owner Review v2 (OV3–OV7):**
  - **OV3: Performance Report Script** (`scripts/generate_performance_report.py`) — consolidated Markdown + JSON performance report from measurement benchmark artifacts. Computes weighted-mean KPIs (Brier, ECE, hit rate), letter grades (A–F), pass/fail gates vs `MeasurementShadowThresholds`. CLI: `--input-dir` / `--output-dir`. 14 unit tests.
  - **OV4: Colorblind Palette** — Tableau-10 safe palette (bull=#1f77b4, bear=#ff7f0e, warn=#17becf, caution=#bcbd22) wired through Core Engine (3 lifecycle colors + 3 resolver functions), Dashboard (7 palette constants + all view modes), Mobile Dashboard (5 palette constants). Activated via existing `color_theme` input → "Colorblind Safe".
  - **OV6: Library Field Audit** — reverse-direction test (`test_every_generated_field_has_pine_consumer`) ensures every generated field has at least one Pine consumer or is declared `_INFRA_ONLY`. 18 enrichment-reserve fields catalogued. Staleness guard for `_INFRA_ONLY`.
  - **OV7: Enrichment A/B Framework** (`scripts/smc_ab_experiment.py`) — deterministic symbol-level experiment assignment (SHA-256 bucketing), flag resolution per arm, JSON experiment spec loading, provenance tagging. Comparison script (`scripts/run_ab_comparison.py`) diffs benchmark KPIs between arms with Markdown + JSON output. 16 unit tests.

- **Hygiene & Feature Round:**
  - **Provider Health Tab** in `streamlit_terminal.py` — neues "🩺 Provider Health" Tab zeigt Gesamtstatus (Coverage/Warnings/Failures), Provider-Domain-Matrix mit Failure-Semantik, Domain-Alerts und Failure-Semantics-Referenz. Basiert auf `provider_health.py` API.
  - **Zone Priority → Pine Consumer** — `SMC_Dashboard.pine` zeigt Zone Priority in Decision Brief (Rank + Score + Catalyst, farbkodiert A/B/C/D) und Audit View (vollständige Details mit Top-Family und Reason). `SkippALGO_Confluence.pine` zeigt Zone Prio als neue Zeile 7 (Rank + Score/100 + Catalyst).
  - **Provider Health Tab Tests** (`tests/test_provider_health_tab.py`) — 5 Integrationstests für die Provider Health Imports.

### Changed (2026-04-20)

- **Sunset Warning Cleanup** — entfernt den 20-Zeilen-Sunset-Warning-Block aus `generate_smc_micro_profiles.py`. `DEPRECATED_COMPATIBILITY_GROUPS` ist seit 2026-04-14 leer; die Warnung war nur noch Noise. `DEPRECATED_FIELD_POLICY` bleibt im Manifest für Contract Verification.
- **Stale asof_date Fixture Warnings** — `pyproject.toml` unterdrückt jetzt die 12 `UserWarning: Microstructure base asof_date is ... days old` Meldungen im Test-Output via `filterwarnings`.
- **Dashboard Row Shift** — Audit View und Decision Brief Row-Nummern in 3 Test-Dateien und e2e-Smoke-Referenz aktualisiert (87→88 Audit Rows).

### Added (2026-04-19)

- **Phase A+B+C — UX optimization (Strategie Q2 2026):**
  - **A1: 6 neue Alert-Conditions** in `SMC_Core_Engine.pine` — Bullish/Bearish BOS, Bullish/Bearish CHoCH, Zone Armed, Zone Invalidated. Nutzer können jetzt über TradingView-Alerts direkt auf Struktur- und Lifecycle-Events reagieren (insgesamt 16 Alert-Conditions).
  - **A2: Focus-Ansicht** im `SMC_Dashboard.pine` — neuer "Focus" View-Modus mit 3-Zeilen Traffic-Light (Ampel + Level + Market). Keine Konfiguration, keine Ablenkung — sofortige Orientierung.
  - **A3: Performance-Tabelle** in `SMC_Long_Strategy.pine` — 8-Zeilen-Table zeigt Trades, Win Rate, Profit Factor, Net Profit, Max Drawdown, Avg Trade und aktuellen Modus. Farbkodiert nach Ergebnis-Qualität.
  - **B4: SkippALGO Confluence Hub** (`SkippALGO_Confluence.pine`) — aggregiert SMC Zone-Lifecycle (BUS) + Trend (EMA) + Momentum (RSI/MACD) + Mean-Reversion (BB) zu einem 0–100 Confluence-Score mit Traffic-Light (🟢 TRADE / 🟡 WATCH / 🔴 STAY AWAY). 2 Alert-Conditions.
  - **B5: SMC Setup Check** (`SMC_Setup_Check.pine`) — validiert BUS-Verbindungen zum Core Engine mit ✅/❌ Checklist. Zeigt Anleitung für nächste Schritte direkt im Chart. Kein leeres Dashboard mehr.
  - **C8: SMC Mobile Dashboard** (`SMC_Mobile_Dashboard.pine`) — Mobile-first 4-Zeilen Dashboard: Traffic-Light + Levels + Market + Quality. Keine Overlays, nur Table. Optimiert für kleine Screens.
  - **C9: AI Zone-Priorisierung** (`scripts/smc_zone_priority.py`) — Composite-Score (0–100) aus 3 Dimensionen: historische Performance (Ensemble, 0–30), aktueller Kontext (Regime/Vol/Session/Projektion/HTF, 0–35+15), News-Catalyst (0–10) minus Event-Risk-Penalty (0–50). Output: Rank (A/B/C/D), Top-Family, Catalyst, Reason. 5 neue `ZONE_PRIORITY_*` Exports in der Generated Library. 26 Unit-Tests.
  - **B7: Signal Replay** Tab in `streamlit_terminal.py` — historische Signal-Timeline mit Aggregate-Metriken (Signals, Resolved, Hit Rate, Avg/Total P&L), Hit-Rate-Matrix nach Gap×RVOL Bucket, tägliche Signal-Timeline mit Expander pro Tag. 11 Unit-Tests.
  - **B6: Gehostetes Terminal** — `Dockerfile`, `docker-compose.yml`, `.dockerignore` für Self-Hosted-Deployment. Token-basierter Auth-Guard `terminal_auth.py` (`STREAMLIT_AUTH_TOKEN` env var), timing-safe Vergleich, Zero-Friction lokal. 10 Unit-Tests.
  - **C10: Explain-Modus** im `SMC_Dashboard.pine` — neuer "Explain" View-Modus mit ✅/❌ Checklist (9 Kriterien: Struktur, Zone, Qualität, Freshness, Session, Market, Event, HTF, Pressure). Zeigt Next Step und erklärt WARUM der aktuelle Zone-State gilt.
  - **Outcome Backfill Pipeline** (`open_prep/outcome_backfill.py`) — Post-Open-Job zum Auffüllen der bisher leeren `profitable_30m`/`pnl_30m_pct` Felder in Outcome-Dateien. Holt 1-min OHLCV-Bars von Databento für das [09:30–10:00 ET]-Fenster, berechnet 30-min P&L, aktualisiert Dateien atomar. CLI: `python -m open_prep.outcome_backfill [--date YYYY-MM-DD] [--lookback N] [--dry-run] [--feature-importance]`. Feature-Importance-Backfill schließt den Kalibrations-Feedback-Loop. 25 Unit-Tests.
  - **Strategiedokument** `docs/SYSTEM_REVIEW_AND_STRATEGY_2026_Q2.md` — vollständiges Systemreview mit Vergleichsmatrix, Designprinzipien und 10-Punkte-Umsetzungsplan (A1–C10).

### Changed (2026-04-09)

- **SMC / Databento / NewsAPI.ai stabilization wave:**
  - Added a Databento reference alias-cache and identifier-change risk layer across the SMC generator, Open Prep, terminal Databento helpers, and the v5 event-risk builder so recent corporate-action ticker changes are no longer invisible to enrichment and ranking.
  - Added NewsAPI.ai Event Registry feed-cursor persistence, provider-status export, and probe tooling so live/news fallback paths can resume incrementally and expose clearer diagnostics when the feed is reachable but has no new symbol-matching items.
  - Added deterministic live-news regression coverage plus verified review/runbook documentation for the recent SMC hardening work; see `docs/smc-databento-change-note-2026-04-09.md` for the compact technical summary of the published mainline range.

### Fixed (2026-04-08)

- **SMC deeper integration and micro-library hardening:**
  - Centralized lazy Open Prep runtime construction in `open_prep_boundary.py` and rewired the Databento, terminal, and bridge FMP consumers to use the shared boundary instead of importing `open_prep.macro.FMPClient` directly.
  - Extracted realtime A0/A1 promotion into `open_prep/rt_promotion.py` so the shared promotion logic no longer depends on Streamlit imports, and added regression coverage that locks the workflow and runtime-boundary rules in place.
  - Hardened Databento bundle base generation with a compatibility fallback from legacy `close` and `volume` columns when `day_close` or `day_volume` are absent in symbol-day features.
  - Fixed SMC news scoring so only actually mentioned universe tickers are exported, and hardened Pine CSV sharding so multi-part exports preserve comma boundaries instead of silently corrupting long strings.
  - Hardened TradingView exact-open verification so Pine declaration lines that carry a matching shorttitle no longer invalidate an otherwise correct `SMC Core` editor identity.
  - Reduced TradingView open-script trace noise by collapsing repeated missing-candidate diagnostics into per-step summaries, while keeping the existing alias-based script recovery intact.
  - Decoupled micro-library publish status from the downstream repo-core preflight gate so exact/idempotent library publishes are reported as `published` while the overall command still stays failed when repo-core validation is red.
  - This removes the oversized neutral-news export path that surfaced during live micro-library validation and restores a compile-clean TradingView library generation path without changing the checked-in seed artifacts.
  - The latest fully green SMC mainline evidence is `automation/tradingview/reports/preflight-2026-04-08T12-37-12-028Z.json`.

### Changed (2026-04-08)

- **SMC mainline settings hierarchy refresh:**
  - Reordered `SMC_Dashboard.pine` so the visible `Product Surface` controls open before the hidden BUS bindings, and relabeled the remaining binding and debug sections as explicit operator-only groups.
  - Reordered `SMC_Long_Strategy.pine` so `Execution Setup` and `Trade Plan` appear before the two `Expert Mapping` sections.
  - Reprioritized `SMC_Core_Engine.pine` settings into `Core Setup`, `Output`, `Trade Plan`, `Session Gate`, and `Runtime Budget`, with the remaining technical groups marked as `Advanced`.
  - Refreshed the operator guide, strategy guide, validation runbooks, and checklist so the active docs match the shipped TradingView settings surface.

- **SMC core first-run hero and overlay cut:**
  - Tightened the `SMC_Core_Engine.pine` Focus View hero copy so `Why now` and `Main risk` stay short and confidence remains tier-based instead of pseudo-precise.
  - Made `Core Trigger` and `Core Invalidation` explicitly depend on the actionable `Ready` / entry states rather than a broader visual-state threshold.
  - Suppressed standalone volume and strict-LTF warning labels plus default strong/weak swing overlays in Focus View so the hero stays the only primary first-run message.
  - Updated the focused TradingView UI and contract tests plus the manual validation docs to lock the compact-surface behavior in place.

- **SMC execution wrapper language cleanup:**
  - Reworded the visible `SMC_Long_Strategy.pine` setup and expert-mapping tooltips so the surface talks about linked core outputs and execution plans instead of raw BUS-contract internals.
  - Refreshed the execution guide and operator guide summary so the wrapper stays clearly operator-only without leaking unnecessary transport jargon into the visible setup path.

- **SMC execution surface copy cut:**
  - Renamed the four visible strategy controls to `Execution Stage`, `Minimum Quality Score`, `Take Profit (R)`, and `Use Take Profit` so the wrapper reads like execution setup instead of mixed setup/transport language.
  - Renamed the visible strategy chart outputs to `Execution Trigger`, `Execution Invalidation`, and `Execution Take Profit`, and aligned the strategy guide, validation docs, screen spec, and evidence manifest to the new execution-surface terminology.

- **SMC product-surface validation evidence contract:**
  - Added a canonical `validationEvidence` block to `scripts/smc_bus_manifest.py` and the checked-in TradingView product-cut artifact so the four required rendered chart captures are defined in one machine-readable contract.
  - Aligned the German and English manual validation runbooks plus report templates to the manifest-backed evidence pack and locked the editor-screenshot exclusion into docs/tests.

### Changed (2026-04-07)

- **SMC mainline surface implementation wave:**
  - Renamed the visible Core/Dashboard/Strategy controls to the new Lite, Companion, and Execution-surface language in `SMC_Core_Engine.pine`, `SMC_Dashboard.pine`, and `SMC_Long_Strategy.pine`.
  - Added actionable trigger and invalidation lines directly to the Core so `READY LONG` and `ENTER LONG` remain legible without switching to a second script.
  - Reordered the dashboard summary first fold around action, blocker reason, and risk plan, and replaced terse blocker copy with clearer trader-facing text.
  - Aligned the strategy guide, migration guide, and manual validation runbooks with the new `Lite Surface`, `Companion Summary`, and `Execution Stage` terminology.

- **SMC post-cut documentation cleanup:**
  - Clarified the post-cut cleanup guardrails in `docs/smc-lite-pro-product-cut.md` so the remaining follow-up items read as later architecture rules rather than open release blockers.
  - Added a UX-review-derived surface concept, concrete copy deltas, and a prioritized implementation backlog for the SMC Core, Dashboard, and Long Strategy mainline surfaces in `docs/smc-lite-pro-product-cut.md`.
  - Replaced the stale SkippALGO strategy guide with an SMC mainline wrapper guide in `docs/TRADINGVIEW_STRATEGY_GUIDE.md`.
  - Refreshed the German and English TradingView manual validation runbooks to reflect that the canonical `tv:preflight:smc-mainline` gate is reproducible from this workspace again.
  - Updated `docs/README.md` and the root `README.md` to point at the canonical SMC mainline gate and product-cut references.

### Changed (2026-04-06)

- **TradingView decision-first first-release closure:**
  - Finished the SMC decision-first surface work for `SMC_Core_Engine.pine` and `SMC_Dashboard.pine`, and aligned the released docs to the Core/Dashboard/Long Strategy scope.
  - Kept the shipped SkippALGO HUD work documented as a separate TradingView surface change, not as part of the SMC architecture scope.
  - Added a decision-first TradingView preflight config for `SMC_Core_Engine.pine`, `SMC_Dashboard.pine`, `SMC_Long_Strategy.pine`, and companion TradingView automation, plus npm wiring for repeatable release validation.
  - Marked the first-release ticketset and R1.1 migration guide as released and updated the README to reflect the corrected SMC scope.

### Changed (2026-04-06)

- **TradingView decision-first R1.1 hardening:**
  - Regrouped the `SMC_Dashboard.pine` Pro diagnostics surface into clearer operator-facing sections without changing the underlying BUS binding order or diagnostic row contracts.
  - Added explicit migration/operator guidance for the decision-first rollout, including safe-default expectations for `compact_mode`, `surface_mode`, and `surfaceMode` plus the operator-only BUS binding workflow for the dashboard companion script.
  - Kept the decision-first visual modes as presentation changes only; no additional engine gating is introduced by the new Lite/Pro defaults.

### Fixed (2026-03-25)

- **Historical Benzinga symbol-day export hardening:**
  - Fixed historical Benzinga news fetches in `newsstack_fmp/ingest_benzinga.py` to retry provider-rejected request shapes with date-only filters and an alternate symbol parameter fallback instead of failing immediately on HTTP 400.
  - Updated `scripts/databento_production_export.py` to use Benzinga-friendly day filters for historical company-news export requests while still enforcing the exact ET/UTC event windows locally after fetch.
  - Added focused regression coverage in `tests/test_benzinga_news_endpoints.py` and updated `tests/test_databento_production_export_news.py` to lock the new historical request shape.

- **SMC base session-minute coverage guard:**
  - Fixed `scripts/smc_microstructure_base_runtime.py` so Databento symbols explicitly reported as unresolved at runtime are excluded from the hard session-minute completeness check instead of causing false `incomplete symbol coverage` failures.
  - Added regression coverage in `tests/test_smc_microstructure_base_runtime.py` for runtime-unsupported symbols.

- **SMC base workbook Excel row-limit hardening:**
  - Fixed `scripts/smc_microstructure_base_runtime.py` workbook export to split oversized `base_snapshot` outputs across numbered sheets when row count exceeds Excel's per-sheet limit, preventing `This sheet is too large` failures during base scan exports.

- **Databento open-window second-detail duplicate handling:**
  - Fixed `databento_volatility_screener.py` duplicate symbol-second logging to distinguish expected multi-publisher `ohlcv-1s` shards from anomalous duplicate rows.
  - Expected venue-level shards are now consolidated into composite OHLCV with info-level logging, while same-publisher anomalies remain warning-level.
  - Added regression coverage in `tests/test_databento_volatility_screener.py` for both multi-publisher composite rows and true duplicate anomalies.

### Fixed (2026-03-24)

- **TradingView validation-layer storage-state hardening:**
  - Fixed portable `TV_STORAGE_STATE` reuse by exporting Playwright storage state with IndexedDB included, instead of relying on cookies and localStorage alone.
  - Fixed false chart-presence detection so generic script-name text and non-actionable editor containers no longer count as proof that a script is already on the chart.
  - Fixed settings-surface targeting to prefer actionable legend wrappers, preventing Dashboard and Strategy checks from landing on unrelated chart or volume settings.
  - Fixed Pine editor reuse under portable auth by auto-restoring TradingView's read-only historical-version state before attempting to write code.
  - Fixed staged target aggregation so any populated runtime/editor error forces `overall_preflight_ok = false` for that target.
  - The latest fully green portable-auth evidence is `automation/tradingview/reports/preflight-2026-03-24T09-10-25-787Z.json`.

### Fixed (2026-03-21)

- **SMC++ intrabar invalidation and watchlist-level consistency:**
  - Kept `Long Setup` and `Long Visual` sticky on `Invalidated` / `Fail` for the rest of the realtime bar after an intrabar invalidation, so the dashboard no longer drops back to a neutral-looking state after the alert already fired.
  - Aligned the long-dip watchlist alert level with the existing active-zone preference logic, so overlapping OB/FVG cases now point at the same preferred active zone used by the setup engine instead of always preferring OB.

### Changed (2026-03-21)

- **SMC++ documentation refresh:**
  - Updated the German dashboard guide to document sticky intrabar invalidation behavior in the dashboard and the watchlist alert-level alignment with active-zone preference.

### Fixed (2026-03-20)

- **SMC++ long-dip state, alert, and profile consistency:**
  - Fixed overlapping OB/FVG long-dip sequencing so strict reclaim history, arming, and invalidation now track the actual source object instead of the merged long-zone view.
  - Fixed armed-source invalidation to compare against the active zone for the armed source kind, preventing overlap cases from silently surviving on the wrong zone.
  - Fixed long-dip watchlist alerts to be generic again: the watchlist event now triggers only when the generic watchlist becomes active, not when OB/FVG source rotation happens inside an already active watchlist.
  - Fixed priority-mode dynamic lifecycle alerts so `Long Invalidated` can still fire on the same realtime bar after a weaker lifecycle alert was already sent earlier in that bar.
  - Fixed TradingView `alertcondition(...)` lifecycle presets and OB/FVG event presets to use per-bar latched event state, reducing missed intrabar transitions for close-safe users.
  - Fixed volume-quality signaling to distinguish current-bar volume loss from rolling feed degradation, and aligned dashboard messaging with that split.
  - Fixed lower-timeframe confirmation fallback handling by separating price availability from volume availability and by tightening when strict-entry fallback is allowed historically.
  - Fixed OB profile value-area construction to expand from the POC outward and hardened profile alignment against empty or zero-volume profiles.
  - Fixed active long-zone selection to prefer the better overlap candidate instead of relying on a first-match merge.
  - Fixed pivot HH/HL/LH/LL labels, FVG hide cleanup, and symbol-token matching for microstructure/profile overrides.

### Changed (2026-03-20)

- **SMC++ dashboard and workflow documentation:**
  - Documented that the Watchlist tier is a generic context stage, while strict sequencing, backing-zone tracking, and invalidation are source-specific to the active OB or FVG.
  - Documented the new microstructure display behavior where the dashboard shows both the primary profile and active modifiers that can tighten or relax long-dip filters.
  - Documented the degraded-data model for relative volume and lower-timeframe checks so users can see when the engine is operating with price-only or fallback-safe context.

### Fixed (2026-03-19)

- **SMC++ long-dip and object lifecycle hardening:**
  - Fixed swing OB break handling so older blocks are no longer skipped just because the newest tracked block was not broken yet.
  - Fixed bullish and bearish FVG maintenance loops so older filled gaps are still updated and migrated even when newer gaps remain open.
  - Fixed `update(FVG this)` so the close-vs-live fill mode is recalculated per gap instead of leaking through a static `var`, which could silently mis-handle later FVG fills.
  - Fixed OB/FVG reclaim detection so a reclaim can complete on a later bar after the initial zone touch, as long as it stays within the configured long signal window.
  - Fixed a follow-up reclaim regression so OB/FVG reclaims fire only once on the actual crossover bar instead of staying latched true across later bars above the reclaimed zone.
  - Replaced fixed-millisecond OB/FVG projection with exact event timestamps for time-based overlays and index-based drawing for chart-timeframe OB/FVG objects, removing weekend/holiday/DST drift.
  - Wired the existing OB/FVG garbage-collection cycle through the main indicator so insignificant objects can actually be cleaned up on schedule.
  - Fixed HTF FVG retention to respect `Keep filled` history settings instead of using a hardcoded history depth of `2`.
  - Stopped HTF FVG `request.security()` calls from running while the HTF overlay is hidden.
  - Tightened long setup expiry semantics so setups now expire exactly when they reach the configured bar limit.
  - Aligned long-dip preset alerts with the multi-bar setup model by using recent-zone context instead of requiring the current bar to still overlap the pullback zone.
  - De-spammed dynamic long-dip state alerts so watchlist, armed, early, clean, and entry presets now emit only on state transitions.
  - Restored the pre-break OB cutoff semantics for index-based rendering so broken order blocks no longer extend one bar too far to the right.
  - Removed leftover dead code from earlier alert/dashboard iterations, including unused compact trend text, unused HTF state locals, unused intrabar event counting, and unused legacy FVG plotting wrappers.
  - Removed redundant per-bar OB/FVG registry rebuilds from the dashboard count path and switched those counts to direct array sizes.
  - Hardened the premium/discount warning helper to reuse a single warning label instead of creating a new one every bar.
  - Added lower-timeframe guardrails that automatically disable `request.security_lower_tf()` sampling when the chart-to-LTF ratio or estimated intrabar array size exceeds configured safety thresholds.
  - Hardened volume-data quality checks so relative volume, OB profiles, and volume-driven confirmations degrade gracefully on symbols with missing or effectively empty volume.
  - Added optional intraday VWAP/session alignment as an extra long filter for users who want session-aware intraday confirmation.
  - Added a practical risk/exit overlay that exposes trigger, invalidation, ATR-buffered stop, and 1R/2R targets directly on the chart and dashboard.
  - Switched strict HTF trend confirmation to a confirmed-only `request.security()` pattern so live HTF bars can no longer repaint strict long-entry gating.
  - Fixed same-bar OB/FVG dip-and-reclaim detection so valid wick-through reclaim candles no longer get missed when the previous close was already back above the zone.
  - Restored newest-last ordering for broken OB and filled FVG event buffers, and aligned downstream alert level lookups with that ordering.
  - Fixed visible-range filtering to respect the effective rendered right edge of extended OB/FVG objects, including the OB break bar.
  - Aligned TradingView `alertcondition(...)` long-dip presets with the existing one-shot dynamic alerts by exposing the preset states as edge events.
  - Wired the volume-quality guard through the OB profile capture/alignment engine path, not only the profile rendering path.

- **SMC++ live alert and timeframe hardening:**
  - Fixed intrabar OB/FVG live alerts in `SMC++.pine` to prefer exact engine event buffers (`ob_broken_new_*`, `filled_fvgs_new_*`) before scanning active objects, preventing silent misses on the event bar.
  - Fixed FVG fill alert levels to report the correct newest filled gap level by using the engine's event ordering instead of `.last()`.
  - Hardened lower-timeframe and HTF-FVG timeframe validation for non-time-based charts by normalizing timeframe seconds and rejecting unsupported chart/HTF combinations explicitly.
  - Tightened HTF FVG validation so the selected HTF must again be strictly higher than the chart timeframe.
  - Upgraded realtime marker dedupe guards to `varip` so reclaim and long-state markers stay stable on open realtime bars.
  - Made OB/FVG engine execution explicit via hidden `Use OB engine` and `Use FVG engine` inputs, preserving the intended visual-only meaning of `Show` toggles while removing silent ambiguity.

### Added (2026-03-19)

- **SMC++ long-dip alert presets:**
  - Added seven reusable alert preset booleans in `SMC++.pine` for `Watchlist`, `Armed+`, `Early`, `Clean`, `Entry Best`, `Entry Strict`, and `Failed` long-dip states.
  - Added matching `alertcondition(...)` definitions so the presets are available directly in TradingView alerts.
  - Added matching `fire_dynamic_alert(...)` calls so dynamic alerts can emit the same long-dip lifecycle states with level context.
  - Added dedicated German and English documentation for the SMC++ dashboard and long-dip workflow under `docs/`.

### Changed (2026-03-19)

- **SMC++ dashboard layout tightened:**
  - Reworked the `SMC++.pine` dashboard to be narrower and taller by splitting wide aggregate rows into shorter stacked rows.
  - HTF trend, object counts, swing/internal levels, zone levels, and trigger levels now render as compact single-purpose rows instead of wide combined summaries.
  - Shortened dashboard labels and legend text so the panel uses vertical space more efficiently without removing state information.

### Added (2026-03-17)

- **Databento bullish-quality score presets:**
  - Added selectable Bullish-Quality weighting presets in `scripts/bullish_quality_config.py`:
    - `conservative`
    - `balanced` (default)
    - `aggressive`
  - The presets change how strongly market-structure signals influence `window_quality_score` without changing the export contract.
  - Added test coverage for preset resolution in `tests/test_generate_bullish_quality_scanner.py`.
  - Added Streamlit sidebar selection for the Bullish-Quality score profile in `databento_volatility_screener.py`.
  - Added production-export CLI support via `--bullish-score-profile` in `scripts/databento_production_export.py`.

### Changed (2026-03-17)

- **Databento structure-aware scanner ranking and documentation:**
  - Bullish-Quality remains structure-forward by default via the new `balanced` preset.
  - Added dedicated structure-feature documentation in `docs/DATABENTO_STRUCTURE_FEATURES.md`.
  - Extended `docs/RFC_BULLISH_QUALITY_PREMARKET_SCANNER.md` with structure-field and score-profile details.
  - Long-Dip and Bullish-Quality ranking now expose the new structure columns more clearly in the Streamlit UI.

### Added (2026-03-05)

- **USI-CHOCH early-entry upgrade (`USI-CHOCH.pine`):**
  - Added **Same-Bar Verify** for bullish CHoCH (`same-bar OR next-bar`), enabling earlier CHoCH confirmation.
  - Added **Early Signal Inputs** for anticipation and momentum pre-signals:
    - anticipation proximity (%),
    - momentum RSI/divergence window,
    - volume spike multiplier,
    - marker visibility toggles.
  - Added **Anticipation markers** (`A↑`/`A↓`) when price approaches swing levels under matching structure context.
  - Added **Momentum Pre-CHoCH markers** (`M↑`/`M↓`) using RSI divergence + volume spike conditions.
  - Added early-signal alertconditions:
    - `Anticipation Bullish/Bearish`,
    - `Momentum Pre-CHoCH Bullish/Bearish`.

### Changed (2026-03-05)

- **CHoCH fast-signal parity across scripts:**
  - The three “earlier BUY/CHoCH” improvements now exist in both `CHoCH.pine` and `USI-CHOCH.pine`:
    1. Same-Bar Verify,
    2. Anticipation,
    3. Momentum Pre-CHoCH.

### Changed (2026-03-04)

- **� RT Engine auto-start across all entry points:**
  - Added `ensure_rt_engine_running()` helper in `realtime_signals.py` — PID file management + pgrep fallback + `subprocess.Popen` background launch.
  - **streamlit_terminal.py**: Auto-starts RT engine on session init (skipped on Streamlit Cloud). Imports `RealtimeEngine` and `ensure_rt_engine_running`.
  - **streamlit_monitor.py**: Auto-starts RT engine on session init (skipped on Streamlit Cloud).
  - **vd_signals_live.sh**: Engine now auto-starts by default (previously required `--start-engine`). Added `--no-engine` flag to opt out.
  - **vd_watch.sh**: Auto-starts RT engine before rendering dashboard.
  - **vd_open_prep.sh**: Auto-starts RT engine before pipeline extraction.

- **🏆 Rankings tab enhanced with realtime signals (streamlit_terminal.py):**
  - Rankings composite score updated: **50% price move + 20% news + 15% RT technical + 15% RT signal tier**. Was 70/30 price/news.
  - New columns: **Signal** (A0/A1/A2), **Tech** (weighted indicator score), **RSI** (RSI-14 with color coding), **MACD** (signal direction).
  - Sort order now prioritizes RT signal tier (A0 > A1) within bullish/bearish tiers.
  - Loads full RT signal data from both VisiData JSONL and structured JSON, enriching each ranked symbol with technical scores, RSI, MACD, direction, and volume ratio from the RT engine.

- **�🔭 Realtime Signals — full universe monitoring (900+ symbols):**
  - Removed the fixed `top_n=15` watchlist limit. The engine now monitors **all scored symbols** from the pipeline run (typically 900+), not just the top-ranked candidates.
  - `_load_watchlist()` merges `ranked_v2` (top scored) + `filtered_out_v2` overflow entries (scored but below display cutoff) + `enriched_quotes` (remaining universe symbols) to build the full monitoring universe.
  - `DEFAULT_TOP_N` changed from `15` → `0` (meaning all). The `--top-n` CLI flag still works for backward compatibility (`--top-n 20` limits to 20).
  - `_enrich_watchlist_live()` now uses FMP bulk profile endpoint (`/stable/profile-bulk`) for avgVolume enrichment across 900+ symbols in a single call. Falls back to per-symbol profile calls (capped at 50) when bulk is unavailable.
  - `_fetch_realtime_quotes()` now chunks FMP batch-quote requests into groups of 500 symbols to avoid URL-length limits.
  - CLI help updated to reflect `0 = all` default.

- **🔧 Realtime Signals — TechnicalScorer integration (6 bug fixes):**
  - Added `TechnicalScorer` class integrating TradingView + FMP technical indicators (RSI, MACD, ADX, MA alignment) into signal detection.
  - Fixed CRITICAL bug: VisiData rows used undefined `existing` variable → `sym_signals` (NameError crash).
  - Fixed `_MIN_CALL_SPACING` 3.0 → 13.0s (must exceed TradingView's 12s rate limit).
  - Fixed RSI/tech A1→A0 upgrade bypassing dynamic cooldown anti-spam protection.
  - Fixed cache eviction to fall back to oldest-entries removal when TTL eviction alone doesn't shrink below max.
  - Fixed `_restore_signals_from_disk()` to include `technical_score`, `technical_signal`, `rsi`, `macd_signal` fields.
  - Fixed ADX scoring to be direction-neutral (amplifies existing bias instead of adding unconditional bullish tilt).

### Added (2026-03-03)

- **Live technicals wired into AI Insights:**
  - `tab_ai.py` now fetches real TradingView technical analysis (RSI, MACD, ADX, oscillators, MAs) for the top 8 tickers by |news_score| on each AI query, using the 15m interval.
  - Previously `_cached_technicals` was referenced but never populated — LLM context only included news headlines. The LLM now receives technicals summaries alongside news, dramatically improving Trade Ideas and Market Pulse quality.
  - Results cached in `st.session_state["_cached_technicals"]` for reuse across tabs.

- **Tech badge column in dashboard tabs:**
  - Top Movers, Actionable, and Defense & Aerospace tabs now display a **Tech** column showing TradingView summary signals (🟢 Buy, 🔴 Sell, ⚪ Neutral, etc.) for each symbol.
  - Added `_get_tech_summary()` helper in `streamlit_terminal.py` reads cached technicals from session state.

- **🎯 Actionable tab (new — tab #4):**
  - Curated view of high-conviction trade setups ranked by composite news + technical score.
  - Includes Tech badge column and news score overlay.
  - Tab count increased 18 → 19.

- **Today Outlook in Outlook tab:**
  - Outlook tab now shows both **Today** and **Next-Trading-Day** outlooks side by side.
  - `compute_today_outlook()` function added to `terminal_poller.py` — uses shared `_compute_outlook_for_date()` core with the current trading day (returns "MARKET CLOSED" on non-trading days).
  - Tomorrow outlook refactored into shared core (`_compute_outlook_for_date()`) with backward-compatible aliases.

- **CHOCH-Indicator.pine alertcondition() calls:**
  - Added 4 `alertcondition()` calls — **Buy**, **Short**, **Exit** (close long), **Cover** (close short) — enabling TradingView "Create Alert" directly from the CHOCH indicator.

- **Leveraged ETF skip-list in terminal_forecast.py:**
  - Added `_NO_FUNDAMENTALS_SYMBOLS` set (~45 tickers: SOXL, TQQQ, UVXY, TSLL, etc.) to skip yfinance fundamental lookups that always 404.
  - Added 30-min negative-TTL cache (`_CACHE_NO_DATA_TTL_S`) to avoid re-fetching symbols with no data.
  - Silenced yfinance internal logger (set to CRITICAL) to stop noisy 404 ERRORs flooding the console.

### Fixed (2026-03-03)

- **Race condition in BackgroundPoller:** `wake_event.set()` now properly interrupts `stop_event.wait()` — replaced `stop_event.wait()` with `wake_event.wait()` inside the poll loop and checking `stop_event.is_set()` explicitly.
- **BackgroundPoller stop_and_join():** Added `stop_and_join()` method for clean thread shutdown in tests and session teardown; previous code called `stop_event.set()` but never joined the thread.
- **Feed stuck on exception:** Empty-poll counter now increments on exception paths too, preventing infinite exception loops that kept the poller alive without producing data.
- **Auto-prune oscillation:** Changed auto-prune `keep=250` → `keep=0` to fully clear the dedup gate and unblock fresh fetches instead of partially pruning.
- **SQLite corruption resilience:** `store_sqlite.py` now runs `PRAGMA quick_check` on init; if the database is corrupt, it auto-renames the file and creates a fresh database instead of crashing.
- **Movers KeyError guards:** Added `.get()` guards for Benzinga movers response fields (`symbol`, `change`, `price`) that could be missing, preventing uncaught KeyError crashes.
- **Feed staleness churn loop:** Feed lifecycle recovery now tracks `last_ingest_ts` (time of most recent successful ingest) with a configurable grace period, preventing the recovery loop from firing repeatedly when published timestamps are old but the feed is actually active.
- **AI Insights "Clear AI result" button:** Added `st.rerun()` after clearing session state so the UI immediately reflects the cleared state.
- **AI Insights preset button switching:** Added `st.rerun()` after preset button clicks (e.g., switching from "Market Pulse" to "Trade Ideas") to ensure the new question is processed immediately instead of requiring a second click.

### Changed (2026-03-03)

- **Technicals cache TTL reduced:** `terminal_technicals.py` `_CACHE_TTL_S` changed from 900s (15 min) → 180s (3 min) for fresher intraday data.
- **"News Score" column rename:** "Score" column in Movers tab renamed to "News Score" for clarity, avoiding confusion with technical/composite scores.
- **CHOCH-Base_Indikator.pine defaults aligned:** `ms_logic` default changed "Standard" → "SMC+Sweep", `ms_mode` default changed "Verify" → "Ping" to match strategy defaults.
- **SkippALGO_Strategy.pine cooldown sync:** Added `presetAutoCooldown` input and synchronized `cooldownTriggersEff`/`ModeEff`/`MinutesEff`/`BarsEff` to respect preset-driven cooldown overrides.
- **VWAP_Reclaim_Indicator.pine alert rename:** Alert titles renamed from "Long Entry / Exit Long / Short Entry / Exit Short" to "Buy / Exit / Short / Cover" for consistency with CHOCH and SkippALGO conventions.
- **Outlook tab refactored:** Renamed from "Tomorrow Outlook" to "Today & Next-Trading-Day Outlook", with `_compute_outlook_for_date()` shared core eliminating code duplication.
- **Outlook return keys normalized:** Generic keys (`target_date`, `earnings_count`, `high_impact_events`) with backward-compatible aliases for existing consumers.

### Fixed (2026-03-02)

- **Streamlit Cloud inotify crash:** Added `fileWatcherType = "none"` to `.streamlit/config.toml` to prevent `OSError: [Errno 24] inotify instance limit reached` on shared Linux hosts. Streamlit's default `watchdog`-based file watcher exhausted the low inotify limit, cascading to EMFILE errors on all network connections (Benzinga, FMP).
- **EMFILE resilience in `load_jsonl_feed`:** Catch `OSError` during JSONL file read so the app degrades gracefully (returns partial data) instead of crashing if file descriptors are exhausted.
- **Sidebar API key detection:** Re-reads `os.environ` directly instead of stale cached `TerminalConfig`, so keys added to `.env` after session start are detected.
- **Streamlit Cloud secrets bridge:** Added `_load_streamlit_secrets()` to both `streamlit_terminal.py` and `open_prep/streamlit_monitor.py` — copies `st.secrets` into `os.environ` for Cloud deployments where `.env` is gitignored.
- **RT Engine path resolution:** VD signals JSONL path now resolved as absolute (`PROJECT_ROOT`-relative) so CWD doesn't matter.

### Changed (2026-03-02)

- **Rebranding: "Real-Time News Intelligence Dashboard — AI supported":**
  - Replaced all "Bloomberg-style" / "News Terminal" branding references across README, docstrings, LLM system prompt, changelog, requirements.txt, and docs/BLOOMBERG_TERMINAL_PLAN.md.
  - Page title and main heading in `streamlit_terminal.py` updated.
  - Added AI Insights anchor link directly below the main heading.
  - Kept factual references to Bloomberg as a news source (source tier classification in playbook.py, FMP endpoint docs) — only product branding was neutralized.
- **Documentation refresh (README):**
  - Updated tab count from 17 → 18 (AI Insights tab added).
  - Updated module count from 14 → 16 (added `terminal_ai_insights.py` and `terminal_tabs/`).
  - Rewrote Tabs Overview table with current tab order (AI Insights #2, Bitcoin #5, Outlook replaces Tomorrow Outlook).
  - Updated architecture diagram with `terminal_ai_insights` and `terminal_tabs/` directory.
  - Updated test count 1 674 → 1 681.
  - Updated Streamlit config section with `fileWatcherType = "none"` and local override instructions.
  - Updated project structure tree with `terminal_ai_insights.py` and `terminal_tabs/` directory.

### Changed (2026-03-01)

- **Documentation refresh (README):**
  - Added a dedicated **Live Feed Score Badge Semantics** section describing sentiment-aware color mapping, thresholds (`0.80` / `0.50`), directional prefixes (`+`, `−`, `n`), and WIIM (`🔍`) marker meaning.
  - Expanded **Open-Prep Streamlit Monitor** docs with operational behavior details: minimum auto-refresh floor, rate-limit cooldown handling, cache-vs-live fetch strategy, stale-cache auto-recovery, stage-progress status panel, UTC/Berlin timestamp display, and extended-hours Benzinga quote overlay behavior.
  - Added **Open-Prep Realtime Engine operations quickstart** (start/verify/restart) and clarified that RT engine is a separate long-running process from Streamlit.
  - Added explicit product positioning language (**Research & Monitoring Terminal**, **News Intelligence + Alerting**, **Workflow/Decision Support**) and clear compliance disclaimers (no personalized recommendations, no order execution).
- **Ops runbook refresh (`docs/OPEN_PREP_OPS_QUICK_REFERENCE.md`):**
  - Updated document date to `01.03.2026`.
  - Added copy/paste sections for RT engine **Start / Verify / Restart** including process and artifact freshness checks.
  - Added the same positioning/compliance framing to align operations documentation with README messaging.

### Changed (2026-02-28)

- **README.md rewritten:** Comprehensive GitHub-ready documentation covering Real-Time News Intelligence Dashboard (17-tab architecture, module map, data sources, configuration, background poller, notifications, export), Open-Prep Pipeline (Streamlit monitor, macro explainability), Pine Script (Outlook/Forecast, signal modes, key features), and Developer Guide (tests, linting, project structure, documentation index).

### Removed (2026-02-28)

- **Dead code removal (~680 lines across 6 files):**
  - `terminal_poller.py`: Removed 21 unused fetch functions — `fetch_treasury_rates`, `fetch_house_trading`, `fetch_congress_trading`, 15× `fetch_finnhub_*` (insider sentiment, peers, market status, FDA calendar, lobbying, USA spending, patents, social sentiment, pattern recognition, support/resistance, aggregate indicators, supply chain, earnings quality, news sentiment, ESG), 3× `fetch_alpaca_*` (news, most active, top movers). File reduced from ~1 865 to ~1 329 lines.
  - `terminal_newsapi.py`: Removed `concept_type_icon` (unused icon mapper) and `fetch_market_articles` (unreferenced ad-hoc article query wrapper).
  - `newsstack_fmp/scoring.py`: Removed `headline_jaccard`, `_headline_tokens`, `_TOKEN_RX`, `_STOP_WORDS` (unused Jaccard-similarity helpers).
  - `open_prep/realtime_signals.py`: Removed `get_a0_signals` and `get_a1_signals` (unused filter methods).
  - `open_prep/streamlit_monitor.py`: Removed `_cached_ind_perf_op`, `_cached_bz_profile_op`, `_cached_bz_detail_op` (uncalled cached wrappers) and their dead imports (`_fetch_ind_perf`, `_fetch_bz_profile`, `_fetch_bz_detail`).
  - `newsstack_fmp/ingest_benzinga_financial.py`: Removed `_extract_dict` (unused extraction method).

### Fixed (2026-02-28)

- **Race condition** in `terminal_notifications.py`: `_last_notified` dict now protected by `threading.Lock()` to prevent concurrent access from background poller and main Streamlit thread.
- **API key leak** in `terminal_bitcoin.py` and `terminal_newsapi.py`: `httpx` exception strings containing full URLs with `apikey=` parameters are now sanitized via `_APIKEY_RE` regex before logging.
- **Silent exception swallowers** in `streamlit_terminal.py`: Added `logger.warning()` to 3 bare `except` handlers (alert rules JSON load, extended-hours quotes, BG extended-hours quotes).
- **SSRF vulnerability** in `streamlit_terminal.py`: Webhook URL input now validated with `_is_safe_webhook_url()` — blocks private IP ranges (127.x, 10.x, 172.16-31.x, 192.168.x, 169.254.x, localhost, 0.0.0.0) and requires http/https scheme.
- **State desync** in `streamlit_terminal.py`: Feed lifecycle cursor reset now propagates to background poller session state, preventing cursor drift after auto-recovery.
- **Unbounded memory** in `terminal_spike_detector.py`: Stale symbols in `_price_buf` and `_last_spike_ts` are now pruned every 100 polls when newest snapshot exceeds `max_event_age_s`.
- **Narrow exception** in `newsstack_fmp/ingest_benzinga.py`: WebSocket JSON parse now catches `(json.JSONDecodeError, ValueError)` instead of bare `Exception`.
- **Pre-existing test failure** in `tests/test_production_gatekeeper.py`: `test_valid_quote_produces_signal` now patches `_is_within_market_hours` and `_expected_cumulative_volume_fraction` to pass regardless of time-of-day.

### Added (2026-02-28)

- **Finnhub + Alpaca Multi-Provider Integration (Phase 1–3):**
  - **`FinnhubClient`** in `open_prep/macro.py` — 15 methods across 3 tiers:
    - Phase 1 FREE (8 endpoints): `get_insider_sentiment` (MSPR score), `get_peers`, `get_market_status`, `get_market_holiday`, `get_fda_calendar`, `get_lobbying`, `get_usa_spending`, `get_patents`
    - Phase 2 PREMIUM (8 endpoints): `get_social_sentiment` (Reddit+Twitter), `get_pattern_recognition`, `get_support_resistance`, `get_aggregate_indicators`, `get_supply_chain`, `get_earnings_quality`, `get_news_sentiment`, `get_esg`
    - Auth via `FINNHUB_API_KEY` env var, 30 req/s free tier
  - **`AlpacaClient`** in `open_prep/macro.py` — 4 methods:
    - `get_news` (real-time news with sentiment), `get_most_active` (screener), `get_top_movers` (gainers/losers), `get_option_chain`
    - Auth via `APCA_API_KEY_ID` + `APCA_API_SECRET_KEY` headers

- **Pipeline expansion (`open_prep/run_open_prep.py`):**
  - `TOTAL_STAGES` 15 → 17 (2 new Finnhub stages)
  - Stage 12: Finnhub Insider Sentiment + Company Peers + FDA Calendar
  - Stage 13: Finnhub Social Sentiment + Pattern Recognition (PREMIUM)
  - 4 new pipeline helpers: `_fetch_finnhub_insider_sentiment`, `_fetch_finnhub_peers`, `_fetch_finnhub_social_sentiment`, `_fetch_finnhub_patterns`
  - Enriched quotes with: `fh_mspr_avg`, `fh_insider_sentiment_emoji`, `fh_peers`, `fh_social_score`, `fh_social_mentions`, `fh_pattern_label`, `fh_tech_signal`, `fh_support_levels`, `fh_resistance_levels`

- **Streamlit dashboard (`streamlit_terminal.py`) — 5 new tabs (16 → 21 total):**
  - 🧠 Insider Sentiment — Finnhub MSPR scores with color-coded emojis + company peers
  - 📡 Social Sentiment — Reddit/Twitter mention counts and sentiment scores
  - 📐 Patterns & S/R — Chart pattern recognition + support/resistance levels + composite tech signals
  - 💊 FDA Calendar — Upcoming FDA advisory committee meetings
  - 🗞️ Alpaca News — Real-time news feed + Most Active screener + Top Movers (sub-tabs)
  - 14 new `@st.cache_data` cached functions (11 Finnhub + 3 Alpaca)

- **Fetch functions (`terminal_poller.py`) — 18 new functions:**
  - 7 Finnhub FREE: `fetch_finnhub_insider_sentiment`, `fetch_finnhub_peers`, `fetch_finnhub_market_status`, `fetch_finnhub_fda_calendar`, `fetch_finnhub_lobbying`, `fetch_finnhub_usa_spending`, `fetch_finnhub_patents`
  - 8 Finnhub PREMIUM: `fetch_finnhub_social_sentiment`, `fetch_finnhub_pattern_recognition`, `fetch_finnhub_support_resistance`, `fetch_finnhub_aggregate_indicators`, `fetch_finnhub_supply_chain`, `fetch_finnhub_earnings_quality`, `fetch_finnhub_news_sentiment`, `fetch_finnhub_esg`
  - 3 Alpaca: `fetch_alpaca_news`, `fetch_alpaca_most_active`, `fetch_alpaca_top_movers`

- **VisiData export (`terminal_export.py`) — 6 new columns:**
  - `insider_mspr` (MSPR avg score), `insider_sent` (emoji), `social_score` (composite), `social_emoji`, `pattern` (detected chart pattern), `tech_signal` (composite buy/sell/neutral)

- **Provider comparison report (`docs/ANBIETER_VERGLEICH_Finnhub_TwelveData_Alpaca.md`):**
  - Comprehensive German-language analysis of Finnhub, Twelve Data, and Alpaca APIs
  - Gap analysis against existing FMP + Benzinga coverage
  - Integration roadmap with effort estimates

### Fixed (2026-02-28)

- **Markdown lint (MD060)** in `docs/FMP_ENDPOINT_GAP_ANALYSE.md`: Fixed all table separator spacing
- **Markdown lint (MD060 + MD051)** in `docs/ANBIETER_VERGLEICH_Finnhub_TwelveData_Alpaca.md`: Fixed table separators and link fragment anchors

### Verification (2026-02-28)

- Full regression suite: **1 674 passed, 34 subtests passed, 0 failures**.
- Pylance/Pyright: **0 workspace errors**.
- Dead code removed: **~680 lines across 6 files** (31 functions).

### Added (2026-02-27)

- **Auto-recovery mechanism (data freshness self-healing):**
  - **Terminal (`streamlit_terminal.py` + `terminal_feed_lifecycle.py`):** When news feed is >30 min stale during market hours (04:00–20:00 ET), automatically resets API cursor + prunes SQLite dedup to force a fresh poll. 5 min cooldown between attempts. Manual "Reset Cursor" sidebar button as escape hatch. Sidebar shows feed age, cursor age, empty poll count.
  - **Open Prep Streamlit (`open_prep/streamlit_monitor.py`):** When cached pipeline data is >5 min old during market hours, automatically invalidates cache and forces a fresh pipeline run (~68s). 5 min cooldown between attempts. Sidebar shows recovery counter. `_STALE_CACHE_MAX_AGE_MIN = 5`.
  - **VisiData signals (`scripts/vd_signals_live.sh`):** When signal file is >5 min old and engine process is not running, auto-starts `open_prep.realtime_signals` in the background.
  - **VisiData open-prep watch mode (`scripts/vd_open_prep.sh`):** Tracks consecutive pipeline failures; after 3 failures, re-sources `.env` (catches rotated keys) and waits 60s before retrying.
  - **Background poller (`terminal_background_poller.py`):** Same hardened prune + cursor reset pattern as terminal — each prune call independent, cursor reset always executes even if prune fails.

- **Staleness thresholds (all surfaces):**

  | Surface | What is checked | Threshold | Action |
  | --- | --- | --- | --- |
  | Terminal feed | Newest article age | 5 min | Cursor reset + dedup prune |
  | Open Prep cache | Pipeline cache age | 5 min | Cache invalidate + fresh pipeline |
  | RT signals (Streamlit) | Signal file mtime | 5 min | Orange warning banner |
  | VD signals launcher | Signal file mtime | 5 min | Auto-start engine |
  | VD open-prep launcher | JSON file mtime | 5 min | Console warning |
  | Sector performance cache | `@st.cache_data` TTL | 60s (was 300s) | Auto-evict |

- **Hardened failure handling (auto-recovery never crashes):**
  - Each `prune_seen` / `prune_clusters` call has its own try/except — one failing doesn't block the other.
  - Cursor reset moved outside try blocks — the primary recovery action always executes even when SQLite prune fails.
  - `manage()` call site wrapped in try/except — lifecycle errors can never crash the Streamlit page.
  - Individual prune error logging (`prune(seen)` vs `prune(clusters)`) for debugging.

- **Benzinga delayed-quote overlay (extended-hours freshness):**
  - Integrated `fetch_benzinga_delayed_quotes()` into terminal spike scanner, VisiData snapshot, open_prep Streamlit monitor, and all stale FMP price displays.
  - During pre-market/after-hours, `bz_price`/`bz_chg_pct` columns overlay fresher Benzinga quotes on top of stale FMP close data.
  - Market-session aware: `market_session()` in `terminal_spike_scanner.py` detects pre-market, regular, after-hours, and closed states.
  - `SESSION_ICONS` extracted as canonical dict in `terminal_spike_scanner.py`, imported by both Streamlit apps.
  - Rankings tab in `streamlit_terminal.py` accepts `bz_quotes` param with RT > BZ > None price source priority.

- **Benzinga calendar, movers & quotes adapters:**
  - `BenzingaCalendarAdapter` in `newsstack_fmp/ingest_benzinga_calendar.py` with typed fetchers (ratings, earnings, economics, conference calls).
  - `fetch_benzinga_movers()` and `fetch_benzinga_delayed_quotes()` via REST endpoints.
  - WIIM article boost in `_classify_item()` for "Why Is It Moving" actionability.
  - 79 tests in `tests/test_benzinga_calendar.py`.

- **Benzinga full API coverage (news + calendar + financial endpoints):**
  - **News endpoints (3 new):** `fetch_benzinga_top_news()` (curated top stories), `fetch_benzinga_channels()` (available channel list), `fetch_benzinga_quantified_news()` (sentiment-scored articles with entity scores) — all added to `newsstack_fmp/ingest_benzinga.py`.
  - **Calendar endpoints (5 new):** `fetch_dividends()`, `fetch_splits()`, `fetch_ipos()`, `fetch_guidance()`, `fetch_retail()` — all added to `BenzingaCalendarAdapter` in `newsstack_fmp/ingest_benzinga_calendar.py`.
  - **Financial Data adapter (20+ methods, new file):** `BenzingaFinancialAdapter` in `newsstack_fmp/ingest_benzinga_financial.py` covering fundamentals, financials, valuation ratios, company profiles, price history, charts, auto-complete, security/instruments lookup, logos, ticker detail, options activity. Eight standalone wrapper functions exported.
  - **Channels & topics filtering:** `channels` and `topics` query parameters wired into REST adapter, WebSocket adapter, `Config`, and `terminal_poller.py`. New env var `TERMINAL_TOPICS`.
  - 103 new tests across 4 files: `test_benzinga_news_endpoints.py` (18), `test_benzinga_financial.py` (44), `test_benzinga_calendar_extended.py` (17), `test_vd_bz_enrichment.py` (24).

- **Benzinga Intelligence — Streamlit Terminal (expanded):**
  - Expanded Benzinga Intel tab from 3 to 11 sub-tabs: Ratings, Earnings, Economics, **Dividends**, **Splits**, **IPOs**, **Guidance**, **Retail**, **Top News**, **Quantified News**, **Options Flow**.
  - All new sub-tabs use `@st.cache_data(ttl=120)` wrappers and graceful error handling.

- **Benzinga Intelligence — Open Prep Streamlit:**
  - New "📊 Benzinga Intelligence" section in `open_prep/streamlit_monitor.py` with 8 tabs: Dividends, Splits, IPOs, Guidance, Retail Sentiment, Top News, Quantified News, Options Flow.
  - 10 cached wrapper functions with `@st.cache_data(ttl=120)` TTLs.
  - All imports guarded by `try/except ImportError` for Streamlit Cloud compatibility.

- **VisiData Benzinga enrichment:**
  - `build_vd_snapshot()` and `save_vd_snapshot()` accept `bz_dividends`, `bz_guidance`, `bz_options` parameters.
  - Per-ticker enrichment columns: `div_exdate`, `div_yield` (from dividends), `guid_eps` (from guidance), `options_flow` (from options activity).
  - New `build_vd_bz_calendar()` and `save_vd_bz_calendar()` functions produce a standalone Benzinga Calendar JSONL file with dividends, splits, IPOs, and guidance events.
  - Default export path: `artifacts/vd_bz_calendar.jsonl`.

- **Terminal UI improvements:**
  - Data table headlines are now clickable links to source articles (`LinkColumn`).
  - Ring-buffer eviction replaces queue drop-on-full (maxsize 100 → 500).
  - Optional import guard for `ingest_benzinga_calendar` on Streamlit Cloud.

### Fixed (2026-02-27)

- **Production readiness hardening (3 review cycles, 12 bugs fixed):**
  - **Review #1:** P0 falsy `or` in dict lookup, P1 `bq.get("last", 0)` default, P1 unconditional API calls in non-extended sessions, P2 inner import, P2 source concatenation, P2 duplicate dicts.
  - **Review #2:** P1 cache key thrashing from non-deterministic set iteration → `sorted()`, P2 6× `market_session()` per render → consolidated to single `_current_session`, P1 `_get_bz_quotes_for_symbols` in open_prep had no caching → added `@st.cache_data(ttl=60)` wrapper, P2 unused `timezone` import.
  - **Review #3:** P2 spike symbols not sorted before `join()` for cache key, P2 BZ overlay ran after `_reorder_ranked_columns` so bz columns appeared at tail.
  - **Refactoring:** DRY `SESSION_ICONS` extraction, symbol extraction `g.get("symbol") or g.get("ticker", "")` pattern, loop var rename `l` → `loser`.

- **Pylance/Pyright lint cleanup (0 workspace errors):**
  - Wrapped `json.load`, `getattr`, `round/max/min`, `st.session_state` returns with explicit casts (`float()`, `str()`, `list()`, `# type: ignore[no-any-return]`).
  - Added `# type: ignore[assignment]` for optional import `None` sentinel assignments.
  - Renamed loop var `q` → `quote` in `terminal_spike_scanner.py` to avoid type-narrowing shadow.
  - Imported `ClassifiedItem` at module level + `dict[str, Any]` annotation on defaults in tests.
  - Fixed `Generator` return type for yield fixtures in `tests/test_benzinga_calendar.py`.
  - Used `callable()` check instead of truthiness for `_market_session` function.

### Verification (2026-02-27)

- Full regression suite: **1599 passed, 34 subtests passed**.
- Pylance/Pyright: **0 workspace errors** (only external `~/.visidatarc` stub, suppressed).
- Lint (`ruff`): clean.

### Added (2026-02-26)

- **Python quality/documentation baseline (repo-level):**
  - Added centralized `pyproject.toml` configuration for `pytest`, `ruff`, `mypy`, and coverage reporting.
  - Added focused coverage expansion in `tests/test_coverage_gaps.py` for Python runtime modules (`terminal_poller`, `terminal_export`, `newsstack_fmp` adapters/pipeline/store).
  - Improved top-level README developer guidance for reproducible quality checks.

- **VWAP Reclaim expansion (Long/Short/Both):**
  - Added new bidirectional scripts:
    - `VWAP_Reclaim_Indicator.pine`
    - `VWAP_Reclaim_Strategy.pine`
  - Added `Trade Direction` toggle (`Long` / `Short` / `Both`) with mirrored short state machine (`Reclaim → Retest → Go`) and dedicated short entry/exit labeling.
  - Added short-side trend gating parity (`matchedTrendsFilter_short`) and USI bear-stack gate parity in bidirectional variants.

- **Signal filter controls (all VWAP reclaim variants):**
  - Added grouped `🔒 Signal Filters` controls:
    - `Bar Close Only`
    - `Volume Filter`
    - `Min Volume Ratio`
    - `Volume SMA Length`
  - Integrated `barCloseGate` + `volGate` into signal generation and visualization flow.

- **News Intelligence Dashboard integration (workspace):**
  - Added terminal pipeline/runtime modules:
    - `terminal_poller.py`
    - `terminal_export.py`
    - `streamlit_terminal.py`
  - Added coverage in `tests/test_terminal.py` and planning doc `docs/BLOOMBERG_TERMINAL_PLAN.md`.

### Fixed (2026-02-26)

- **VWAP reclaim reliability hardening (indicator/strategy parity):**
  - ATR bootstrap safety: `atr = nz(ta.atr(14), syminfo.mintick * 10)` to avoid early-bar `na` tolerance propagation.
  - Anchor reset hardening: reclaim/position state now resets fully on `isNewPeriod` (including reclaim bar markers), preventing stale sequence carry-over.
  - Strategy reset parity: bidirectional strategy closes all active exposure with unified `strategy.position_size != 0` guard on period reset.
  - Bidirectional strategy concurrency: `pyramiding=2` to allow intended simultaneous long+short behavior in `Both` mode.
  - Long-stop safety: `nz(retestLow, vwapValue)` guard prevents `na` stop propagation in long-only strategy.
  - Debug marker stability: reclaim/retest debug markers now respect `barCloseGate`.
  - UX semantics: long-only USI status now uses `FLAT` (gray) instead of `BEAR` when no bull stack is present.

### Verification (2026-02-26)

- Full regression suite (local): **1028 passed, 34 subtests passed**.

### Added (2026-02-25)

- **Open-Prep Streamlit v2: auto-promotion for realtime A0/A1 signals:**
  - Added deterministic promotion logic in `open_prep/streamlit_monitor.py` to lift symbols from
    `filtered_out_v2` into `ranked_v2` when all of the following are true:
    - active realtime level is `A0` or `A1`,
    - symbol is **not** already ranked,
    - pipeline reason is exactly `below_top_n_cutoff`.
  - Promoted rows are flagged with `rt_promoted=true` and include realtime context
    (`rt_level`, `rt_direction`, `rt_pattern`, `rt_change_pct`, `rt_volume_ratio`).
  - Streamlit UI now renders a dedicated **🔥 RT-PROMOTED** block above the normal v2 tiers.
  - Promoted symbols are removed from `filtered_out_v2` display to avoid duplicate listing.
  - Cross-reference panel now reuses preloaded realtime A0/A1 data and excludes already-promoted symbols,
    so “missing from v2” only reflects hard-filtered or non-universe cases.

- **New unit test coverage for promotion behavior:**
  - Added `tests/test_rt_promotion.py` with coverage for:
    - below-cutoff promotion (A0/A1),
    - hard-filter exclusion,
    - no-duplication for already-ranked symbols,
    - case-insensitive symbol matching,
    - fallback semantics for promoted price fields,
    - multi-symbol and no-op edge cases.

### Verification (2026-02-25)

- Targeted suite: **13 passed** (`tests/test_rt_promotion.py`).
- Full regression suite: **985 passed, 34 subtests passed**.

### Added (2026-02-21)

- **Indicator/Strategy parity hardening finalized:**
  - Synced `EXIT` timing state in Strategy with Indicator (`enTime := time`).
  - Kept same-bar reversal/entry gate mapping aligned (`COVER→BUY`, `EXIT→SHORT`) with strict anti-same-direction guard.
  - Added/updated regression coverage to lock parity behavior in:
    - `tests/test_skippalgo_pine.py`
    - `tests/test_skippalgo_strategy_pine.py`
    - `tests/test_behavioral.py`
    - `tests/pine_sim.py`

- **REV JSON alert-action parity in Strategy:**
  - Consolidated runtime `alert()` path in `SkippALGO_Strategy.pine` now maps first signal label like Indicator:
    - `BUY`/`REV-BUY` → `buy`
    - `SHORT`/`REV-SHORT` → `sell`
    - `EXIT`/`COVER` → `exit`
  - Prevents action misclassification when reversal labels are emitted.

- **Open-prep robustness and data-output refresh:**
  - Strengthened macro/news processing paths and updated report artifacts in `reports/`.

### Verification (2026-02-21)

- Pine-focused parity suites: **193 passed, 8 subtests passed**.
- Full regression suite: **551 passed, 32 subtests passed**.

### Added (2026-02-20)

- **VWT integration (Volume Weighted Trend) in Indicator + Strategy:**
  - Added configurable VWT filter inputs in both scripts:
    - `useVwtTrendFilter`
    - `vwtPreset` (`Auto`, `Default`, `Fast Response`, `Smooth Trend`, `Custom`)
    - `vwtLengthInput`, `vwtAtrMultInput`
    - `vwtReversalOnly`, `vwtReversalWindowBars`
    - `showVwtTrendBackground`, `vwtBgTransparency`
  - Added effective Auto mapping (`vwtPresetEff`, `vwtReversalWindowEff`) based on `entryPreset`.
  - Added VWT runtime state and entry guards:
    - `vwtTrendDirection`, `vwtTurnedBull/Bear`, `vwtBullRecent/BearRecent`
    - `vwtLongEntryOk` / `vwtShortEntryOk`
  - Wired VWT gates into all entry paths:
    - engine gates (`gateLongNow`, `gateShortNow`),
    - reversal globals (`revBuyGlobal`, `revShortGlobal`),
    - score entries (`scoreBuy`, `scoreShort`).

- **Optional VWT trend background overlay (Indicator + Strategy):**
  - Added regime-based background coloring for bullish/bearish VWT trend state.

- **New regression tests for VWT feature:**
  - `tests/test_skippalgo_pine.py`
    - `test_vwt_inputs_exist`
    - `test_vwt_gating_wired_into_all_entry_paths`
  - `tests/test_skippalgo_strategy_pine.py`
    - `test_vwt_inputs_exist`
    - `test_vwt_gating_wired_into_all_entry_paths`

### Verification (2026-02-20)

- Full test run completed locally:
  - **478 passed, 16 subtests passed, 0 failed**.

### Evidence (Databento live, 10 025 events / 78 pairs)

- FVG hit-rate **56.1 %** vs BOS **86.8 %** — confirms WP21 FVG
  weakness at 55× sample size; not a small-sample artifact.
- `session:ASIA` boosts every family's HR (OB +0.3005, FVG +0.1175,
  SWEEP +0.1338) — coherent regime signal.
- `session:NY_AM` FVG underperformance -0.0812 at n=2 662 — single
  largest actionable lever.
- Aggregate smECE 0.1349, ECE 0.1332, dCE 0.1260 — all three agree;
  grid-artifact risk is low.
- Production `artifacts/reports/zone_priority_calibration.json`
  intentionally NOT bumped: global OB drift -0.3534 exceeds the 0.15
  drift-gate. F2 contextual promotion gated on G3 30-day A/B with
  SPRT/fixed-N stop rule per plan.

### Added — Pine Library Modularization (Task 3)

- **Five new Pine Script v6 libraries** (`pine/` folder) extracting shared logic
  from the SkippALGO family:
  - `skipp_math` — constants, clamping, probability/logit, percentile,
    statistics, array safety, scoring helpers (24 exports).
  - `skipp_scoring` — trend/regime detection, ensemble scoring, binning,
    quantile helpers, decision quality (20 exports).
  - `skipp_indicators` — zero-lag EMA variants, log regression oscillator
    (5 exports).
  - `skipp_calibration` — rolling accumulators, 3-way probability,
    calibration engine, eval stats (16 exports).
  - `skipp_labels` — label text truncation, capped label buffer (2 exports).

- **Consumer slimming** — 6 Pine scripts now delegate shared functions to the
  libraries via thin wrappers (`f_xxx(…) => lib.xxx(…)`):
  - `SkippALGO.pine`: ~50 functions delegated (4 545 → 4 178 lines, −367).
  - `QuickALGO.pine`: 50 functions delegated (4 908 → 4 709 lines, −199).
  - `SkippALGO_Strategy.pine`: 48 functions (4 839 → 4 642, −197).
  - `SkippALGO_Mid.pine`: 18 functions (2 930 → 2 847, −83).
  - `SkippALGO_Mid_Strategy.pine`: 18 functions (2 954 → 2 871, −83).
  - `SkippALGO_Mid_Indicator.pine`: 18 functions (2 948 → 2 865, −83).
  - **Total: ~1 012 duplicated lines removed** across consumers.

- **Bulk slimming script** `scripts/pine_slim.py` — automates import injection
  and function body→delegate replacement for future Pine library extraction.

- Functions with heavy global/UDT dependencies (TfState, input-bound
  parameters) intentionally kept inline to preserve semantic safety.

### Added (2026-03-02 – 2026-03-02)

- **📊 Actionable / Rankings / Segments tab enrichment:**

- **🧠 AI Insights consolidation & tab reorder:**
  - Removed the old "AI Insights" tab (was using basic TradingView-only context)
  - Renamed "FMP AI" → "AI Insights" (the multi-layer enriched version is now the default)
  - Deleted `terminal_tabs/tab_ai.py` (no longer needed)
  - Reordered tabs: AI Insights → Actionable → Segments → Rankings → Outlook → Live Feed → Bitcoin → Alerts → Data Table

- **📊 Actionable / Rankings / Segments tab enrichment:**
  - **Actionable tab** — now shows 6 new inline columns: `Price`, `Chg%`, `Social` (Finnhub), `Analyst` (FMP consensus + upside%), `NLP` (NewsAPI.ai), `P/E`, `Vol`. Includes column guide popover explaining each data source.
  - **Rankings tab** — added 4 new inline columns: `Tech` (TradingView signal), `Social`, `Analyst`, `P/E`. FMP batch quotes enrich price data when spike data is missing. Social sentiment and analyst forecasts use cached data or fetch fresh.
  - **Segments tab** — added GICS sector performance overlay (expandable metric cards at top). "Top Symbols per Segment" drill-down now shows `Price`, `Chg%`, `Tech`, `Social`, `Analyst`, `P/E` columns per ticker.
  - All three tabs gracefully fall back to cached data or empty columns when APIs are unavailable.

- **🧠 FMP AI multi-layer enrichment (8 new data sources):**
  - FMP AI context now includes **11 data layers** (up from 3) for dramatically richer LLM analysis:
    1. **FMP quotes** (price, change%, volume, P/E, EPS) — *existing*
    2. **FMP profiles** (sector, industry, beta) — *existing*
    3. **TradingView technicals** (RSI, MACD, Stoch, MAs) — *existing*
    4. **Economic calendar** — today's US macro events (GDP, CPI, FOMC, NFP) with estimates vs actuals from FMP
    5. **Sector performance** — 11 GICS sector % changes for rotation analysis from FMP
    6. **Social sentiment** — Reddit + Twitter mention counts and bullish/bearish scores from Finnhub
    7. **Analyst forecasts** — price targets, consensus ratings, EPS estimates, recent upgrades/downgrades from FMP
    8. **Benzinga analyst ratings** — institutional upgrades, downgrades, price target changes (last 7 days)
    9. **Benzinga earnings calendar** — upcoming/recent EPS and revenue estimates vs actuals (±7 days)
    10. **Insider trades** — recent executive buys/sells with transaction values from FMP
    11. **Congressional trades** — Senate + House member stock trades from FMP
  - Each data source has independent caching and graceful fallback if the API is unavailable.
  - UI metadata line now shows `🔗 N data layers` count alongside existing article/ticker/FMP metrics.
  - System prompt upgraded to instruct the LLM to cross-reference ALL available layers and identify disconnects (e.g. bullish news + bearish technicals, insider selling + analyst upgrades).
  - Context expander description updated to list all data sources.
  - `assemble_context()` expanded with 8 new optional keyword parameters — fully backward-compatible.

- **🏦 FMP AI tab (new):**
  - Mirrors the AI Insights tab UI — same 6 preset questions, custom question input, Generate/Regenerate/Clear buttons.
  - Fetches real-time FMP quotes (price, change%, volume, market cap, P/E, EPS) and company profiles (sector, industry, beta) for the top 12 tickers in the feed.
  - Sends FMP-enriched context to OpenAI GPT-4o with a finance-data-aware system prompt that cross-references news sentiment with actual price action.
  - Separate session state keys (`fmp_ai_*`), separate cache, separate save file (`fmp_ai_trade_ideas.txt`).
  - Auto-refresh pauses when FMP AI result is being reviewed (`fmp_ai_pause_auto_refresh`).
  - Requires both `FMP_API_KEY` and `OPENAI_API_KEY`.
  - New files: `terminal_fmp_insights.py` (backend), `terminal_tabs/tab_fmp_ai.py` (UI).
  - Tab count increased 9 → 10.

- **FMP technicals fallback provider:**
  - New `terminal_fmp_technicals.py` module — fetches RSI(14), MACD(12,26), Stochastic(14,3,3), Williams %R(14), ADX(14), SMA & EMA (10, 20, 50, 100, 200) from FMP REST API.
  - Computes Buy/Sell/Neutral signals using standard thresholds (RSI >70/< 30, MACD crossover, Stoch >80/<20, etc.).
  - Returns data in the same `TechnicalResult` format as TradingView — transparent to all callers.
  - 3-minute in-memory cache with thread-safe locking and auto-eviction.
  - FMP has 3,000 calls/min rate limit — no 429 risk.

### Fixed (2026-03-02 – 2026-03-02)

- **TradingView 429 spam — proper cooldown escalation (`51a84e6`):**
  - `_tv_register_success()` was resetting the consecutive 429 counter while a cooldown was still active, preventing escalation (120s → 240s → 480s). Now only resets when cooldown has fully expired.
  - Cooldown early-return in `fetch_technicals()` now caches its result so repeated calls during cooldown skip immediately.
  - Cooldown `RuntimeError`s from `_tv_throttle()` are now distinguished from actual TradingView 429 responses — they no longer re-register as new 429s, which was artificially escalating cooldown timers.
  - Cooldown-block log messages downgraded from WARNING to DEBUG to reduce noise.

- **AI Insights infinite spinner — 30s time budget (`d98aa25`):**
  - The AI tab was hanging at "Fetching technicals for 8 tickers…" because each TradingView call has a 12s minimum spacing (anti-429 throttle). 8 tickers × up to 3 exchanges × 12s = up to 288 seconds of blocking.
  - Added a 30-second time budget to the technicals fetch loop — breaks out early and uses whatever was collected.
  - Falls back to previously cached technicals from session state if the time budget expires before any fresh data is fetched.
  - Spinner now shows "≤30 s" hint so users know it won't hang indefinitely.

- **AI tabs blocked during TradingView cooldown (`bb61050`, `caf082d`):**
  - AI Insights and FMP AI tabs now check `_tv_is_cooling_down()` before the technicals fetch loop and skip entirely when TradingView is rate-limited.
  - Shows a visible caption with remaining cooldown time (e.g., "⏳ TradingView rate-limited — cooldown 120s remaining. Using cached technicals.").
  - Both tabs proceed straight to the LLM query with whatever data is available.
  - Technical Data expander widgets in `streamlit_terminal.py` and `_shared.py` also had redundant cooldown guards that were removed after fallback integration.

- **FMP as automatic TradingView fallback (`cbee41f`):**
  - `fetch_technicals()` cooldown path now calls `_fmp_fallback()` which imports `fetch_fmp_technicals` and converts its dict result to a `TechnicalResult`.
  - When TradingView is in 429 cooldown (120–900s), all callers transparently receive FMP-sourced technicals instead of error results.
  - FMP results are cached in the TradingView cache so subsequent calls return instantly.
  - Redundant widget-level cooldown guards removed from `streamlit_terminal.py` and `terminal_tabs/_shared.py` since `fetch_technicals()` now handles fallback internally.

- **Deprecated `use_container_width` warnings (`836e223`, `72385f0`):**
  - Replaced all 7 occurrences of `use_container_width=True` with `width='stretch'` across `streamlit_terminal.py` (3), `terminal_tabs/tab_ai.py` (3), and `terminal_tabs/tab_heatmap.py` (1).

- **Rankings tab empty during off-hours (`f592850`):**
  - Rankings tab was empty because it only sourced from `SpikeDetector.events` (empty outside market hours).
  - Added feed items as a fallback data source so Rankings populates whenever there is feed data.

- **Sector performance chart styling (`b32de5f`):**
  - Restored original vertical bar chart with red-yellow-green gradient (`#FF1744`, `#FFC107`, `#00C853`), dark background, and angled labels — matching the pre-refactor appearance.

### Changed (2026-03-02 – 2026-03-02)

- **API budget optimization (`fc477c6`):**
  - Removed 10 low-value tabs (~1,500 lines of UI code) to reduce API call volume and rendering overhead.
  - Poll interval changed from 5s → 10s during market hours.
  - Added 30-second periodic dedup reset to prevent feed staleness from accumulating duplicate filters.
  - Slowed Bitcoin-related TTLs to reduce FMP bandwidth consumption.
  - Refactored Rankings tab to use only feed + RT spike data (removed extra API calls).
  - Removed 7 orphaned cached functions that were no longer called after tab removal.
  - Added Sector Performance chart above the tab bar.
  - Created `docs/API_BUDGET_CALCULATIONS.md` with detailed FMP budget analysis (150 GB/30d bandwidth, 3,000 calls/min rate limit).

- **Feed staleness bypass fix (`6d9732e`):**
  - `notify_ingest()` now only fires when the feed actually grows, preventing false staleness resets.

### Verification (2026-02-26, later run)

- Full regression suite (local): **1116 passed, 34 subtests passed**.
- Linting (`ruff`): **All checks passed**.
- Type-checking (`mypy`): **Success, no issues found**.
- Core Python coverage (`newsstack_fmp`, `terminal_poller`, `terminal_export`): **83%**.

### Added

- **ChoCH fast-mode parity in Strategy (v6.3.13 line):**
  - Added Strategy-side ChoCH runtime controls to match Indicator behavior:
    - `ChoCH signal mode` (`Ping (Fast)`, `Verify (Safer)`, `Ping+Verify`),
    - `Show ChoCH Ping markers`.
  - Added Strategy ChoCH presets:
    - `ChoCH Scalp Fast preset` (forces `Wick` + `Ping (Fast)` + effective `swingR=max(swingR,1)`),
    - `ChoCH Fast+Safer preset` (forces `Wick` + `Ping+Verify` + effective `swingR=max(swingR,1)`).
  - Strategy eval HUD now appends active ChoCH runtime configuration (`preset/mode/source/R`) for on-chart verification.

- **Runtime Success-Rate HUD + Eval mode guidance (indicator + strategy):**
  - Added a lightweight last-bar chart label showing live evaluation success rate and sample count:
    - `Success rate (History+Live): xx% (N=yy)` or
    - `Success rate (LiveOnly): xx% (N=yy)`
  - Added explicit `Evaluation mode` tooltip guidance with practical examples:
    - `History+Live` shows immediate populated values from confirmed history,
    - `LiveOnly` starts at `0% (N=0)` on historical bars and grows only in realtime.

- **Configurable BUY re-entry timing after COVER (indicator + strategy):**
  - Added `allowSameBarBuyAfterCover` (default `false`) to both scripts.
  - `false` keeps legacy one-bar delay after a `COVER` before the next `BUY`.
  - `true` allows immediate same-bar `COVER → BUY` re-entry.

- **Configurable SHORT re-entry timing after EXIT (strategy):**
  - Added `allowSameBarShortAfterExit` (default `false`) to strategy.
  - `false` keeps legacy one-bar delay after an `EXIT` before the next `SHORT`.
  - `true` allows immediate same-bar `EXIT → SHORT` re-entry.

- **Same-bar reversal mapping correction (indicator + strategy):**
  - Corrected cross-directional pairing to match runtime exit semantics:
    - `BUY` same-bar control is now `COVER → BUY` (`allowSameBarBuyAfterCover`),
    - `SHORT` same-bar control is now `EXIT → SHORT` (`allowSameBarShortAfterExit`).
  - Rewired phase-2 guards accordingly (`didCover` for BUY, `didExit` for SHORT).
  - Added regression tests to lock this mapping and prevent future inversion.

- **USI Length 5 lower-bound update (indicator + strategy):**
  - `Length 5 (fastest / Red)` now supports `minval=1` (previously `2`) in both scripts.
  - This allows a more aggressive fast-line configuration for USI Quantum Pulse tuning.

- **USI Aggressive Entry Mode guidance (indicator + strategy):**
  - Compact fast-scalping preset recommendation:
    - `USI Aggressive: same-bar verify = ON`
    - `USI Aggressive: verify 1-of-3 = ON`
    - `USI Aggressive: tight-spread votes = ON` (optional)
    - `Hardened Hold (L5 > L4) = OFF`

- **Scalp Early entry behavior profile (indicator + strategy):**
  - Added `Scalp Early (v6.3.12-fast)` to `Entry behavior profile`.
  - Keeps v6.3.12 structure but biases for earlier entries via:
    - slightly lower score thresholds,
    - slightly lower directional/score probability thresholds,
    - lower ChoCH probability threshold,
    - disabled score confidence hard-gate.

- **Cooldown trigger mode `EntriesOnly` (indicator + strategy):**
  - Added new `cooldownTriggers` option `EntriesOnly` in both scripts.
  - `EntriesOnly` updates cooldown timestamps only on entry signals (`BUY`/`SHORT`).
  - In `EntriesOnly` with `cooldownBars >= 1`, exits are hold-gated by entry bar index to enforce one full bar after entry before `EXIT`/`COVER` can fire.
  - Exception update: `EXIT SL` and `COVER` bypass this hold and may fire immediately after entry.
  - Existing modes remain unchanged:
    - `ExitsOnly` updates on `EXIT`/`COVER`.
    - `AllSignals` updates on all signals.

- **Global directional probability floors (indicator + strategy):**
  - Added `Enforce score min pU/pD on all entries` (default `true`).
  - When enabled, `Score min pU (Long)` / `Score min pD (Short)` are enforced as hard floors across BUY/SHORT entry paths.
  - `REV-BUY` is exempt and keeps its dedicated reversal probability gates (`revMinProb` + reversal/open-window logic).
  - Added `Global floor: bypass in open window` (default `true`) to optionally preserve open-window entry behavior.

- **Dedicated REV alert conditions (indicator + strategy):**
  - Added standalone `REV-BUY` and `REV-SHORT` alert conditions.
  - Consolidated runtime alert text now prioritizes `REV-BUY`/`REV-SHORT` labels over generic `BUY`/`SHORT` when reversal entries fire.

- **Dedicated consolidation alert condition (indicator + strategy):**
  - Added standalone `CONSOLIDATION` alert condition.
  - Trigger is phase-entry based (`sidewaysVisual and not sidewaysVisual[1]`) to avoid repeated alerts on every consolidation bar.

- **Sideways visual hysteresis parity (strategy):**
  - Strategy now uses the same visual consolidation hysteresis model as indicator (`sideEnter`/`sideExit` + latched `sidewaysVisual`).
  - This aligns consolidation alert timing semantics across both scripts without changing engine-side entry gating.

- **Consolidation dot color refinement (indicator):**
  - Consolidation dots are now **reddish** when USI is short (`usiStackDir == -1`).
  - All other consolidation states remain **orange**.

- **Directional consolidation entry veto (indicator + strategy):**
  - `BUY` is blocked during bearish/reddish consolidation.
  - `SHORT` is blocked during bullish/orange consolidation.
  - Veto applies to entries only; exits keep normal behavior.

- **Directional consolidation entry veto removed (indicator + strategy):**
  - Consolidation dot color/state is now informational only.
  - `BUY`/`SHORT` are no longer directly blocked by bearish/bullish consolidation dot state.

- **Intrabar alerts/labels default enabled (indicator + strategy):**
  - `Alerts: bar close only` now defaults to `false`.
  - Runtime alert/label flow is intrabar-first by default for BUY/SHORT/EXIT/COVER and PRE-BUY/PRE-SHORT.
  - Close-confirmed-only behavior remains available by setting `Alerts: bar close only = true`.

- **v6.3.13 parity hardening (indicator + strategy):**
  - restored strict entry gating parity in Strategy (`reliabilityOk`, `evidenceOk`, `evalOk`, `abstainGate/decisionFinal`) while preserving session filtering,
  - added full Strategy-side dynamic TP/SL runtime profile support:
    - Dynamic TP expansion (`useDynamicTpExpansion`, `dynamicTpKickInR`, `dynamicTpAddATRPerR`, `dynamicTpMaxAddATR`, trend/conf gates),
    - Dynamic SL profile (`useDynamicSlProfile`, widen/tighten phases, trend/conf gates),
    - preset-driven effective dynamic TP mapping (`Manual/Conservative/Balanced/Runner/Super Runner`) aligned with indicator.
- **Structure tag wiring completed:**
  - Strategy now renders BOS/ChoCH structure tags (not only entry/exit labels),
  - Indicator now renders BOS tags alongside existing ChoCH tags.
- **ChoCH volume requirement wired:**
  - `chochReqVol` now actively gates ChoCH-triggered entries in both scripts.

### Verification

- Targeted strict-related suites (local, 2026-02-16): **152 passed, 8 subtests passed**.
- Full regression suite (local, 2026-02-16): **390 passed, 16 subtests passed**.

- **Entry behavior profile toggle (legacy timing fallback):** added `entryBehaviorProfile` in indicator + strategy under **Score Engine (Option C)**:
  - `Current (v6.3.12)` keeps stricter score gating/chop veto behavior.
  - `Legacy (v6.3.9-like)` relaxes entry strictness for earlier signal timing by:
    - disabling score probability and confidence hard-gates,
    - disabling score directional-context hard requirement,
    - disabling hard chop veto in final score merge,
    - disabling Regime Classifier 2 auto-tightening,
    - slightly loosening ChoCH probability threshold.

  ### Changed

  - **Fallback activated by default:** `entryBehaviorProfile` now defaults to `Legacy (v6.3.9-like)` in both indicator and strategy for immediate v6.3.9-like signal timing behavior out of the box.

---

## Schema Versions

Canonical version pin: [`smc_core/schema_version.py::SCHEMA_VERSION`](smc_core/schema_version.py).
Versioning policy lives in [`docs/schema_versioning.md`](docs/schema_versioning.md);
the breaking-change gate runbook in
[`docs/release_process/breaking_change_gate_runbook.md`](docs/release_process/breaking_change_gate_runbook.md).

Bump rules (semver):

- **PATCH** (`x.y.Z`): internal-only changes (docs, comments, refactors) — no payload change.
- **MINOR** (`x.Y.z`): additive, backwards-compatible field additions — consumers can ignore new fields.
- **MAJOR** (`X.y.z`): breaking changes that require consumer updates. The
  governance gate (`scripts/smc_version_governance.py`) escalates **any**
  export field-count delta to MAJOR, including purely additive new fields.
  See `/memories/repo/schema-version-bump-must-be-major-on-field-count-change.md`.

| Version | Date | Commit | Bump | Notes |
|---|---|---|---|---|
| **3.0.0** | 2026-04-23 | `f7884602` (#23, fix #22) | MAJOR | Pine-library export field count 200 → 201 (`ZONE_CAL_TRUST` + `ZONE_CAL_CONFIDENCE` for Phase-H consumer maturity, ADR 2026-04-22, PR #19). Although additive, the governance gate rejected the prior MINOR bump as 2.1.0; this MAJOR bump is the canonical landing. Bulk-updated all `"schema_version": "2.1.0"` pins in tests / spec / pine fixtures. |
| ~~2.1.0~~ | ~~2026-04-23~~ | `9e46947c` (#18, **superseded**) | ~~MINOR~~ | Attempted MINOR bump for `ZONE_CAL_TRUST`. Rejected by governance gate — refresh-run #24807633995 skipped TV-publish + library-bump steps because field-count change requires MAJOR. Replaced by 3.0.0. |
| **2.0.0** | 2026-03-30 | `54f44acf` | MAJOR | SMC v5.5 Lean — all 9 Arbeitspakete delivered. First major payload restructuring under the consolidated `smc_core` layering. |
| 1.2.0 | 2026-03-27 | `65bb2238` | MINOR | Meta-enrichment (calendar risk, enriched news, regime bridge) — additive 35-test surface. |
| 1.1.0 | 2026-03-27 | `e49a51f5` | MINOR | Schema-versioning enforcement: consolidated to single source-of-truth, semver utilities + 18 enforcement tests. |
| **1.0.0** | 2026-03-26 | `0dff8eff` | MAJOR | Initial introduction of `smc_core/schema_version.py` with `SCHEMA_VERSION = "1.0.0"` (Phase-1 domain core + layering). |

---

## [v6.3.13] - 2026-02-16

### Added

- Strategy parity completion for dynamic runtime risk modules:
  - Dynamic TP expansion,
  - Dynamic SL profile (widen/tighten),
  - preset-aware effective dynamic TP mapping.
- Structure visualization parity updates:
  - BOS tags now rendered in indicator,
  - BOS/ChoCH structure tags now rendered in strategy.

### Changed

- Restored strict Strategy entry gating parity with indicator:
  - reliability/evidence/eval/abstain decision checks active again in `allowEntry`.
- Wired `chochReqVol` into ChoCH-triggered entry filtering in both scripts.
- Version sync: bumped visible script versions/titles to `v6.3.13`.

### Verification

- Full regression suite: **386 passed**.

## [v6.3.12] - 2026-02-15

### Added

- **RFC v6.4 Phase-3 quality tuning (regime hysteresis):** added state-stability controls for Regime Classifier 2.0 in both scripts:
  - `regimeMinHoldBars` (minimum hold duration before non-shock regime switches)
  - `regimeShockReleaseDelta` (VOL_SHOCK release threshold hysteresis)
  - latched regime logic via `rawRegime2State`, `regime2State`, `regime2HoldBars`
  - shock persistence rule keeps `VOL_SHOCK` active until ATR percentile cools below release threshold

### Changed

- **Version sync:** bumped visible script versions to `v6.3.12` in indicator and strategy headers/titles.
- **Tests:** added Phase-3 parity lock in `tests/test_score_engine_parity.py` (`test_phase3_regime_hysteresis_parity`).
- **Tests (behavioral):** added simulator snapshot coverage for Phase-3 hysteresis edge cases in `tests/test_functional_features.py` (`TestPhase3RegimeHysteresisBehavior`):
  - regime flapping damping via `regimeMinHoldBars`
  - VOL_SHOCK sticky release via `regimeShockReleaseDelta`

### Verification

- Full regression suite passes after integration: **384 passed**.

## [v6.3.11] - 2026-02-15

### Added

- **RFC v6.4 Phase-2 opt-in wiring (default-safe):** integrated the Phase-1 scaffold into active signal controls when explicitly enabled (`useRegimeClassifier2` + `regimeAutoPreset` + detected regime):
  - new effective tuning variables `cooldownBarsEff`, `chochMinProbEff`, `abstainOverrideConfEff`
  - regime-aware mapping for TREND/RANGE/CHOP/VOL_SHOCK under `regime2TuneOn`
  - trend core activation in signal layer via `trendReg = f_trend_regime(trendCoreFast, trendCoreSlow, atrNormHere)` and `trendStrength = f_trend_strength(trendCoreFast, trendCoreSlow)`
  - ChoCH gating updated to effective threshold (`chochMinProbEff`) in all relevant entry paths
  - abstain override uses effective threshold (`abstainOverrideConfEff`)

### Changed

- **Version sync:** bumped visible script versions to `v6.3.11` in indicator and strategy headers/titles.
- **Tests:**
  - added Phase-2 wiring parity coverage in `tests/test_score_engine_parity.py` (`test_phase2_optin_wiring_parity`)
  - aligned trend-regime presence checks to trend-core wiring in:
    - `tests/test_skippalgo_pine.py`
    - `tests/test_skippalgo_strategy.py`

### Verification

- Full regression suite passes after integration: **378 passed**.

## [v6.3.10] - 2026-02-15

### Added

- **RFC v6.4 Phase-1 scaffold (default-off):** added non-invasive foundation in both `SkippALGO.pine` and `SkippALGO_Strategy.pine`:
  - Zero-Lag Trend Core inputs (`useZeroLagTrendCore`, `trendCoreMode`, `zlTrendLenFast/Slow`, `zlTrendAggressiveness`, `zlTrendNoiseGuard`)
  - Regime Classifier 2.0 inputs (`useRegimeClassifier2`, `regimeLookback`, `regimeAtrShockPct`, `regimeAdxTrendMin`, `regimeHurstRangeMax`, `regimeChopBandMax`, `regimeAutoPreset`)
  - debug visibility toggle `showPhase1Debug` with hidden Data Window plots
  - helper functions `f_zl_trend_core` and `f_hurst_proxy`
  - derived diagnostic state variables (`trendCoreFast/Slow`, `trendCoreDiffNorm`, `regime2State`, `regime2Name`)

### Changed

- **Version sync:** bumped visible script versions to `v6.3.10` in indicator and strategy headers/titles.
- **Tests:** expanded parity/functional coverage for Phase-1 scaffold invariants:
  - `tests/test_score_engine_parity.py`
  - `tests/test_functional_features.py`
  - `tests/pine_sim.py` (Phase-1 config surface)

### Verification

- Full regression suite passes after integration: **377 passed**.

## [v6.3.9] - 2026-02-15

### Added

- **Functional behavior test matrix (new):** added simulator-driven feature coverage in `tests/test_functional_features.py` for:
  - gate functionality (`reliabilityOk`, `evidenceOk`, `evalOk`, `decisionFinal`),
  - open-window + strict-mode behavior,
  - engine scenarios (Hybrid/Breakout/Trend+Pullback/Loose),
  - risk/exit behavior,
  - reversal logic,
  - feature-flag matrix,
  - randomized invariants,
  - golden-master snapshots.
- **Label/display regression suite (new):** added `tests/test_label_display_regression.py` to lock label payload/style/color contracts and event→label family mapping (BUY/REV-BUY/SHORT/REV-SHORT/EXIT/COVER).
- **Functional test documentation:** added `docs/FUNCTIONAL_TEST_MATRIX.md` and linked it from `README.md`.

### Changed

- **CI guard hardened:** `.github/workflows/ci.yml` now includes explicit read permissions, concurrency cancel-in-progress, manual dispatch (`workflow_dispatch`), timeout guard, and strict pytest execution (`-q --maxfail=1`).
- **Version sync:** updated script headers/titles and docs references to `v6.3.9` for consistency.

### Verification

- Full regression suite passes after integration: **375 passed**.

### Changed

- **Entry presets (new):** added score presets in indicator + strategy via:
  - `entryPreset = Manual | Intraday | Swing`
  - `presetAutoCooldown` (default `false`)
  Presets now drive effective score variables (`*_Eff`) for thresholds, weights, and score probability floors.
- **Optional preset-driven cooldown:** when `presetAutoCooldown = true` and preset is not `Manual`, cooldown uses effective preset values:
  - mode: `Bars`
  - triggers: `ExitsOnly`
  - minutes: `15` (Intraday) / `45` (Swing)
  With `presetAutoCooldown = false` (default), cooldown remains fully user-input controlled.
- **Score integration mode adjusted (Option C):** restored hybrid signal merge so score can inject entries again while still respecting engine logic context.
- **Score directional context gate (new, default ON):** added `scoreRequireDirectionalContext` so score injection requires directional context:
  - BUY score injection needs bullish context (`trendUp`/USI bull state),
  - SHORT score injection needs bearish context (`trendDn`/USI bear state).
- **Dynamic TP expansion:** outward-only TP mode is active by default (default ON) in indicator + strategy:
  - `useDynamicTpExpansion`
  - `dynamicTpKickInR`, `dynamicTpAddATRPerR`, `dynamicTpMaxAddATR`
  - optional gates: `dynamicTpRequireTrend`, `dynamicTpRequireConf`, `dynamicTpMinConf`
  TP expands as unrealized $R$ grows and never tightens due to this module.
- **Dynamic SL profile (new, default ON):** added adaptive stop profiling in indicator + strategy:
  - optional early widening window (`dynamicSlWidenUntilR`, `dynamicSlMaxWidenATR`) to reduce noise stopouts,
  - progressive tightening phase (`dynamicSlTightenStartR`, `dynamicSlTightenATRPerR`, `dynamicSlMaxTightenATR`) as $R$ grows,
  - optional gates: `dynamicSlRequireTrend`, `dynamicSlRequireConf`, `dynamicSlMinConf`.
  Widening is disabled once BE was hit or trailing is active.
- **Score hard confidence gate (new):** added optional hard confidence floor for score entries in indicator + strategy:
  - `scoreUseConfGate`
  - `scoreMinConfLong`, `scoreMinConfShort`
  - integrated in final score entry decisions via effective vars (`*_Eff`) for preset parity.
  - **Current defaults:** `scoreUseConfGate = true`, `scoreMinConfLong = 0.50`, `scoreMinConfShort = 0.50`.

### Fixed

- **Chop penalty enforcement:** added explicit chop veto in final score merge path:
  - `chopVeto = isChop and (wChopPenalty < 0)`
  - final merge now blocks BUY/SHORT when chop veto is active.
- **Unified exit trigger (LONG + SHORT):** exit/cover now use one OR-union trigger in both scripts:
  - `riskExitHit (TP/SL/Trailing) OR usiExitHit OR engExitHit`
  - whichever condition fires first closes the position.
- **Cooldown semantics restored:** when `cooldownTriggers` is `ExitsOnly` or `AllSignals`, cooldown timestamps are updated on both EXIT and COVER events again (indicator + strategy parity).
- **Debug transparency:** score debug panel now prints chop veto status (`veto:0/1`) next to `chop` for faster root-cause diagnosis.
- **Debug blocker clarity:** score debug now shows explicit block reason (for example `BLOCK:IN_POSITION`) and prints last-signal age safely (`LS:...@n/a` instead of `NaN` when unavailable).
- **Debug context visibility:** score debug now prints directional context gate flags:
  - `ctxL:0/1` for long score-context pass/fail,
  - `ctxS:0/1` for short score-context pass/fail.
- **Token-budget hardening (Strategy):** reduced compile-token pressure by compacting debug payloads and removing Strategy table rendering (visual-only) while keeping signal/risk/entry-exit logic intact.
- **Parity:** same logic mirrored in both `SkippALGO.pine` and `SkippALGO_Strategy.pine`.

## [v6.3.8] - 2026-02-15

### Changed

- **USI Exit/Flip Touch Logic (Tier A Red vs Blue):** refined cross detection to treat visual touch/near-touch transitions as valid flip events, improving practical EXIT timing when Red approaches Blue from above.
- **USI Red De-lag Option (Option 2):** added optional Red-line source de-lag controls:
  - `useUsiZeroLagRed`
  - `usiZlAggressiveness`
  This is applied pre-RSI on Line5 for earlier flips with controllable aggressiveness.

### Fixed

- **Contra-state entries blocked (hard rule):** BUY is now vetoed when USI is bearish, and SHORT is vetoed when USI is bullish (when USI is enabled).
- **Parity hardening:** synchronized logic in both `SkippALGO.pine` and `SkippALGO_Strategy.pine`, including gate-timeframe (`f_usi_30m_calc_raw`) handling for the new Red-line de-lag path.

### Tests

- Extended parity checks in `tests/test_score_engine_parity.py` to verify:
  - presence of new USI Red de-lag inputs,
  - Red-line implementation parity,
  - hard USI state blocking in score decisions.

## [v6.3.7] - 2026-02-14

### Added

- **Exit control flexibility:** `useStrictEmaExit` added to allow relaxed trend exits (wait for full EMA trend flip when disabled), reducing deep-pullback shakeouts.

## [v6.3.4] - 2026-02-14

### Fixed

- **SkippALGO Strategy**: Synchronized fix for `plotchar()` scope (global scope with conditional logic) to resolve "Cannot use plotchar in local scope".
- **Maintenance**: Unified versioning across Indicator (v6.3.3 based) and Strategy.

## [v6.3.3] - 2026-02-14

### Fixed

- **SkippALGO Indicator**: Moved `plotchar()` debug calls from local scope (if-block) to global scope with conditional `debugUsiPulse and ...` logic to fix "Cannot use plotchar in local scope" errors.

## [v6.3.2] - 2026-02-14

### Fixed

- **SkippALGO Indicator**: Replaced `color.cyan` with `color.aqua` to resolve an undeclared identifier error (Pine v6 standard).

## [v6.3.1] - 2026-02-14

### Fixed

- **SkippALGO Indicator**: Removed duplicate/erroneous code block related to `qVerifyBuy` logic that caused a "Mismatched input bool" syntax error.
- **Maintenance**: Parity version bump for Strategy script (no functional changes in Strategy).

## [v6.3.0] - 2026-02-14

### Added (System Hardening)

- **Time-Based Cooldown**: `cooldownMode` input ("Bars" vs "Minutes") allows proper HTF trade management without multi-hour lockouts.
- **Explicit Triggers**: `cooldownTriggers` input ("ExitsOnly" vs "AllSignals") strictly defines what resets the timer. "ExitsOnly" (default) ensures fast add-on entries are possible.

### Changed (Optimization)

- **QuickALGO Logic**: Switched from restrictive "Hard-AND" momentum check to "Score+Verify" weighted approach.
- **QuickALGO MTF Fix**: Added `lookahead=barmerge.lookahead_off` to prevent repainting.
- **Cleanup**: Removed legacy "Deep Upgrade" branding from script headers.

## [2026-02-12]

### Added (Signals & Volatility)

- New input: `REV: Min dir prob` (`revMinProb`, default `0.50`) for the normal REV entry probability path.

### Changed (Parity)

- Stabilized script titles to preserve TradingView input settings across updates:
  - `indicator("SkippALGO", ...)`
  - `strategy("SkippALGO Strategy", ...)`
- Consolidated runtime alert dispatch to one `alert()` call per bar per symbol, reducing watchlist alert-rate pressure and TradingView throttling risk.
- EXIT/COVER label text layout split into shorter multi-line rows for better chart readability.
- Open-window directional probability (`pU`/`pD`) bypass behavior applies during configured market-open windows as implemented in current logic.

### Clarified

- `Rescue Mode: Min Probability` (`rescueMinProb`) controls only the rescue fallback path (requires volume + impulse), while `revMinProb` controls the normal REV path.

### Fixed

- Corrected Strategy-side forecast gate indentation/structure parity so open-window bypass behavior is consistently applied.

### Added

- Optional **3-candle engulfing filter** (default OFF) in both `SkippALGO.pine` and `SkippALGO_Strategy.pine`:
  - Long entries require bullish engulfing after 3 bearish candles.
  - Short entries require bearish engulfing after 3 bullish candles.
  - Optional body-dominance condition (`body > previous body`).
  - Optional engulfing bar coloring (bullish yellow / bearish white).
- Optional **ATR volatility context layer** (default OFF) in both scripts:
  - Regime overlay and label: `COMPRESSION`, `EXPANSION`, `HIGH VOL`, `EXHAUSTION`.
  - ATR ratio to configurable baseline (`SMA`/`EMA`).
  - Optional ATR percentile context (`0..100`) with configurable lookback.

### Changed

- Maintained strict **Indicator ⇄ Strategy parity** for new signal/context features to avoid behavior drift between visual and strategy paths.

---

## Notes

- This changelog tracks user-facing behavior and operational reliability updates.
- Historical items before this file was introduced may still be referenced in commit history and docs.
