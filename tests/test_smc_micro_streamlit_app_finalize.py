from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from scripts import smc_micro_streamlit_app
from scripts.smc_micro_streamlit_app import (
    build_finalize_base_result,
    resolve_base_manifest_for_csv,
    run_streamlit_micro_base_app,
)


class _ContextBlock:
    def __enter__(self) -> "_ContextBlock":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class _StatusRecorder:
    def __init__(self, label: str) -> None:
        self.label = label
        self.messages: list[str] = []
        self.updates: list[dict[str, object]] = []

    def write(self, message: str) -> None:
        self.messages.append(str(message))

    def update(self, **kwargs: object) -> None:
        self.updates.append(kwargs)


class _FakeColumn:
    def __init__(self, owner: "_FakeStreamlit") -> None:
        self.owner = owner

    def button(self, label: str, **_: object) -> bool:
        return bool(self.owner.button_responses.get(label, False))

    def metric(self, *args: object, **kwargs: object) -> None:
        self.owner.metrics.append((args, kwargs))


class _FakeStreamlit(types.ModuleType):
    def __init__(
        self,
        *,
        export_dir: Path,
        button_responses: dict[str, bool] | None = None,
    ) -> None:
        super().__init__("streamlit")
        self.session_state: dict[str, object] = {}
        self.sidebar = _ContextBlock()
        self.button_responses = button_responses or {}
        self.text_input_values = {"Export directory": str(export_dir)}
        self.selectbox_values: dict[str, object] = {}
        self.success_messages: list[str] = []
        self.error_messages: list[str] = []
        self.warning_messages: list[str] = []
        self.info_messages: list[str] = []
        self.metrics: list[tuple[tuple[object, ...], dict[str, object]]] = []
        self.statuses: list[_StatusRecorder] = []

    def set_page_config(self, **_: object) -> None:
        return None

    def title(self, *_: object, **__: object) -> None:
        return None

    def caption(self, *_: object, **__: object) -> None:
        return None

    def subheader(self, *_: object, **__: object) -> None:
        return None

    def divider(self) -> None:
        return None

    def text_input(
        self,
        label: str,
        value: str = "",
        **_: object,
    ) -> str:
        return str(self.text_input_values.get(label, value))

    def selectbox(
        self,
        label: str,
        options: list[object],
        index: int | None = 0,
        **_: object,
    ) -> object:
        if label in self.selectbox_values:
            return self.selectbox_values[label]
        if options and index is not None:
            return options[index]
        return None

    def number_input(self, label: str, value: object = None, **_: object) -> object:
        return value

    def checkbox(self, label: str, value: bool = False, **_: object) -> bool:
        return value

    def columns(self, spec: int | list[object]) -> list[_FakeColumn]:
        count = spec if isinstance(spec, int) else len(spec)
        return [_FakeColumn(self) for _ in range(count)]

    def status(self, label: str, **_: object) -> _StatusRecorder:
        status = _StatusRecorder(label)
        self.statuses.append(status)
        return status

    def error(self, message: object) -> None:
        self.error_messages.append(str(message))

    def success(self, message: object) -> None:
        self.success_messages.append(str(message))

    def warning(self, message: object) -> None:
        self.warning_messages.append(str(message))

    def info(self, message: object) -> None:
        self.info_messages.append(str(message))

    def dataframe(self, *_: object, **__: object) -> None:
        return None

    def expander(self, *_: object, **__: object) -> _ContextBlock:
        return _ContextBlock()

    def text(self, *_: object, **__: object) -> None:
        return None


class _FakeDotenv(types.ModuleType):
    def load_dotenv(self, *args: object, **kwargs: object) -> None:
        return None


def _write_base_csv(path: Path) -> Path:
    pd.DataFrame(
        [
            {
                "asof_date": "2026-04-03",
                "symbol": "AAPL",
                "adv_dollar_rth_20d": 1_000_000.0,
            }
        ]
    ).to_csv(path, index=False)
    return path


def test_resolve_base_manifest_for_csv_prefers_companion_manifest(tmp_path: Path) -> None:
    base_csv = _write_base_csv(
        tmp_path / "demo__smc_microstructure_base_2026-04-03.csv"
    )
    manifest = tmp_path / "demo__smc_microstructure_base_manifest.json"
    manifest.write_text("{}\n", encoding="utf-8")

    assert resolve_base_manifest_for_csv(base_csv, tmp_path) == manifest


def test_resolve_base_manifest_for_csv_matches_manifest_payload(tmp_path: Path) -> None:
    base_csv = _write_base_csv(
        tmp_path / "selected__smc_microstructure_base_2026-04-03.csv"
    )
    manifest = tmp_path / "other__smc_microstructure_base_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "base_csv_path": base_csv.name,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert resolve_base_manifest_for_csv(base_csv, tmp_path) == manifest


