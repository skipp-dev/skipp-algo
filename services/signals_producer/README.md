# smc-signals-producer

The 24/7 realtime signal engine (`python -m open_prep.realtime_signals`) deployed
on Railway. Two instances are declared in `railway.toml`:

- `smc-signals-producer` — production.
- `smc-signals-producer-databento-shadow` — shadow instance used to soak the
  Databento quote path in a real deploy environment before cutover.

Build contract: `Dockerfile` (build context = repo root; clear the Railway
"Root Directory" setting), deploy contract: `railway.toml` (startCommand,
`/readyz` healthcheck, watchPatterns). Both are pinned by
`tests/test_signals_producer_service_contract.py`, including a runtime
import-closure probe that rebuilds the image's module surface from the
Dockerfile `COPY` statements and imports the engine inside it (regression
guard for the `scripts.smc_atomic_write` ModuleNotFoundError class, #4148).

## Environment contract (Railway dashboard)

`railway.toml` carries no variables — Railway service variables live in the
dashboard per service and are **not statically provable from the repo**. This
section is the repo-side contract; `test_readme_documents_deploy_critical_env_vars`
keeps it from silently rotting. When flipping quote-source flags, verify the
variables below in the Railway dashboard for BOTH instances.

### Deploy-critical

| Variable | Read at | Behavior |
|----------|---------|----------|
| `DATABENTO_API_KEY` | `open_prep/realtime_signals.py` (`_build_databento_quote_source`) | Required for the default quote path. Missing/empty raises `RuntimeError`, which `_default_quote_source` catches: the engine logs a WARNING and runs on the FMP fallback with `_quote_source_fallback_reason` telemetry — prod silently loses the Databento path, so treat the alert (#4170) as actionable. |
| `FMP_API_KEY` | `newsstack_fmp/config.py`, `open_prep/macro.py` | News/macro pipeline and the FMP quote fallback. |
| `SIGNALS_INTERNAL_TOKEN` | `open_prep/realtime_signals.py` | Bearer token required by `/signals` and `/metrics` in hosted environments. |
| `RT_QUOTE_SOURCE` | `open_prep/realtime_signals.py` (`_selected_quote_source`) | `databento` (default) or `fmp` (explicit rollback). |

### Snapshot inputs (defaults point at this repo's `bot/live-open-prep-snapshot` branch)

| Variable | Purpose |
|----------|---------|
| `OPEN_PREP_SNAPSHOT_URL` | Watchlist snapshot (`latest_open_prep_run.json`). Present-but-empty keeps local/offline operation possible. |
| `QUOTE_REFERENCE_SNAPSHOT_URL` | Databento-path `quote_reference.json` (prev_close/ADV), produced by `run-open-prep-daily.yml`'s publish step. Fetch failures keep the last-good local copy. |
| `OPEN_PREP_SNAPSHOT_URL_TOKEN` | Auth for the snapshot URLs. For GitHub Contents-API URLs only, falls back to `GITHUB_WORKFLOW_MONITOR_TOKEN` → `GH_PAT` → `GITHUB_TOKEN`; generic credentials are never forwarded to custom URLs. |

### Tuning (optional, engine defaults apply)

`PORT` (telemetry port, Railway-injected), `TELEMETRY_BIND_HOST`,
`RT_POLL_INTERVAL_SECS`, `RT_TOP_N`, `RT_NEAR_A0_REPOLL_SECS`,
`RT_EXTENDED_SHADOW_ENABLED`, `RT_A0_PARITY_LOG_DIR`,
`RT_CALIBRATION_UTC_HHMM`, `RT_SIGNAL_EVENT_LOG_DIR`, `LOG_LEVEL`,
`OPENAI_API_KEY` (optional judge features).

`RT_CALIBRATION_UTC_HHMM` is a UTC wall-clock `HH:MM` (e.g. `21:30` ≈ 17:30 ET)
and sets when the in-process nightly follow-through calibration runs. A value
that is not a valid time leaves calibration OFF and logs a warning saying so —
check for `nightly calibration stays OFF` after changing it.

## Local smoke

`bash services/signals_producer/e2e/smoke.sh` boots the engine with shadowed
secrets and drives the telemetry surface. Note it runs against the full repo
checkout on `sys.path` — the image's restricted module surface is what the
import-closure test in `tests/test_signals_producer_service_contract.py`
covers.
