"""Tests for ``scripts/plan_2_8_ledger_downtime.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_downtime.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_ledger_downtime", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_downtime"] = mod
    spec.loader.exec_module(mod)
    return mod


dt = _load()


def _rec(ts: str, status: str) -> dict[str, Any]:
    return {"captured_at": ts, "status": status}


def test_no_records_empty_report() -> None:
    rep = dt.compute([])
    assert rep["counts"] == {"intervals": 0, "total_seconds": 0.0}
    assert rep["by_status"] == {"amber": 0.0, "red": 0.0, "unknown": 0.0}


def test_all_green_no_downtime() -> None:
    records = [
        _rec("2026-04-01T00:00:00+00:00", "green"),
        _rec("2026-04-08T00:00:00+00:00", "green"),
    ]
    rep = dt.compute(records)
    assert rep["counts"]["intervals"] == 0


def test_single_amber_interval() -> None:
    records = [
        _rec("2026-04-01T00:00:00+00:00", "green"),
        _rec("2026-04-08T00:00:00+00:00", "amber"),
        _rec("2026-04-15T00:00:00+00:00", "green"),
    ]
    rep = dt.compute(records)
    assert rep["counts"]["intervals"] == 1
    assert rep["by_status"]["amber"] == 7 * 24 * 3600


def test_trailing_non_green_not_counted() -> None:
    records = [
        _rec("2026-04-01T00:00:00+00:00", "green"),
        _rec("2026-04-08T00:00:00+00:00", "amber"),
    ]
    rep = dt.compute(records)
    assert rep["counts"]["intervals"] == 0


def test_multiple_statuses_accumulate() -> None:
    records = [
        _rec("2026-04-01T00:00:00+00:00", "amber"),
        _rec("2026-04-02T00:00:00+00:00", "red"),
        _rec("2026-04-03T00:00:00+00:00", "unknown"),
        _rec("2026-04-04T00:00:00+00:00", "green"),
    ]
    rep = dt.compute(records)
    assert rep["by_status"]["amber"] == 86400
    assert rep["by_status"]["red"] == 86400
    assert rep["by_status"]["unknown"] == 86400
    assert rep["counts"]["intervals"] == 3


def test_bad_timestamp_dropped() -> None:
    records = [
        _rec("not-a-date", "amber"),
        _rec("2026-04-02T00:00:00+00:00", "green"),
    ]
    rep = dt.compute(records)
    assert rep["counts"]["intervals"] == 0


def test_invalid_status_dropped() -> None:
    records = [
        _rec("2026-04-01T00:00:00+00:00", "bogus"),
        _rec("2026-04-02T00:00:00+00:00", "green"),
    ]
    rep = dt.compute(records)
    assert rep["counts"]["intervals"] == 0


def test_negative_span_clamped_to_zero() -> None:
    # Out-of-order timestamps; should clamp to 0 rather than blow up.
    records = [
        _rec("2026-04-10T00:00:00+00:00", "amber"),
        _rec("2026-04-01T00:00:00+00:00", "green"),
    ]
    rep = dt.compute(records)
    assert rep["counts"]["intervals"] == 1
    assert rep["by_status"]["amber"] == 0.0


def test_render_markdown_shape() -> None:
    records = [
        _rec("2026-04-01T00:00:00+00:00", "amber"),
        _rec("2026-04-02T00:00:00+00:00", "green"),
    ]
    md = dt.render_markdown(dt.compute(records))
    assert "ledger downtime" in md
    assert "| amber | 86400 |" in md


def test_cli_json_output(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        "\n".join(json.dumps(r) for r in [
            _rec("2026-04-01T00:00:00+00:00", "amber"),
            _rec("2026-04-02T00:00:00+00:00", "green"),
        ]) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "d.json"
    rc = dt.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["by_status"]["amber"] == 86400


def test_cli_md_format(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        json.dumps(_rec("2026-04-01T00:00:00+00:00", "green")) + "\n",
        encoding="utf-8",
    )
    rc = dt.main(["--ledger", str(p), "--format", "md"])
    assert rc == 0
    assert "ledger downtime" in capsys.readouterr().out


def test_cli_missing_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = dt.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert rc == 1
    assert "ledger not found" in capsys.readouterr().err


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_downtime_step() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger downtime" in names
    assert "Upload Plan 2.8 ledger downtime" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger downtime")
    assert "plan_2_8_ledger_downtime.py" in step["run"]
