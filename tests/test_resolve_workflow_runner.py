from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "resolve_workflow_runner.py"
    spec = importlib.util.spec_from_file_location("resolve_workflow_runner", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_required_labels_appends_custom_label_once() -> None:
    module = _load_module()

    labels = module.build_required_labels("Skipp-Local")

    assert labels == ["self-hosted", "windows", "x64", "Skipp-Local"]
    assert module.build_required_labels("windows") == ["self-hosted", "windows", "x64"]


def test_resolve_runs_on_prefers_idle_matching_self_hosted_runner() -> None:
    module = _load_module()

    runners = [
        {
            "name": "local-laptop",
            "status": "online",
            "busy": False,
            "labels": [
                {"name": "self-hosted"},
                {"name": "windows"},
                {"name": "x64"},
                {"name": "skipp-local"},
            ],
        }
    ]

    resolution = module.resolve_runs_on(
        runners=runners,
        custom_label="skipp-local",
        hosted_runner="ubuntu-latest",
    )

    assert resolution.runs_on == ["self-hosted", "windows", "x64", "skipp-local"]
    assert resolution.runner_environment == "self-hosted"
    assert resolution.reason == "matched_idle_self_hosted_runner"
    assert resolution.matched_runner_name == "local-laptop"


def test_resolve_runs_on_falls_back_when_runner_is_busy_or_offline() -> None:
    module = _load_module()

    runners = [
        {
            "name": "busy-runner",
            "status": "online",
            "busy": True,
            "labels": [
                {"name": "self-hosted"},
                {"name": "windows"},
                {"name": "x64"},
            ],
        },
        {
            "name": "offline-runner",
            "status": "offline",
            "busy": False,
            "labels": [
                {"name": "self-hosted"},
                {"name": "windows"},
                {"name": "x64"},
            ],
        },
    ]

    resolution = module.resolve_runs_on(
        runners=runners,
        custom_label="",
        hosted_runner="ubuntu-latest",
    )

    assert resolution.runs_on == "ubuntu-latest"
    assert resolution.runner_environment == "github-hosted"
    assert resolution.reason == "no_idle_matching_self_hosted_runner"
    assert resolution.matched_runner_name is None


def test_resolve_runs_on_no_idle_fallback_required_self_hosted_routes_to_labels() -> None:
    module = _load_module()

    runners = [
        {
            "name": "busy-runner",
            "status": "online",
            "busy": True,
            "labels": [
                {"name": "self-hosted"},
                {"name": "windows"},
                {"name": "x64"},
            ],
        },
    ]

    resolution = module.resolve_runs_on(
        runners=runners,
        custom_label="",
        hosted_runner="ubuntu-latest",
        no_idle_fallback="required-self-hosted",
    )

    assert resolution.runs_on == ["self-hosted", "windows", "x64"]
    assert resolution.runner_environment == "self-hosted"
    assert resolution.reason == "no_idle_matching_self_hosted_runner:forced_required_self_hosted"
    assert resolution.matched_runner_name is None


def test_resolve_runs_on_no_idle_fallback_hosted_preserves_legacy_behavior() -> None:
    module = _load_module()

    runners = [
        {
            "name": "offline-runner",
            "status": "offline",
            "busy": False,
            "labels": [
                {"name": "self-hosted"},
                {"name": "windows"},
                {"name": "x64"},
            ],
        },
    ]

    resolution = module.resolve_runs_on(
        runners=runners,
        custom_label="",
        hosted_runner="ubuntu-latest",
        no_idle_fallback="hosted",
    )

    assert resolution.runs_on == "ubuntu-latest"
    assert resolution.runner_environment == "github-hosted"
    assert resolution.reason == "no_idle_matching_self_hosted_runner"


def test_runner_matches_required_labels_is_case_insensitive() -> None:
    module = _load_module()

    runner = {
        "labels": [
            {"name": "Self-Hosted"},
            {"name": "WINDOWS"},
            {"name": "x64"},
            {"name": "Skipp-Local"},
        ]
    }

    assert module.runner_matches_required_labels(
        runner,
        ["self-hosted", "windows", "x64", "skipp-local"],
    )


def test_build_required_labels_supports_gpu_priority_label() -> None:
    module = _load_module()

    labels = module.build_required_labels("priority-gpu")

    assert labels == ["self-hosted", "windows", "x64", "priority-gpu"]


def test_main_forces_required_self_hosted_when_inventory_unavailable(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()

    output_path = tmp_path / "github_output.txt"
    monkeypatch.setenv("GH_TOKEN", "fake-token")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))

    def _raise_inventory_error(*args, **kwargs):
        raise ValueError("simulated inventory failure")

    monkeypatch.setattr(module, "_fetch_repository_runners", _raise_inventory_error)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "resolve_workflow_runner.py",
            "--repository",
            "owner/repo",
            "--custom-label",
            "priority-cron",
            "--inventory-unavailable-fallback",
            "required-self-hosted",
        ],
    )

    exit_code = module.main()

    assert exit_code == 0
    payload = output_path.read_text(encoding="utf-8")
    assert 'runs_on_json=["self-hosted", "windows", "x64", "priority-cron"]' in payload
    assert "runner_environment=self-hosted" in payload
    assert "resolution_reason=runner_inventory_unavailable:ValueError:forced_required_self_hosted" in payload


