"""Per-client dataset-cache scoping (PR-C, audit 2026-05-10).

Pre-PR-C, ``_dataset_cache`` was a single module-global ``str | None``.
The first client's preferred dataset was therefore returned for every
subsequent ``_pick_dataset`` call, regardless of which API key (and
which Databento entitlement set) was in use.  These tests pin that the
cache is now scoped per client fingerprint and that distinct keys never
collide.
"""

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


def test_dataset_cache_per_client_isolation() -> None:
    """Two clients with disjoint dataset entitlements must not collide."""
    # Client A only sees XNAS.ITCH.
    client_a = _make_client(["XNAS.ITCH"])
    ds_a = terminal_databento._pick_dataset(client_a, "key-A")

    # Client B only sees DBEQ.BASIC.  Pre-fix, this returned client A's
    # cached XNAS.ITCH even though B has no entitlement for it.
    client_b = _make_client(["DBEQ.BASIC"])
    ds_b = terminal_databento._pick_dataset(client_b, "key-B")

    assert ds_a == "XNAS.ITCH"
    assert ds_b == "DBEQ.BASIC"


def test_same_client_uses_cached_dataset() -> None:
    """Second call with the same key must not re-hit ``list_datasets``."""
    calls = {"n": 0}

    def list_datasets() -> list[str]:
        calls["n"] += 1
        return ["DBEQ.BASIC"]

    client = SimpleNamespace(metadata=SimpleNamespace(list_datasets=list_datasets))

    first = terminal_databento._pick_dataset(client, "key-cached")
    second = terminal_databento._pick_dataset(client, "key-cached")

    assert first == second == "DBEQ.BASIC"
    assert calls["n"] == 1, "Cached fingerprint must short-circuit list_datasets"


def test_distinct_keys_each_trigger_lookup() -> None:
    """Different fingerprints must each perform their own dataset lookup."""
    calls = {"n": 0}

    def list_datasets() -> list[str]:
        calls["n"] += 1
        return ["DBEQ.BASIC"]

    client = SimpleNamespace(metadata=SimpleNamespace(list_datasets=list_datasets))

    terminal_databento._pick_dataset(client, "key-1")
    terminal_databento._pick_dataset(client, "key-2")
    terminal_databento._pick_dataset(client, "key-1")  # cached
    terminal_databento._pick_dataset(client, "key-2")  # cached

    assert calls["n"] == 2


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


def test_list_datasets_failure_caches_fallback_per_key() -> None:
    """Even on error, the fallback must be scoped per key."""

    def boom() -> list[str]:
        raise RuntimeError("network down")

    client = SimpleNamespace(metadata=SimpleNamespace(list_datasets=boom))

    ds = terminal_databento._pick_dataset(client, "broken-key")
    assert ds == "DBEQ.BASIC"
    # Cache hit on second call with same key, no re-raise.
    assert terminal_databento._pick_dataset(client, "broken-key") == "DBEQ.BASIC"
