"""Tests for ``scripts/plan_2_8_digest_schema.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_digest_schema.py"
WEEKLY = REPO / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_digest_schema", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_digest_schema"] = mod
    spec.loader.exec_module(mod)
    return mod


ds = _load()


def _valid_alert(**overrides: Any) -> dict[str, Any]:
    base = {
        "tf":           "5m",
        "family":       "HR",
        "hit_rate_pct": 42.5,
        "delta_pp":     1.0,
        "events":       100,
        "severity":     "info",
    }
    base.update(overrides)
    return base


def _valid_digest(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "schema_version": 1,
        "captured_at":    "2026-04-20T00:00:00+00:00",
        "scoring_root":   "master",
        "alerts":         [_valid_alert()],
    }
    base.update(overrides)
    return base


def test_valid_digest_reports_no_errors() -> None:
    rep = ds.validate(_valid_digest())
    assert rep["valid"] is True
    assert rep["counts"]["errors"] == 0
    assert rep["counts"]["alerts"] == 1


def test_empty_alerts_still_valid() -> None:
    rep = ds.validate(_valid_digest(alerts=[]))
    assert rep["valid"] is True
    assert rep["counts"]["alerts"] == 0


def test_non_dict_root_rejected() -> None:
    rep = ds.validate(["not", "a", "dict"])
    assert rep["valid"] is False
    assert rep["counts"]["errors"] == 1
    assert rep["errors"][0]["where"] == "<root>"


def test_missing_top_required() -> None:
    digest = _valid_digest()
    del digest["scoring_root"]
    rep = ds.validate(digest)
    assert rep["valid"] is False
    assert any(e["key"] == "scoring_root" and e["issue"] == "missing"
               for e in rep["errors"])


def test_wrong_top_type() -> None:
    rep = ds.validate(_valid_digest(schema_version="1"))
    assert rep["valid"] is False
    assert any(e["key"] == "schema_version" and e["issue"] == "wrong_type"
               for e in rep["errors"])


def test_bool_rejected_where_int_required() -> None:
    rep = ds.validate(_valid_digest(alerts=[_valid_alert(events=True)]))
    assert rep["valid"] is False
    assert any(e["key"] == "events" and e.get("actual") == "bool"
               for e in rep["errors"])


def test_missing_alert_field() -> None:
    bad = _valid_alert()
    del bad["severity"]
    rep = ds.validate(_valid_digest(alerts=[bad]))
    assert rep["valid"] is False
    assert any(e["where"] == "alerts[0]" and e["key"] == "severity"
               for e in rep["errors"])


def test_non_dict_alert_rejected() -> None:
    rep = ds.validate(_valid_digest(alerts=["not-a-dict"]))
    assert rep["valid"] is False
    assert any(e["where"] == "alerts[0]" and e["key"] == "<alert>"
               for e in rep["errors"])


def test_extra_unknown_keys_allowed() -> None:
    rep = ds.validate(_valid_digest(extra="tolerated"))
    assert rep["valid"] is True


def test_float_accepted_for_numeric_alert_field() -> None:
    rep = ds.validate(_valid_digest(
        alerts=[_valid_alert(hit_rate_pct=0, delta_pp=-0.1)],
    ))
    assert rep["valid"] is True


def test_render_markdown_valid() -> None:
    md = ds.render_markdown(ds.validate(_valid_digest()))
    assert "valid:   true" in md
    assert "matches expected schema" in md


def test_render_markdown_errors_table() -> None:
    bad = _valid_digest()
    del bad["captured_at"]
    md = ds.render_markdown(ds.validate(bad))
    assert "| where | key | issue" in md
    assert "captured_at" in md


def _seed(tmp: Path, digest: Any) -> Path:
    p = tmp / "d.json"
    p.write_text(json.dumps(digest), encoding="utf-8")
    return p


def test_cli_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = _seed(tmp_path, _valid_digest())
    rc = ds.main([
        "--digest", str(p), "--format", "json",
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is True


def test_cli_md_output(tmp_path: Path) -> None:
    p = _seed(tmp_path, _valid_digest())
    out = tmp_path / "r.md"
    rc = ds.main([
        "--digest", str(p), "--output", str(out),
    ])
    assert rc == 0
    assert "Plan 2.8 digest schema report" in out.read_text(encoding="utf-8")


def test_cli_fail_on_invalid_returns_1(tmp_path: Path) -> None:
    p = _seed(tmp_path, {"bogus": True})
    rc = ds.main([
        "--digest", str(p), "--fail-on-invalid",
    ])
    assert rc == 1


def test_cli_fail_on_invalid_passes_when_valid(tmp_path: Path) -> None:
    p = _seed(tmp_path, _valid_digest())
    rc = ds.main([
        "--digest", str(p), "--fail-on-invalid",
    ])
    assert rc == 0


def test_cli_missing_digest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = ds.main(["--digest", str(tmp_path / "nope.json")])
    assert rc == 1
    assert "digest not found" in capsys.readouterr().err


def test_cli_bad_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    p = tmp_path / "bad.json"
    p.write_text("not json", encoding="utf-8")
    rc = ds.main(["--digest", str(p)])
    assert rc == 1
    assert "not valid JSON" in capsys.readouterr().err


# ---- weekly wiring pin tests --------------------------------------------

def _wf(path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-not-found]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "on": data.get("on", data.get(True)),
        **{k: v for k, v in data.items() if k not in ("on", True)},
    }


def test_weekly_has_digest_schema_step() -> None:
    pytest.importorskip("yaml")
    wf = _wf(WEEKLY)
    steps = wf["jobs"]["weekly-digest"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Plan 2.8 digest schema check" in names
    assert "Upload Plan 2.8 digest schema report" in names
    step = next(s for s in steps
                if s.get("name") == "Plan 2.8 digest schema check")
    assert "plan_2_8_digest_schema.py" in step["run"]
