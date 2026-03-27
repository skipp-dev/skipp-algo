"""Tests for the public API boundary of databento_utils and databento_provider.

Ensures that:
1. All public (unprefixed) aliases in ``databento_utils`` resolve and point
   to the same underlying implementation as their underscore-prefixed originals.
2. ``databento_provider.list_accessible_datasets`` is importable and callable.
3. ``scripts.smc_microstructure_base_runtime`` no longer references the
   screener monolith (``databento_volatility_screener``).
"""

from __future__ import annotations

import importlib
import inspect
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import databento_utils


# ── 1. Public-alias parity ──────────────────────────────────────────────────

_EXPECTED_PUBLIC_ALIASES: list[tuple[str, str]] = [
    ("clamp_request_end", "_clamp_request_end"),
    ("extract_unresolved_symbols_from_warning_messages", "_extract_unresolved_symbols_from_warning_messages"),
    ("iter_symbol_batches", "_iter_symbol_batches"),
    ("read_cached_frame", "_read_cached_frame"),
    ("store_to_frame", "_store_to_frame"),
    ("trade_day_cache_max_age_seconds", "_trade_day_cache_max_age_seconds"),
    ("validate_frame_columns", "_validate_frame_columns"),
    ("warn_with_redacted_exception", "_warn_with_redacted_exception"),
    ("write_cached_frame", "_write_cached_frame"),
]


class TestPublicAliasesExist:
    """Every public alias must be importable and point to the private impl."""

    @pytest.mark.parametrize("public_name,private_name", _EXPECTED_PUBLIC_ALIASES)
    def test_alias_is_same_object(self, public_name: str, private_name: str) -> None:
        public_obj = getattr(databento_utils, public_name)
        private_obj = getattr(databento_utils, private_name)
        assert public_obj is private_obj, (
            f"databento_utils.{public_name} is not the same object as "
            f"databento_utils.{private_name}"
        )

    @pytest.mark.parametrize("public_name,private_name", _EXPECTED_PUBLIC_ALIASES)
    def test_alias_is_callable(self, public_name: str, private_name: str) -> None:
        assert callable(getattr(databento_utils, public_name))


class TestPublicConstantsAccessible:
    """Constants and non-underscore functions must be directly importable."""

    @pytest.mark.parametrize(
        "name",
        [
            "US_EASTERN_TZ",
            "PREFERRED_DATABENTO_DATASETS",
            "build_cache_path",
            "choose_default_dataset",
            "resolve_display_timezone",
            "normalize_symbol_for_databento",
        ],
    )
    def test_constant_or_function_exists(self, name: str) -> None:
        assert hasattr(databento_utils, name), f"databento_utils.{name} missing"


# ── 2. Provider-level list_accessible_datasets ──────────────────────────────

class TestProviderListAccessibleDatasets:
    """``list_accessible_datasets`` lives in ``databento_provider``."""

    def test_importable(self) -> None:
        from databento_provider import list_accessible_datasets
        assert callable(list_accessible_datasets)

    def test_delegates_to_provider(self) -> None:
        """Calling list_accessible_datasets instantiates DabentoProvider."""
        from databento_provider import list_accessible_datasets

        mock_client = MagicMock()
        mock_client.metadata.list_datasets.return_value = ["DBEQ.BASIC", "XNAS.ITCH"]
        with patch(
            "databento_provider.DabentoProvider.__init__",
            return_value=None,
        ) as mock_init, patch.object(
            importlib.import_module("databento_provider").DabentoProvider,
            "list_datasets",
            return_value=["DBEQ.BASIC", "XNAS.ITCH"],
        ):
            result = list_accessible_datasets("fake-key")
            mock_init.assert_called_once_with("fake-key")
            assert isinstance(result, list)


# ── 3. Base runtime screener-free ───────────────────────────────────────────

class TestBaseRuntimeScreenerFree:
    """smc_microstructure_base_runtime must not import from the screener."""

    def test_no_screener_import_in_source(self) -> None:
        source_path = (
            Path(__file__).resolve().parent.parent
            / "scripts"
            / "smc_microstructure_base_runtime.py"
        )
        source = source_path.read_text(encoding="utf-8")
        assert "from databento_volatility_screener" not in source, (
            "base runtime still imports from databento_volatility_screener"
        )
        assert "import databento_volatility_screener" not in source, (
            "base runtime still imports databento_volatility_screener"
        )

    def test_no_underscore_imports_from_databento_utils(self) -> None:
        """Import block should use only public (non-underscore) names."""
        source_path = (
            Path(__file__).resolve().parent.parent
            / "scripts"
            / "smc_microstructure_base_runtime.py"
        )
        source = source_path.read_text(encoding="utf-8")
        # Find the import block from databento_utils
        in_import_block = False
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("from databento_utils import"):
                in_import_block = True
                continue
            if in_import_block:
                if stripped == ")":
                    break
                # Each imported name (strip trailing comma)
                name = stripped.rstrip(",").strip()
                if name and not name.startswith("#"):
                    assert not name.startswith("_"), (
                        f"base runtime imports underscore-prefixed name "
                        f"'{name}' from databento_utils"
                    )
