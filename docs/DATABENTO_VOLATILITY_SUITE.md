# Databento Volatility Suite

## Purpose

The Databento Volatility Suite is a separate workflow inside this repository for pre-open, open-window, and watchlist-oriented US equity analysis.

It is designed to:

- build a broad US equity universe without depending on a narrow paid screener path,
- fetch daily and 1-second Databento bars for the supported universe,
- compute full-universe symbol-day features,
- derive premarket and open-window signals for ranking,
- generate a Long-Dip watchlist with laddered entry and exit levels,
- optionally convert the watchlist into IBKR dry-run previews or live orders.

This is research and workflow support infrastructure. It is not an always-on autonomous trading system by default.

## Main Components

### Core engine

`databento_volatility_screener.py` contains the main screening logic:

- Databento dataset selection and client creation
- symbol normalization and unsupported-symbol handling
- cache path generation and Parquet cache IO
- timezone-aware window construction
- daily bar loading
- intraday 1-second aggregation
- full-universe feature construction
- export workbook and manifest helpers
- standalone Streamlit UI logic via `run_streamlit_app()`

### Streamlit UI

`streamlit_databento_volatility_screener.py` is the thin launcher for the dedicated Databento Streamlit application.

Run it with:

```bash
streamlit run streamlit_databento_volatility_screener.py
```

The UI is intended as a single place for:

- freshness checks,
- production export refresh,
- watchlist generation,
- top-N review,
- per-entry detail inspection.

### Production export pipeline

`scripts/databento_production_export.py` is the main materialization pipeline.

It performs the end-to-end batch workflow:

1. discover recent trading days for the selected Databento dataset,
2. build the raw US equity universe,
3. enrich that universe with optional FMP fundamentals,
4. probe and filter unsupported Databento symbols,
5. load Databento daily bars,
6. compute intraday open-window metrics,
7. generate full-universe feature tables,
8. export Parquet tables, manifest JSON, and Excel workbook,
9. write exact-named Parquet files for downstream consumers.

Run it with:

```bash
python scripts/databento_production_export.py
```

Required environment:

- `DATABENTO_API_KEY`

Optional environment:

- `FMP_API_KEY`
- `DATABENTO_DATASET`
- `DATABENTO_TOP_FRACTION`

### Bundle loader

`scripts/load_databento_export_bundle.py` loads a manifest-backed export bundle and prints a summary plus table previews.

Typical usage:

```bash
python scripts/load_databento_export_bundle.py ~/Downloads --head 3
python scripts/load_databento_export_bundle.py ~/Downloads/databento_volatility_production_20260307_114724_manifest.json
```

The script accepts:

- a manifest path,
- an export directory containing one or more `*_manifest.json` files,
- or a bundle basename without the `_manifest.json` suffix.

### Watchlist generation

`scripts/generate_databento_watchlist.py` consumes the exported feature bundle and applies the Long-Dip strategy configuration.

It can load either:

- exact-named Parquet files from an export directory, or
- the latest manifest-backed bundle as a fallback when the exact-named files are missing or unreadable.

Typical usage:

```bash
python scripts/generate_databento_watchlist.py --export-dir ~/Downloads
python scripts/generate_databento_watchlist.py --bundle ~/Downloads --top-n 5
```

Key parameters include:

- `--top-n`
- `--min-gap-pct`
- `--max-gap-pct`
- `--min-previous-close`
- `--min-premarket-volume`
- `--min-premarket-trade-count`
- `--output-csv`
- `--output-md`

Outputs usually include:

- a CSV watchlist,
- a Markdown report,
- configuration and source metadata embedded in the result payload when used programmatically.

### IBKR execution bridge

`scripts/execute_ibkr_watchlist.py` translates the watchlist into IBKR order intents.

It supports:

- dry-run JSON previews,
- connection checks,
- optional live order placement,
- scheduled cancellation of unfilled entries,
- scheduled flattening via time-stop,
- reconnect attempts on connection-related failures.

Typical dry-run usage:

```bash
python scripts/execute_ibkr_watchlist.py \
  --watchlist-csv reports/databento_watchlist_top5_pre1530.csv \
  --output-json reports/ibkr_watchlist_preview.json
```

Generate watchlist from a bundle on the fly:

```bash
python scripts/execute_ibkr_watchlist.py \
  --bundle ~/Downloads \
  --watchlist-top-n 5 \
  --output-json reports/ibkr_watchlist_preview.json
```

Live placement is opt-in only:

```bash
python scripts/execute_ibkr_watchlist.py \
  --watchlist-csv reports/databento_watchlist_top5_pre1530.csv \
  --place-orders
```

Important CLI controls:

- `--check-connection`
- `--host`
- `--port`
- `--client-id`
- `--account`
- `--outside-rth`
- `--tif`
- `--exit-mode`
- `--cancel-unfilled-after`
- `--time-stop-after`
- `--clock-timezone`
- `--symbols`
- `--trade-date`

