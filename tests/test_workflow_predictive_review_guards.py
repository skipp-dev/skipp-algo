from __future__ import annotations

from pathlib import Path

from scripts import restore_databento_export_bundle as restore_bundle


_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOWS = _REPO_ROOT / ".github" / "workflows"


def _read_workflow(name: str) -> str:
    return (_WORKFLOWS / name).read_text(encoding="utf-8")


def test_sharded_reduce_uses_setup_python_interpreter_name() -> None:
    body = _read_workflow("smc-databento-production-export-sharded.yml")
    assert "python3 -c" not in body, (
        "Inline reduce/compat gates must use the setup-python-resolved `python` "
        "binary, not system `python3`, so the partial-run guard executes under "
        "the pinned 3.12 toolchain."
    )


def test_library_refresh_rejects_stale_fallback_on_automated_runs() -> None:
    body = _read_workflow("smc-library-refresh.yml")
    assert "Reject stale Databento fallback on automated refresh" in body
    assert "github.event_name != 'workflow_dispatch'" in body
    assert "steps.restore_export_bundle_today.outputs.found_artifact != 'true'" in body
    assert "steps.restore_export_bundle_fallback.outputs.found_artifact == 'true'" in body
    assert "Refusing to publish against a stale producer bundle" in body


def test_rolling_benchmark_error_annotation_points_to_sharded_producer() -> None:
    body = _read_workflow("smc-measurement-benchmark-rolling.yml")
    assert "::error file=.github/workflows/smc-databento-production-export-sharded.yml" in body
    assert "Re-run smc-databento-production-export-sharded" in body
    assert "::error file=.github/workflows/smc-databento-production-export.yml" not in body
    assert "Re-run smc-databento-production-export and then" not in body


def test_rolling_benchmark_uv_install_targets_system_interpreter() -> None:
    body = _read_workflow("smc-measurement-benchmark-rolling.yml")
    assert 'uv pip install --python "$SMC_PYTHON_BIN" --system -r requirements.txt pytest' in body
    assert 'uv pip install --python "$SMC_PYTHON_BIN" -r requirements.txt pytest' not in body


def test_rolling_benchmark_artifact_upload_has_meta_fallbacks() -> None:
    body = _read_workflow("smc-measurement-benchmark-rolling.yml")
    upload_start = body.index("- name: Upload rolling benchmark artifacts")
    upload_block = body[upload_start : upload_start + 700]
    assert "steps.meta.outputs.run_date || 'unknown'" in upload_block
    assert "steps.meta.outputs.out_dir || 'artifacts/ci/measurement_benchmark_rolling'" in upload_block


def test_live_news_secret_is_in_step_env_not_inline_shell() -> None:
    body = _read_workflow("smc-live-newsapi-refresh.yml")
    assert "NEWSAPI_KEY: ${{ secrets.NEWSAPI_KEY }}" in body
    assert "NEWSAPI_KEY='${{ secrets.NEWSAPI_KEY }}'" not in body
    assert "live-news state persistence warning" in body


def test_restore_bundle_filters_deprecated_monolith_artifacts(monkeypatch) -> None:
    today = "smc-databento-production-export-2026-05-20-"
    artifacts = [
        {
            "id": 1,
            "name": f"{today}111",
            "created_at": "2026-05-20T18:00:00Z",
            "expired": False,
            "workflow_run": {"id": 101, "head_branch": "main"},
        },
        {
            "id": 2,
            "name": f"{today}222",
            "created_at": "2026-05-20T18:10:00Z",
            "expired": False,
            "workflow_run": {"id": 202, "head_branch": "main"},
        },
        {
            "id": 3,
            "name": "smc-databento-production-export-2026-05-19-333",
            "created_at": "2026-05-19T18:10:00Z",
            "expired": False,
            "workflow_run": {"id": 303, "head_branch": "main"},
        },
    ]

    def fake_api_get_json(_token: str, path: str) -> dict:
        if path == "repos/skippALGO/skipp-algo/actions/artifacts?per_page=100&page=1":
            return {"artifacts": artifacts}
        if path == "repos/skippALGO/skipp-algo/actions/runs/101":
            return {"path": ".github/workflows/smc-databento-production-export.yml", "name": "smc-databento-production-export"}
        if path == "repos/skippALGO/skipp-algo/actions/runs/202":
            return {"path": ".github/workflows/smc-databento-production-export-sharded.yml", "name": "smc-databento-production-export-sharded"}
        if path == "repos/skippALGO/skipp-algo/actions/runs/303":
            return {"path": ".github/workflows/smc-databento-production-export-sharded.yml", "name": "smc-databento-production-export-sharded"}
        raise AssertionError(f"unexpected API path: {path}")

    monkeypatch.setattr(restore_bundle, "_api_get_json", fake_api_get_json)

    candidates = restore_bundle._list_candidates("token", "skippALGO/skipp-algo", today)
    assert [item["name"] for item in candidates] == [
        f"{today}222",
        "smc-databento-production-export-2026-05-19-333",
    ]
