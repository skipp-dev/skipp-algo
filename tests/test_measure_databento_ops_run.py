from __future__ import annotations

from datetime import UTC, datetime
import json
import subprocess
from pathlib import Path

from scripts.measure_databento_ops_run import _build_status_after_run, _run_full_history_refresh_subprocess


def test_build_status_after_run_reads_latest_manifest(tmp_path: Path) -> None:
    current_iso = datetime.now(UTC).isoformat(timespec="seconds")
    manifest_path = tmp_path / "databento_volatility_production_20260309_081243_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "export_generated_at": current_iso,
                "premarket_fetched_at": current_iso,
                "intraday_fetched_at": current_iso,
                "second_detail_fetched_at": current_iso,
            }
        ),
        encoding="utf-8",
    )

    status = _build_status_after_run(tmp_path)

    assert status["is_stale"] is False
    assert status["export_generated_at"] == current_iso
    assert status["premarket_fetched_at"] == current_iso
    assert status["manifest_path"] == str(manifest_path)


def test_build_status_after_run_fast_manifest_does_not_use_full_history_second_detail_fallback(tmp_path: Path) -> None:
    manifest_path = tmp_path / "databento_preopen_fast_20260310_093100_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "mode": "preopen_fast_reduced_scope",
                "export_generated_at": "2026-03-10T09:31:00+00:00",
                "premarket_fetched_at": "2026-03-10T09:30:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "full_universe_second_detail_open.parquet").write_bytes(b"placeholder")

    status = _build_status_after_run(tmp_path, stale_after_minutes=10_000)

    assert status["manifest_path"] == str(manifest_path)
    assert status["second_detail_fetched_at"] is None


def test_build_status_after_run_prefers_older_parseable_manifest(tmp_path: Path) -> None:
    older_manifest = tmp_path / "databento_volatility_production_20260309_081243_manifest.json"
    older_manifest.write_text(
        json.dumps(
            {
                "dataset": "DBEQ.BASIC",
                "lookback_days": 30,
                "export_generated_at": "2026-03-09T08:12:43+00:00",
                "premarket_fetched_at": "2026-03-09T08:12:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    newer_manifest = tmp_path / "databento_volatility_production_20260309_081500_manifest.json"
    newer_manifest.write_text("{invalid json", encoding="utf-8")
    older_manifest.touch()
    newer_manifest.touch()

    status = _build_status_after_run(tmp_path, stale_after_minutes=10_000)

    assert status["manifest_path"] == str(older_manifest)
    assert status["export_generated_at"] == "2026-03-09T08:12:43+00:00"
    assert status["premarket_fetched_at"] == "2026-03-09T08:12:00+00:00"


def test_run_full_history_refresh_subprocess_returns_last_json_line(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_run(cmd, capture_output, text, check):
        captured["cmd"] = cmd
        captured["capture_output"] = capture_output
        captured["text"] = text
        captured["check"] = check
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout='progress line\n{"manifest_path": "/tmp/manifest.json", "output_checks": {"trade_date_count": 30}}\n',
            stderr="",
        )

    monkeypatch.setattr("scripts.measure_databento_ops_run.subprocess.run", fake_run)

    result = _run_full_history_refresh_subprocess(
        databento_api_key="db-key",
        fmp_api_key="fmp-key",
        dataset="DBEQ.BASIC",
        lookback_days=30,
        cache_dir=tmp_path / "cache",
        export_dir=tmp_path / "export",
        force_refresh=False,
    )

    assert result["manifest_path"] == "/tmp/manifest.json"
    assert result["output_checks"]["trade_date_count"] == 30
    assert captured["capture_output"] is True
    assert captured["text"] is True
    assert captured["check"] is False


def test_run_full_history_refresh_subprocess_raises_on_failure(monkeypatch, tmp_path: Path) -> None:
    def fake_run(cmd, capture_output, text, check):
        return subprocess.CompletedProcess(args=cmd, returncode=137, stdout="", stderr="killed")

    monkeypatch.setattr("scripts.measure_databento_ops_run.subprocess.run", fake_run)

    try:
        _run_full_history_refresh_subprocess(
            databento_api_key="db-key",
            fmp_api_key="fmp-key",
            dataset="DBEQ.BASIC",
            lookback_days=30,
            cache_dir=tmp_path / "cache",
            export_dir=tmp_path / "export",
            force_refresh=False,
        )
        raise AssertionError("Expected RuntimeError")
    except RuntimeError as exc:
        assert "killed" in str(exc)