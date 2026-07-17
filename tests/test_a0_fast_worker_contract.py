"""Static and pure configuration contract for the shadow-only A0 worker."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from services.a0_fast_detector import worker


def test_worker_refuses_every_mode_except_shadow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A0_FAST_MODE", "off")
    with pytest.raises(RuntimeError, match="shadow"):
        worker._shadow_mode()
    monkeypatch.setenv("A0_FAST_MODE", "shadow")
    assert worker._shadow_mode() == "shadow"


def test_worker_requires_explicit_symbols(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("A0_FAST_SYMBOLS", raising=False)
    with pytest.raises(RuntimeError, match="explicit"):
        worker._symbols()
    monkeypatch.setenv("A0_FAST_SYMBOLS", " nvda,AMD,nvda ")
    assert worker._symbols() == ["NVDA", "AMD"]


def test_reference_loader_rejects_fmp_source(tmp_path: Path) -> None:
    path = tmp_path / "references.json"
    path.write_text(json.dumps([{
        "symbol": "NVDA",
        "previous_close": 100.0,
        "average_daily_volume": 1_000_000.0,
        "source": "fmp",
        "as_of_session": "2026-07-16",
        "lookback_sessions": 20,
        "reference_version": "v1",
        "corporate_action_version": "v1",
    }]), encoding="utf-8")
    with pytest.raises(ValueError, match="non-Databento"):
        worker._load_references(path)


def test_worker_has_no_notification_or_publication_import() -> None:
    path = Path(worker.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not any("rt_notify" in name or "slack" in name for name in imports)
    source = path.read_text(encoding="utf-8")
    assert "notify_fresh_signals" not in source
    assert '"mode": "shadow"' in source
