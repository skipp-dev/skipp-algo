from __future__ import annotations

from databento_access import DatasetAccessStatus
from scripts.probe_databento_entitlement import format_status, run_probe


class _Metadata:
    def list_datasets(self):
        return ["OPRA.PILLAR"]

    def get_dataset_range(self, *, dataset: str):
        assert dataset == "OPRA.PILLAR"
        return {"start": "2023-01-01", "end": "2026-07-17"}


class _Client:
    metadata = _Metadata()


def test_historical_access_does_not_claim_live_access() -> None:
    statuses = run_probe(
        _Client(),
        api_key="unused",
        datasets=["OPRA.PILLAR"],
        probe_live=False,
        live_schema="trades",
        live_symbol="AAPL.OPT",
        live_timeout_seconds=0.1,
    )
    assert statuses[0].historical_range_available is True
    assert statuses[0].live_checked is False
    assert "live=UNKNOWN" in format_status(statuses[0])


def test_formatter_preserves_catalog_and_access_as_separate_facts() -> None:
    status = DatasetAccessStatus(
        dataset="TEST.DATASET",
        catalog_present=True,
        historical_range_available=False,
        historical_start=None,
        historical_end=None,
        live_checked=True,
        live_entitled=None,
        reason="live_probe_timeout_no_record",
    )
    text = format_status(status)
    assert "catalog=YES" in text
    assert "historical=NO" in text
    assert "live=UNKNOWN" in text
