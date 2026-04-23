"""Coverage uplift for `scripts.generate_smc_micro_profiles`.

Module is already 87% covered by the legacy test suite. This file targets the
remaining gaps:
- `build_parser()` defaults
- `main()` both branches (assess-input shortcut + full run_generation)
- a few edge cases in `_safe_bool`, `load_state`, `load_overrides`,
  `apply_overrides`, `assess_csv_against_schema` and `validate_schema`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from scripts import generate_smc_micro_profiles as gsm
from scripts.generate_smc_micro_profiles import (
    _safe_bool,
    apply_overrides,
    assess_csv_against_schema,
    build_parser,
    fail,
    load_overrides,
    load_state,
    main,
    validate_schema,
)

# ---------------------------------------------------------------------------
# fail
# ---------------------------------------------------------------------------


def test_fail_raises_runtimeerror() -> None:
    with pytest.raises(RuntimeError, match="boom"):
        fail("boom")


# ---------------------------------------------------------------------------
# _safe_bool
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, False),
        (float("nan"), False),
        ("true", True),
        ("YES", True),
        ("on", True),
        ("0", False),
        ("no", False),
        (1, True),
        (0, False),
        (1.5, True),
        (object(), True),
    ],
)
def test_safe_bool_branches(value: Any, expected: bool) -> None:
    assert _safe_bool(value) is expected


# ---------------------------------------------------------------------------
# load_state
# ---------------------------------------------------------------------------


def test_load_state_returns_empty_when_path_missing(tmp_path: Path) -> None:
    out = load_state(tmp_path / "missing.csv")
    assert isinstance(out, pd.DataFrame)
    # Should have all STATE_COLUMNS even if empty
    assert "is_active" in out.columns
    assert out.empty


def test_load_state_fills_missing_columns(tmp_path: Path) -> None:
    p = tmp_path / "state.csv"
    # Only a subset of columns; loader must add the missing ones with defaults.
    pd.DataFrame({"symbol": ["AAPL"], "list_name": ["clean_reclaim"]}).to_csv(p, index=False)
    out = load_state(p)
    assert "is_active" in out.columns
    assert out["is_active"].iloc[0] == 0
    assert out["active_since"].iloc[0] == ""
    assert out["last_score"].iloc[0] == 0.0


# ---------------------------------------------------------------------------
# load_overrides
# ---------------------------------------------------------------------------


def test_load_overrides_returns_empty_when_path_none() -> None:
    out = load_overrides(None, asof_date="2026-04-23")
    assert isinstance(out, pd.DataFrame)
    assert out.empty


def test_load_overrides_returns_empty_when_path_missing(tmp_path: Path) -> None:
    out = load_overrides(tmp_path / "missing.csv", asof_date="2026-04-23")
    assert out.empty


def test_load_overrides_returns_empty_csv_passthrough(tmp_path: Path) -> None:
    p = tmp_path / "ov.csv"
    pd.DataFrame(columns=["asof_date", "symbol", "list_name", "action", "reason"]).to_csv(p, index=False)
    out = load_overrides(p, asof_date="2026-04-23")
    assert out.empty


def test_load_overrides_filters_by_asof(tmp_path: Path) -> None:
    # Use one of the valid LISTS values from the module
    list_name = gsm.LISTS[0]
    p = tmp_path / "ov.csv"
    pd.DataFrame({
        "asof_date": ["2026-04-22", "2026-04-23"],
        "symbol": ["aapl", "msft"],
        "list_name": [list_name, list_name],
        "action": ["add", "remove"],
        "reason": ["a", "b"],
    }).to_csv(p, index=False)
    out = load_overrides(p, asof_date="2026-04-23")
    assert len(out) == 1
    assert out.iloc[0]["symbol"] == "MSFT"
    assert out.iloc[0]["action"] == "remove"


def test_load_overrides_unknown_list_fails(tmp_path: Path) -> None:
    p = tmp_path / "ov.csv"
    pd.DataFrame({
        "asof_date": ["2026-04-23"],
        "symbol": ["AAPL"],
        "list_name": ["nonsense_list"],
        "action": ["add"],
        "reason": ["x"],
    }).to_csv(p, index=False)
    with pytest.raises(RuntimeError, match="unknown lists"):
        load_overrides(p, asof_date="2026-04-23")


def test_load_overrides_unknown_action_fails(tmp_path: Path) -> None:
    list_name = gsm.LISTS[0]
    p = tmp_path / "ov.csv"
    pd.DataFrame({
        "asof_date": ["2026-04-23"],
        "symbol": ["AAPL"],
        "list_name": [list_name],
        "action": ["delete"],
        "reason": ["x"],
    }).to_csv(p, index=False)
    with pytest.raises(RuntimeError, match="unknown actions"):
        load_overrides(p, asof_date="2026-04-23")


# ---------------------------------------------------------------------------
# apply_overrides
# ---------------------------------------------------------------------------


def test_apply_overrides_returns_state_when_overrides_empty() -> None:
    state = pd.DataFrame({"symbol": ["AAPL"], "list_name": ["x"]})
    out = apply_overrides(state, pd.DataFrame(), asof_date="2026-04-23")
    assert out.equals(state)


def test_apply_overrides_adds_new_row_for_missing_key() -> None:
    state = pd.DataFrame(columns=["symbol", "list_name", "is_active", "active_since",
                                    "add_streak", "remove_streak", "last_score",
                                    "last_run_date", "candidate_active",
                                    "decision_source", "decision_reason"])
    overrides = pd.DataFrame({
        "symbol": ["AAPL"],
        "list_name": ["clean_reclaim"],
        "action": ["add"],
        "reason": ["manual unit-test"],
    })
    out = apply_overrides(state, overrides, asof_date="2026-04-23")
    assert len(out) == 1
    assert out.iloc[0]["is_active"] == 1
    assert out.iloc[0]["decision_source"] == "override:add"
    assert out.iloc[0]["decision_reason"] == "manual unit-test"


def test_apply_overrides_remove_existing_key() -> None:
    state = pd.DataFrame({
        "symbol": ["AAPL"],
        "list_name": ["clean_reclaim"],
        "is_active": [1],
        "active_since": ["2026-04-01"],
        "add_streak": [3],
        "remove_streak": [0],
        "last_score": [1.0],
        "last_run_date": ["2026-04-22"],
        "candidate_active": [1],
        "decision_source": ["generator"],
        "decision_reason": ["above add"],
    })
    overrides = pd.DataFrame({
        "symbol": ["AAPL"],
        "list_name": ["clean_reclaim"],
        "action": ["remove"],
        "reason": [""],
    })
    out = apply_overrides(state, overrides, asof_date="2026-04-23")
    row = out.iloc[0]
    assert row["is_active"] == 0
    assert row["decision_source"] == "override:remove"
    assert row["decision_reason"] == "manual override"
    assert row["last_run_date"] == "2026-04-23"


# ---------------------------------------------------------------------------
# validate_schema
# ---------------------------------------------------------------------------


def _minimal_schema() -> dict[str, Any]:
    return {
        "required_columns": ["asof_date", "symbol", "score"],
        "primary_key": ["asof_date", "symbol"],
        "value_ranges": {"score": [0.0, 1.0]},
    }


def test_validate_schema_passes_for_valid_input() -> None:
    schema = _minimal_schema()
    df = pd.DataFrame({
        "asof_date": ["2026-04-23", "2026-04-23"],
        "symbol": ["AAPL", "MSFT"],
        "score": [0.5, 0.7],
    })
    # Should not raise
    validate_schema(df, schema)


def test_validate_schema_missing_columns_fails() -> None:
    schema = _minimal_schema()
    df = pd.DataFrame({"asof_date": ["2026-04-23"], "symbol": ["AAPL"]})
    with pytest.raises(RuntimeError, match="Missing required columns"):
        validate_schema(df, schema)


def test_validate_schema_value_outside_range_fails() -> None:
    schema = _minimal_schema()
    df = pd.DataFrame({
        "asof_date": ["2026-04-23"],
        "symbol": ["AAPL"],
        "score": [2.0],  # outside [0, 1]
    })
    with pytest.raises(RuntimeError, match=r"outside \[0\.0, 1\.0\]"):
        validate_schema(df, schema)


def test_validate_schema_multiple_asof_dates_fails() -> None:
    schema = _minimal_schema()
    df = pd.DataFrame({
        "asof_date": ["2026-04-22", "2026-04-23"],
        "symbol": ["AAPL", "MSFT"],
        "score": [0.5, 0.5],
    })
    with pytest.raises(RuntimeError, match="exactly one asof_date"):
        validate_schema(df, schema)


# ---------------------------------------------------------------------------
# assess_csv_against_schema
# ---------------------------------------------------------------------------


def test_assess_csv_against_schema_reports_present_missing_extra(tmp_path: Path) -> None:
    schema = _minimal_schema()
    p = tmp_path / "in.csv"
    pd.DataFrame({
        "asof_date": ["2026-04-23"],
        "symbol": ["AAPL"],
        "extra_col": [42],
    }).to_csv(p, index=False)
    out = assess_csv_against_schema(schema, p)
    assert out["present_required"] == ["asof_date", "symbol"]
    assert out["missing_required"] == ["score"]
    assert out["extra_columns"] == ["extra_col"]
    assert out["required_coverage"] == round(2 / 3, 4)


def test_assess_csv_against_schema_full_coverage(tmp_path: Path) -> None:
    schema = _minimal_schema()
    p = tmp_path / "in.csv"
    pd.DataFrame({
        "asof_date": ["2026-04-23"],
        "symbol": ["AAPL"],
        "score": [0.5],
    }).to_csv(p, index=False)
    out = assess_csv_against_schema(schema, p)
    assert out["missing_required"] == []
    assert out["required_coverage"] == 1.0


# ---------------------------------------------------------------------------
# build_parser
# ---------------------------------------------------------------------------


def test_build_parser_defaults() -> None:
    parser = build_parser()
    args = parser.parse_args([])
    assert isinstance(args.schema, Path)
    assert isinstance(args.input, Path)
    assert isinstance(args.overrides, Path)
    assert args.output_root == Path(".")
    assert args.library_owner == "preuss_steffen"
    assert args.library_version == 1
    assert args.assess_input is None
    assert args.assess_output is None


def test_build_parser_overrides() -> None:
    parser = build_parser()
    args = parser.parse_args([
        "--schema", "/tmp/s.json",
        "--input", "/tmp/in.csv",
        "--overrides", "/tmp/ov.csv",
        "--output-root", "/tmp/root",
        "--library-owner", "alice",
        "--library-version", "7",
        "--assess-input", "/tmp/assess.csv",
        "--assess-output", "/tmp/assess.md",
    ])
    assert args.schema == Path("/tmp/s.json")
    assert args.input == Path("/tmp/in.csv")
    assert args.library_owner == "alice"
    assert args.library_version == 7
    assert args.assess_input == Path("/tmp/assess.csv")
    assert args.assess_output == Path("/tmp/assess.md")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def test_main_assess_input_branch_uses_publisher(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, Any] = {}

    fake_validator = type(
        "M", (),
        {"assess_input_coverage": staticmethod(lambda schema, path: {"x": 1})},
    )
    fake_publisher = type(
        "M", (),
        {"publish_readiness_report": staticmethod(
            lambda assessment, *, output_path: captured.update(
                assessment=assessment, output_path=output_path
            )
        )},
    )
    monkeypatch.setitem(__import__("sys").modules, "scripts.smc_micro_validator", fake_validator)
    monkeypatch.setitem(__import__("sys").modules, "scripts.smc_micro_publisher", fake_publisher)
    monkeypatch.setattr(gsm, "load_schema", lambda path: {"required_columns": []})

    assess_input = tmp_path / "in.csv"
    assess_input.touch()
    monkeypatch.setattr(
        "sys.argv",
        [
            "generate_smc_micro_profiles",
            "--assess-input", str(assess_input),
        ],
    )
    main()
    assert captured["assessment"] == {"x": 1}
    # Default output path under reports/
    assert "in_microstructure_readiness.md" in str(captured["output_path"])


def test_main_assess_input_with_explicit_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, Any] = {}
    fake_validator = type("M", (), {
        "assess_input_coverage": staticmethod(lambda schema, path: {"ok": True})
    })
    fake_publisher = type("M", (), {
        "publish_readiness_report": staticmethod(
            lambda assessment, *, output_path: captured.update(output_path=output_path)
        )
    })
    monkeypatch.setitem(__import__("sys").modules, "scripts.smc_micro_validator", fake_validator)
    monkeypatch.setitem(__import__("sys").modules, "scripts.smc_micro_publisher", fake_publisher)
    monkeypatch.setattr(gsm, "load_schema", lambda path: {"required_columns": []})

    assess_input = tmp_path / "in.csv"
    assess_input.touch()
    out_path = tmp_path / "explicit.md"
    monkeypatch.setattr(
        "sys.argv",
        [
            "generate_smc_micro_profiles",
            "--assess-input", str(assess_input),
            "--assess-output", str(out_path),
        ],
    )
    main()
    assert captured["output_path"] == out_path


def test_main_full_pipeline_invokes_run_generation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, Any] = {}

    def fake_run_generation(**kwargs: Any) -> dict[str, Path]:
        captured.update(kwargs)
        return {"manifest": tmp_path / "manifest.json"}

    monkeypatch.setattr(gsm, "run_generation", fake_run_generation)
    monkeypatch.setattr(
        "sys.argv",
        [
            "generate_smc_micro_profiles",
            "--schema", str(tmp_path / "schema.json"),
            "--input", str(tmp_path / "in.csv"),
            "--overrides", str(tmp_path / "ov.csv"),
            "--output-root", str(tmp_path),
            "--library-owner", "alice",
            "--library-version", "9",
        ],
    )

    main()

    assert captured["library_owner"] == "alice"
    assert captured["library_version"] == 9
    assert captured["output_root"] == tmp_path
    assert captured["schema_path"] == tmp_path / "schema.json"
