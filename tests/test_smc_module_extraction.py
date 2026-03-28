"""Boundary tests verifying the module-extraction refactor.

These tests ensure:
1. All re-exports from `smc_microstructure_base_runtime` still resolve.
2. The three extracted modules can be imported directly.
3. No circular imports.
4. Canonical and re-export paths point to the same objects.
"""
from __future__ import annotations

import importlib
import sys
import types

import pytest


# ── 1. Direct import of extracted modules ────────────────────────────

class TestDirectImports:
    """Each extracted module must import cleanly without side-effects."""

    def test_import_publish_guard(self):
        mod = importlib.import_module("scripts.smc_micro_publish_guard")
        assert isinstance(mod, types.ModuleType)
        for name in (
            "evaluate_micro_library_publish_guard",
            "inspect_generated_micro_library_contract",
            "publish_micro_library_to_tradingview",
        ):
            assert hasattr(mod, name), f"missing {name}"

    def test_import_streamlit_app(self):
        mod = importlib.import_module("scripts.smc_micro_streamlit_app")
        assert isinstance(mod, types.ModuleType)
        for name in (
            "_resolve_ui_dataset_options",
            "list_generated_base_csvs",
            "resolve_base_csv_selection",
            "resolve_base_csv_action_target",
            "run_streamlit_micro_base_app",
        ):
            assert hasattr(mod, name), f"missing {name}"

    def test_import_session_detail(self):
        mod = importlib.import_module("scripts.smc_databento_session_detail")
        assert isinstance(mod, types.ModuleType)
        for name in (
            "PREMARKET_START_ET",
            "REGULAR_OPEN_ET",
            "REGULAR_CLOSE_ET",
            "AFTERHOURS_END_ET",
            "PREMARKET_MINUTES",
            "REGULAR_MINUTES",
            "AFTERHOURS_MINUTES",
            "collect_full_universe_session_minute_detail",
            "_universe_fingerprint",
            "_coverage_stats",
            "_assert_complete_symbol_coverage",
        ):
            assert hasattr(mod, name), f"missing {name}"


# ── 2. Re-exports from runtime still resolve ────────────────────────

class TestRuntimeReExports:
    """Importing the extracted symbols from the original runtime must work."""

    def test_publish_guard_reexports(self):
        from scripts.smc_microstructure_base_runtime import (
            evaluate_micro_library_publish_guard,
            inspect_generated_micro_library_contract,
            publish_micro_library_to_tradingview,
        )
        assert callable(evaluate_micro_library_publish_guard)
        assert callable(inspect_generated_micro_library_contract)
        assert callable(publish_micro_library_to_tradingview)

    def test_streamlit_app_reexports(self):
        from scripts.smc_microstructure_base_runtime import (
            _resolve_ui_dataset_options,
            list_generated_base_csvs,
            resolve_base_csv_selection,
            resolve_base_csv_action_target,
            run_streamlit_micro_base_app,
        )
        assert callable(list_generated_base_csvs)
        assert callable(resolve_base_csv_selection)
        assert callable(resolve_base_csv_action_target)
        assert callable(run_streamlit_micro_base_app)

    def test_session_detail_reexports(self):
        from scripts.smc_microstructure_base_runtime import (
            PREMARKET_START_ET,
            REGULAR_OPEN_ET,
            REGULAR_CLOSE_ET,
            AFTERHOURS_END_ET,
            PREMARKET_MINUTES,
            REGULAR_MINUTES,
            AFTERHOURS_MINUTES,
            collect_full_universe_session_minute_detail,
        )
        assert callable(collect_full_universe_session_minute_detail)
        from datetime import time
        assert isinstance(PREMARKET_START_ET, time)
        assert isinstance(REGULAR_OPEN_ET, time)
        assert isinstance(REGULAR_CLOSE_ET, time)
        assert isinstance(AFTERHOURS_END_ET, time)
        assert isinstance(PREMARKET_MINUTES, int)
        assert isinstance(REGULAR_MINUTES, int)
        assert isinstance(AFTERHOURS_MINUTES, int)


# ── 3. Canonical vs re-export identity ──────────────────────────────

