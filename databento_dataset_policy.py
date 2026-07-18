"""Fail-closed Databento dataset roles and schema contracts.

Dataset identifiers are not quality tiers.  A consolidated equity feed, a
single-venue order book, and an options feed cannot safely replace one another.
This module makes the intended market coverage part of the runtime contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DatasetPolicyError(ValueError):
    """Raised when an override would change a dataset role's semantics."""


class DatasetRole(StrEnum):
    EQUITY_LIVE_BROAD = "equity_live_broad"
    EQUITY_INTRADAY_PARITY = "equity_intraday_parity"
    EQUITY_EOD_CANONICAL = "equity_eod_canonical"
    VENUE_NASDAQ_DEPTH = "venue_nasdaq_depth"
    VENUE_NYSE = "venue_nyse"
    VENUE_AMERICAN = "venue_american"
    VENUE_ARCA = "venue_arca"
    EQUITY_BROAD_TRADES_RESEARCH = "equity_broad_trades_research"
    OPTIONS_LIVE = "options_live"
    FUTURES_RESEARCH = "futures_research"
    OVERNIGHT_RESEARCH = "overnight_research"


class DatasetMode(StrEnum):
    LIVE = "live"
    HISTORICAL = "historical"


class DatasetCoverage(StrEnum):
    CONSOLIDATED = "consolidated"
    SINGLE_VENUE = "single_venue"
    OPTIONS = "options"
    FUTURES = "futures"
    OVERNIGHT = "overnight"


@dataclass(frozen=True)
class DatasetContract:
    role: DatasetRole
    dataset: str
    coverage: DatasetCoverage
    modes: frozenset[DatasetMode]
    schemas: frozenset[str]


_INTRADAY_SCHEMAS = frozenset(
    {"ohlcv-1s", "ohlcv-1m", "ohlcv-1h", "trades", "mbp-1", "bbo-1s", "bbo-1m"}
)
_VENUE_SCHEMAS = frozenset(
    {
        "ohlcv-1s",
        "ohlcv-1m",
        "trades",
        "mbp-1",
        "mbp-10",
        "mbo",
        "imbalance",
        "definition",
        "statistics",
    }
)


DATASET_CONTRACTS: dict[DatasetRole, DatasetContract] = {
    DatasetRole.EQUITY_LIVE_BROAD: DatasetContract(
        DatasetRole.EQUITY_LIVE_BROAD,
        "EQUS.MINI",
        DatasetCoverage.CONSOLIDATED,
        frozenset({DatasetMode.LIVE}),
        _INTRADAY_SCHEMAS,
    ),
    DatasetRole.EQUITY_INTRADAY_PARITY: DatasetContract(
        DatasetRole.EQUITY_INTRADAY_PARITY,
        "EQUS.MINI",
        DatasetCoverage.CONSOLIDATED,
        frozenset({DatasetMode.LIVE, DatasetMode.HISTORICAL}),
        _INTRADAY_SCHEMAS,
    ),
    DatasetRole.EQUITY_EOD_CANONICAL: DatasetContract(
        DatasetRole.EQUITY_EOD_CANONICAL,
        "EQUS.SUMMARY",
        DatasetCoverage.CONSOLIDATED,
        frozenset({DatasetMode.HISTORICAL}),
        frozenset({"ohlcv-1d", "statistics", "definition"}),
    ),
    DatasetRole.VENUE_NASDAQ_DEPTH: DatasetContract(
        DatasetRole.VENUE_NASDAQ_DEPTH,
        "XNAS.ITCH",
        DatasetCoverage.SINGLE_VENUE,
        frozenset({DatasetMode.LIVE, DatasetMode.HISTORICAL}),
        _VENUE_SCHEMAS,
    ),
    DatasetRole.VENUE_NYSE: DatasetContract(
        DatasetRole.VENUE_NYSE,
        "XNYS.PILLAR",
        DatasetCoverage.SINGLE_VENUE,
        frozenset({DatasetMode.LIVE, DatasetMode.HISTORICAL}),
        _VENUE_SCHEMAS,
    ),
    DatasetRole.VENUE_AMERICAN: DatasetContract(
        DatasetRole.VENUE_AMERICAN,
        "XASE.PILLAR",
        DatasetCoverage.SINGLE_VENUE,
        frozenset({DatasetMode.LIVE, DatasetMode.HISTORICAL}),
        _VENUE_SCHEMAS,
    ),
    DatasetRole.VENUE_ARCA: DatasetContract(
        DatasetRole.VENUE_ARCA,
        "ARCX.PILLAR",
        DatasetCoverage.SINGLE_VENUE,
        frozenset({DatasetMode.HISTORICAL}),
        _VENUE_SCHEMAS,
    ),
    DatasetRole.EQUITY_BROAD_TRADES_RESEARCH: DatasetContract(
        DatasetRole.EQUITY_BROAD_TRADES_RESEARCH,
        "XNAS.BASIC",
        DatasetCoverage.CONSOLIDATED,
        frozenset({DatasetMode.HISTORICAL}),
        frozenset({"trades", "ohlcv-1s", "ohlcv-1m", "definition"}),
    ),
    DatasetRole.OPTIONS_LIVE: DatasetContract(
        DatasetRole.OPTIONS_LIVE,
        "OPRA.PILLAR",
        DatasetCoverage.OPTIONS,
        frozenset({DatasetMode.LIVE}),
        frozenset({"tcbbo", "trades", "definition"}),
    ),
    DatasetRole.FUTURES_RESEARCH: DatasetContract(
        DatasetRole.FUTURES_RESEARCH,
        "GLBX.MDP3",
        DatasetCoverage.FUTURES,
        frozenset({DatasetMode.HISTORICAL}),
        _VENUE_SCHEMAS,
    ),
    DatasetRole.OVERNIGHT_RESEARCH: DatasetContract(
        DatasetRole.OVERNIGHT_RESEARCH,
        "OCEA.MEMOIR",
        DatasetCoverage.OVERNIGHT,
        frozenset({DatasetMode.HISTORICAL}),
        _VENUE_SCHEMAS,
    ),
}


