"""Regression: ``FMPClient.get_batch_quotes`` must honor a batch-level deadline.

PIPELINE-lane finding (2026-07-05): the concurrent branch used
``as_completed(future_map)`` with **no** timeout inside a
``with ThreadPoolExecutor`` that joins on exit, so a single stalled/slow FMP
endpoint blocked the entire macro breadth fetch — and therefore the daily
open-prep run — until every worker's ``retry_attempts × timeout`` budget was
exhausted (waves of that for a saturated pool). The fix derives a batch
deadline; workers still running past it are recorded as failed and the run
continues with partial results, with the executor shut down WITHOUT joining
the stragglers (``shutdown(wait=False, cancel_futures=True)``).

This mirrors the ``as_completed(timeout=…)`` + shutdown-policy pattern already
used by every batch loop in ``run_open_prep.py``.
"""

from __future__ import annotations

import threading
import time

from open_prep.macro import FMPClient


def _make_client(**kwargs: object) -> FMPClient:
    # api_key is irrelevant here: _execute_get is stubbed in every test.
    return FMPClient(api_key="test-key", **kwargs)  # type: ignore[arg-type]


class TestBatchQuoteDeadline:
    def test_slow_symbol_does_not_block_the_batch(self) -> None:
        client = _make_client()
        # Shorten the deadline so the test is fast and deterministic.
        client._quote_batch_deadline_seconds = lambda: 0.3  # type: ignore[method-assign]

        release = threading.Event()

        def fake_execute_get(path: str, params: dict, *, use_circuit_breaker: bool):
            sym = params["symbol"]
            if sym == "SLOW":
                # Simulate a hung/slow endpoint: block past the batch deadline.
                # Released in `finally` so no background thread lingers.
                release.wait(timeout=5.0)
            return [{"symbol": sym, "price": 100.0}]

        client._execute_get = fake_execute_get  # type: ignore[method-assign]

        started = time.perf_counter()
        try:
            rows = client.get_batch_quotes(["FAST1", "FAST2", "FAST3", "SLOW"])
            elapsed = time.perf_counter() - started

            # The call returns near the 0.3s deadline, NOT after the slow worker.
            assert elapsed < 1.2, f"batch blocked on the slow worker ({elapsed:.2f}s)"

            diag = client.get_last_quote_fetch_diagnostics()
            fetched = set(diag["fetched_unique_symbols"])
            assert {"FAST1", "FAST2", "FAST3"} <= fetched
            assert "SLOW" in diag["failed_quote_symbols"]
            assert diag["partial_quote_fetch"] is True
            # Returned rows contain exactly the successfully-fetched symbols.
            assert {r["symbol"] for r in rows} == fetched
        finally:
            release.set()

    def test_all_fast_symbols_are_unaffected(self) -> None:
        client = _make_client()
        client._quote_batch_deadline_seconds = lambda: 5.0  # type: ignore[method-assign]

        def fake_execute_get(path: str, params: dict, *, use_circuit_breaker: bool):
            return [{"symbol": params["symbol"], "price": 42.0}]

        client._execute_get = fake_execute_get  # type: ignore[method-assign]

        rows = client.get_batch_quotes(["AAA", "BBB", "CCC"])
        diag = client.get_last_quote_fetch_diagnostics()
        assert diag["failed_quote_symbols"] == []
        assert diag["partial_quote_fetch"] is False
        assert {r["symbol"] for r in rows} == {"AAA", "BBB", "CCC"}

    def test_deadline_exceeds_one_worst_case_call(self) -> None:
        # The deadline must comfortably exceed a single worst-case-but-successful
        # call (timeout_seconds × retry_attempts) so legitimate slow fetches are
        # not cut off; only a genuinely stuck batch trips it.
        client = _make_client(timeout_seconds=30.0, retry_attempts=2)
        assert client._quote_batch_deadline_seconds() > 30.0 * 2
