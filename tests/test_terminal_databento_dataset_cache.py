"""Fail-closed canonical daily-dataset selection and cache scoping."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import terminal_databento


@pytest.fixture(autouse=True)
def _reset_cache():
    terminal_databento._reset_dataset_cache()
    yield
    terminal_databento._reset_dataset_cache()


def _make_client(datasets: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        metadata=SimpleNamespace(list_datasets=lambda: datasets),
    )


def test_dataset_role_is_independent_of_catalog_order() -> None:
    client_a = _make_client(["XNAS.ITCH"])
    ds_a = terminal_databento._pick_dataset(client_a, "key-A")
    client_b = _make_client(["DBEQ.BASIC"])
    ds_b = terminal_databento._pick_dataset(client_b, "key-B")
    assert ds_a == ds_b == "EQUS.SUMMARY"


def test_same_client_uses_cached_dataset_without_catalog_lookup() -> None:
    calls = {"n": 0}

    def list_datasets() -> list[str]:
        calls["n"] += 1
        return ["DBEQ.BASIC"]

    client = SimpleNamespace(metadata=SimpleNamespace(list_datasets=list_datasets))

    first = terminal_databento._pick_dataset(client, "key-cached")
    second = terminal_databento._pick_dataset(client, "key-cached")

    assert first == second == "EQUS.SUMMARY"
    assert calls["n"] == 0


def test_distinct_keys_never_trigger_catalog_lookup() -> None:
    calls = {"n": 0}

    def list_datasets() -> list[str]:
        calls["n"] += 1
        return ["DBEQ.BASIC"]

    client = SimpleNamespace(metadata=SimpleNamespace(list_datasets=list_datasets))

    terminal_databento._pick_dataset(client, "key-1")
    terminal_databento._pick_dataset(client, "key-2")
    terminal_databento._pick_dataset(client, "key-1")  # cached
    terminal_databento._pick_dataset(client, "key-2")  # cached

    assert calls["n"] == 0


def test_client_fingerprint_is_stable_and_opaque() -> None:
    """Fingerprint must not be the raw key and must be deterministic."""
    fp1 = terminal_databento._client_fingerprint("super-secret-key")
    fp2 = terminal_databento._client_fingerprint("super-secret-key")
    fp_other = terminal_databento._client_fingerprint("other-key")

    assert fp1 == fp2
    assert fp1 != fp_other
    assert "super-secret-key" not in fp1
    # 16 hex chars
    assert len(fp1) == 16
    int(fp1, 16)


def test_reset_helper_clears_all_fingerprints() -> None:
    client = _make_client(["DBEQ.BASIC"])
    terminal_databento._pick_dataset(client, "key-X")
    assert terminal_databento._dataset_cache  # populated

    terminal_databento._reset_dataset_cache()
    assert terminal_databento._dataset_cache == {}


def test_catalog_failure_cannot_change_canonical_role() -> None:

    def boom() -> list[str]:
        raise RuntimeError("network down")

    client = SimpleNamespace(metadata=SimpleNamespace(list_datasets=boom))

    ds = terminal_databento._pick_dataset(client, "broken-key")
    assert ds == "EQUS.SUMMARY"
    assert terminal_databento._pick_dataset(client, "broken-key") == "EQUS.SUMMARY"


def test_cross_role_override_fails_before_provider_lookup(monkeypatch) -> None:
    monkeypatch.setenv("DATABENTO_EQUITY_EOD_DATASET", "XNAS.ITCH")
    client = _make_client(["XNAS.ITCH"])
    with pytest.raises(ValueError, match="invalid for role"):
        terminal_databento._pick_dataset(client, "key-invalid")
