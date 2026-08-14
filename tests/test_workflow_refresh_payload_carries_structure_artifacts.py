"""The refresh must hand over the directory the post-release gates read from.

Between 2026-08-13 21:17Z and 2026-08-14 04:51Z `smc-library-publish` failed on
six consecutive runs, every time AFTER "Publish library to TradingView"
succeeded. The post-release gates found no structure artifacts, so nothing was
recorded: TradingView reached version 238 of `smc_micro_profiles_generated`
while the repository manifest and all consumers still pinned 230.

The cause was a documented assumption. `smc-library-refresh.yml` explained that
the raw Databento bundle is not handed over because "seine Nach-Tore brauchen
dieselben Daten" -- but they do not. `provider_health` resolves through
`smc_integration.sources.structure_artifact_json`, which reads
`reports/smc_structure_artifacts/`: files derived by a 45-minute step with
external API keys that only the refresh runs. The publisher had the bundle and
not one artifact.

That outage was ended by #4693, not by this change, and the publisher has been
green since 2026-08-14 12:30Z. The missing handover is still there: in green run
31823202979 `provider_health` reports 84 MISSING_ARTIFACT and is non-blocking
only because `daily_export_absent` downgrades it. A defect covered by an
unrelated condition is still a defect, and the next run whose daily export IS
published pays for it.

Two properties are pinned here:

* The refresh uploads exactly the directory the resolver reads from. This test
  does not compare two strings -- it imports the resolver and asks it where it
  reads, so moving the resolver without moving the handover turns red.
* The publisher refuses on the refresh's own MARKER, not on a cross-check.
  That matters because the publish job checks out the tip of main rather than
  the tree of the refresh that produced its payload (7 of 7 workflow_run
  publishes on 2026-08-14). A cross-check would reject every payload from a
  refresh predating the contract, and with hourly cadence several of those are
  always in flight.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from smc_integration.sources.structure_artifact_json import REPO_ROOT, STRUCTURE_ARTIFACTS_DIR

ROOT = Path(__file__).resolve().parents[1]
REFRESH = ROOT / ".github" / "workflows" / "smc-library-refresh.yml"
PUBLISH = ROOT / ".github" / "workflows" / "smc-library-publish.yml"

MARKER_STEP = "Declare the structure-artifact handover"
UPLOAD_STEP = "Upload refresh payload"
REFUSE_STEP = "Refuse to publish without the handed-over structure artifacts"
PUBLISH_STEP = "Publish library to TradingView"


def _steps(path: Path) -> list[dict[str, Any]]:
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [step for job in workflow["jobs"].values() for step in job.get("steps", [])]


def _named(steps: list[dict[str, Any]], prefix: str) -> int:
    matches = [i for i, s in enumerate(steps) if str(s.get("name", "")).startswith(prefix)]
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one step starting with {prefix!r}, found {len(matches)}")
    return matches[0]


def _payload_paths() -> list[str]:
    steps = _steps(REFRESH)
    step = steps[_named(steps, UPLOAD_STEP)]
    return [line.strip() for line in step["with"]["path"].splitlines() if line.strip()]


def _run(script: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Execute a workflow step's own script, not a re-implementation of it."""
    return subprocess.run(
        ["bash", "-c", script],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={**os.environ, "SMC_PYTHON_BIN": sys.executable, "PYTHONPATH": str(ROOT)},
        check=False,
    )


def _seed(directory: Path, count: int) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        (directory / f"manifest_{index}.json").write_text("{}", encoding="utf-8")


@pytest.fixture(name="relative_dir")
def _relative_dir() -> str:
    return STRUCTURE_ARTIFACTS_DIR.relative_to(REPO_ROOT).as_posix()


@pytest.fixture(name="marker_script")
def _marker_script() -> str:
    steps = _steps(REFRESH)
    return str(steps[_named(steps, MARKER_STEP)]["run"])


@pytest.fixture(name="refusal_script")
def _refusal_script() -> str:
    steps = _steps(PUBLISH)
    return str(steps[_named(steps, REFUSE_STEP)]["run"])


def test_the_resolver_directory_is_inside_the_repository() -> None:
    """Guards the premise every other assertion rests on."""
    assert STRUCTURE_ARTIFACTS_DIR.is_relative_to(REPO_ROOT), STRUCTURE_ARTIFACTS_DIR


