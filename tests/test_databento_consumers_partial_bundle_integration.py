"""Integration test for F-V8-D5 / A9b.5 partial-run guard wiring.

The unit tests in ``test_load_databento_export_bundle_partial.py`` cover
the helper ``assert_bundle_is_complete`` in isolation. This file is the
defense-in-depth complement: it verifies that the two production
consumers actually CALL the helper after their respective
``load_export_bundle`` invocations, so a future refactor that drops the
wire-in (e.g. silently moves the call out of the function body) gets
caught here rather than in a midnight cron failure.

Strategy: monkeypatch each module's bound name of
``load_export_bundle`` to return a synthetic payload with
``partial_run=true``, invoke the public entry function with the minimum
viable kwargs to reach the assert, and require that a ``RuntimeError``
mentioning ``partial_run=true`` is raised.

We intentionally do NOT build real on-disk bundles here — the helper
unit tests already exercise the diagnostics format, and a full e2e
roundtrip would require Databento-shaped parquet fixtures that are
disproportionate for a wiring guard.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest


def _partial_payload() -> dict[str, Any]:
    return {
        "manifest": {
            "partial_run": True,
            "shard_count": 1,
            "expected_shard_count": 2,
            "failed_shard_ids": [2],
            "trade_dates_covered": ["20260515"],
        },
        "frames": {},
        "manifest_path": Path("synthetic/_manifest.json"),
        "bundle_dir": Path("synthetic"),
        "base_prefix": "databento_volatility_production_",
    }


def test_preopen_fast_refresh_raises_on_partial_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    # F-V8-D5 wiring guard for scripts/databento_preopen_fast.py: the
    # `assert_bundle_is_complete` call must execute right after
    # `load_export_bundle` so a partial sharded merge cannot silently
    # corrupt the preopen scope selection.
    import scripts.databento_preopen_fast as preopen_fast

    monkeypatch.setattr(
        preopen_fast,
        "load_export_bundle",
        lambda *args, **kwargs: _partial_payload(),
    )

    with pytest.raises(RuntimeError, match=r"partial_run=true"):
        preopen_fast.run_preopen_fast_refresh(
            databento_api_key="test-key-not-used",
            dataset="EQUS.MINI",
            export_dir="synthetic",
            bundle="synthetic",
        )


def test_production_workbook_raises_on_partial_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    # F-V8-D5 wiring guard for scripts/databento_production_workbook.py:
    # workbook readers expect full-universe frames; consuming a partial
    # bundle would silently underreport. The assert must run before any
    # frame access.
    import scripts.databento_production_workbook as production_workbook

    monkeypatch.setattr(
        production_workbook,
        "load_export_bundle",
        lambda *args, **kwargs: _partial_payload(),
    )

    with pytest.raises(RuntimeError, match=r"partial_run=true"):
        production_workbook.write_databento_production_workbook(
            export_bundle_path=Path("synthetic"),
            output_path=Path("synthetic/out.xlsx"),
        )


def test_override_env_lets_consumers_proceed_past_assert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # When operator opts in via SMC_ALLOW_PARTIAL_BUNDLE=1 the helper
    # warns but does not raise; consumers then proceed. The function may
    # complete successfully (with whatever the synthetic payload allows)
    # or fail later for an unrelated reason. The only invariant we check
    # here is that the partial-run RuntimeError is NOT raised.
    monkeypatch.setenv("SMC_ALLOW_PARTIAL_BUNDLE", "1")
    import scripts.databento_production_workbook as production_workbook

    monkeypatch.setattr(
        production_workbook,
        "load_export_bundle",
        lambda *args, **kwargs: _partial_payload(),
    )

    raised: BaseException | None = None
    try:
        production_workbook.write_databento_production_workbook(
            export_bundle_path=Path("synthetic"),
            output_path=Path("synthetic/out.xlsx"),
        )
    except BaseException as exc:  # noqa: BLE001 - want to inspect any error
        raised = exc

    if raised is not None and "partial_run=true" in str(raised):
        raise AssertionError(
            f"override env failed to bypass the partial-run assert: {raised!r}"
        )
