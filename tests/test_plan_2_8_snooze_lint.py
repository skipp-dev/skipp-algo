"""Tests for ``scripts/plan_2_8_snooze_lint.py``."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "plan_2_8_snooze_lint.py"


def _load():
    spec = importlib.util.spec_from_file_location("plan_2_8_snooze_lint", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["plan_2_8_snooze_lint"] = mod
    spec.loader.exec_module(mod)
    return mod


lint_mod = _load()


def test_clean_config_passes() -> None:
    r = lint_mod.lint({"snoozes": [{"tf": "5m"}]})
    assert r["ok"] is True
    assert r["findings"] == []


def test_rejects_non_object_top_level() -> None:
    r = lint_mod.lint([{"tf": "5m"}])
    assert r["ok"] is False
    assert r["findings"][0]["kind"] == "schema"


def test_rejects_non_list_snoozes() -> None:
    r = lint_mod.lint({"snoozes": "nope"})
    assert r["ok"] is False
    assert any(f["kind"] == "schema" for f in r["findings"])


def test_missing_tf_flagged() -> None:
    r = lint_mod.lint({"snoozes": [{"family": "FVG"}]})
    assert any(f["kind"] == "missing_tf" for f in r["findings"])


def test_bad_family_flagged() -> None:
    r = lint_mod.lint({"snoozes": [{"tf": "5m", "family": ""}]})
    assert any(f["kind"] == "bad_family" for f in r["findings"])


def test_duplicate_flagged() -> None:
    r = lint_mod.lint({"snoozes": [
        {"tf": "5m", "family": "FVG"},
        {"tf": "5m", "family": "FVG"},
    ]})
    assert any(f["kind"] == "duplicate" for f in r["findings"])


def test_bad_expires_flagged() -> None:
    r = lint_mod.lint({"snoozes": [{"tf": "5m", "expires": "not-a-ts"}]})
    assert any(f["kind"] == "bad_expires" for f in r["findings"])


def test_stale_entry_flagged() -> None:
    import datetime as _dt
    r = lint_mod.lint(
        {"snoozes": [{"tf": "5m", "expires": "2024-01-01T00:00:00Z"}]},
        now=_dt.datetime(2026, 4, 21, tzinfo=_dt.UTC),
    )
    assert any(f["kind"] == "stale" for f in r["findings"])


def test_render_markdown_clean_and_dirty() -> None:
    assert "No findings" in lint_mod.render_markdown(
        lint_mod.lint({"snoozes": []}),
    )
    bad = lint_mod.render_markdown(
        lint_mod.lint({"snoozes": [{"family": "FVG"}]}),
    )
    assert "missing_tf" in bad


def test_cli_exits_one_on_findings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    cfg = tmp_path / "snoozes.json"
    cfg.write_text(json.dumps({"snoozes": [{"family": "FVG"}]}),
                   encoding="utf-8")
    rc = lint_mod.main(["--config", str(cfg), "--format", "json"])
    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False


def test_cli_warn_only_always_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    cfg = tmp_path / "snoozes.json"
    cfg.write_text(json.dumps({"snoozes": [{"family": "FVG"}]}),
                   encoding="utf-8")
    rc = lint_mod.main(["--config", str(cfg), "--warn-only"])
    assert rc == 0


def test_cli_missing_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    rc = lint_mod.main(["--config", str(tmp_path / "no.json")])
    assert rc == 1
    assert "config not found" in capsys.readouterr().err


def test_cli_invalid_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    cfg = tmp_path / "snoozes.json"
    cfg.write_text("{not json", encoding="utf-8")
    rc = lint_mod.main(["--config", str(cfg)])
    assert rc == 1
    assert "invalid JSON" in capsys.readouterr().err
