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

from pathlib import Path

import pandas as pd
import pytest

import scripts.databento_production_export as export_mod
from scripts.databento_production_export import (
    CANONICAL_WORKBOOK_SHEETS_ALL_TOKEN,
    CANONICAL_WORKBOOK_SHEETS_ENV_VAR,
    DEFAULT_SLIM_CANONICAL_WORKBOOK_SHEET_NAMES,
    _resolve_canonical_workbook_sheet_whitelist,
)
from scripts.databento_production_workbook import WorkbookWriteResult


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


# ---------------------------------------------------------------------------
# consumer-level tests — exercise the slim-whitelist branch inside
# ``_write_canonical_production_workbook`` (smc_base_only=False path).
# Mirrors the fixture pattern in test_databento_production_workbook_shared.py
# but focuses on the env-resolved whitelist behaviour added by Bridge 1c.
# ---------------------------------------------------------------------------


def _placeholder_frame() -> pd.DataFrame:
    """One-row placeholder so additional_sheets keys carry payload."""
    return pd.DataFrame([{"trade_date": "2026-03-26", "symbol": "AAPL"}])


def _invoke_write_canonical_workbook(
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    progress_callback=None,
) -> dict[str, object]:
    """Drive ``_write_canonical_production_workbook`` with stubbed writer.

    Returns the kwargs captured by the fake writer so callers can assert
    on the resulting ``additional_sheets`` / minute_detail / second_detail
    after the slim-whitelist filter has been applied.
    """
    recorded: dict[str, object] = {}

    def _fake_writer(**kwargs):
        recorded.update(kwargs)
        out_path = Path(kwargs["output_path"])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"ok")
        return WorkbookWriteResult(
            output_path=out_path,
            generated_at="2026-03-26T00:00:00+00:00",
            row_counts={"summary": len(kwargs["summary"])},
            sheet_names=["summary"],
            canonical_upstream_artifact="databento_production_export_bundle",
        )

    monkeypatch.setattr(
        export_mod,
        "write_databento_production_workbook_from_frames",
        _fake_writer,
    )

    export_mod._write_canonical_production_workbook(
        export_dir=tmp_path,
        summary=pd.DataFrame([{"symbol": "AAPL"}]),
        minute_detail=pd.DataFrame(
            [{"timestamp": "2026-03-26T13:30:00Z", "price": 1.0}]
        ),
        second_detail=pd.DataFrame(
            [{"timestamp": "2026-03-26T13:30:00Z", "price": 1.0}]
        ),
        manifest={"dataset": "DBEQ.BASIC"},
        raw_universe=_placeholder_frame(),
        daily_bars=_placeholder_frame(),
        intraday=_placeholder_frame(),
        ranked=_placeholder_frame(),
        daily_symbol_features_full_universe=_placeholder_frame(),
        full_universe_second_detail_open=_placeholder_frame(),
        full_universe_second_detail_close=_placeholder_frame(),
        full_universe_close_trade_detail=_placeholder_frame(),
        full_universe_close_outcome_minute=_placeholder_frame(),
        close_imbalance_features_full_universe=_placeholder_frame(),
        close_imbalance_outcomes_full_universe=_placeholder_frame(),
        premarket_features_full_universe=_placeholder_frame(),
        premarket_window_features_full_universe=_placeholder_frame(),
        symbol_day_diagnostics=_placeholder_frame(),
        research_event_flags_full_universe=_placeholder_frame(),
        research_event_flag_coverage=_placeholder_frame(),
        research_event_flag_trade_date_distribution=_placeholder_frame(),
        research_event_flag_outcome_slices=_placeholder_frame(),
        research_news_flags_full_universe=_placeholder_frame(),
        research_news_flag_coverage=_placeholder_frame(),
        research_news_flag_trade_date_distribution=_placeholder_frame(),
        research_news_flag_outcome_slices=_placeholder_frame(),
        core_vs_benzinga_news_side_by_side=_placeholder_frame(),
        core_vs_benzinga_news_overlap_stats=_placeholder_frame(),
        quality_window_status=_placeholder_frame(),
        batl_debug={"ok": True},
        output_summary={"rows": 1},
        smc_base_only=False,
        progress_callback=progress_callback,
    )
    return recorded


