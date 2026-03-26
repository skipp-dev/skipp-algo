from __future__ import annotations

import json
from pathlib import Path

from scripts.export_smc_snapshot_bundle import export_snapshot_bundle
from tests.helpers.smc_test_artifacts import make_minimal_workbook


def test_single_symbol_export_works_with_explicit_workbook(tmp_path: Path) -> None:
    workbook = make_minimal_workbook(tmp_path)
    out = tmp_path / "bundle.json"
    written = export_snapshot_bundle(symbol="IBG", timeframe="15m", output=out, workbook_path=str(workbook))

    assert written == out
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["resolved_inputs"]["workbook_path"] == str(workbook)


def test_single_symbol_export_fallback_to_canonical_resolver_path(tmp_path: Path, monkeypatch) -> None:
    workbook = make_minimal_workbook(tmp_path)

    import smc_integration.artifact_resolution as resolution

    monkeypatch.setattr(resolution, "REPO_ROOT", tmp_path)
    out = tmp_path / "bundle.json"
    export_snapshot_bundle(symbol="IBG", timeframe="15m", output=out)

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["resolved_inputs"]["workbook_path"] == str(workbook)


def test_single_symbol_missing_input_is_deterministic(tmp_path: Path, monkeypatch) -> None:
    import smc_integration.artifact_resolution as resolution

    monkeypatch.setattr(resolution, "REPO_ROOT", tmp_path)
    out = tmp_path / "bundle.json"
    export_snapshot_bundle(symbol="IBG", timeframe="15m", output=out)

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["resolved_inputs"]["workbook_path"] is None
    assert payload["resolved_inputs"]["export_bundle_root"] is None
    assert any(item.get("code") == "WORKBOOK_NOT_FOUND" for item in payload.get("errors", []))
