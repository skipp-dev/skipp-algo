"""Audit guard for F-V5-D2 / F-V5-D3 (2026-05-01).

Specifically the Databento production-export *bundle* hand-off between
the canonical producer (``smc-databento-production-export-sharded.yml``
since F-V8-cutover 2026-05-18; previously the monolithic
``smc-databento-production-export.yml``) and the consumer
(``smc-library-refresh.yml``) MUST NOT reuse the legacy
``smc-prod-export-*`` cache key prefix:

* ``actions/cache`` entries are branch-scoped on github.com — the
  consumer running on a non-default branch silently misses bundles
  written from ``main``.
* Cross-workflow restore semantics are unspecified and have flipped
  several times in the past, leading to F-V5-D1's silent-warning
  regression.

The supported pattern is ``actions/upload-artifact`` on the producer
side + ``dawidd6/action-download-artifact`` (or
``actions/download-artifact`` with ``run-id``) on the consumer side.

This guard is *bundle-handoff specific*: same-workflow cache usage with
other prefixes (e.g. ``smc-incremental-base-seed-*`` scoped to
``github.ref_name``) is legitimate and intentionally out of scope.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

WORKFLOWS_DIR = Path(__file__).resolve().parents[1] / ".github" / "workflows"

# F-V8-cutover (2026-05-18): the sharded workflow is the canonical live
# producer; the monolith is workflow_dispatch-only fallback. Both must
# still satisfy the F-V5-D2/D3 cache-prefix guard because either lane can
# be the source of the artifact a consumer downloads.
CANONICAL_PRODUCER_WORKFLOW = "smc-databento-production-export-sharded.yml"
DEPRECATED_FALLBACK_WORKFLOW = "smc-databento-production-export.yml"

_HANDOFF_WORKFLOWS = [
    CANONICAL_PRODUCER_WORKFLOW,
    DEPRECATED_FALLBACK_WORKFLOW,
    "smc-library-refresh.yml",
]

_PRODUCER_NAME_RE = re.compile(r"^smc-databento-production-export-")


def _load_workflow(name: str) -> dict:
    path = WORKFLOWS_DIR / name
    assert path.exists(), f"missing workflow: {name}"
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    assert isinstance(data, dict), f"{name}: workflow YAML must parse as a mapping"
    return data


def _iter_steps(workflow: dict):
    jobs = workflow.get("jobs") or {}
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if isinstance(step, dict):
                yield job_name, step


@pytest.mark.parametrize("workflow_name", _HANDOFF_WORKFLOWS)
def test_handoff_workflow_uses_no_cache_for_bundle(workflow_name: str) -> None:
    """F-V5-D2/D3: cross-workflow bundle hand-off must not use actions/cache.

    We fingerprint the *old* hand-off by its cache-key prefix
    ``smc-prod-export-``.  Same-workflow cache usage with other prefixes
    (e.g. the incremental_base_seed cache scoped to ``github.ref_name``)
    is legitimate and out of scope for this audit.
    """
    workflow_path = WORKFLOWS_DIR / workflow_name
    assert workflow_path.exists(), f"missing workflow: {workflow_name}"
    text = workflow_path.read_text(encoding="utf-8")
    offending_lines = [
        f"  L{idx}: {line.strip()}"
        for idx, line in enumerate(text.splitlines(), start=1)
        if "smc-prod-export-" in line and not line.lstrip().startswith("#")
    ]
    assert not offending_lines, (
        f"{workflow_name}: found stale `smc-prod-export-*` cache key reference(s). "
        "F-V5-D2/D3 (2026-05-01) replaced the cross-workflow cache hand-off "
        "with upload-artifact/download-artifact. Offenders:\n"
        + "\n".join(offending_lines)
    )


def test_producer_uploads_artifact() -> None:
    """F-V5-D2: producer must publish the bundle via actions/upload-artifact.

    Verified structurally by walking the parsed YAML for an
    ``actions/upload-artifact`` step whose ``with.name`` matches the
    bundle naming convention. A pure substring scan would accept the
    string appearing in a comment or unrelated step.

    F-V8-cutover (2026-05-18): asserts the canonical sharded producer.
    The legacy monolith retains the same upload step as a dispatch-only
    fallback; both workflows must keep emitting the legacy artifact name
    so the consumer's prefix glob keeps matching no matter which lane
    fired.
    """
    workflow = _load_workflow(CANONICAL_PRODUCER_WORKFLOW)
    matched_steps: list[str] = []
    for job_name, step in _iter_steps(workflow):
        uses = step.get("uses") or ""
        if not uses.startswith("actions/upload-artifact"):
            continue
        with_block = step.get("with") or {}
        artifact_name = str(with_block.get("name") or "")
        if _PRODUCER_NAME_RE.match(artifact_name):
            matched_steps.append(f"{job_name}:{step.get('name') or uses}")
    assert matched_steps, (
        f"{CANONICAL_PRODUCER_WORKFLOW} must publish the export bundle "
        "via an actions/upload-artifact step whose `with.name` starts with "
        "`smc-databento-production-export-` (F-V5-D2, F-V8-cutover)."
    )


def test_consumer_downloads_cross_workflow_artifact() -> None:
    """F-V5-D3: consumer must use dawidd6/action-download-artifact for hand-off.

    F-V8-cutover (2026-05-18): the consumer's ``with.workflow`` now points
    at the canonical sharded producer. Any path back to the deprecated
    monolith would silently miss the live cron's artifacts because the
    monolith no longer runs on a schedule.
    """
    workflow = _load_workflow("smc-library-refresh.yml")
    matched_steps: list[str] = []
    for job_name, step in _iter_steps(workflow):
        uses = step.get("uses") or ""
        if not uses.startswith("dawidd6/action-download-artifact"):
            continue
        with_block = step.get("with") or {}
        if str(with_block.get("workflow") or "") == CANONICAL_PRODUCER_WORKFLOW:
            matched_steps.append(f"{job_name}:{step.get('name') or uses}")
    assert matched_steps, (
        "smc-library-refresh.yml must restore the Databento export bundle "
        "via a dawidd6/action-download-artifact step whose `with.workflow` "
        f"is `{CANONICAL_PRODUCER_WORKFLOW}` (F-V5-D3, F-V8-cutover)."
    )


def test_consumer_does_not_target_deprecated_monolith() -> None:
    """F-V8-cutover (2026-05-18): consumer must never pin the deprecated
    monolith as a download source. The monolith has no schedule, so a
    consumer pinned to it would silently downgrade to whatever the last
    manual dispatch produced (potentially days stale).
    """
    workflow = _load_workflow("smc-library-refresh.yml")
    offenders: list[str] = []
    for job_name, step in _iter_steps(workflow):
        uses = step.get("uses") or ""
        if not uses.startswith("dawidd6/action-download-artifact"):
            continue
        with_block = step.get("with") or {}
        if str(with_block.get("workflow") or "") == DEPRECATED_FALLBACK_WORKFLOW:
            offenders.append(f"{job_name}:{step.get('name') or uses}")
    assert not offenders, (
        "smc-library-refresh.yml has dawidd6/action-download-artifact step(s) "
        f"still pinned to the deprecated monolith ({DEPRECATED_FALLBACK_WORKFLOW}):\n  - "
        + "\n  - ".join(offenders)
        + "\nF-V8-cutover (2026-05-18) moved the live cron to "
        f"{CANONICAL_PRODUCER_WORKFLOW}; consumer must follow."
    )
