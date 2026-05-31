"""EV-10 tests: end-to-end edge pipeline (bars + structure -> archived verdict)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.run_edge_pipeline import _coerce_as_of, main, run_pipeline

_T0 = 1_700_000_000.0
_STEP = 86_400.0  # daily bars


def _bars(closes: list[float]) -> list[dict]:
    return [
        {
            "timestamp": _T0 + i * _STEP,
            "high": closes[i] + 1.0,
            "low": closes[i] - 1.0,
            "close": closes[i],
        }
        for i in range(len(closes))
    ]


def _payload_with_bos_events() -> dict:
    # Monotonic up-trend so every immediate-long BOS yields a positive return.
    # 40 BOS events clears the gate's 30-return minimum for PSR.
    closes = [100.0 + i for i in range(80)]
    bars = _bars(closes)
    structure = {
        "bos": [
            {"id": f"b{i}", "time": _T0 + i * _STEP, "price": closes[i], "dir": "UP"}
            for i in range(40)
        ]
    }
    return {
        "bars": bars,
        "structure": structure,
        "periods_per_year": 252,
        "as_of": _T0 + 79 * _STEP,
    }


def test_coerce_as_of_accepts_epoch_iso_and_none() -> None:
    assert _coerce_as_of(None) is None
    assert _coerce_as_of(1_700_000_000) == 1_700_000_000.0
    assert _coerce_as_of("2023-11-14T22:13:20+00:00") == pytest.approx(1_700_000_000.0)


def test_coerce_as_of_rejects_bool_and_garbage() -> None:
    with pytest.raises(ValueError):
        _coerce_as_of(True)
    with pytest.raises(ValueError):
        _coerce_as_of(["not", "a", "time"])


def test_run_pipeline_end_to_end_produces_report_and_verdicts(tmp_path: Path) -> None:
    result = run_pipeline(_payload_with_bos_events(), archive_dir=tmp_path)

    report = result["report"]
    assert report["schema_version"] == 1
    families = {d["family"] for d in report["decisions"]}
    assert "BOS" in families

    # Honest verdict report is produced over the same in-memory report.
    summary = result["verdict_report"]["summary"]
    assert set(summary) == {
        "edge_supported",
        "no_edge",
        "inconclusive",
        "not_evaluated",
    }
    assert sum(summary.values()) >= 1

    # The run was archived to the real-archive-shaped directory.
    assert result["archived_path"] is not None
    archived = list(tmp_path.glob("promotion_decisions_*.json"))
    assert len(archived) == 1
    assert result["events"] == 40


def test_run_pipeline_archiving_disabled(tmp_path: Path) -> None:
    result = run_pipeline(_payload_with_bos_events(), archive_dir=None)
    assert result["archived_path"] is None
    assert list(tmp_path.glob("*.json")) == []


def test_run_pipeline_rejects_empty_bars() -> None:
    with pytest.raises(ValueError, match="bars"):
        run_pipeline({"bars": [], "structure": {"bos": [{}]}})


def test_run_pipeline_rejects_structure_without_events() -> None:
    with pytest.raises(ValueError, match="no events"):
        run_pipeline({"bars": _bars([100.0, 101.0]), "structure": {}})


def test_run_pipeline_honest_empty_when_no_triggered_returns() -> None:
    # A BOS anchored beyond the last bar is dropped -> no returns at all.
    payload = {
        "bars": _bars([100.0 + i for i in range(5)]),
        "structure": {
            "bos": [{"id": "b1", "time": _T0 + 999 * _STEP, "price": 105.0, "dir": "UP"}]
        },
    }
    with pytest.raises(ValueError, match="honest empty result"):
        run_pipeline(payload)


def test_main_writes_output_and_archive(tmp_path: Path) -> None:
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(_payload_with_bos_events()), encoding="utf-8")
    output_path = tmp_path / "report.json"
    archive_dir = tmp_path / "archive"

    code = main(
        [
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--archive-dir",
            str(archive_dir),
        ]
    )

    # Exit code is 0 (all promoted) or 2 (some blocked) — never a crash.
    assert code in (0, 2)
    assert output_path.exists()
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert "decisions" in report
    assert list(archive_dir.glob("promotion_decisions_*.json"))


def test_main_config_error_returns_1(tmp_path: Path) -> None:
    input_path = tmp_path / "bad.json"
    input_path.write_text(json.dumps({"bars": [], "structure": {}}), encoding="utf-8")
    assert main(["--input", str(input_path), "--archive-dir", ""]) == 1
