"""Pin append_jsonl in-memory fallback on OSError (Lane 16)."""
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast
from unittest.mock import patch

import terminal_export
from terminal_poller import ClassifiedItem


class _FakeItem:
    def __init__(self, d):
        self._d = d

    def to_dict(self):
        return self._d


def _classified_item(d: dict[str, Any]) -> ClassifiedItem:
    return cast(ClassifiedItem, _FakeItem(d))


def test_append_jsonl_falls_back_on_permission_error(tmp_path, caplog):
    terminal_export.clear_fallback_buffer()
    target = tmp_path / "denied.jsonl"
    item = _classified_item({"event": "test", "value": 1})
    with patch("builtins.open", side_effect=PermissionError("denied")), caplog.at_level(logging.WARNING, logger="terminal_export"):
        terminal_export.append_jsonl(item, str(target))
    buf = terminal_export.get_fallback_buffer()
    assert len(buf) >= 1
    assert buf[-1] == {"event": "test", "value": 1}
    assert any("append_jsonl" in r.message for r in caplog.records)


def test_append_jsonl_succeeds_normally(tmp_path):
    terminal_export.clear_fallback_buffer()
    target = tmp_path / "ok.jsonl"
    terminal_export.append_jsonl(_classified_item({"x": 1}), str(target))
    assert target.exists()
    assert terminal_export.get_fallback_buffer() == []


def test_fallback_buffer_concurrent_access_does_not_crash(tmp_path):
    terminal_export.clear_fallback_buffer()
    target = tmp_path / "denied.jsonl"

    def writer(worker: int) -> None:
        for idx in range(25):
            terminal_export.append_jsonl(_classified_item({"worker": worker, "idx": idx}), str(target))

    def reader() -> None:
        for _ in range(100):
            terminal_export.get_fallback_buffer()

    try:
        with patch("builtins.open", side_effect=PermissionError("denied")), ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(writer, worker) for worker in range(4)]
            futures.append(pool.submit(reader))
            for future in futures:
                future.result()

        assert len(terminal_export.get_fallback_buffer()) == 100
    finally:
        terminal_export.clear_fallback_buffer()
