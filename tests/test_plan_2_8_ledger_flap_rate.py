"""Tests for ``scripts/plan_2_8_ledger_flap_rate.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_flap_rate.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_flap_rate", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_flap_rate"] = mod
    spec.loader.exec_module(mod)
    return mod


fr = _load()


def _rec(ts: str, status: str) -> dict[str, Any]:
    return {"captured_at": ts, "status": status}


def test_empty_no_flips() -> None:
    rep = fr.compute([])
    assert rep["total_flips"] == 0
    assert rep["weeks"] == []


def test_no_flips_when_same_status() -> None:
    rep = fr.compute([
        _rec("2026-04-20T00:00:00+00:00", "green"),
        _rec("2026-04-21T00:00:00+00:00", "green"),
    ])
    assert rep["total_flips"] == 0


def test_counts_single_flip() -> None:
    rep = fr.compute([
        _rec("2026-04-20T00:00:00+00:00", "green"),
        _rec("2026-04-21T00:00:00+00:00", "amber"),
    ])
    assert rep["total_flips"] == 1
    assert rep["weeks"][0]["week"] == "2026-W17"


def test_flips_grouped_by_to_week() -> None:
    rep = fr.compute([
        _rec("2026-04-13T00:00:00+00:00", "green"),   # W16
        _rec("2026-04-20T00:00:00+00:00", "amber"),   # W17 (flip)
        _rec("2026-04-27T00:00:00+00:00", "green"),   # W18 (flip)
    ])
    assert rep["total_flips"] == 2
    assert rep["weeks_covered"] == 2
    assert rep["flips_per_week"] == 1.0


def test_invalid_records_dropped() -> None:
    rep = fr.compute([
        _rec("2026-04-20T00:00:00+00:00", "green"),
        _rec("bad", "amber"),
        _rec("2026-04-21T00:00:00+00:00", "bogus"),
        _rec("2026-04-22T00:00:00+00:00", "amber"),
    ])
    assert rep["total_flips"] == 1


def test_markdown_shape() -> None:
    rep = fr.compute([
        _rec("2026-04-20T00:00:00+00:00", "green"),
        _rec("2026-04-21T00:00:00+00:00", "amber"),
    ])
    md = fr.render_markdown(rep)
    assert "total flips" in md
    assert "2026-W17" in md


def test_markdown_empty_placeholder() -> None:
    md = fr.render_markdown(fr.compute([]))
    assert "no flips" in md


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        "\n".join(json.dumps(r) for r in [
            _rec("2026-04-20T00:00:00+00:00", "green"),
            _rec("2026-04-21T00:00:00+00:00", "amber"),
        ]) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "o.json"
    rc = fr.main([
        "--ledger", str(p), "--format", "json",
        "--output", str(out),
    ])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["total_flips"] == 1


def test_cli_fail_on_flips(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        "\n".join(json.dumps(r) for r in [
            _rec("2026-04-20T00:00:00+00:00", "green"),
            _rec("2026-04-21T00:00:00+00:00", "amber"),
        ]) + "\n",
        encoding="utf-8",
    )
    rc = fr.main(["--ledger", str(p), "--fail-on-flips"])
    assert rc == 1


def test_cli_fail_on_flips_clean(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        json.dumps(_rec("2026-04-20T00:00:00+00:00", "green")) + "\n",
        encoding="utf-8",
    )
    rc = fr.main(["--ledger", str(p), "--fail-on-flips"])
    assert rc == 0


def test_cli_missing_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = fr.main(["--ledger", str(tmp_path / "nope.jsonl")])
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


def test_weekly_has_flap_rate_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger flap rate" in names
    assert "Upload Plan 2.8 ledger flap rate" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger flap rate")
    assert "plan_2_8_ledger_flap_rate.py" in step["run"]
