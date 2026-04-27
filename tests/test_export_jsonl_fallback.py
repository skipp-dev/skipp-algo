"""Pin append_jsonl in-memory fallback on OSError (Lane 16)."""
import logging
from unittest.mock import patch

import terminal_export


class _FakeItem:
    def __init__(self, d):
        self._d = d

    def to_dict(self):
        return self._d


def test_append_jsonl_falls_back_on_permission_error(tmp_path, caplog):
    terminal_export.clear_fallback_buffer()
    target = tmp_path / "denied.jsonl"
    item = _FakeItem({"event": "test", "value": 1})
    with patch("builtins.open", side_effect=PermissionError("denied")):
        with caplog.at_level(logging.WARNING, logger="terminal_export"):
            terminal_export.append_jsonl(item, str(target))
    buf = terminal_export.get_fallback_buffer()
    assert len(buf) >= 1
    assert buf[-1] == {"event": "test", "value": 1}
    assert any("append_jsonl" in r.message for r in caplog.records)


def test_append_jsonl_succeeds_normally(tmp_path):
    terminal_export.clear_fallback_buffer()
    target = tmp_path / "ok.jsonl"
    terminal_export.append_jsonl(_FakeItem({"x": 1}), str(target))
    assert target.exists()
    assert terminal_export.get_fallback_buffer() == []
