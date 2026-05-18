"""Pin: every ``continue-on-error: true`` step has advisory-grade naming.

PR #124 introduced a name-allowlist for CoE-true steps and this test
extends it with a *semantic* check: the step's ``name:`` (or, when
missing, its ``id:``) MUST contain at least one keyword that signals an
advisory / best-effort / notification intent. This stops a future
contributor from sneaking a critical step under ``continue-on-error:
true`` (which would silently swallow real failures).

The walker is YAML-aware (see ``tests/_workflow_yaml.py``) so the check
is no longer fooled by indentation, comments, or step-boundary edge
cases that the previous regex-based scan had to special-case.
"""

from __future__ import annotations

from tests._workflow_yaml import (
    has_continue_on_error_true,
    iter_steps,
    iter_workflow_files,
    load_workflow,
)

# Reflects the four legitimate CoE-true use cases in this repo:
# notification side-effects, advisory probes, downloads of optional
# prior artefacts, and explicitly-labelled best-effort hops.
_ADVISORY_KEYWORDS: tuple[str, ...] = (
    "notify",
    "send",
    "publish",
    "telegram",
    "probe",
    "summary",
    "advisory",
    "best-effort",
    "best effort",
    "best.effort",
    "download",
    "commit",
    "run evidence gate",
    "run tradingview",
    "run deeper",
    "run e2e",
)


def _step_handle(step: dict[str, object]) -> str:
    """Human-readable handle for diagnostics."""
    name = step.get("name")
    if isinstance(name, str) and name:
        return name
    sid = step.get("id")
    if isinstance(sid, str) and sid:
        return f"<id:{sid}>"
    return "<unnamed step>"


def _advisory_text(step: dict[str, object]) -> str:
    """Lower-cased text we accept advisory keywords from (name first, then id)."""
    parts: list[str] = []
    for key in ("name", "id"):
        value = step.get(key)
        if isinstance(value, str):
            parts.append(value)
    return " ".join(parts).lower()


def test_continue_on_error_steps_have_advisory_naming() -> None:
    failures: list[str] = []
    for workflow in iter_workflow_files():
        data = load_workflow(workflow)
        for job_id, step in iter_steps(data):
            if not has_continue_on_error_true(step):
                continue
            handle = _step_handle(step)
            text = _advisory_text(step)
            if not text:
                failures.append(
                    f"{workflow.name}::{job_id}::{handle}: continue-on-error: "
                    "true on a step without a discoverable name/id"
                )
                continue
            if not any(kw in text for kw in _ADVISORY_KEYWORDS):
                failures.append(
                    f"{workflow.name}::{job_id}::{handle}: step name does not "
                    f"match any advisory keyword ({_ADVISORY_KEYWORDS}). "
                    "Either rename the step to express intent or remove "
                    "the continue-on-error flag — silent failure is not OK."
                )
    assert not failures, (
        "Workflow CoE-semantics violations:\n  " + "\n  ".join(failures)
    )


def test_at_least_one_continue_on_error_step_exists() -> None:
    total = 0
    for workflow in iter_workflow_files():
        for _job_id, step in iter_steps(load_workflow(workflow)):
            if has_continue_on_error_true(step):
                total += 1
    assert total > 0, (
        "No `continue-on-error: true` steps found in any workflow file. "
        "If the discipline was removed deliberately, delete this pin; "
        "otherwise the YAML walker has drifted."
    )
