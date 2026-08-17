"""Static and pure configuration contract for the shadow-only A0 worker."""

from __future__ import annotations

import ast
import json
import logging
from pathlib import Path

import pytest

from services.a0_fast_detector import worker


def test_worker_suppresses_per_symbol_databento_mapping_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mapping_logger = logging.getLogger("databento.live.client")
    monkeypatch.setattr(mapping_logger, "level", logging.NOTSET)
    worker._configure_logging()
    assert mapping_logger.level == logging.WARNING


def test_worker_refuses_every_mode_except_shadow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A0_FAST_MODE", "off")
    with pytest.raises(RuntimeError, match="shadow"):
        worker._shadow_mode()
    monkeypatch.setenv("A0_FAST_MODE", "shadow")
    assert worker._shadow_mode() == "shadow"
    monkeypatch.setenv("RT_A0_FAST_MODE", "off")
    with pytest.raises(RuntimeError, match="shadow"):
        worker._shadow_mode()
    monkeypatch.setenv("RT_A0_FAST_MODE", "shadow")
    assert worker._shadow_mode() == "shadow"


def test_worker_requires_explicit_symbols(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("A0_FAST_SYMBOLS", raising=False)
    with pytest.raises(RuntimeError, match="explicit"):
        worker._symbols()
    monkeypatch.setenv("A0_FAST_SYMBOLS", " nvda,AMD,nvda ")
    assert worker._symbols() == ["NVDA", "AMD"]


def test_worker_requires_durable_parity_log_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("A0_FAST_PARITY_LOG_DIR", raising=False)
    with pytest.raises(RuntimeError, match="durable storage"):
        worker._parity_log_dir()
    monkeypatch.setenv("A0_FAST_PARITY_LOG_DIR", str(tmp_path))
    assert worker._parity_log_dir() == tmp_path


def test_worker_uses_bounded_capacity_and_validates_runtime_ports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("A0_FAST_BUFFER_CAPACITY", raising=False)
    assert worker._buffer_capacity(900) == 3_600
    monkeypatch.setenv("A0_FAST_BUFFER_CAPACITY", "128")
    assert worker._buffer_capacity(900) == 128
    monkeypatch.setenv("A0_FAST_BUFFER_CAPACITY", "0")
    with pytest.raises(ValueError, match="BUFFER_CAPACITY"):
        worker._buffer_capacity(1)

    monkeypatch.setenv("A0_FAST_METRICS_PORT", "0")
    assert worker._metrics_port() == 0
    monkeypatch.setenv("A0_FAST_METRICS_PORT", "70000")
    with pytest.raises(ValueError, match="METRICS_PORT"):
        worker._metrics_port()
    monkeypatch.setenv("A0_FAST_METRICS_HOST", "")
    assert worker._metrics_host() == "127.0.0.1"


def test_worker_bounds_reconnect_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A0_FAST_RECONNECT_BACKOFF_SECONDS", "0.1")
    assert worker._reconnect_backoff_seconds() == 0.1
    monkeypatch.setenv("A0_FAST_RECONNECT_BACKOFF_SECONDS", "61")
    with pytest.raises(ValueError, match="RECONNECT_BACKOFF"):
        worker._reconnect_backoff_seconds()


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
    assert imports, "worker module parsed to zero imports — the ban below would pass vacuously"
    assert not any("rt_notify" in name or "slack" in name for name in imports)
    source = path.read_text(encoding="utf-8")
    assert "notify_fresh_signals" not in source
    assert '"mode": "shadow"' in source


def test_worker_image_packages_pre_a0_atomic_parquet_runtime() -> None:
    root = Path(worker.__file__).parents[2]
    dockerfile = (root / "services/a0_fast_detector/Dockerfile").read_text(encoding="utf-8")
    requirements = (root / "services/a0_fast_detector/requirements.txt").read_text(encoding="utf-8")
    railway = (root / "services/a0_fast_detector/railway.toml").read_text(encoding="utf-8")
    assert "COPY scripts/smc_atomic_write.py /app/scripts/smc_atomic_write.py" in dockerfile
    assert "pyarrow==25.0.1" in requirements  # 2026-08-17 (#4778 dependabot): 25.0.0->25.0.1 patch bump, full suite in throwaway venv per pin-contract doctrine
    assert '"open_prep/pre_a0*.py"' in railway
    assert '"scripts/smc_atomic_write.py"' in railway


def test_packaged_reference_excludes_unresolvable_live_symbols() -> None:
    root = Path(worker.__file__).parents[2]
    rows = json.loads(
        (root / "services/a0_fast_detector/bootstrap/a0-reference.json").read_text(
            encoding="utf-8"
        )
    )
    symbols = {str(row["symbol"]).strip().upper() for row in rows}
    assert symbols.isdisjoint({"EEX", "QTEXW", "FGMC", "APM"})