def test_build_finalize_base_result_reuses_matching_session_result(tmp_path: Path) -> None:
    base_csv = _write_base_csv(
        tmp_path / "demo__smc_microstructure_base_2026-04-03.csv"
    )
    session_result = {
        "base_snapshot": pd.read_csv(base_csv),
        "output_paths": {"base_csv": base_csv},
    }

    result = build_finalize_base_result(
        base_csv_path=base_csv,
        export_dir=tmp_path,
        session_base_result=session_result,
    )

    assert result is session_result


def test_build_finalize_base_result_reconstructs_output_paths_from_manifest(
    tmp_path: Path,
) -> None:
    base_csv = _write_base_csv(
        tmp_path / "demo__smc_microstructure_base_2026-04-03.csv"
    )
    mapping_md = tmp_path / "demo__smc_microstructure_mapping_2026-04-03.md"
    mapping_json = tmp_path / "demo__smc_microstructure_mapping_2026-04-03.json"
    micro_day = tmp_path / "demo__smc_microstructure_symbol_day_features.parquet"
    mapping_md.write_text("# mapping\n", encoding="utf-8")
    mapping_json.write_text("{}\n", encoding="utf-8")
    micro_day.write_text("placeholder\n", encoding="utf-8")
    manifest = tmp_path / "demo__smc_microstructure_base_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "base_csv_path": base_csv.name,
                "mapping_md_path": mapping_md.name,
                "mapping_json_path": mapping_json.name,
                "micro_day_parquet_path": micro_day.name,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = build_finalize_base_result(
        base_csv_path=base_csv,
        export_dir=tmp_path,
        session_base_result=None,
    )

    assert list(result["base_snapshot"]["symbol"]) == ["AAPL"]
    assert result["output_paths"]["base_csv"] == base_csv
    assert result["output_paths"]["base_manifest"] == manifest
    assert result["output_paths"]["mapping_md"] == mapping_md
    assert result["output_paths"]["mapping_json"] == mapping_json
    assert result["output_paths"]["micro_day_parquet"] == micro_day


def test_run_streamlit_micro_base_app_generate_pine_uses_shared_finalizer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    base_csv = _write_base_csv(
        export_dir / "demo__smc_microstructure_base_2026-04-03.csv"
    )
    manifest = export_dir / "demo__smc_microstructure_base_manifest.json"
    manifest.write_text(
        json.dumps({"base_csv_path": base_csv.name}) + "\n",
        encoding="utf-8",
    )

    fake_streamlit = _FakeStreamlit(
        export_dir=export_dir,
        button_responses={"Generate Pine Library": True},
    )
    fake_dotenv = _FakeDotenv("dotenv")
    schema_path = tmp_path / "microstructure_schema.json"
    schema_path.write_text("{}\n", encoding="utf-8")
    finalize_calls: list[dict[str, Any]] = []

    def fake_finalize_pipeline(**kwargs: Any) -> dict[str, Any]:
        finalize_calls.append(kwargs)
        return {
            "pine_paths": {"library_pine": export_dir / "generated_library.pine"},
            "symbols_count": 1,
            "output_root": kwargs["output_root"],
            "artifacts_root": kwargs["artifacts_root"],
            "stale_providers": [],
            "live_news_snapshot": {
                "status": "ok",
                "snapshot_path": export_dir / "smc_live_news_snapshot.json",
                "state_path": export_dir / "smc_live_news_state.json",
            },
        }

    import scripts.generate_smc_micro_base_from_databento as generator_module
    import scripts.smc_micro_publish_guard as publish_guard_module
    import scripts.smc_microstructure_base_runtime as runtime_module
    import scripts.smc_schema_resolver as schema_resolver_module

    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)
    monkeypatch.setitem(sys.modules, "dotenv", fake_dotenv)
    monkeypatch.setattr(
        generator_module,
        "finalize_pipeline",
        fake_finalize_pipeline,
    )
    monkeypatch.setattr(
        publish_guard_module,
        "evaluate_micro_library_publish_guard",
        lambda **_: {
            "can_publish": False,
            "message": "Publish disabled for smoke test.",
            "severity": "warning",
            "contract": {},
        },
    )
    monkeypatch.setattr(
        runtime_module,
        "run_databento_base_scan_pipeline",
        lambda **_: pytest.fail(
            "run_databento_base_scan_pipeline should not run during generate-only smoke test"
        ),
    )
    monkeypatch.setattr(
        schema_resolver_module,
        "resolve_microstructure_schema_path",
        lambda: schema_path,
    )

    run_streamlit_micro_base_app()

    assert len(finalize_calls) == 1
    finalize_call = finalize_calls[0]
    assert finalize_call["schema_path"] == schema_path
    assert finalize_call["output_root"] == Path(smc_micro_streamlit_app.__file__).resolve().parents[1]
    assert finalize_call["artifacts_root"] == export_dir
    assert finalize_call["emit_live_news_snapshot"] is True
    assert finalize_call["base_result"]["output_paths"]["base_csv"] == base_csv
    assert list(finalize_call["base_result"]["base_snapshot"]["symbol"]) == ["AAPL"]
    pine_result = fake_streamlit.session_state["smc_pine_result"]
    assert isinstance(pine_result, dict)
    assert pine_result["artifacts_root"] == export_dir
    assert not fake_streamlit.error_messages
    assert any(
        "shared finalize pipeline" in message.lower()
        for message in fake_streamlit.success_messages
    )


