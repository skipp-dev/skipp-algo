"""Tests for ``scripts/plan_2_8_ledger_status_entropy.py``."""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_ledger_status_entropy.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "plan_2_8_ledger_status_entropy", SCRIPT,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_ledger_status_entropy"] = mod
    spec.loader.exec_module(mod)
    return mod


en = _load()


def _r(s: str) -> dict[str, Any]:
    return {"status": s, "captured_at": "t"}


def test_empty() -> None:
    assert en.compute([])["status_entropy_bits"] == 0.0


def test_single_status() -> None:
    assert en.compute([_r("green")] * 3)["status_entropy_bits"] == 0.0


def test_uniform_two() -> None:
    recs = [_r("green"), _r("red")]
    assert en.compute(recs)["status_entropy_bits"] == 1.0


def test_uniform_four() -> None:
    recs = [_r("green"), _r("amber"), _r("red"), _r("unknown")]
    assert en.compute(recs)["status_entropy_bits"] == 2.0


def test_invalid_ignored() -> None:
    recs = [_r("green"), _r("bogus"), _r("red")]
    # now 1 green, 1 red -> entropy 1.0
    assert en.compute(recs)["status_entropy_bits"] == 1.0


def test_markdown_shape() -> None:
    text = en.render_markdown(en.compute([_r("green")]))
    assert "status_entropy_bits" in text


def test_cli_json(tmp_path: Path) -> None:
    p = tmp_path / "l.jsonl"
    p.write_text(
        "\n".join(json.dumps(_r(s)) for s in ("green", "red")) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "o.json"
    code = en.main([
        "--ledger", str(p), "--format", "json", "--output", str(out),
    ])
    assert code == 0
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert math.isclose(rep["status_entropy_bits"], 1.0)


def test_cli_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    code = en.main(["--ledger", str(tmp_path / "nope.jsonl")])
    assert code == 1
    assert "ledger not found" in capsys.readouterr().err


def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_entropy_steps() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 ledger status entropy" in names
    assert "Upload Plan 2.8 ledger status entropy" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 ledger status entropy")
    assert "plan_2_8_ledger_status_entropy.py" in step["run"]