class TestIdentity:
    """Re-exported names must be the exact same objects, not copies."""

    def test_publish_guard_identity(self):
        from scripts.smc_micro_publish_guard import evaluate_micro_library_publish_guard as canonical
        from scripts.smc_microstructure_base_runtime import evaluate_micro_library_publish_guard as reexport
        assert canonical is reexport

    def test_streamlit_app_identity(self):
        from scripts.smc_micro_streamlit_app import run_streamlit_micro_base_app as canonical
        from scripts.smc_microstructure_base_runtime import run_streamlit_micro_base_app as reexport
        assert canonical is reexport

    def test_session_detail_identity(self):
        from scripts.smc_databento_session_detail import collect_full_universe_session_minute_detail as canonical
        from scripts.smc_microstructure_base_runtime import collect_full_universe_session_minute_detail as reexport
        assert canonical is reexport

    def test_session_constant_identity(self):
        from scripts.smc_databento_session_detail import PREMARKET_START_ET as canonical
        from scripts.smc_microstructure_base_runtime import PREMARKET_START_ET as reexport
        assert canonical is reexport


# ── 4. No circular imports ──────────────────────────────────────────

class TestNoCircularImports:
    """Extracted modules must not import from runtime (one-directional)."""

    def test_publish_guard_does_not_import_runtime(self):
        import scripts.smc_micro_publish_guard as mod
        import ast
        tree = ast.parse(open(mod.__file__).read())
        imported_modules = {
            alias.name if isinstance(node, ast.Import) else node.module
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom)) and (node.module if isinstance(node, ast.ImportFrom) else None) is not None or isinstance(node, ast.Import)
            for alias in (node.names if isinstance(node, ast.Import) else [node])
        }
        for mod_name in imported_modules:
            if mod_name and "smc_microstructure_base_runtime" in str(mod_name):
                pytest.fail(f"publish_guard imports from runtime: {mod_name}")

    def test_session_detail_does_not_import_runtime(self):
        import scripts.smc_databento_session_detail as mod
        import ast
        tree = ast.parse(open(mod.__file__).read())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and "smc_microstructure_base_runtime" in node.module:
                pytest.fail(f"session_detail imports from runtime: {node.module}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if "smc_microstructure_base_runtime" in alias.name:
                        pytest.fail(f"session_detail imports from runtime: {alias.name}")

    # smc_micro_streamlit_app intentionally imports from runtime
    # (generate_pine_library_from_base, run_databento_base_scan_pipeline),
    # which is fine — one direction: streamlit_app ← runtime.


# ── 5. Simple functional behavior checks ────────────────────────────

class TestFunctionalBehavior:
    """Spot-check that extracted helpers behave correctly."""

    def test_list_generated_base_csvs_empty(self, tmp_path):
        from scripts.smc_micro_streamlit_app import list_generated_base_csvs
        assert list_generated_base_csvs(tmp_path) == []

    def test_resolve_base_csv_selection_empty(self):
        from scripts.smc_micro_streamlit_app import resolve_base_csv_selection
        assert resolve_base_csv_selection([], None) is None

    def test_resolve_base_csv_selection_single(self, tmp_path):
        from scripts.smc_micro_streamlit_app import resolve_base_csv_selection
        path = tmp_path / "test.csv"
        path.touch()
        assert resolve_base_csv_selection([path], None) == path

    def test_resolve_base_csv_action_target_no_candidates(self):
        from scripts.smc_micro_streamlit_app import resolve_base_csv_action_target
        target, error = resolve_base_csv_action_target([], None)
        assert target is None
        assert error is not None

    def test_resolve_base_csv_action_target_multiple_no_selection(self, tmp_path):
        from scripts.smc_micro_streamlit_app import resolve_base_csv_action_target
        p1, p2 = tmp_path / "a.csv", tmp_path / "b.csv"
        p1.touch(); p2.touch()
        target, error = resolve_base_csv_action_target([p1, p2], None)
        assert target is None
        assert error is not None

    def test_universe_fingerprint_deterministic(self):
        from scripts.smc_databento_session_detail import _universe_fingerprint
        symbols = ["AAPL", "MSFT", "GOOG"]
        fp1 = _universe_fingerprint(symbols)
        fp2 = _universe_fingerprint(symbols)
        assert fp1 == fp2
        # Different symbols → different fingerprint
        fp3 = _universe_fingerprint(["AAPL", "TSLA"])
        assert fp3 != fp1
