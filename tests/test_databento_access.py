from __future__ import annotations

from types import SimpleNamespace

from databento_access import inspect_historical_access, list_catalog_datasets_from_client


def _client(*, datasets, dataset_range=None, error=None):
    def get_dataset_range(*, dataset):
        assert dataset
        if error is not None:
            raise error
        return dataset_range

    return SimpleNamespace(
        metadata=SimpleNamespace(
            list_datasets=lambda: datasets,
            get_dataset_range=get_dataset_range,
        )
    )


def test_catalog_list_is_normalized_but_not_called_entitlements() -> None:
    client = _client(datasets=["xnas.itch", "OPRA.PILLAR"], dataset_range={})
    assert list_catalog_datasets_from_client(client) == ["OPRA.PILLAR", "XNAS.ITCH"]


def test_historical_range_does_not_claim_live_access() -> None:
    status = inspect_historical_access(
        _client(
            datasets=["OPRA.PILLAR"],
            dataset_range={"start": "2023-01-01", "end": "2026-07-18"},
        ),
        "opra.pillar",
    )
    assert status.catalog_present is True
    assert status.historical_range_available is True
    assert status.historical_start == "2023-01-01"
    assert status.live_checked is False
    assert status.live_entitled is None


def test_catalog_presence_without_range_is_not_access() -> None:
    status = inspect_historical_access(
        _client(datasets=["GLBX.MDP3"], error=RuntimeError("license denied")),
        "GLBX.MDP3",
    )
    assert status.catalog_present is True
    assert status.historical_range_available is False
    assert status.live_entitled is None
    assert status.reason.startswith("historical_range_license_or_auth_denied:")


def test_network_failure_is_unknown_not_no_access() -> None:
    status = inspect_historical_access(
        _client(datasets=["GLBX.MDP3"], error=TimeoutError("network timeout")),
        "GLBX.MDP3",
    )
    assert status.historical_range_available is None
    assert status.reason.startswith("historical_range_network_error:")
