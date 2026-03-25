from __future__ import annotations

import open_prep.run_open_prep as rop


class _FakeClient:
    def get_dcf(self, _sym: str):
        return {"dcf": 100.0, "stockPrice": 110.0, "date": "2026-03-25"}


class _FakeExecutor:
    instances: list["_FakeExecutor"] = []

    def __init__(self, max_workers: int):
        self.max_workers = max_workers
        self.shutdown_calls: list[tuple[bool, bool]] = []
        _FakeExecutor.instances.append(self)

    def submit(self, _fn, *_args, **_kwargs):
        return object()

    def shutdown(self, wait: bool = True, cancel_futures: bool = False):
        self.shutdown_calls.append((wait, cancel_futures))


def test_dcf_timeout_uses_non_blocking_executor_shutdown(monkeypatch) -> None:
    _FakeExecutor.instances.clear()

    def _raise_timeout(_futs, timeout=None):
        raise rop.FuturesTimeoutError()

    monkeypatch.setattr(rop, "ThreadPoolExecutor", _FakeExecutor)
    monkeypatch.setattr(rop, "as_completed", _raise_timeout)

    result = rop._fetch_dcf_valuations(
        client=_FakeClient(),  # type: ignore[arg-type]
        symbols=["AAPL", "MSFT"],
    )

    assert result == {}
    assert _FakeExecutor.instances
    # On timeout the executor must not wait for hung workers.
    assert _FakeExecutor.instances[0].shutdown_calls[-1] == (False, True)