## End-to-End Workflow

### 1. Install dependencies

The relevant dependencies already listed in `requirements.txt` are:

- `databento`
- `streamlit`
- `python-dotenv`
- `openpyxl`
- `pyarrow`
- `ib_insync`

Install with:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure credentials

At minimum:

```bash
export DATABENTO_API_KEY=...
```

Optional:

```bash
export FMP_API_KEY=...
export DATABENTO_DATASET=DBEQ.BASIC
export DATABENTO_TOP_FRACTION=0.20
```

For the Streamlit apps and scripts in this repository, `.env` loading is also supported.

### 3. Run a quick smoke test

Use the lightweight script before a full export run:

```bash
python scripts/databento_smoke_test.py
```

This exercises:

- trading day discovery,
- universe construction,
- Databento support filtering,
- daily bar fetch,
- intraday screening,
- summary ranking,
- detail fetch for the top row.

### 4. Materialize a production bundle

```bash
python scripts/databento_production_export.py
```

By default this uses:

- the best accessible Databento dataset from the preferred list,
- `Europe/Berlin` as the display timezone,
- an ET-relative screening window when no explicit window is passed,
- exact-named downstream Parquet exports in the export directory.

### 5. Inspect the bundle

```bash
python scripts/load_databento_export_bundle.py ~/Downloads --head 5
```

Use this to verify:

- manifest metadata,
- table presence,
- row counts,
- expected column shapes.

### 6. Build the watchlist

```bash
python scripts/generate_databento_watchlist.py --export-dir ~/Downloads
```

This yields ranked symbols and three ladder levels per symbol-day.

### 7. Review in Streamlit

```bash
streamlit run streamlit_databento_volatility_screener.py
```

The standalone UI can:

- refresh the production data basis,
- generate the watchlist from latest exports,
- show a filter funnel when no symbols survive the rules,
- display detailed per-entry strategy fields.

### 8. Produce an execution preview or place orders

Dry run first:

```bash
python scripts/execute_ibkr_watchlist.py \
  --watchlist-csv reports/databento_watchlist_top5_pre1530.csv \
  --output-json reports/ibkr_watchlist_preview.json
```

Move to live placement only after validating the preview, TWS connectivity, account routing, and schedule settings.

## Universe and Data Source Model

### Universe discovery

The suite does not default to the constrained FMP company screener for broad runs.

Instead, `fetch_us_equity_universe()` prefers the official Nasdaq Trader symbol directories for US listed issues and only uses the FMP screener path when:

- `min_market_cap` is explicitly requested, or
- the Nasdaq Trader directory fetch fails and FMP is available.

This makes the default universe much broader and less dependent on paid screening limits.

### Symbol normalization

Databento-specific symbol normalization is applied centrally. Examples:

- `BRK-A -> BRK.A`
- `BRK-B -> BRK.B`
- `BF-B -> BF.B`
- `MKC-V -> MKC.V`
- `MOG-A -> MOG.A`

Known unsupported symbols for the active account or dataset can be dropped before repeated fetch attempts. The current code explicitly excludes `CTA-PA`.

### Support preflight

`filter_supported_universe_for_databento()` performs a dataset-specific symbol support probe and caches the result.

Support-cache characteristics:

- category: `symbol_support`
- cache root: `artifacts/databento_volatility_cache`
- TTL: 7 days
- purpose: avoid repeated unresolved-symbol warnings and wasted requests

## Timezone and Window Semantics

The suite is explicit about timezone handling.

- Market anchor timezone: `America/New_York`
- Default display timezone: `Europe/Berlin`
- Window computation is ET-relative and then converted to display timezone for UI and output fields.

Important defaults:

- intraday pre-open offset: 10 minutes before regular open
- intraday post-open window: 30 minutes after regular open
- open-window detail pre-open offset: 1 minute before regular open
- open-window detail end: 5 minutes and 59 seconds after regular open
- premarket anchor: `08:00:00 ET`

The production export manifest documents the effective window and formulas used during the run.

## Export Artifacts

### Bundle outputs

The export pipeline writes a manifest-backed bundle with a basename like:

```text
databento_volatility_production_YYYYMMDD_HHMMSS
```

Associated files include:

- `..._manifest.json`
- `...xlsx`
- `...__summary.parquet`
- `...__daily_bars.parquet`
- `...__intraday.parquet`
- `...__daily_symbol_features_full_universe.parquet`
- `...__premarket_features_full_universe.parquet`
- `...__full_universe_second_detail_open.parquet`
- `...__symbol_day_diagnostics.parquet`

### Exact-named downstream files

For stable downstream consumers, the export pipeline also writes:

- `daily_symbol_features_full_universe.parquet`
- `premarket_features_full_universe.parquet`
- `full_universe_second_detail_open.parquet`
- `symbol_day_diagnostics.parquet`

