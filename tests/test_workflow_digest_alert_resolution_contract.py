"""A broken measurement must not clear the drift alarm (plan-2-8 digest).

2026-08-15 sweep finding (Population B, workflow suppressions): the
``resolve_alerts`` step read ``has_alerts`` with ``|| echo False`` — the
upstream digest and snooze steps are ``set +e`` fail-soft, so a missing or
half-written ``alerts.json`` mapped to ``False``, and the step
"Close drift-alert issues when alerts cleared" (gated on ``== 'False'``)
then CLOSED open drift alerts on the strength of a measurement that never
happened. The fallback is now the sentinel ``unknown``, which matches
neither the opening condition (``== 'True'``) nor the closing one
(``== 'False'``): a run whose measurement broke leaves the issue state
alone and says so with a ``::warning``.

The resolve fragment is EXECUTED against the three input shapes rather than
string-matched, because the wrong behavior was invisible in the text: the
``|| echo False`` read fine — only running it against a missing file shows
the alarm-clearing output.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "plan-2-8-weekly-digest.yml"


def _steps() -> list[dict]:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return [
        step
        for job in document["jobs"].values()
        for step in job.get("steps", [])
        if isinstance(step, dict)
    ]


def _resolve_fragment() -> str:
    step = next(s for s in _steps() if s.get("id") == "resolve_alerts")
    return step["run"]


def _run_resolve(tmp_path: Path, alerts_payload: str | None) -> tuple[str, str]:
    """Execute the fragment; return (GITHUB_OUTPUT content, stdout)."""
    work = tmp_path / "work"
    (work / "artifacts" / "plan_2_8_digest").mkdir(parents=True)
    if alerts_payload is not None:
        (work / "artifacts" / "plan_2_8_digest" / "alerts.json").write_text(
            alerts_payload, encoding="utf-8"
        )
    out_file = tmp_path / "gh_output"
    out_file.write_text("")
    venv_bin = "/Users/spreuss/Documents/skipp-algo/.venv/bin"
    path = f"{venv_bin}:{os.environ['PATH']}" if Path(venv_bin).is_dir() else os.environ["PATH"]
    done = subprocess.run(
        ["/bin/bash", "-c", _resolve_fragment()],
        cwd=work,
        env={"PATH": path, "HOME": str(tmp_path), "GITHUB_OUTPUT": str(out_file)},
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    return out_file.read_text(encoding="utf-8"), done.stdout


def test_a_missing_or_unreadable_alerts_file_reads_as_unknown_not_false(
    tmp_path: Path,
) -> None:
    output, stdout = _run_resolve(tmp_path, alerts_payload=None)
    assert "has_alerts=unknown" in output, (
        "a measurement that never happened must not read as 'no alerts' — "
        f"'False' here CLOSES open drift alerts (output: {output!r})"
    )
    assert "weder geoeffnet noch geschlossen" in stdout

    output, _ = _run_resolve(tmp_path / "malformed", alerts_payload="{not json")
    assert "has_alerts=unknown" in output


def test_a_real_measurement_still_resolves_both_ways(tmp_path: Path) -> None:
    output, stdout = _run_resolve(
        tmp_path / "t", alerts_payload=json.dumps({"has_alerts": False})
    )
    assert "has_alerts=False" in output
    assert "weder geoeffnet noch geschlossen" not in stdout
    output, _ = _run_resolve(
        tmp_path / "f", alerts_payload=json.dumps({"has_alerts": True})
    )
    assert "has_alerts=True" in output


def test_unknown_matches_neither_the_open_nor_the_close_condition() -> None:
    """The sentinel only protects if BOTH conditions are exact equality —
    a `!= 'True'`-style close condition would treat unknown as cleared."""
    steps = _steps()
    conditions = [
        str(s.get("if"))
        for s in steps
        if "resolve_alerts.outputs.has_alerts" in str(s.get("if"))
    ]
    assert len(conditions) == 2, conditions
    assert sorted(conditions) == [
        "steps.resolve_alerts.outputs.has_alerts == 'False'",
        "steps.resolve_alerts.outputs.has_alerts == 'True'",
    ], conditions


def test_the_close_query_targets_only_the_digests_own_issues() -> None:
    """`cron-failure` is a SHARED label (f2-promotion-gate and others open
    standing alarms with it): a digest all-clear closing by label alone would
    destroy unrelated alarms — the bug class fixed for F2 on 2026-06-12. The
    close query must carry a title filter, and it must be the SAME prefix the
    opening step uses, or the close silently stops matching after a rename."""
    steps = _steps()
    close = next(
        s for s in _steps() if "has_alerts == 'False'" in str(s.get("if"))
    )
    open_step = next(
        s for s in _steps() if "has_alerts == 'True'" in str(s.get("if"))
    )
    assert "in:title" in close["run"], "close query filters by label only"
    title_prefix = "Plan 2.8 weekly digest: drift alerts"
    assert title_prefix in close["run"]
    assert title_prefix in open_step["run"], (
        "the opening step no longer uses the prefix the close query searches "
        "for — the two must rename together"
    )
    assert steps  # population sanity: _steps() walked a real workflow
