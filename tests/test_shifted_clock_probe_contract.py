"""Contract for `shifted-clock-probe.yml` — a measurement whose gates are the point.

The probe answers whether a nightly shifted-clock run is feasible here. Its danger
is that a GREEN run means nothing unless the shift actually took effect: if
`faketime` silently fails to inject, the suite runs on the real clock and reports
a clean pass. That is the vacuity class this repo already fights elsewhere, so the
probe carries a ladder of gates before its expensive measurement, and this file
pins them.

Gate 0 is EXECUTED rather than read (see `tests/_workflow_step_shell.py`): a
string match cannot distinguish "refuses when the anchor is today" from "emits a
constant forever".
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from tests._workflow_step_shell import run_step

WORKFLOW = "shifted-clock-probe.yml"
_PATH = Path(__file__).resolve().parent.parent / ".github" / "workflows" / WORKFLOW


def _steps() -> list[dict]:
    doc = yaml.safe_load(_PATH.read_text(encoding="utf-8"))
    return doc["jobs"]["probe"]["steps"]


def _step_names() -> list[str]:
    return [s.get("name", "") for s in _steps()]


def test_the_three_gates_precede_the_expensive_measurement() -> None:
    """Order is load-bearing: a gate that runs after the suite cannot stop it.

    Gate 0 (anchor != today) keeps the probe from passing for the wrong reason on
    one calendar day. Gate 2 proves the control test is not vacuous. Gate 3 proves
    the shift reaches the xdist workers, not just the parent process.

    Pinned by IDENTITY, not by count: Gate 1 grew sub-gates (1b, 1c) once a run
    showed that asserting one clock configuration measures nothing when that
    configuration is the broken one. A count assertion would have made splitting
    the gate look like a regression.
    """
    names = _step_names()
    gates = [i for i, n in enumerate(names) if n.startswith("Gate ")]
    measures = [i for i, n in enumerate(names) if n.startswith("Measure ")]

    gate_ids = {names[i].split(":")[0].strip() for i in gates}
    assert {"Gate 0", "Gate 1", "Gate 2", "Gate 3"} <= gate_ids, (
        f"a numbered gate went missing, found {sorted(gate_ids)}"
    )
    assert measures, "no measurement steps -- the probe would prove nothing"
    assert max(gates) < min(measures), (
        "a gate runs after the measurement it is supposed to protect:\n  "
        + "\n  ".join(names)
    )


def test_the_anchor_is_an_advancing_start_at_instant() -> None:
    """`@<instant>` advances; a bare instant freezes; `+1d` is calendar-coupled.

    libfaketime's README: "Whenever possible, you should use relative offsets or
    'start at' dates, and not use absolute dates" -- a frozen clock "is likely to
    break programs which measure the time passing by". The `@` form is the
    documented start-at spelling. `+1d` would advance too, but a `+1d` job is
    itself coupled to the day it runs on, so a failure could never be re-run
    identically -- which is the property this whole probe exists to protect.
    """
    doc = yaml.safe_load(_PATH.read_text(encoding="utf-8"))
    # YAML 1.1 parses a bare `on:` key as the boolean True; the repo's other
    # workflow contracts use the same two-key lookup.
    on_block = doc.get("on") or doc.get(True)
    default = on_block["workflow_dispatch"]["inputs"]["anchor"]["default"]
    assert default.startswith("@"), (
        f"anchor default {default!r} is not the advancing start-at form; a frozen "
        "clock would make every date assertion in the suite deterministic-but-wrong"
    )
    assert not default.startswith(("+", "-")), "a relative offset is not re-runnable"
    anchor_date = datetime.strptime(default[1:].split(" ")[0], "%Y-%m-%d").replace(tzinfo=UTC)
    assert anchor_date > datetime.now(UTC), (
        f"the anchor {default!r} is in the past. It must stay ahead of the wall "
        "clock, or Gate 0 starts refusing runs and the probe rots."
    )


# The matrix step exists precisely to run the switch BOTH ways; exempting it by
# name is the honest encoding, and the assertion below pins that it really does.
_MATRIX_STEP = "Gate 1: measure the clock-shift configuration matrix"


def test_the_monotonic_clock_is_left_alone() -> None:
    """Nothing here fakes ELAPSED time, only the wall date -- but per invocation.

    This used to be pinned as a workflow-level `env:`. Run 31113611523 showed why
    that is wrong twice over: a workflow-level value makes the "switch off" cell
    unmeasurable, and on the libfaketime the runner's apt tree ships (0.9.10) the
    switch is itself the trigger for `OSError(EINVAL)` at `time.sleep()`, because
    that version rewrites a CLOCK_MONOTONIC absolute deadline unconditionally
    (wolfcw/libfaketime#426, fixed 2023-06-06, first released in v0.9.11).
    """
    doc = yaml.safe_load(_PATH.read_text(encoding="utf-8"))
    assert "FAKETIME_DONT_FAKE_MONOTONIC" not in (doc.get("env") or {}), (
        "a workflow-level FAKETIME_DONT_FAKE_MONOTONIC would leak into the "
        "configuration matrix and make its 'switch off' cell unmeasurable"
    )

    offenders = [
        step.get("name", "<unnamed>")
        for step in _steps()
        if 'LD_PRELOAD="$FT_LIB"' in (step.get("run") or "")
        and step.get("name") != _MATRIX_STEP
        and "FAKETIME_DONT_FAKE_MONOTONIC=1" not in (step.get("run") or "")
    ]
    assert not offenders, (
        "these steps shift the clock without leaving the monotonic clock real, "
        f"which is the documented timed-wait hang hazard: {offenders}"
    )


def test_the_configuration_matrix_measures_the_switch_both_ways() -> None:
    """Otherwise the exemption above would be a hole rather than a reason."""
    matrix = next(s for s in _steps() if s.get("name") == _MATRIX_STEP)
    run = matrix["run"]
    assert 'run_cell "DONT_FAKE_MONOTONIC=1" 1' in run
    assert 'run_cell "DONT_FAKE_MONOTONIC unset" ""' in run


def test_libfaketime_is_built_from_a_pin_that_carries_the_sleep_fix() -> None:
    """The distribution package cannot do this job, and it fails LOUDLY enough to
    look like an unrelated bug: `apt` ships 0.9.10 (2022-03), three years older
    than the release carrying the clock_nanosleep fix.
    """
    text = _PATH.read_text(encoding="utf-8")
    assert "apt-get install -y -qq faketime" not in text, (
        "the packaged libfaketime raises OSError(EINVAL) at time.sleep() under "
        "CPython >= 3.11, or hangs in timed waits with the switch off"
    )
    doc = yaml.safe_load(text)
    assert len(doc["env"]["FT_COMMIT"]) == 40, "pin the build to a commit, not a tag"
    build = next(s for s in _steps() if s.get("name", "").startswith("Build libfaketime"))
    assert "get_fake_monotonic_setting(&fake_monotonic_clock)" in build["run"], (
        "the build step must verify the pinned source carries the #426 fix "
        "rather than trusting the commit id to mean what we think it means"
    )


def test_the_control_test_is_written_outside_the_repo_test_tree() -> None:
    """It must fail on the real clock, so it cannot live in tests/."""
    writer = next(s for s in _steps() if s.get("name", "").startswith("Write the worker"))
    assert "$PROBE_DIR" in writer["run"]
    assert "PROBE_DIR: /tmp/" in _PATH.read_text(encoding="utf-8")
    assert not (Path(__file__).parent / "test_clock_reaches_workers.py").exists(), (
        "the probe's control test was committed into tests/; it fails on the real "
        "clock and would turn every ordinary run red"
    )


@pytest.mark.parametrize(
    ("anchor", "expect_rc", "why"),
    [
        ("@2028-02-29 12:00:00", 0, "a future anchor is accepted"),
        ("@TODAY 12:00:00", 1, "an anchor equal to today must be refused"),
    ],
)
def test_gate_0_refuses_an_anchor_that_equals_today(
    tmp_path: Path, anchor: str, expect_rc: int, why: str
) -> None:
    """EXECUTED, not matched. Substituting today's date for the anchor must make
    the step exit non-zero -- otherwise the probe could report a clean pass on the
    one day when the shift is indistinguishable from no shift at all.
    """
    today = datetime.now(UTC).date().isoformat()
    result = run_step(
        WORKFLOW,
        "Gate 0: the anchor is not today",
        tmp_path,
        env={"ANCHOR": anchor.replace("TODAY", today)},
    )
    assert result.returncode == expect_rc, f"{why}: rc={result.returncode}\n{result.stdout}"
    if expect_rc == 0:
        assert result.env_file.get("ANCHOR_DATE") == "2028-02-29", (
            "the gate passed without publishing ANCHOR_DATE, so every later gate "
            f"would compare against an empty string: {result.env_file}"
        )
    else:
        assert "::error::" in result.stdout, "a refusal must be visible in the log"
