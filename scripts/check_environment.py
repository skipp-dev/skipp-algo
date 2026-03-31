"""Verify the local Python environment matches project requirements.

Usage::

    python scripts/check_environment.py

Checks:
  - Python >= 3.12
  - Key packages importable
  - smc_core modules present

Exit code 0 = all checks passed, 1 = failure.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MIN_PYTHON = (3, 12)

REQUIRED_MODULES = [
    "smc_core.schema_version",
    "smc_core.benchmark",
    "smc_core.scoring",
    "smc_core.vol_regime",
    "smc_core.bias_merge",
]


def main() -> int:
    errors: list[str] = []

    # Python version check
    if sys.version_info[:2] < MIN_PYTHON:
        errors.append(
            f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required, "
            f"found {sys.version_info[0]}.{sys.version_info[1]}"
        )
    else:
        print(f"✓ Python {sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]}")

    # Module import checks
    for mod in REQUIRED_MODULES:
        try:
            importlib.import_module(mod)
            print(f"✓ {mod}")
        except ImportError as exc:
            errors.append(f"Cannot import {mod}: {exc}")

    if errors:
        print("\nEnvironment check FAILED:")
        for e in errors:
            print(f"  ✗ {e}")
        return 1

    print("\nAll environment checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
