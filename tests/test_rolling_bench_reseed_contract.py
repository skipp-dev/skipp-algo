"""Contract pin: the one-time accumulated-pool reseed path (2026-07-06).

The rolling benchmark's accumulate step rebuilds the FamilyEvent pool by
merging today's events onto the previous accumulated artifact. That artifact
was poisoned for weeks by the pre-score-persistence accumulator (scores
stripped off aged events), so the magnitude walk-forward saw ~0 usable
samples. This pins the ``reseed_accumulated`` dispatch input + wiring that
lets an operator merge onto a committed clean rebuild once, and pins that the
clean rebuild file exists.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WF = _REPO_ROOT / ".github" / "workflows" / "smc-measurement-benchmark-rolling.yml"
_RESEED_SEED = _REPO_ROOT / "artifacts" / "ci" / "scored_family_events_accumulated_reseed.json"


def _load() -> dict:
    return yaml.safe_load(_WF.read_text(encoding="utf-8"))


def test_reseed_input_declared() -> None:
    data = _load()
    on_block = data.get("on") or data.get(True)
    inputs = on_block["workflow_dispatch"]["inputs"]
    assert "reseed_accumulated" in inputs
    assert inputs["reseed_accumulated"]["default"] is False, (
        "reseed must default OFF — it is a one-time un-poisoning, not normal flow"
    )


def test_accumulate_step_wires_reseed() -> None:
    data = _load()
    steps = data["jobs"]["rolling-benchmark"]["steps"]
    step = next(s for s in steps if s.get("id") == "accumulate_events")
    env = step.get("env") or {}
    assert env.get("RESEED") == "${{ inputs.reseed_accumulated }}"
    seed_file = env.get("RESEED_SEED_FILE", "")
    assert seed_file.endswith("scored_family_events_accumulated_reseed.json")
    body = step["run"]
    # When reseed is on, the committed clean rebuild is used as --previous
    # instead of the downloaded (poisoned) artifact.
    assert 'if [ "${RESEED}" = "true" ]' in body
    assert "RESEED_SEED_FILE" in body


def test_accumulated_pool_never_overwrites_last_good_when_restore_fails() -> None:
    data = _load()
    steps = data["jobs"]["rolling-benchmark"]["steps"]
    accumulate = next(step for step in steps if step.get("id") == "accumulate_events")
    body = str(accumulate.get("run") or "")
    assert "previous accumulated pool was not restored" in body
    assert 'echo "publishable=false"' in body
    assert 'cp "${CURRENT}" "${ACCUMULATED}"' not in body

    upload = next(
        step
        for step in steps
        if step.get("name") == "Upload accumulated family events (ADR-0023 Option B)"
    )
    assert upload["if"] == "always() && steps.accumulate_events.outputs.publishable == 'true'"


def test_reseed_seed_file_exists_and_is_a_family_event_list() -> None:
    assert _RESEED_SEED.is_file(), f"missing committed reseed pool: {_RESEED_SEED}"
    events = json.loads(_RESEED_SEED.read_text(encoding="utf-8"))
    assert isinstance(events, list) and events, "reseed pool must be a non-empty list"
    # Sanity: it carries scored events (the whole point — recovered scores).
    scored = sum(1 for e in events if isinstance(e, dict) and e.get("score") is not None)
    assert scored > 0, "reseed pool has no scored events — nothing to recover"
    fams = {e.get("family") for e in events if isinstance(e, dict)}
    assert {"BOS", "SWEEP"} <= fams, f"reseed pool missing candidate families: {fams}"
