"""Tests for ``scripts/plan_2_8_history_export.py``."""

from __future__ import annotations

import csv
import datetime as _dt
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_history_export.py"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_history_export", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_history_export"] = mod
    spec.loader.exec_module(mod)
    return mod


he = _load()


def _rec(day: str, tf: str = "5m", fam: str = "HR", **extra: Any) -> dict[str, Any]:
    return {
        "captured_at": f"{day}T00:00:00+00:00",
        "scoring_root": "master",
        "tf":           tf,
        "family":       fam,
        "events":       100,
        "hit_rate_pct": 55.0,
        "delta_pp":     0.5,
        **extra,
    }


def _seed(tmp: Path, records: list[dict[str, Any]]) -> Path:
    log = tmp / "history.jsonl"
    log.write_text("\n".join(json.dumps(r) for r in records) + "\n",
                   encoding="utf-8")
    return log


def _read_csv(p: Path) -> tuple[list[str], list[dict[str, str]]]:
    with p.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def test_default_fields(tmp_path: Path) -> None:
    log = _seed(tmp_path, [_rec("2026-04-20")])
    out = tmp_path / "out.csv"
    rep = he.export_csv(
        list(he._iter_records(log)),
        list(he.DEFAULT_FIELDS),
        out,
    )
    assert rep["rows"] == 1
    fields, rows = _read_csv(out)
    assert fields == list(he.DEFAULT_FIELDS)
    assert rows[0]["tf"] == "5m"


def test_missing_keys_rendered_empty(tmp_path: Path) -> None:
    records = [
        {"captured_at": "2026-04-20T00:00:00+00:00", "tf": "5m"},
    ]
    log = _seed(tmp_path, records)
    out = tmp_path / "out.csv"
    he.export_csv(
        list(he._iter_records(log)),
        list(he.DEFAULT_FIELDS),
        out,
    )
    _, rows = _read_csv(out)
    assert rows[0]["family"] == ""
    assert rows[0]["events"] == ""


def test_extra_keys_dropped(tmp_path: Path) -> None:
    log = _seed(tmp_path, [_rec("2026-04-20", note="ignore me")])
    out = tmp_path / "out.csv"
    he.export_csv(
        list(he._iter_records(log)),
        list(he.DEFAULT_FIELDS),
        out,
    )
    fields, _ = _read_csv(out)
    assert "note" not in fields


def test_custom_fields(tmp_path: Path) -> None:
    log = _seed(tmp_path, [_rec("2026-04-20")])
    out = tmp_path / "out.csv"
    he.export_csv(
        list(he._iter_records(log)),
        ["tf", "family"],
        out,
    )
    fields, rows = _read_csv(out)
    assert fields == ["tf", "family"]
    assert rows[0] == {"tf": "5m", "family": "HR"}


def test_filter_by_lookback_days() -> None:
    records = [_rec("2025-01-01"), _rec("2026-04-20")]
    now = _dt.datetime(2026, 4, 22, tzinfo=_dt.UTC)
    kept = he.filter_records(records, lookback_days=30, now=now)
    assert len(kept) == 1
    assert kept[0]["captured_at"].startswith("2026-04-20")


def test_iter_records_skips_malformed_and_blank(tmp_path: Path) -> None:
    log = tmp_path / "h.jsonl"
    log.write_text(
        "\n".join([json.dumps(_rec("2026-04-20")),
                   "not-json",
                   "",
                   json.dumps(_rec("2026-04-21"))]) + "\n",
        encoding="utf-8",
    )
    recs = list(he._iter_records(log))
    assert len(recs) == 2


def test_cli_writes_csv(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    log = _seed(tmp_path, [_rec("2026-04-20")])
    out = tmp_path / "out.csv"
    rc = he.main([
        "--history", str(log), "--output", str(out), "--quiet",
    ])
    assert rc == 0
    assert out.exists()
    fields, rows = _read_csv(out)
    assert fields == list(he.DEFAULT_FIELDS)
    assert len(rows) == 1


def test_cli_custom_fields_flag(tmp_path: Path) -> None:
    log = _seed(tmp_path, [_rec("2026-04-20")])
    out = tmp_path / "out.csv"
    rc = he.main([
        "--history", str(log), "--output", str(out),
        "--fields", "tf,family", "--quiet",
    ])
    assert rc == 0
    fields, _ = _read_csv(out)
    assert fields == ["tf", "family"]


def test_cli_empty_fields_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    log = _seed(tmp_path, [_rec("2026-04-20")])
    rc = he.main([
        "--history", str(log), "--output", str(tmp_path / "x.csv"),
        "--fields", ",,,",
    ])
    assert rc == 1
    assert "fields" in capsys.readouterr().err.lower()


def test_cli_missing_history(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = he.main([
        "--history", str(tmp_path / "nope.jsonl"),
        "--output",  str(tmp_path / "out.csv"),
    ])
    assert rc == 1
    assert "history not found" in capsys.readouterr().err
