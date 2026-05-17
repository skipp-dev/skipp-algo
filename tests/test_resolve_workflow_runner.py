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


def test_resolve_runs_on_prefers_least_specific_idle_runner(monkeypatch) -> None:
    """Non-GPU cron jobs must not monopolise the GPU-labelled runner."""
    module = _load_module()

    runners = [
        {
            "name": "ASUS",  # GPU runner, registered first
            "status": "online",
            "busy": False,
            "labels": [
                {"name": "self-hosted"}, {"name": "windows"}, {"name": "x64"},
                {"name": "skipp-self-hosted"},
                {"name": "priority-cron"},
                {"name": "priority-gpu"},
            ],
        },
        {
            "name": "ASUS-2",  # non-GPU runner, registered later
            "status": "online",
            "busy": False,
            "labels": [
                {"name": "self-hosted"}, {"name": "windows"}, {"name": "x64"},
                {"name": "skipp-self-hosted"},
                {"name": "priority-cron"},
            ],
        },
    ]

    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    resolution = module.resolve_runs_on(
        runners=runners,
        custom_label="priority-cron",
        hosted_runner="ubuntu-latest",
    )

    assert resolution.matched_runner_name == "ASUS-2"
    assert resolution.runner_environment == "self-hosted"


def test_resolve_runs_on_round_robin_tiebreaker_across_equal_runners(monkeypatch) -> None:
    """When two runners are equally specific, GITHUB_RUN_ID rotates the choice."""
    module = _load_module()

    runners = [
        {
            "name": "ASUS-2",
            "status": "online", "busy": False,
            "labels": [
                {"name": "self-hosted"}, {"name": "windows"}, {"name": "x64"},
                {"name": "skipp-self-hosted"},
            ],
        },
        {
            "name": "ASUS-3",
            "status": "online", "busy": False,
            "labels": [
                {"name": "self-hosted"}, {"name": "windows"}, {"name": "x64"},
                {"name": "skipp-self-hosted"},
            ],
        },
    ]

    picks = set()
    for run_id in (1000, 1001, 1002, 1003):
        monkeypatch.setenv("GITHUB_RUN_ID", str(run_id))
        resolution = module.resolve_runs_on(
            runners=runners,
            custom_label="skipp-self-hosted",
            hosted_runner="ubuntu-latest",
        )
        picks.add(resolution.matched_runner_name)

    assert picks == {"ASUS-2", "ASUS-3"}, f"Round-robin should hit both runners; got {picks}"


def test_resolve_runs_on_gpu_required_still_picks_gpu_runner() -> None:
    module = _load_module()

    runners = [
        {
            "name": "ASUS-2",  # non-GPU – must NOT match a priority-gpu request
            "status": "online", "busy": False,
            "labels": [
                {"name": "self-hosted"}, {"name": "windows"}, {"name": "x64"},
                {"name": "skipp-self-hosted"}, {"name": "priority-cron"},
            ],
        },
        {
            "name": "ASUS",
            "status": "online", "busy": False,
            "labels": [
                {"name": "self-hosted"}, {"name": "windows"}, {"name": "x64"},
                {"name": "skipp-self-hosted"},
                {"name": "priority-cron"}, {"name": "priority-gpu"},
            ],
        },
    ]

    resolution = module.resolve_runs_on(
        runners=runners,
        custom_label="priority-gpu",
        hosted_runner="ubuntu-latest",
    )

    assert resolution.matched_runner_name == "ASUS"


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
