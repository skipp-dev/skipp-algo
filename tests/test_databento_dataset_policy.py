from __future__ import annotations

import pytest

from databento_dataset_policy import (
    DatasetMode,
    DatasetPolicyError,
    DatasetRole,
    dataset_manifest_fields,
    resolve_dataset,
)


@pytest.mark.parametrize(
    ("role", "dataset"),
    [
        (DatasetRole.EQUITY_LIVE_BROAD, "EQUS.MINI"),
        (DatasetRole.EQUITY_INTRADAY_PARITY, "EQUS.MINI"),
        (DatasetRole.EQUITY_EOD_CANONICAL, "EQUS.SUMMARY"),
        (DatasetRole.VENUE_NASDAQ_DEPTH, "XNAS.ITCH"),
        (DatasetRole.VENUE_NYSE, "XNYS.PILLAR"),
        (DatasetRole.VENUE_AMERICAN, "XASE.PILLAR"),
        (DatasetRole.VENUE_ARCA, "ARCX.PILLAR"),
        (DatasetRole.OPTIONS_LIVE, "OPRA.PILLAR"),
    ],
)
def test_roles_resolve_to_canonical_dataset(role: DatasetRole, dataset: str) -> None:
    assert resolve_dataset(role) == dataset


def test_override_is_case_insensitive_but_not_cross_coverage() -> None:
    assert (
        resolve_dataset(
            DatasetRole.EQUITY_INTRADAY_PARITY,
            requested_dataset=" equs.mini ",
        )
        == "EQUS.MINI"
    )
    with pytest.raises(DatasetPolicyError, match="invalid for role"):
        resolve_dataset(
            DatasetRole.EQUITY_INTRADAY_PARITY,
            requested_dataset="XNAS.ITCH",
        )


def test_schema_and_mode_fail_closed() -> None:
    with pytest.raises(DatasetPolicyError, match="schema"):
        resolve_dataset(DatasetRole.EQUITY_EOD_CANONICAL, schema="ohlcv-1m")
    with pytest.raises(DatasetPolicyError, match="mode"):
        resolve_dataset(
            DatasetRole.EQUITY_EOD_CANONICAL,
            schema="ohlcv-1d",
            mode=DatasetMode.LIVE,
        )


def test_manifest_fields_include_semantics() -> None:
    assert dataset_manifest_fields(
        DatasetRole.EQUITY_EOD_CANONICAL,
        schema="ohlcv-1d",
        mode=DatasetMode.HISTORICAL,
    ) == {
        "dataset": "EQUS.SUMMARY",
        "dataset_role": "equity_eod_canonical",
        "dataset_schema": "ohlcv-1d",
        "dataset_mode": "historical",
        "dataset_coverage": "consolidated",
    }