def dataset_contract(role: DatasetRole | str) -> DatasetContract:
    """Return the immutable contract for *role*."""
    try:
        normalized_role = role if isinstance(role, DatasetRole) else DatasetRole(str(role))
    except ValueError as exc:
        raise DatasetPolicyError(f"unknown Databento dataset role: {role!r}") from exc
    return DATASET_CONTRACTS[normalized_role]


def resolve_dataset(
    role: DatasetRole | str,
    *,
    requested_dataset: str | None = None,
    schema: str | None = None,
    mode: DatasetMode | str | None = None,
) -> str:
    """Resolve *role* without allowing cross-coverage fallback.

    An override is accepted only when it names the role's canonical dataset.
    This intentionally rejects the former behavior of choosing the first item
    returned by ``metadata.list_datasets()``.
    """
    contract = dataset_contract(role)
    requested = str(requested_dataset or "").strip().upper()
    if requested and requested != contract.dataset:
        raise DatasetPolicyError(
            f"dataset {requested!r} is invalid for role {contract.role.value!r}; "
            f"expected {contract.dataset!r} ({contract.coverage.value})"
        )
    normalized_schema = str(schema or "").strip().lower()
    if normalized_schema and normalized_schema not in contract.schemas:
        raise DatasetPolicyError(
            f"schema {normalized_schema!r} is invalid for role {contract.role.value!r}"
        )
    if mode is not None:
        try:
            normalized_mode = mode if isinstance(mode, DatasetMode) else DatasetMode(str(mode))
        except ValueError as exc:
            raise DatasetPolicyError(f"unknown Databento mode: {mode!r}") from exc
        if normalized_mode not in contract.modes:
            raise DatasetPolicyError(
                f"mode {normalized_mode.value!r} is invalid for role {contract.role.value!r}"
            )
    return contract.dataset


def dataset_manifest_fields(role: DatasetRole | str, *, schema: str, mode: DatasetMode | str) -> dict[str, str]:
    """Return stable dataset provenance fields for manifests and telemetry."""
    contract = dataset_contract(role)
    dataset = resolve_dataset(contract.role, schema=schema, mode=mode)
    normalized_mode = mode.value if isinstance(mode, DatasetMode) else DatasetMode(str(mode)).value
    return {
        "dataset": dataset,
        "dataset_role": contract.role.value,
        "dataset_schema": str(schema).strip().lower(),
        "dataset_mode": normalized_mode,
        "dataset_coverage": contract.coverage.value,
    }