def test_main_forces_required_self_hosted_when_token_missing(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()

    output_path = tmp_path / "github_output.txt"
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "resolve_workflow_runner.py",
            "--repository",
            "owner/repo",
            "--custom-label",
            "priority-cron",
            "--inventory-unavailable-fallback",
            "required-self-hosted",
        ],
    )

    exit_code = module.main()

    assert exit_code == 0
    payload = output_path.read_text(encoding="utf-8")
    assert 'runs_on_json=["self-hosted", "windows", "x64", "priority-cron"]' in payload
    assert "runner_environment=self-hosted" in payload
    assert "resolution_reason=missing_token_env:GH_TOKEN:forced_required_self_hosted" in payload


def test_main_no_idle_fallback_required_self_hosted_routes_when_all_busy(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_module()

    output_path = tmp_path / "github_output.txt"
    monkeypatch.setenv("GH_TOKEN", "fake-token")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))

    def _busy_inventory(*args, **kwargs):
        return [
            {
                "name": "busy-runner",
                "status": "online",
                "busy": True,
                "labels": [
                    {"name": "self-hosted"},
                    {"name": "windows"},
                    {"name": "x64"},
                ],
            },
        ]

    monkeypatch.setattr(module, "_fetch_repository_runners", _busy_inventory)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "resolve_workflow_runner.py",
            "--repository",
            "owner/repo",
            "--no-idle-fallback",
            "required-self-hosted",
        ],
    )

    exit_code = module.main()

    assert exit_code == 0
    payload = output_path.read_text(encoding="utf-8")
    assert 'runs_on_json=["self-hosted", "windows", "x64"]' in payload
    assert "runner_environment=self-hosted" in payload
    assert (
        "resolution_reason=no_idle_matching_self_hosted_runner:forced_required_self_hosted"
        in payload
    )


def test_main_force_hosted_flag_bypasses_inventory_and_self_hosted(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_module()

    output_path = tmp_path / "github_output.txt"
    monkeypatch.setenv("GH_TOKEN", "fake-token")
    monkeypatch.delenv("SMC_FORCE_GH_HOSTED", raising=False)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))

    def _explode(*args, **kwargs):
        raise AssertionError("inventory must not be queried when force-hosted")

    monkeypatch.setattr(module, "_fetch_repository_runners", _explode)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "resolve_workflow_runner.py",
            "--repository",
            "owner/repo",
            "--force-hosted",
            "--inventory-unavailable-fallback",
            "required-self-hosted",
        ],
    )

    exit_code = module.main()

    assert exit_code == 0
    payload = output_path.read_text(encoding="utf-8")
    assert 'runs_on_json="ubuntu-latest"' in payload
    assert "runner_environment=github-hosted" in payload
    assert "resolution_reason=forced_github_hosted" in payload


def test_main_force_hosted_via_env_var_without_token(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()

    output_path = tmp_path / "github_output.txt"
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("SMC_FORCE_GH_HOSTED", "1")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))

    def _explode(*args, **kwargs):
        raise AssertionError("inventory must not be queried when force-hosted")

    monkeypatch.setattr(module, "_fetch_repository_runners", _explode)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "resolve_workflow_runner.py",
            "--repository",
            "owner/repo",
            "--inventory-unavailable-fallback",
            "required-self-hosted",
        ],
    )

    exit_code = module.main()

    assert exit_code == 0
    payload = output_path.read_text(encoding="utf-8")
    assert 'runs_on_json="ubuntu-latest"' in payload
    assert "runner_environment=github-hosted" in payload
    assert "resolution_reason=forced_github_hosted" in payload
