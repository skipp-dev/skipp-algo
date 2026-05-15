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