def test_run_streamlit_micro_base_app_generate_pine_reuses_selected_session_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    skipped_base_csv = _write_base_csv(
        export_dir / "older__smc_microstructure_base_2026-04-02.csv"
    )
    selected_base_csv = _write_base_csv(
        export_dir / "selected__smc_microstructure_base_2026-04-03.csv"
    )
    selected_manifest = export_dir / "selected__smc_microstructure_base_manifest.json"
    selected_manifest.write_text(
        json.dumps({"base_csv_path": selected_base_csv.name}) + "\n",
        encoding="utf-8",
    )

    fake_streamlit = _FakeStreamlit(
        export_dir=export_dir,
        button_responses={"Generate Pine Library": True},
    )
    fake_streamlit.selectbox_values["Base snapshot for Pine generation"] = (
        selected_base_csv.name
    )
    session_base_result = {
        "base_snapshot": pd.read_csv(selected_base_csv),
        "output_paths": {
            "base_csv": selected_base_csv,
            "base_manifest": selected_manifest,
        },
        "warnings": [],
    }
    fake_streamlit.session_state["smc_base_result"] = session_base_result
    fake_dotenv = _FakeDotenv("dotenv")
    schema_path = tmp_path / "microstructure_schema.json"
    schema_path.write_text("{}\n", encoding="utf-8")
    finalize_calls: list[dict[str, Any]] = []

    def fake_finalize_pipeline(**kwargs: Any) -> dict[str, Any]:
        finalize_calls.append(kwargs)
        return {
            "pine_paths": {"library_pine": export_dir / "selected_library.pine"},
            "symbols_count": 1,
            "output_root": kwargs["output_root"],
            "artifacts_root": kwargs["artifacts_root"],
            "stale_providers": [],
            "live_news_snapshot": {
                "status": "ok",
                "snapshot_path": export_dir / "smc_live_news_snapshot.json",
                "state_path": export_dir / "smc_live_news_state.json",
            },
        }

    import scripts.generate_smc_micro_base_from_databento as generator_module
    import scripts.smc_micro_publish_guard as publish_guard_module
    import scripts.smc_microstructure_base_runtime as runtime_module
    import scripts.smc_schema_resolver as schema_resolver_module

    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)
    monkeypatch.setitem(sys.modules, "dotenv", fake_dotenv)
    monkeypatch.setattr(
        generator_module,
        "finalize_pipeline",
        fake_finalize_pipeline,
    )
    monkeypatch.setattr(
        publish_guard_module,
        "evaluate_micro_library_publish_guard",
        lambda **_: {
            "can_publish": False,
            "message": "Publish disabled for smoke test.",
            "severity": "warning",
            "contract": {},
        },
    )
    monkeypatch.setattr(
        runtime_module,
        "run_databento_base_scan_pipeline",
        lambda **_: pytest.fail(
            "run_databento_base_scan_pipeline should not run during generate-only regression test"
        ),
    )
    monkeypatch.setattr(
        schema_resolver_module,
        "resolve_microstructure_schema_path",
        lambda: schema_path,
    )

    run_streamlit_micro_base_app()

    assert skipped_base_csv.exists()
    assert len(finalize_calls) == 1
    finalize_call = finalize_calls[0]
    assert finalize_call["base_result"] is session_base_result
    assert finalize_call["schema_path"] == schema_path
    assert finalize_call["artifacts_root"] == export_dir
    assert finalize_call["base_result"]["output_paths"]["base_csv"] == selected_base_csv
    assert fake_streamlit.statuses
    status = fake_streamlit.statuses[0]
    assert any(
        "resolving the selected base snapshot" in message.lower()
        for message in status.messages
    )
    assert any(
        "running the shared finalizer" in message.lower()
        for message in status.messages
    )
    assert any(
        update.get("label") == "Pine library artifacts generated."
        and update.get("state") == "complete"
        for update in status.updates
    )
    assert not any(
        "multiple generated base snapshots were found" in message.lower()
        for message in fake_streamlit.info_messages
    )
