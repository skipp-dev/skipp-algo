"""Tests for the canonical-workbook slim-whitelist (Bridge 1c).

Background
----------
Five consecutive cron runs of ``smc-databento-production-export.yml`` failed
between 2026-05-11 and 2026-05-13 (run IDs 25687318767, 25733577369,
25738826438, 25752310158, 25785343691). All died with SIGTERM (exit 143)
during ``openpyxl.Workbook.__exit__`` XML serialization while writing the
full 28-sheet canonical workbook at ``lookback_days=30``; RSS climbed to
41–56 GB on the 64 GB ``ubuntu-latest-l`` runner.

The last green run (25675320709, workflow_dispatch with ``lookback_days=5``)
peaked at 8.1 GB and finished in 51m46s, confirming that the failure mode
is workbook-size driven, not data-quality driven.

Bridge 1c (this PR) restricts the canonical xlsx to the four sheets that
are either consumed downstream or required for diagnostics:
  - ``manifest`` / ``batl_debug`` / ``output_checks`` — diagnostics
  - ``daily_bars`` — read by ``smc_integration/structure_batch.py`` (l. 86,
    500) and ``scripts/export_smc_structure_artifact.py`` (l. 164).
All other 24 sheets remain available as parquet via Step 10/10b
(``_write_exact_named_exports``). The env variable
``CANONICAL_WORKBOOK_SHEETS`` overrides the default; setting it to
``all`` restores the historic full-workbook behaviour for manual
``workflow_dispatch`` debugging only.

This contract is the only thing standing between the cron and another OOM,
so it gets its own dedicated test module.
"""
from __future__ import annotations

import pytest

import scripts.databento_production_export as export_mod
from scripts.databento_production_export import (
    CANONICAL_WORKBOOK_SHEETS_ALL_TOKEN,
    CANONICAL_WORKBOOK_SHEETS_ENV_VAR,
    DEFAULT_SLIM_CANONICAL_WORKBOOK_SHEET_NAMES,
    _resolve_canonical_workbook_sheet_whitelist,
)


# ---------------------------------------------------------------------------
# resolver-level tests
# ---------------------------------------------------------------------------


def test_resolver_returns_default_slim_whitelist_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(CANONICAL_WORKBOOK_SHEETS_ENV_VAR, raising=False)

    result = _resolve_canonical_workbook_sheet_whitelist()

    assert result == frozenset(DEFAULT_SLIM_CANONICAL_WORKBOOK_SHEET_NAMES)
    assert "daily_bars" in result, (
        "daily_bars must stay in the default slim list — it is read by "
        "smc_integration/structure_batch.py and export_smc_structure_artifact.py"
    )
    assert "manifest" in result
    assert "batl_debug" in result
    assert "output_checks" in result
    # The historic full-workbook sheets that caused the OOM must NOT be
    # in the default slim whitelist.
    assert "premarket_window_features_full" not in result
    assert "workbook_minute_detail" not in result


def test_resolver_returns_default_when_env_is_empty_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CANONICAL_WORKBOOK_SHEETS_ENV_VAR, "")

    assert _resolve_canonical_workbook_sheet_whitelist() == frozenset(
        DEFAULT_SLIM_CANONICAL_WORKBOOK_SHEET_NAMES
    )


def test_resolver_returns_default_when_env_is_whitespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CANONICAL_WORKBOOK_SHEETS_ENV_VAR, "   \t  ")

    assert _resolve_canonical_workbook_sheet_whitelist() == frozenset(
        DEFAULT_SLIM_CANONICAL_WORKBOOK_SHEET_NAMES
    )


def test_resolver_returns_default_when_env_is_only_commas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pathological case: env set but contains no actual sheet names."""
    monkeypatch.setenv(CANONICAL_WORKBOOK_SHEETS_ENV_VAR, ", , ,")

    assert _resolve_canonical_workbook_sheet_whitelist() == frozenset(
        DEFAULT_SLIM_CANONICAL_WORKBOOK_SHEET_NAMES
    )


def test_resolver_returns_none_when_env_is_all_token_lowercase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        CANONICAL_WORKBOOK_SHEETS_ENV_VAR,
        CANONICAL_WORKBOOK_SHEETS_ALL_TOKEN,
    )

    assert _resolve_canonical_workbook_sheet_whitelist() is None


def test_resolver_returns_none_when_env_is_all_token_uppercase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ALL`` must be case-insensitive — humans set env in mixed case."""
    monkeypatch.setenv(CANONICAL_WORKBOOK_SHEETS_ENV_VAR, "ALL")

    assert _resolve_canonical_workbook_sheet_whitelist() is None


