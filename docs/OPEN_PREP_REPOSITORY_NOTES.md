# Open Prep Repository Notes

## Purpose

This repository snapshot contains the `open_prep` workflow and related tests used to generate a macro-aware US open preparation output.

## Included Components

- `open_prep/run_open_prep.py` — CLI entrypoint and event/time filtering
- `open_prep/macro.py` — FMP API client, US event filters, macro bias scoring
- `open_prep/screen.py` — candidate ranking logic
- `open_prep/ai.py` — deterministic trade-card generation
- `scripts/export_open_prep_reports.py` — timestamped HTML/XLS report export
- `tests/test_open_prep.py` — regression tests for parsing, event logic, API-path assumptions

## Recent Hardening Highlights

- Switched quote batch fetch to `"/stable/batch-quote"`
- Hardened macro event time parsing (`HH:MM`, `HH:MM:SS`, validation)
- Added robust JSON error handling in API client
- Improved deterministic sorting/tie handling in ranking flow
- Added ATR-based trail-stop profiles in trade cards (`tight`, `balanced`, `wide`)
- Added concrete ATR stop price levels using `entry_price`/`vwap`/`price` as stop reference
- Expanded regression test coverage for open-prep behavior

## Reporting Exports

Generate versioned report files (UTC timestamp in filename):

- `reports/open_prep_report_YYYYMMDD_HHMMSSZ.html`
- `reports/open_prep_report_YYYYMMDD_HHMMSSZ.xls`

Export command:

- `PYTHONPATH=/Users/steffenpreuss/Downloads/skipp-algo python scripts/export_open_prep_reports.py`

## Validation

Test command:

- `python -m pytest -q`

Last local verification:

- `502 passed, 16 subtests passed`

## Remote Repository

Created GitHub repository:

- `https://github.com/skipp-dev/skipp-algo-open-prep-20260220`
