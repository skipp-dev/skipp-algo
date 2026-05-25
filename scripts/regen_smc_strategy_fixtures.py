"""Regenerate / verify SMC strategy mirror snapshot fixtures (#2353).

Default (read-only, CI-safe): runs the Python mirror against
``tests/fixtures/smc_strategy/<strategy>_input.csv`` and compares the
result against ``<strategy>_expected_signals.csv``. Exits 0 on match,
1 on mismatch, 2 if the mirror is not implemented yet.

Maintainer mode (``--apply``): writes the mirror output as the new
expected fixture. Always cross-validate against the Pine side using
``docs/smc_strategy_mirror_validation.md`` before committing the
refreshed fixture.

The Python mirror under ``python/strategies/smc_mirror/`` does not
exist yet (2026-05-25). The CLI exits with code 2 and a clear message
in that case; it is wired up now so the regeneration loop is mechanical
once the mirror lands.
"""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "smc_strategy"
SIGNAL_STRING_COLS = ("signal_type",)
SIGNAL_FLOAT_COLS = ("sl", "tp", "confidence")
KNOWN_STRATEGIES = ("long_strategy",)

EXIT_OK = 0
EXIT_MISMATCH = 1
EXIT_MIRROR_MISSING = 2


def _load_mirror():
    try:
        return importlib.import_module("python.strategies.smc_mirror")
    except ModuleNotFoundError:
        return None


def _run_mirror(mirror_module, strategy: str, input_frame: pd.DataFrame) -> pd.DataFrame:
    runner = getattr(mirror_module, f"run_{strategy}")
    return runner(input_frame)


def _input_path(strategy: str) -> Path:
    return FIXTURE_ROOT / f"{strategy}_input.csv"


def _expected_path(strategy: str) -> Path:
    return FIXTURE_ROOT / f"{strategy}_expected_signals.csv"


def _compare(actual: pd.DataFrame, expected: pd.DataFrame) -> list[str]:
    diffs: list[str] = []
    if len(actual) != len(expected):
        diffs.append(f"row count mismatch: actual={len(actual)} expected={len(expected)}")
        return diffs
    if list(actual["bar_index"]) != list(expected["bar_index"]):
        diffs.append("bar_index drift")
        return diffs
    for col in SIGNAL_STRING_COLS:
        bad = actual[col].astype(str).values != expected[col].astype(str).values
        if bad.any():
            diffs.append(
                f"{col} mismatch at bar_index="
                f"{actual.loc[bad, 'bar_index'].tolist()[:10]}"
            )
    for col in SIGNAL_FLOAT_COLS:
        a = actual[col].to_numpy(dtype=float)
        e = expected[col].to_numpy(dtype=float)
        if not np.allclose(a, e, rtol=1e-9, atol=1e-9, equal_nan=True):
            d = np.abs(a - e)
            worst = int(np.nanargmax(d))
            diffs.append(
                f"{col} diverged beyond rtol=atol=1e-9; "
                f"worst bar_index={int(actual.loc[worst, 'bar_index'])}, "
                f"actual={a[worst]}, expected={e[worst]}"
            )
    return diffs


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--strategy",
        choices=KNOWN_STRATEGIES,
        default=KNOWN_STRATEGIES[0],
        help="Which strategy fixture to regenerate / verify.",
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="Write mirror output as the new expected fixture (maintainer-only).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    mirror = _load_mirror()
    if mirror is None:
        print(
            "ERROR: python/strategies/smc_mirror not implemented yet (#2353). "
            "Fixture verification is wired up but inert until the mirror lands.",
            file=sys.stderr,
        )
        return EXIT_MIRROR_MISSING

    input_path = _input_path(args.strategy)
    expected_path = _expected_path(args.strategy)
    if not input_path.exists():
        print(f"ERROR: input fixture missing: {input_path}", file=sys.stderr)
        return EXIT_MISMATCH

    input_frame = pd.read_csv(input_path)
    actual = _run_mirror(mirror, args.strategy, input_frame)

    if args.apply:
        cols = ["bar_index", *SIGNAL_STRING_COLS, *SIGNAL_FLOAT_COLS]
        # ATOMIC-WRITE-EXEMPT: one-shot dev CLI (--apply regen of golden fixture); operator-supervised, no concurrent writers, not pipeline-consumed.
        actual[cols].to_csv(expected_path, index=False)
        print(f"wrote {expected_path} ({len(actual)} rows) — cross-validate vs Pine before committing.")
        return EXIT_OK

    if not expected_path.exists():
        print(
            f"ERROR: expected fixture missing: {expected_path}. "
            "Run with --apply (after Pine-side cross-validation) to seed it.",
            file=sys.stderr,
        )
        return EXIT_MISMATCH

    expected = pd.read_csv(expected_path)
    diffs = _compare(actual, expected)
    if diffs:
        print(f"FIXTURE MISMATCH for {args.strategy}:", file=sys.stderr)
        for d in diffs:
            print(f"  - {d}", file=sys.stderr)
        return EXIT_MISMATCH

    print(f"OK: {args.strategy} mirror output matches expected fixture.")
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