def test_resolver_returns_none_when_env_is_all_token_mixed_case_padded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CANONICAL_WORKBOOK_SHEETS_ENV_VAR, "  AlL  ")

    assert _resolve_canonical_workbook_sheet_whitelist() is None


def test_resolver_parses_comma_separated_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        CANONICAL_WORKBOOK_SHEETS_ENV_VAR,
        "manifest,daily_bars",
    )

    result = _resolve_canonical_workbook_sheet_whitelist()

    assert result == frozenset({"manifest", "daily_bars"})


def test_resolver_strips_whitespace_around_csv_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        CANONICAL_WORKBOOK_SHEETS_ENV_VAR,
        "  manifest , daily_bars ,  output_checks  ",
    )

    assert _resolve_canonical_workbook_sheet_whitelist() == frozenset(
        {"manifest", "daily_bars", "output_checks"}
    )


def test_resolver_ignores_empty_chunks_in_csv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        CANONICAL_WORKBOOK_SHEETS_ENV_VAR,
        "manifest,,daily_bars,,,output_checks,",
    )

    assert _resolve_canonical_workbook_sheet_whitelist() == frozenset(
        {"manifest", "daily_bars", "output_checks"}
    )


def test_resolver_preserves_case_of_sheet_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sheet names are case-sensitive — ``ALL`` is special, others are not."""
    monkeypatch.setenv(
        CANONICAL_WORKBOOK_SHEETS_ENV_VAR,
        "Manifest,DAILY_BARS",
    )

    # The resolver MUST preserve sheet-name case so it can match the
    # exact pandas DataFrame keys downstream.
    result = _resolve_canonical_workbook_sheet_whitelist()
    assert result == frozenset({"Manifest", "DAILY_BARS"})


def test_resolver_supports_single_sheet_with_no_commas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CANONICAL_WORKBOOK_SHEETS_ENV_VAR, "daily_bars")

    assert _resolve_canonical_workbook_sheet_whitelist() == frozenset(
        {"daily_bars"}
    )


# ---------------------------------------------------------------------------
# defensive-constants tests
# ---------------------------------------------------------------------------


def test_default_slim_whitelist_constant_is_immutable_tuple() -> None:
    """Catches accidental list/set conversions during future edits."""
    assert isinstance(DEFAULT_SLIM_CANONICAL_WORKBOOK_SHEET_NAMES, tuple)


def test_default_slim_whitelist_constant_has_expected_members() -> None:
    """If this fails the audit trail in the module docstring is stale.

    Update the docstring AND this test together, never one without the
    other.
    """
    assert set(DEFAULT_SLIM_CANONICAL_WORKBOOK_SHEET_NAMES) == {
        "manifest",
        "daily_bars",
        "batl_debug",
        "output_checks",
    }


def test_env_var_name_constant_is_stable() -> None:
    """The workflow yaml references this env var by string literal."""
    assert CANONICAL_WORKBOOK_SHEETS_ENV_VAR == "CANONICAL_WORKBOOK_SHEETS"


def test_all_token_constant_is_lowercase() -> None:
    """Documentation in the module says ``all`` is the canonical form."""
    assert CANONICAL_WORKBOOK_SHEETS_ALL_TOKEN == "all"


# ---------------------------------------------------------------------------
# module export surface — what the workflow / consumers can rely on
# ---------------------------------------------------------------------------


def test_module_exports_whitelist_symbols() -> None:
    """All four symbols are part of the bridge-1c public contract."""
    for name in (
        "DEFAULT_SLIM_CANONICAL_WORKBOOK_SHEET_NAMES",
        "CANONICAL_WORKBOOK_SHEETS_ENV_VAR",
        "CANONICAL_WORKBOOK_SHEETS_ALL_TOKEN",
        "_resolve_canonical_workbook_sheet_whitelist",
    ):
        assert hasattr(export_mod, name), (
            f"{name} disappeared from scripts.databento_production_export — "
            "bridge-1c contract broken"
        )