def test_the_refresh_hands_over_the_directory_the_gates_read_from(relative_dir: str) -> None:
    paths = _payload_paths()

    assert len(paths) >= 4, f"payload path list looks truncated: {paths}"
    assert any(p.rstrip("/") == relative_dir for p in paths), (
        f"{relative_dir} is where provider_health resolves structure artifacts, but the "
        f"refresh payload carries only {paths}"
    )


def test_the_marker_is_written_immediately_before_the_upload() -> None:
    """Marker and upload must not be separable.

    The whole point of a marker over a cross-check is that the step declaring
    the handover and the step performing it cannot disagree. A step inserted
    between them could make the declaration describe a different tree.
    """
    steps = _steps(REFRESH)

    marker = _named(steps, MARKER_STEP)
    upload = _named(steps, UPLOAD_STEP)

    assert upload == marker + 1, (
        f"the marker runs at step {marker} and the upload at {upload}; "
        "anything in between can change what is uploaded after it was counted"
    )


def test_the_publisher_refuses_before_it_writes_to_tradingview() -> None:
    """Order is the whole point.

    A refusal after the publish is worthless: the TradingView version has
    already moved and cannot be taken back. The six failures of 2026-08-13/14
    each published first and discovered the missing data afterwards.
    """
    steps = _steps(PUBLISH)

    refuse = _named(steps, REFUSE_STEP)
    publish = _named(steps, PUBLISH_STEP)

    assert refuse < publish, (
        f"the refusal runs at step {refuse} but the publish at {publish}; "
        "a refusal after the write cannot prevent the drift"
    )


def test_the_refusal_keys_off_the_marker_not_the_availability_report(refusal_script: str) -> None:
    """A cross-check would reject payloads the publisher must still accept.

    `structure_artifact_availability.json` is written by the refresh whenever it
    verified the artifacts in ITS OWN workspace. The publish job runs against a
    different tree, so a payload predating this contract carries an "ok" report
    and no directory -- a state that is old, not broken.
    """
    assert "structure_artifact_handover.json" in refusal_script
    assert "structure_artifact_availability.json" not in refusal_script


@pytest.mark.parametrize(
    ("label", "declared_count", "arrived_count", "expected_exit"),
    [
        ("full handover arrives", 91, 91, 0),
        ("nothing arrives", 91, 0, 1),
        ("partial handover arrives", 91, 40, 1),
        ("refresh had nothing to hand over", 0, 0, 0),
    ],
)
def test_marker_and_refusal_round_trip(
    tmp_path: Path,
    marker_script: str,
    refusal_script: str,
    relative_dir: str,
    label: str,
    declared_count: int,
    arrived_count: int,
    expected_exit: int,
) -> None:
    """Runs the refresh's marker script and the publisher's refusal back to back.

    Both halves are executed as the workflows define them, so the two counting
    rules cannot drift apart without this turning red. The first row is the
    forward probe: it proves the guard PERMITS the fixed state, not merely that
    it forbids the broken one.
    """
    _seed(tmp_path / relative_dir, declared_count)

    marker = _run(marker_script, tmp_path)
    assert marker.returncode == 0, marker.stdout + marker.stderr

    declared = json.loads((tmp_path / "artifacts" / "ci" / "structure_artifact_handover.json").read_text())
    assert declared["directory"] == relative_dir
    assert declared["file_count"] == declared_count

    # The upload is what may lose files between the two jobs; model that by
    # rebuilding the directory with only the files that arrived.
    for path in (tmp_path / relative_dir).glob("*"):
        path.unlink()
    _seed(tmp_path / relative_dir, arrived_count)

    refusal = _run(refusal_script, tmp_path)
    assert refusal.returncode == expected_exit, refusal.stdout + refusal.stderr


def test_a_payload_without_a_marker_warns_instead_of_blocking(
    tmp_path: Path,
    refusal_script: str,
    relative_dir: str,
) -> None:
    """The skew case, executed rather than argued.

    A refresh that started before this change uploads no marker. Its publish
    run checks out the tip of main and therefore RUNS this guard. It must warn.
    """
    (tmp_path / "artifacts" / "ci").mkdir(parents=True)
    (tmp_path / "artifacts" / "ci" / "structure_artifact_availability.json").write_text(
        json.dumps({"ok": True, "verified": {"5m": 12}}), encoding="utf-8"
    )

    refusal = _run(refusal_script, tmp_path)

    assert refusal.returncode == 0, refusal.stdout + refusal.stderr
    assert "::warning::" in refusal.stdout
