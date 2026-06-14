"""Pin: every workflow declares a `# live-window: <posture>` marker.

Audit follow-up to **F-V6-F2.1 (2026-05-02)**.

Background
----------
Operational posture of a workflow (when it can fire, what it can mutate)
is implicit today — you have to read the trigger block + permissions + cron
schedule to reconstruct it. This pin makes the posture explicit at the top
of every workflow file, so a reviewer can see at a glance whether a
``permissions:`` change or a new cron entry violates the declared contract.

Posture vocabulary (7 values)
-----------------------------
- ``off-hours-only`` — schedule-only AND no contents/pull-requests/issues
  writes (read-only telemetry / report generation).
- ``mutating-on-cron`` — schedule-triggered AND has at least one write
  permission (commits artifacts, opens PRs, files issues).
- ``live-cron`` — schedule-triggered workflow intentionally running inside
    the live trading handoff window (Databento producer cutover).
- ``any-trigger`` — fires on push/pull_request (CI gates, ephemeral).
- ``manual-only`` — workflow_dispatch / workflow_call only.
- ``deprecated-workflow_dispatch-only`` — legacy manual-only workflow kept
    temporarily for rollback / compat until downstream cutover is complete.
- ``release-driven`` — fires on release events.

The marker MUST appear within the first 10 lines and match the regex
``^# live-window: (\\S+)``.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WF_DIR = _REPO_ROOT / ".github" / "workflows"
_MARKER_RE = re.compile(r"^# live-window:\s+(\S+)")
_VALID_POSTURES = {
    "off-hours-only",
    "mutating-on-cron",
    "live-cron",
    "any-trigger",
    "manual-only",
    "deprecated-workflow_dispatch-only",
    "release-driven",
}
_WRITE_PERMS_OF_INTEREST = {"contents", "pull-requests", "issues"}


def _all_workflow_files() -> list[Path]:
    # F1 (audit 2026-05-02): also match `.yaml` so future renames don't silently bypass this guard.
    return sorted(set(_WF_DIR.glob("*.yml")) | set(_WF_DIR.glob("*.yaml")))


def _read_marker(path: Path) -> str | None:
    for line in path.read_text(encoding="utf-8").splitlines()[:10]:
        m = _MARKER_RE.match(line)
        if m:
            return m.group(1)
    return None


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _trigger_keys(wf: dict) -> set[str]:
    triggers = wf.get(True, wf.get("on", {}))  # PyYAML: `on:` parses as True
    if isinstance(triggers, dict):
        return set(triggers.keys())
    if isinstance(triggers, list):
        return set(triggers)
    if isinstance(triggers, str):
        return {triggers}
    return set()


def _write_perms(wf: dict) -> set[str]:
    # Union of workflow-level AND job-level permissions: a workflow whose
    # job carries issues:write is mutating regardless of where the grant
    # is declared (least-privilege layouts put it on the job, e.g.
    # meta-watchdog.yml).
    def _from(perms: object) -> set[str]:
        if perms == "write-all":
            return {"ALL"}
        if not isinstance(perms, dict):
            return set()
        return {k for k, v in perms.items() if v == "write"}

    writes = _from(wf.get("permissions"))
    jobs = wf.get("jobs")
    if isinstance(jobs, dict):
        for job in jobs.values():
            if isinstance(job, dict):
                writes |= _from(job.get("permissions"))
    return writes


def test_all_workflows_have_known_posture_marker() -> None:
    files = _all_workflow_files()
    assert files, f"No workflow files under {_WF_DIR}"
    missing: list[str] = []
    invalid: list[str] = []
    for path in files:
        posture = _read_marker(path)
        if posture is None:
            missing.append(path.name)
        elif posture not in _VALID_POSTURES:
            invalid.append(f"{path.name}: '{posture}' not in {sorted(_VALID_POSTURES)}")
    assert not missing, (
        "F-V6-F2.1 (2026-05-02): the following workflows lack a "
        "`# live-window:` marker in the first 10 lines:\n  " + "\n  ".join(missing)
    )
    assert not invalid, (
        "F-V6-F2.1 (2026-05-02): the following workflows declare a posture "
        "outside the accepted vocabulary:\n  " + "\n  ".join(invalid)
    )


@pytest.mark.parametrize("path", _all_workflow_files(), ids=lambda p: p.name)
def test_off_hours_only_has_no_write_permissions(path: Path) -> None:
    posture = _read_marker(path)
    if posture != "off-hours-only":
        pytest.skip(f"posture is {posture!r}, not off-hours-only")
    wf = _load_yaml(path)
    writes = _write_perms(wf) & _WRITE_PERMS_OF_INTEREST
    assert not writes, (
        f"{path.name} declares `# live-window: off-hours-only` but has "
        f"write permissions on {sorted(writes)}. Either drop the writes "
        "or change the marker to `mutating-on-cron`."
    )


@pytest.mark.parametrize("path", _all_workflow_files(), ids=lambda p: p.name)
def test_mutating_on_cron_has_schedule_and_write(path: Path) -> None:
    posture = _read_marker(path)
    if posture != "mutating-on-cron":
        pytest.skip(f"posture is {posture!r}, not mutating-on-cron")
    wf = _load_yaml(path)
    triggers = _trigger_keys(wf)
    assert "schedule" in triggers, (
        f"{path.name} declares `# live-window: mutating-on-cron` but has no "
        f"schedule trigger (triggers={sorted(triggers)}). Use "
        "`manual-only` or `any-trigger` instead."
    )
    writes = _write_perms(wf) & _WRITE_PERMS_OF_INTEREST
    assert writes, (
        f"{path.name} declares `# live-window: mutating-on-cron` but has no "
        "write permissions on contents/pull-requests/issues. Either grant a "
        "write permission or change the marker to `off-hours-only`."
    )


@pytest.mark.parametrize("path", _all_workflow_files(), ids=lambda p: p.name)
def test_live_cron_has_schedule(path: Path) -> None:
    posture = _read_marker(path)
    if posture != "live-cron":
        return
    wf = _load_yaml(path)
    triggers = _trigger_keys(wf)
    assert "schedule" in triggers, (
        f"{path.name} declares `# live-window: live-cron` but has no schedule "
        f"trigger (triggers={sorted(triggers)})."
    )


@pytest.mark.parametrize("path", _all_workflow_files(), ids=lambda p: p.name)
def test_deprecated_dispatch_only_has_no_schedule(path: Path) -> None:
    posture = _read_marker(path)
    if posture != "deprecated-workflow_dispatch-only":
        return
    wf = _load_yaml(path)
    triggers = _trigger_keys(wf)
    assert "workflow_dispatch" in triggers, (
        f"{path.name} declares deprecated dispatch-only posture but has no "
        f"workflow_dispatch trigger (triggers={sorted(triggers)})."
    )
    assert "schedule" not in triggers, (
        f"{path.name} declares deprecated dispatch-only posture but still has "
        f"a schedule trigger (triggers={sorted(triggers)})."
    )


@pytest.mark.parametrize("path", _all_workflow_files(), ids=lambda p: p.name)
def test_at_most_one_live_window_marker(path: Path) -> None:
    """Exactly one posture marker per file.

    A second ``# live-window:`` line in the header is dead config: only the
    first match is read (``_read_marker``), so a divergent posture word on a
    later line silently misrepresents the workflow. Document the cron schedule
    with a plain ``# Schedule:`` comment instead.
    """
    head = path.read_text(encoding="utf-8").splitlines()[:10]
    markers = [ln for ln in head if _MARKER_RE.match(ln)]
    assert len(markers) <= 1, (
        f"{path.name}: {len(markers)} `# live-window:` markers in the first 10 "
        "lines; only the first is read by the posture pins. Keep one marker and "
        "use a plain `# Schedule:` comment for cron documentation.\n  "
        + "\n  ".join(markers)
    )


def test_workflow_count_matches_expected() -> None:
    """Sanity: alert if a new workflow was added without a posture mapping."""
    assert len(_all_workflow_files()) >= 28, (
        "Expected ≥28 workflows; F-V6-F2.1 was authored against 28. "
        "If you added new workflows, give each one a `# live-window:` marker."
    )