These exact-named files are what the watchlist and UI layer prefer first.

### Manifest content

The manifest records:

- dataset and lookback settings,
- display timezone,
- window start/end,
- premarket anchor,
- fetch timestamps,
- covered trade dates,
- formulas for the main derived fields,
- output row counts,
- unsupported symbols,
- diagnostic output checks.

## Key Feature Tables

### `daily_symbol_features_full_universe`

This is the main symbol-day feature table for downstream filtering and ranking.

It includes:

- market structure columns such as `window_start_price`, `window_high`, `window_low`, `window_end_price`
- volatility metrics such as `window_range_pct`, `window_return_pct`, `realized_vol_pct`
- reference and fundamentals coverage flags
- selection columns such as `rank_within_trade_date`, `selected_top20pct`
- open volume metrics and rolling relative-volume features

### `premarket_features_full_universe`

This table is tailored to pre-open filtering. It includes:

- `has_premarket_data`
- `premarket_last`
- `premarket_volume`
- `premarket_trade_count`
- `prev_close_to_premarket_pct`
- `premarket_to_open_pct`

### `full_universe_second_detail_open`

This is the 1-second open-window detail table used to derive open-window and premarket features.

It spans from the premarket anchor through the configured open-window end and labels each bar as:

- `premarket` before `09:30 ET`
- `regular` from `09:30 ET` onward

### `symbol_day_diagnostics`

This table explains why a symbol-day was excluded or not selected. It is the main debugging surface when expected names disappear from the final watchlist.

## Long-Dip Watchlist Logic

The watchlist strategy defaults live in `strategy_config.py`.

Important defaults:

- minimum gap: `5.0%`
- maximum gap: `40.0%`
- minimum previous close: `$2.00`
- minimum premarket volume: `50,000`
- minimum premarket trade count: `200`
- position budget: `$10,000`
- top N: `5`
- ladder percentages: `(-0.004, -0.009, -0.017)`
- ladder weights: `(0.25, 0.35, 0.40)`
- first take profit: `1.5%`
- hard stop: `1.6%`
- trailing stop distance: `1.0%`

The generated watchlist includes:

- ranked symbol-day candidates,
- L1/L2/L3 buy levels,
- take-profit levels,
- stop-loss levels,
- trailing-stop anchor prices,
- position sizing derived from the configured budget.

## IBKR Notes

The IBKR bridge is intentionally conservative by default.

- default mode is dry run,
- live order placement requires `--place-orders`,
- order timing logic is timezone-aware,
- reconnect attempts are built in for connection-related failures,
- cancellation and flattening schedules are explicit CLI options.

Recommended practice:

1. Run a production export.
2. Generate a watchlist.
3. Generate a dry-run JSON preview.
4. Validate symbols, quantities, ladder prices, and schedule times.
5. Only then enable `--place-orders`.

## Integration With the Rest of the Repository

The Databento work is not isolated from the rest of the codebase.

- `terminal_databento.py` provides Databento quote helpers for the main terminal and Open-Prep monitor.
- `streamlit_terminal.py` and `open_prep/streamlit_monitor.py` can consume Databento-backed price enrichment via those helpers.
- `strategy_config.py` centralizes the Long-Dip defaults shared by watchlist generation, Streamlit UI, and execution flows.

## Testing

The main regression coverage is in:

- `tests/test_databento_volatility_screener.py`
- `tests/test_generate_databento_watchlist.py`
- `tests/test_execute_ibkr_watchlist.py`

Run the targeted suite with:

```bash
python -m pytest tests/test_databento_volatility_screener.py -q
python -m pytest tests/test_generate_databento_watchlist.py -q
python -m pytest tests/test_execute_ibkr_watchlist.py -q
```

## Operational Notes

- Generated Parquet and Excel files are expected outputs of the workflow, not incidental temp files.
- Cache files under `artifacts/databento_volatility_cache` improve repeat-run performance and preserve symbol-support probe results.
- The watchlist layer is intentionally resilient to missing or corrupt exact-named Parquet files by falling back to the latest manifest-backed bundle.
- The manifest is the source of truth for what a given export actually contained and how it was computed.

## Recommended Daily Routine

```bash
# 1. Refresh the data basis
python scripts/databento_production_export.py

# 2. Review the bundle quickly
python scripts/load_databento_export_bundle.py ~/Downloads --head 3

# 3. Build the watchlist
python scripts/generate_databento_watchlist.py --export-dir ~/Downloads

# 4. Review or operate from the Streamlit app
streamlit run streamlit_databento_volatility_screener.py

# 5. Produce an IBKR preview
python scripts/execute_ibkr_watchlist.py \
  --watchlist-csv reports/databento_watchlist_top5_pre1530.csv \
  --output-json reports/ibkr_watchlist_preview.json
```

This keeps the workflow deterministic: export first, watchlist second, execution preview third.