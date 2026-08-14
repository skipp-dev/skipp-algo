"""The refresh must hand over the directory the post-release gates read from.

Between 2026-08-13 21:17Z and 2026-08-14 `smc-library-publish` failed on six
consecutive runs, every time AFTER "Publish library to TradingView" succeeded.
The post-release gates found no structure artifacts, so nothing was recorded:
TradingView reached version 238 of `smc_micro_profiles_generated` while the
repository manifest and all consumers still pinned 230, and every consumer
rollout stayed blocked on the drift check.

The cause was a documented assumption. `smc-library-refresh.yml` explained that
the raw Databento bundle is not handed over because "seine Nach-Tore brauchen
dieselben Daten" -- but they do not. `provider_health` resolves through
`smc_integration.sources.structure_artifact_json`, which reads
`reports/smc_structure_artifacts/`: 91 files derived by a 45-minute step with
external API keys that only the refresh runs. The publisher had the bundle and
not one artifact.

This test therefore does not compare two strings. It imports the resolver and
asks it where it reads from, then requires the refresh to upload exactly that
path. Moving the resolver's directory without moving the handover turns red.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from smc_integration.sources.structure_artifact_json import STRUCTURE_ARTIFACTS_DIR

ROOT = Path(__file__).resolve().parents[1]
REFRESH = ROOT / ".github" / "workflows" / "smc-library-refresh.yml"
PUBLISH = ROOT / ".github" / "workflows" / "smc-library-publish.yml"


def _steps(path: Path) -> list[dict[str, Any]]:
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [step for job in workflow["jobs"].values() for step in job.get("steps", [])]


def _named(steps: list[dict[str, Any]], prefix: str) -> int:
    matches = [i for i, s in enumerate(steps) if str(s.get("name", "")).startswith(prefix)]
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one step starting with {prefix!r}, found {len(matches)}")
    return matches[0]


def _payload_paths() -> list[str]:
    step = next(
        s
        for s in _steps(REFRESH)
        if str(s.get("name", "")).startswith("Upload refresh payload")
    )
    return [line.strip() for line in step["with"]["path"].splitlines() if line.strip()]


def test_the_resolver_directory_is_inside_the_repository() -> None:
    """Guards the premise the next assertion rests on."""
    assert STRUCTURE_ARTIFACTS_DIR.is_relative_to(ROOT), STRUCTURE_ARTIFACTS_DIR


def test_the_refresh_hands_over_the_directory_the_gates_read_from() -> None:
    wanted = STRUCTURE_ARTIFACTS_DIR.relative_to(ROOT).as_posix()
    paths = _payload_paths()

    assert len(paths) >= 4, f"payload path list looks truncated: {paths}"
    assert any(p.rstrip("/") == wanted for p in paths), (
        f"{wanted} is where provider_health resolves structure artifacts, but the "
        f"refresh payload carries only {paths}"
    )


def test_the_publisher_refuses_before_it_writes_to_tradingview() -> None:
    """Order is the whole point.

    A refusal after the publish is worthless: the TradingView version has
    already moved and cannot be taken back. The six failures of 2026-08-13/14
    each published first and discovered the missing data afterwards.
    """
    steps = _steps(PUBLISH)

    refuse = _named(steps, "Refuse to publish without the handed-over structure artifacts")
    publish = _named(steps, "Publish library to TradingView")

    assert refuse < publish, (
        f"the refusal runs at step {refuse} but the publish at {publish}; "
        "a refusal after the write cannot prevent the drift"
    )


def test_the_refusal_cross_checks_the_refresh_report_rather_than_guessing() -> None:
    """It must key off evidence the refresh produced, not a hard-coded count.

    A fixed expected file count would be a second copy of the symbol/timeframe
    matrix and would drift from it.
    """
    steps = _steps(PUBLISH)
    script = steps[_named(steps, "Refuse to publish")]["run"]

    assert "structure_artifact_availability.json" in script
    assert "reports/smc_structure_artifacts" in script
    assert 'payload.get("ok")' in script


@pytest.mark.parametrize(
    ("label", "report_ok", "artifact_count", "expected_exit"),
    [
        ("report ok, artifacts missing", True, 0, 1),
        ("report ok, artifacts present", True, 91, 0),
        ("report says not ok, artifacts missing", False, 0, 0),
    ],
)
def test_the_refusal_logic_behaves_on_every_state(
    tmp_path: Path,
    label: str,
    report_ok: bool,
    artifact_count: int,
    expected_exit: int,
) -> None:
    """Executes the step's own script, not a re-implementation of it.

    The middle row is the forward probe: it proves the guard PERMITS the fixed
    state instead of merely forbidding the broken one.
    """
    import json
    import os
    import subprocess
    import sys

    steps = _steps(PUBLISH)
    script = steps[_named(steps, "Refuse to publish")]["run"]

    (tmp_path / "artifacts" / "ci").mkdir(parents=True)
    (tmp_path / "artifacts" / "ci" / "structure_artifact_availability.json").write_text(
        json.dumps({"ok": report_ok, "verified": {"5m": 12}}), encoding="utf-8"
    )
    if artifact_count:
        directory = tmp_path / "reports" / "smc_structure_artifacts"
        directory.mkdir(parents=True)
        for index in range(artifact_count):
            (directory / f"a{index}.json").write_text("{}", encoding="utf-8")

    completed = subprocess.run(
        ["bash", "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={**os.environ, "SMC_PYTHON_BIN": sys.executable},
        check=False,
    )

    assert completed.returncode == expected_exit, completed.stdout + completed.stderr