def test_write_canonical_workbook_slims_to_default_whitelist_when_env_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default behaviour (env unset): drop everything except the 4 slim sheets.

    This is the contract that keeps the cron from another OOM. If a future
    refactor accidentally widens the default, this test catches it before
    the cron does.
    """
    monkeypatch.delenv(CANONICAL_WORKBOOK_SHEETS_ENV_VAR, raising=False)

    recorded = _invoke_write_canonical_workbook(
        tmp_path=tmp_path, monkeypatch=monkeypatch
    )

    additional = recorded["additional_sheets"]
    assert isinstance(additional, dict)
    # `manifest` / `daily_bars` survive; `batl_debug` / `output_checks`
    # are added by the writer downstream from a dict, not via
    # additional_sheets, so they are *not* expected here.
    assert "manifest" in additional
    assert "daily_bars" in additional
    # The OOM-driving 24+ sheets must all be filtered out at this layer.
    for forbidden in (
        "universe",
        "intraday_all",
        "ranked",
        "daily_symbol_features_full_universe",
        "premarket_window_features_full_universe",
        "symbol_day_diagnostics",
    ):
        assert forbidden not in additional, (
            f"slim-whitelist regressed: {forbidden!r} leaked into the "
            "canonical workbook — would re-trigger the cron OOM"
        )
    # minute_detail / second_detail are not in the default slim list and
    # MUST be suppressed.
    assert recorded["minute_detail"].empty
    assert recorded["second_detail"].empty


def test_write_canonical_workbook_emits_dropped_progress_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Progress callback receives a `slim-whitelist active` marker when sheets are dropped."""
    monkeypatch.delenv(CANONICAL_WORKBOOK_SHEETS_ENV_VAR, raising=False)
    messages: list[str] = []

    _invoke_write_canonical_workbook(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        progress_callback=messages.append,
    )

    slim_msgs = [m for m in messages if "slim-whitelist active" in m]
    assert slim_msgs, (
        "Slim-whitelist progress marker was not emitted — operators rely on "
        "it to confirm the cron is running the slim path."
    )
    joined = "\n".join(slim_msgs)
    assert "kept=" in joined and "dropped=" in joined
    assert CANONICAL_WORKBOOK_SHEETS_ENV_VAR in joined


def test_write_canonical_workbook_honours_env_override_csv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``CANONICAL_WORKBOOK_SHEETS=manifest`` keeps only manifest."""
    monkeypatch.setenv(CANONICAL_WORKBOOK_SHEETS_ENV_VAR, "manifest")

    recorded = _invoke_write_canonical_workbook(
        tmp_path=tmp_path, monkeypatch=monkeypatch
    )

    additional = recorded["additional_sheets"]
    assert isinstance(additional, dict)
    assert set(additional.keys()) == {"manifest"}
    assert recorded["minute_detail"].empty
    assert recorded["second_detail"].empty


def test_write_canonical_workbook_env_all_retains_full_sheet_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``CANONICAL_WORKBOOK_SHEETS=all`` restores historic full-workbook path.

    No filtering, no whitelist progress marker, and minute_detail /
    second_detail are forwarded unchanged.
    """
    monkeypatch.setenv(
        CANONICAL_WORKBOOK_SHEETS_ENV_VAR,
        CANONICAL_WORKBOOK_SHEETS_ALL_TOKEN,
    )
    messages: list[str] = []

    recorded = _invoke_write_canonical_workbook(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        progress_callback=messages.append,
    )

    additional = recorded["additional_sheets"]
    assert isinstance(additional, dict)
    # Sample of sheets that the slim-whitelist would have dropped — all
    # must remain in the `all` path.
    for retained in (
        "manifest",
        "daily_bars",
        "universe",
        "premarket_window_features_full_universe",
    ):
        assert retained in additional, (
            f"`CANONICAL_WORKBOOK_SHEETS=all` regressed: {retained!r} "
            "dropped from the full-workbook path"
        )
    assert not recorded["minute_detail"].empty
    assert not recorded["second_detail"].empty
    assert not any(
        "slim-whitelist active" in m for m in messages
    ), "slim-whitelist progress marker leaked into the `all` path"


def test_write_canonical_workbook_env_minute_detail_keeps_minute_detail_frame(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the whitelist names ``minute_detail`` explicitly, the frame is kept.

    Exercises the conditional re-assignment of ``workbook_minute_detail`` /
    ``workbook_second_detail`` inside the slim-whitelist branch.
    """
    monkeypatch.setenv(
        CANONICAL_WORKBOOK_SHEETS_ENV_VAR,
        "manifest,minute_detail,second_detail",
    )

    recorded = _invoke_write_canonical_workbook(
        tmp_path=tmp_path, monkeypatch=monkeypatch
    )

    assert not recorded["minute_detail"].empty, (
        "minute_detail was named in CANONICAL_WORKBOOK_SHEETS but the "
        "writer received an empty frame — the positional-suppression "
        "branch incorrectly fired"
    )
    assert not recorded["second_detail"].empty, (
        "second_detail was named in CANONICAL_WORKBOOK_SHEETS but the "
        "writer received an empty frame — the positional-suppression "
        "branch incorrectly fired"
    )
