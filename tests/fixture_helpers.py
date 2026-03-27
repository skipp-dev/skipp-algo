"""Fixture-loading helpers for regression tests."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    """Load a JSON fixture by filename (relative to tests/fixtures/)."""
    path = _FIXTURES_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"fixture not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def assert_keys_subset(expected_keys: set[str], actual: dict[str, Any], context: str = "") -> None:
    """Assert that *expected_keys* are all present in *actual*."""
    missing = expected_keys - set(actual.keys())
    if missing:
        label = f" ({context})" if context else ""
        raise AssertionError(f"missing keys{label}: {sorted(missing)}")
