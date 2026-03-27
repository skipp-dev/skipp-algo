"""Paket C – Base-Generator-Cleanup acceptance tests.

Verifies:
  C-DEAD-1  resolve_latest_base_csv is no longer importable from runtime
  C-DEDUP-1 MappingStatus in databento module is identical to runtime
  C-DEDUP-2 infer_asset_type in databento module is identical to runtime
  C-DEDUP-3 infer_universe_bucket in databento module is identical to runtime
  C-DEDUP-4 ETF_KEYWORDS in databento module is identical to runtime
  C-DEDUP-5 databento module no longer defines local dataclass import
  C-DEDUP-6 infer_asset_type compat – single-arg call still works
  C-DEDUP-7 infer_universe_bucket compat – all buckets reachable
"""

from __future__ import annotations

import importlib
import inspect


# ---------------------------------------------------------------------------
# C-DEAD-1: resolve_latest_base_csv removed
# ---------------------------------------------------------------------------

def test_resolve_latest_base_csv_not_importable():
    """Dead function resolve_latest_base_csv must no longer exist in runtime."""
    import scripts.smc_microstructure_base_runtime as rt
    assert not hasattr(rt, "resolve_latest_base_csv")


# ---------------------------------------------------------------------------
# C-DEDUP-1 .. C-DEDUP-4: shared objects are the *same* objects
# ---------------------------------------------------------------------------

def test_mapping_status_is_same_object():
    from scripts.smc_microstructure_base_runtime import MappingStatus as rt_cls
    from scripts.generate_smc_micro_base_from_databento import MappingStatus as db_cls
    assert rt_cls is db_cls


def test_infer_asset_type_is_same_object():
    from scripts.smc_microstructure_base_runtime import infer_asset_type as rt_fn
    from scripts.generate_smc_micro_base_from_databento import infer_asset_type as db_fn
    assert rt_fn is db_fn


def test_infer_universe_bucket_is_same_object():
    from scripts.smc_microstructure_base_runtime import infer_universe_bucket as rt_fn
    from scripts.generate_smc_micro_base_from_databento import infer_universe_bucket as db_fn
    assert rt_fn is db_fn


def test_etf_keywords_is_same_object():
    from scripts.smc_microstructure_base_runtime import ETF_KEYWORDS as rt_kw
    from scripts.generate_smc_micro_base_from_databento import ETF_KEYWORDS as db_kw
    assert rt_kw is db_kw


# ---------------------------------------------------------------------------
# C-DEDUP-5: no local dataclass import (MappingStatus is imported, not defined)
# ---------------------------------------------------------------------------

def test_databento_module_does_not_import_dataclass():
    """dataclass decorator should no longer be imported in the databento module."""
    src = inspect.getsource(
        importlib.import_module("scripts.generate_smc_micro_base_from_databento")
    )
    assert "from dataclasses import dataclass" not in src


# ---------------------------------------------------------------------------
# C-DEDUP-6 & C-DEDUP-7: functional compatibility after dedup
# ---------------------------------------------------------------------------

def test_infer_asset_type_single_arg_compat():
    """infer_asset_type must still work with a single positional arg."""
    from scripts.generate_smc_micro_base_from_databento import infer_asset_type
    assert infer_asset_type("SPDR S&P 500 ETF Trust") == "etf"
    assert infer_asset_type("Apple Inc.") == "stock"


def test_infer_universe_bucket_all_buckets():
    """All universe bucket paths must remain reachable."""
    from scripts.generate_smc_micro_base_from_databento import infer_universe_bucket
    assert infer_universe_bucket("etf", None) == "us_etf"
    assert infer_universe_bucket("stock", 50_000_000_000) == "us_largecap"
    assert infer_universe_bucket("stock", 5_000_000_000) == "us_midcap"
    assert infer_universe_bucket("stock", 500_000_000) == "us_smallcap"
    assert infer_universe_bucket("stock", None) == "us_unknown"
