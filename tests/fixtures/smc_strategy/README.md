# SMC strategy mirror snapshot fixtures (#2353)

These fixtures pin numerical equivalence between the Pine v6 strategies and
their (planned) Python mirror under `python/strategies/smc_mirror/`.

> **Status (2026-05-25):** the Python mirror does not exist yet. The
> snapshot tests in `tests/test_smc_strategy_snapshot.py` are skipped
> until the mirror is published (tracked by issue #2353 / Re-audit F4).
> The fixture layout, regeneration helper, and Pine-side validation
> procedure are in place so that wiring the mirror later is mechanical.

## Layout

For each strategy `<strategy_name>` (currently only `long_strategy`):

- `<strategy_name>_input.csv` — deterministic OHLCV slice, ~500 bars,
  one row per bar. Columns:
  - `bar_index` (int, 0-based, contiguous)
  - `timestamp` (ISO-8601 UTC, sortable)
  - `open`, `high`, `low`, `close` (float)
  - `volume` (float)
- `<strategy_name>_expected_signals.csv` — expected mirror output. Columns:
  - `bar_index` (int, joins to input)
  - `signal_type` (string, one of `LONG_ENTRY`, `LONG_EXIT`,
    `SHORT_ENTRY`, `SHORT_EXIT`, `NONE`)
  - `sl` (float, stop-loss price; `NaN` when no signal)
  - `tp` (float, take-profit price; `NaN` when no signal)
  - `confidence` (float in `[0.0, 1.0]`; `NaN` when no signal)

Comparison contract:

- `bar_index`, `signal_type` — exact equality.
- `sl`, `tp`, `confidence` — compared with
  `np.allclose` at `rtol=1e-9`, `atol=1e-9`, `equal_nan=True`.

## Regeneration

Read-only verification (CI-safe, default):

```text
python scripts/regen_smc_strategy_fixtures.py --strategy long_strategy
```

Apply mode (maintainer-only, on legit. mirror changes):

```text
python scripts/regen_smc_strategy_fixtures.py --strategy long_strategy --apply
```

See [docs/smc_strategy_mirror_validation.md](../../../docs/smc_strategy_mirror_validation.md)
for the manual Pine-side cross-check procedure that must be run before
committing a fixture refresh.
