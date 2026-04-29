"""Tests for ``scripts/plan_2_8_status_ledger_prune.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_status_ledger_prune.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_status_ledger_prune", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_status_ledger_prune"] = mod
    spec.loader.exec_module(mod)
    return mod


lp = _load()


def _records(n: int) -> list[str]:
    return [json.dumps({"status": "green", "i": i}) for i in range(n)]


def test_prune_keeps_last_n() -> None:
    lines = _records(5)
    kept = lp.prune(lines, keep=3)
    assert len(kept) == 3
    assert json.loads(kept[0])["i"] == 2
    assert json.loads(kept[-1])["i"] == 4


def test_prune_preserves_all_when_keep_exceeds_total() -> None:
    lines = _records(3)
    kept = lp.prune(lines, keep=100)
    assert len(kept) == 3


def test_prune_keep_zero_empties_ledger() -> None:
    kept = lp.prune(_records(4), keep=0)
    assert kept == []


def test_prune_negative_keep_rejected() -> None:
    with pytest.raises(ValueError):
        lp.prune(_records(1), keep=-1)


def test_prune_skips_blank_and_malformed() -> None:
    lines = [
        "", "  ",
        json.dumps({"status": "green"}),
        "not-json",
        json.dumps([1, 2, 3]),  # list, not dict
        json.dumps({"status": "amber"}),
    ]
    kept = lp.prune(lines, keep=10)
    assert len(kept) == 2


def test_rewrite_is_atomic_and_replaces_file(tmp_path: Path) -> None:
    ledger = tmp_path / "l.jsonl"
    ledger.write_text("old\nold\n", encoding="utf-8")
    lp._rewrite(ledger, ['{"status": "green"}'])
    content = ledger.read_text(encoding="utf-8")
    assert content == '{"status": "green"}\n'


def test_cli_prunes_ledger_file(tmp_path: Path) -> None:
    ledger = tmp_path / "l.jsonl"
    ledger.write_text("\n".join(_records(5)) + "\n", encoding="utf-8")
    rc = lp.main([
        "--ledger", str(ledger), "--keep", "2", "--quiet",
    ])
    assert rc == 0
    lines = ledger.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[-1])["i"] == 4


def test_cli_prints_stats_by_default(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    ledger = tmp_path / "l.jsonl"
    ledger.write_text("\n".join(_records(3)) + "\n", encoding="utf-8")
    rc = lp.main([
        "--ledger", str(ledger), "--keep", "1",
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"before": 3, "after": 1, "keep": 1}


def test_cli_missing_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = lp.main([
        "--ledger", str(tmp_path / "nope.jsonl"), "--keep", "5",
    ])
    assert rc == 1
    assert "ledger not found" in capsys.readouterr().err


def test_cli_negative_keep_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    ledger = tmp_path / "l.jsonl"
    ledger.write_text("{}\n", encoding="utf-8")
    rc = lp.main([
        "--ledger", str(ledger), "--keep", "-1",
    ])
    assert rc == 1
    assert "non-negative" in capsys.readouterr().err


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_ledger_prune_step() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 status ledger prune" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 status ledger prune")
    assert "plan_2_8_status_ledger_prune.py" in step["run"]
    assert "--keep 104" in step["run"]
