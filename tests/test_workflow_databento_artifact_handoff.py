"""Audit guard for F-V5-D2 / F-V5-D3 (2026-05-01).

The Databento production export bundle hand-off between
``smc-databento-production-export.yml`` (producer) and
``smc-library-refresh.yml`` (consumer) MUST NOT use ``actions/cache``:

* ``actions/cache`` entries are branch-scoped on github.com — the
  consumer running on a non-default branch silently misses bundles
  written from ``main``.
* Cross-workflow restore semantics are unspecified and have flipped
  several times in the past, leading to F-V5-D1's silent-warning
  regression.

The supported pattern is ``actions/upload-artifact`` on the producer
side + ``dawidd6/action-download-artifact`` (or
``actions/download-artifact`` with ``run-id``) on the consumer side.

This test enforces that no ``actions/cache`` reference appears in
either workflow file. New cross-workflow data flows added later must
follow the same pattern or be explicitly exempted here with a tracking
finding ID.
"""

from __future__ import annotations

from pathlib import Path

import pytest

WORKFLOWS_DIR = Path(__file__).resolve().parents[1] / ".github" / "workflows"

_HANDOFF_WORKFLOWS = [
    "smc-databento-production-export.yml",
    "smc-library-refresh.yml",
]


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
    text = workflow_path.read_text()
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
    """F-V5-D2: producer must publish the bundle via actions/upload-artifact."""
    text = (WORKFLOWS_DIR / "smc-databento-production-export.yml").read_text()
    assert "actions/upload-artifact" in text, (
        "smc-databento-production-export.yml must publish the export bundle "
        "via actions/upload-artifact (F-V5-D2)."
    )
    assert "smc-databento-production-export-" in text, (
        "Producer artifact name must follow the smc-databento-production-export-* "
        "convention so the consumer's regex search picks it up (F-V5-D2)."
    )


def test_consumer_downloads_cross_workflow_artifact() -> None:
    """F-V5-D3: consumer must use dawidd6/action-download-artifact for hand-off."""
    text = (WORKFLOWS_DIR / "smc-library-refresh.yml").read_text()
    assert "dawidd6/action-download-artifact" in text, (
        "smc-library-refresh.yml must restore the Databento export bundle "
        "via dawidd6/action-download-artifact (F-V5-D3)."
    )
    assert "smc-databento-production-export.yml" in text, (
        "Consumer must reference the producer workflow filename in its "
        "download step so the cross-workflow link is explicit (F-V5-D3)."
    )
