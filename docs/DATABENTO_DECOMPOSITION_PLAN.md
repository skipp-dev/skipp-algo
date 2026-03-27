# Databento Monolith Decomposition Plan

Status: **Tranche 1 complete** — provider protocol + first utility extraction.

## Completed — Tranche 1

| Deliverable | File |
|---|---|
| Provider protocol (`MarketDataProvider`) | `databento_provider.py` |
| `DabentoProvider` (delegates to monolith internals) | `databento_provider.py` |
| `DegradedProvider` (offline / test fallback) | `databento_provider.py` |
| Utility extraction (cache, symbols, TZ, frames, warnings, datasets) | `databento_utils.py` |
| First consumer refactored (`collect_full_universe_session_minute_detail`) | `scripts/smc_microstructure_base_runtime.py` |
| Tests (54 unit tests: protocol, implementations, utilities, injection) | `tests/test_databento_provider.py` |

### Design decisions

- **Temporary duplication**: Extracted functions are copied into `databento_utils.py`;
  originals remain in `databento_volatility_screener.py` so other consumers
  (`databento_production_export.py`, `databento_preopen_fast.py`,
  `terminal_databento.py`, `databento_smoke_test.py`) continue working unchanged.
- **Provider lazy-imports**: `DabentoProvider` imports monolith internals at call
  time to avoid circular imports and keep the protocol module lightweight.

---

## Tranche 2 — Deduplicate & shim

Remove duplicate definitions from the monolith and replace them with re-exports:

```python
# databento_volatility_screener.py — after tranche 2
from databento_utils import build_cache_path, normalize_symbol_for_databento, ...
```

This keeps all existing `from databento_volatility_screener import X` statements
working while the canonical source moves to `databento_utils.py`.

Scope: ~25 functions/constants. Zero behavior change.

---

## Tranche 3 — Migrate `databento_production_export.py`

- Replace its monolith imports with `databento_utils` + `databento_provider`.
- Add `provider: MarketDataProvider | None = None` parameter to its main
  orchestrator function.
- Add tests for provider injection in export path.

Consumer imports (~20 symbols):
`_make_databento_client`, `_databento_get_range_with_retry`,
`_get_schema_available_end`, `build_cache_path`, `normalize_symbol_for_databento`,
`_normalize_symbols`, `_iter_symbol_batches`, `_coerce_timestamp_frame`,
`_store_to_frame`, `_validate_frame_columns`, `_clamp_request_end`,
`_exclusive_ohlcv_1s_end`, `_redact_sensitive_error_text`,
`_warn_with_redacted_exception`, `choose_default_dataset`,
`US_EASTERN_TZ`, `PREFERRED_DATABENTO_DATASETS`, plus several feature-engineering
helpers not yet extracted.

---

## Tranche 4 — Migrate `databento_preopen_fast.py`

Same pattern as tranche 3. This consumer uses ~14 monolith symbols.

---

## Tranche 5 — Extract remaining utilities

Functions still in the monolith that are pure logic (no SDK dependency):

| Category | Examples |
|---|---|
| Universe / watchlist | `load_universe_symbols`, `get_sp500_symbols`, `_build_watchlist_frame` |
| Feature engineering | `_compute_atr`, `_compute_rsi`, `_compute_vwap`, `_compute_volume_profile`, `_score_microstructure_quality` |
| Window definitions | `_session_windows`, `_preopen_window`, `_regular_hours_window` |
| Export formatting | `_format_pine_library_line`, `_format_csv_export_row` |

Target: new module `databento_features.py` for feature engineering,
enrich `databento_utils.py` for window/export helpers.

---

## Tranche 6 — Extract Streamlit UI

The monolith contains ~800 lines of Streamlit rendering code interleaved with
data logic. Extract into a dedicated UI module that imports from the provider
and utilities layers.

---

## Principles

1. **No mega-rewrite** — one consumer path per tranche.
2. **No behavior changes** unless required for safer degradation.
3. **Preserve current outputs** — diff-test before and after each tranche.
4. **Small reviewable commits** — each tranche is one commit.
5. **Re-export shims** maintain backward compatibility during transition.
