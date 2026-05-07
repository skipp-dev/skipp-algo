"""A9b.1 — CLI coverage for matrix-sharded producer args.

Validates the four new arguments added to
``scripts.databento_production_export.main``:

  --start-date YYYY-MM-DD   (paired with --end-date)
  --end-date   YYYY-MM-DD   (paired with --start-date)
  --shard-id   INT          (paired with --shard-of)
  --shard-of   INT          (paired with --shard-id)

Backward compatibility, success path, and all validation failure modes are
covered without invoking any network IO (load_dotenv, dataset listing,
trading-day listing, and the export pipeline are all mocked).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest


def _patch_common(monkeypatch) -> dict[str, Any]:
    """Install the shared mocks used by every case below.

    Returns the ``captured`` dict that records the kwargs passed to
    ``run_production_export_pipeline``.
    """
    from scripts import databento_production_export as mod

    captured: dict[str, Any] = {}

    monkeypatch.setattr(mod, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        mod, "list_accessible_datasets", lambda api_key: ["XNAS.ITCH", "DBEQ.BASIC"]
    )

    # Default mock: returns a stable list spanning the full April 2026 range
    # used in the success test.  Individual tests can re-patch as needed.
    monkeypatch.setattr(
        mod,
        "list_recent_trading_days",
        lambda *args, **kwargs: [
            date(2026, 4, 1),
            date(2026, 4, 2),
            date(2026, 4, 3),
            date(2026, 4, 6),
            date(2026, 4, 7),
        ],
    )

    def fake_pipeline(**kwargs):
        captured.update(kwargs)
        return {
            "manifest": {"export_dir": "/tmp/export"},
            "output_checks": {},
            "batl_debug": {},
            "exported_paths": {},
        }

    monkeypatch.setattr(mod, "run_production_export_pipeline", fake_pipeline)
    monkeypatch.setenv("DATABENTO_API_KEY", "test-key")
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    monkeypatch.delenv("DATABENTO_DATASET", raising=False)

    return captured


def test_a9b1_no_range_args_passes_none_override(monkeypatch) -> None:
    """Backward compat: without range args, trading_days_override stays None."""
    from scripts import databento_production_export as mod

    captured = _patch_common(monkeypatch)
    mod.main([])

    assert captured["trading_days_override"] is None


def test_a9b1_explicit_range_resolves_filtered_override(monkeypatch) -> None:
    """--start-date + --end-date resolves to a filtered trading-day list."""
    from scripts import databento_production_export as mod

    captured = _patch_common(monkeypatch)
    mod.main(["--start-date", "2026-04-02", "--end-date", "2026-04-06"])

    override = captured["trading_days_override"]
    assert override == [date(2026, 4, 2), date(2026, 4, 3), date(2026, 4, 6)]


def test_a9b1_start_without_end_exits(monkeypatch) -> None:
    from scripts import databento_production_export as mod

    _patch_common(monkeypatch)
    with pytest.raises(SystemExit, match="must be provided together"):
        mod.main(["--start-date", "2026-04-01"])


def test_a9b1_end_without_start_exits(monkeypatch) -> None:
    from scripts import databento_production_export as mod

    _patch_common(monkeypatch)
    with pytest.raises(SystemExit, match="must be provided together"):
        mod.main(["--end-date", "2026-04-30"])


def test_a9b1_end_before_start_exits(monkeypatch) -> None:
    from scripts import databento_production_export as mod

    _patch_common(monkeypatch)
    with pytest.raises(SystemExit, match="must be on or before"):
        mod.main(["--start-date", "2026-04-30", "--end-date", "2026-04-01"])


def test_a9b1_shard_id_without_of_exits(monkeypatch) -> None:
    from scripts import databento_production_export as mod

    _patch_common(monkeypatch)
    with pytest.raises(SystemExit, match="--shard-id and --shard-of"):
        mod.main(["--shard-id", "1"])


def test_a9b1_shard_of_without_id_exits(monkeypatch) -> None:
    from scripts import databento_production_export as mod

    _patch_common(monkeypatch)
    with pytest.raises(SystemExit, match="--shard-id and --shard-of"):
        mod.main(["--shard-of", "3"])


def test_a9b1_shard_id_out_of_range_exits(monkeypatch) -> None:
    from scripts import databento_production_export as mod

    _patch_common(monkeypatch)
    with pytest.raises(SystemExit, match=r"must be in \[1, --shard-of=3\]"):
        mod.main(["--shard-id", "5", "--shard-of", "3"])


def test_a9b1_shard_id_zero_exits(monkeypatch) -> None:
    from scripts import databento_production_export as mod

    _patch_common(monkeypatch)
    with pytest.raises(SystemExit, match=r"must be in \[1, --shard-of=3\]"):
        mod.main(["--shard-id", "0", "--shard-of", "3"])


def test_a9b1_shard_of_zero_exits(monkeypatch) -> None:
    from scripts import databento_production_export as mod

    _patch_common(monkeypatch)
    with pytest.raises(SystemExit, match="--shard-of must be >= 1"):
        mod.main(["--shard-id", "1", "--shard-of", "0"])


def test_a9b1_empty_resolved_range_exits(monkeypatch) -> None:
    """If filter yields zero days, abort with an explicit error."""
    from scripts import databento_production_export as mod

    _patch_common(monkeypatch)
    # Re-patch trading days to a list disjoint from the requested window.
    monkeypatch.setattr(
        mod,
        "list_recent_trading_days",
        lambda *args, **kwargs: [date(2025, 1, 1), date(2025, 1, 2)],
    )
    with pytest.raises(SystemExit, match="No trading days available"):
        mod.main(["--start-date", "2026-04-01", "--end-date", "2026-04-30"])


def test_a9b1_valid_shard_pair_does_not_affect_override(monkeypatch) -> None:
    """shard-id/of are metadata-only and do not influence trading_days_override."""
    from scripts import databento_production_export as mod

    captured = _patch_common(monkeypatch)
    mod.main(
        [
            "--start-date",
            "2026-04-02",
            "--end-date",
            "2026-04-06",
            "--shard-id",
            "2",
            "--shard-of",
            "6",
        ]
    )
    assert captured["trading_days_override"] == [
        date(2026, 4, 2),
        date(2026, 4, 3),
        date(2026, 4, 6),
    ]
