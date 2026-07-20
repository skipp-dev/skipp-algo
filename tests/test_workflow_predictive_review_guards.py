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
    assert "steps.restore_export_bundle.outputs.artifact_mode == 'fallback'" in body
    assert "scripts/restore_databento_export_bundle.py" in body
    assert (
        "Refusing to publish against a stale producer bundle" in body
        or "Refusing to generate from a stale producer bundle" in body
    )


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
    # NewsAPI.ai retired 2026-07-08; assert the discipline on a still-present
    # secret (FMP): secrets belong in step env, never interpolated inline.
    body = _read_workflow("smc-live-news-refresh.yml")
    assert "FMP_API_KEY: ${{ secrets.FMP_API_KEY }}" in body
    assert "FMP_API_KEY='${{ secrets.FMP_API_KEY }}'" not in body
    assert "NEWSAPI_KEY" not in body, "NEWSAPI_KEY must not be re-added (NewsAPI.ai retired)"
    assert "scripts/publish_bot_snapshot.py" in body
    assert "refusing a cold start that could replace rolling dedup state" in body


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

    candidates = restore_bundle._list_candidates(
        "token", "skippALGO/skipp-algo", today, restore_bundle._horizon_iso("2026-05-20")
    )
    assert [item["name"] for item in candidates] == [
        f"{today}222",
        "smc-databento-production-export-2026-05-19-333",
    ]


def test_rolling_benchmark_arms_both_frame_gates() -> None:
    """Frame-integrity audit 2026-07-13: the rolling workflow hard-fails on a
    regression to the legacy 1D-onto-intraday aliasing fallback AND — since
    #3616/#3619 shipped genuine full-session frames within the CI budget
    (proof run 29285965312) — on degenerate intraday frames (<= 1
    bar/trading day). A degenerate frame now means the producer's
    benchmark_universe_ohlcv_1m frame went missing; the honest reaction is a
    red run, not silently-cloned per-TF slices."""
    body = _read_workflow("smc-measurement-benchmark-rolling.yml")
    assert "--strict-structure-tf" in body
    non_comment_lines = [
        line for line in body.splitlines() if not line.strip().startswith("#")
    ]
    assert any("--strict-frame-distinctness" in line for line in non_comment_lines), (
        "--strict-frame-distinctness must be ARMED in the rolling workflow "
        "(frame gate, armed after #3616/#3619)"
    )
    # The doc comment must be honest about the structure-tf guard's blind spot.
    assert "does NOT detect degenerate bar frames" in body
