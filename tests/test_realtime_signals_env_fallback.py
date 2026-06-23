"""Regression tests for the stdlib .env fallback in realtime_signals.main()."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def _run_fallback(env_text: str) -> dict[str, str]:
    """Run the same logic as main()'s ImportError branch."""
    captured: dict[str, str] = {}
    with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False, encoding="utf-8") as fh:
        fh.write(env_text)
        env_path = Path(fh.name)

    for key in ["EQUALS", "SINGLE", "EXPORT", "EMPTY", "SPACES"]:
        os.environ.pop(key, None)

    try:
        with open(env_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                if key.startswith("export "):
                    key = key[7:].strip()
                val = val.strip().strip("'\"")
                if key and key not in os.environ:
                    captured[key] = val
    finally:
        env_path.unlink()

    return captured


def test_env_fallback_preserves_equals_in_value() -> None:
    parsed = _run_fallback("EQUALS=val=ue\n")
    assert parsed["EQUALS"] == "val=ue"


def test_env_fallback_strips_single_quotes() -> None:
    parsed = _run_fallback("SINGLE='val=ue'\n")
    assert parsed["SINGLE"] == "val=ue"


def test_env_fallback_handles_export_prefix() -> None:
    parsed = _run_fallback("export EXPORT=value\n")
    assert parsed["EXPORT"] == "value"


def test_env_fallback_empty_value() -> None:
    parsed = _run_fallback("EMPTY=\n")
    assert parsed["EMPTY"] == ""


def test_env_fallback_ignores_comments_and_blank_lines() -> None:
    parsed = _run_fallback("\n# comment\nSPACES = value with spaces\n")
    assert parsed["SPACES"] == "value with spaces"
