"""Tests for ``scripts/plan_2_8_ledger_csv_export.py``."""

from __future__ import annotations

import csv
import importlib.util
import io
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_csv_export.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_ledger_csv_export", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_csv_export"] = mod
    spec.loader.exec_module(mod)
    return mod


ex = _load()


def test_render_csv_default_fields() -> None:
    records = [
        {"captured_at": "t1", "status": "green", "run_url": "u1"},
        {"captured_at": "t2", "status": "amber"},
    ]
    out = ex.render_csv(records)
    rows = list(csv.DictReader(io.StringIO(out)))
    assert rows[0] == {"captured_at": "t1", "status": "green", "run_url": "u1"}
    assert rows[1]["run_url"] == ""


def test_render_csv_custom_fields() -> None:
    records = [{"captured_at": "t1", "status": "green", "extra": "x"}]
    out = ex.render_csv(records, fields=("status", "extra"))
    rows = list(csv.DictReader(io.StringIO(out)))
    assert rows[0] == {"status": "green", "extra": "x"}


def test_render_csv_none_normalised_to_empty() -> None:
    out = ex.render_csv([{"captured_at": "t1", "status": "green", "run_url": None}])
    rows = list(csv.DictReader(io.StringIO(out)))
    assert rows[0]["run_url"] == ""


def test_render_csv_header_only_for_empty() -> None:
    out = ex.render_csv([])
    lines = out.strip().splitlines()
    assert len(lines) == 1
    assert lines[0] == "captured_at,status,run_url"


def test_iter_skips_blank_and_malformed(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        json.dumps({"captured_at": "t1", "status": "green"})
        + "\n\nnot-json\n"
        + json.dumps([1, 2])
        + "\n"
        + json.dumps({"captured_at": "t2", "status": "amber"}) + "\n",
        encoding="utf-8",
    )
    records = ex._iter_records(p)
    assert len(records) == 2


def test_cli_writes_file(tmp_path: Path) -> None:
    ledger = tmp_path / "l.jsonl"
    ledger.write_text(
        json.dumps({"captured_at": "t1", "status": "green",
                    "run_url": "u1"}) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "l.csv"
    rc = ex.main([
        "--ledger", str(ledger), "--output", str(out),
    ])
    assert rc == 0
    rows = list(csv.DictReader(io.StringIO(out.read_text(encoding="utf-8"))))
    assert rows[0]["status"] == "green"


def test_cli_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    ledger = tmp_path / "l.jsonl"
    ledger.write_text(
        json.dumps({"captured_at": "t1", "status": "green"}) + "\n",
        encoding="utf-8",
    )
    rc = ex.main(["--ledger", str(ledger)])
    assert rc == 0
    assert "captured_at,status,run_url" in capsys.readouterr().out


def test_cli_custom_fields(tmp_path: Path) -> None:
    ledger = tmp_path / "l.jsonl"
    ledger.write_text(
        json.dumps({"captured_at": "t1", "status": "green"}) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "l.csv"
    rc = ex.main([
        "--ledger", str(ledger), "--output", str(out),
        "--fields", "status,captured_at",
    ])
    assert rc == 0
    header = out.read_text(encoding="utf-8").splitlines()[0]
    assert header == "status,captured_at"


def test_cli_empty_fields_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    ledger = tmp_path / "l.jsonl"
    ledger.write_text("{}\n", encoding="utf-8")
    rc = ex.main([
        "--ledger", str(ledger), "--fields", "  ,  ",
    ])
    assert rc == 1


def test_cli_missing_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = ex.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert rc == 1


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_csv_export_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger CSV export" in names
    assert "Upload Plan 2.8 ledger CSV" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger CSV export")
    assert "plan_2_8_ledger_csv_export.py" in step["run"]
