"""Audit guard: when ``smc-library-refresh`` detects that the generated
library content has actually changed but the upstream Databento producer
artifact is missing, the workflow MUST hard-fail with a clickable
annotation pointing at the producer workflow — not paper over the gap
with ``::warning::`` and publish a refreshed library against stale data.

Audit marker: F-V5-D1 (2026-05-01).
"""
from __future__ import annotations

import pathlib
import re

_WORKFLOW = (
    pathlib.Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "smc-library-refresh.yml"
)


def test_verify_export_bundle_step_hard_fails_on_missing_producer() -> None:
    body = _WORKFLOW.read_text(encoding="utf-8")

    assert "id: verify_export_bundle" in body, (
        "smc-library-refresh.yml: verify_export_bundle step missing "
        "(F-V5-D1 hard-fail guard relies on it)."
    )

    # Slice out just that step body to keep the assertion narrow.
    after = body.split("id: verify_export_bundle", 1)[1]
    # Step ends at the next sibling `- name:`. Steps under
    # jobs.<job>.steps are indented 6 spaces in this file (the leading
    # `      - name:` opens each step), so split on that pattern.
    step_body = re.split(r"\n      - name:", after, maxsplit=1)[0]

    assert "set -euo pipefail" in step_body, (
        "verify_export_bundle: must run with `set -euo pipefail` so the "
        "explicit `exit 1` actually aborts the job (F-V5-D1)."
    )
    assert "exit 1" in step_body, (
        "verify_export_bundle: missing `exit 1` on the missing-bundle "
        "branch — workflow would silently publish against stale data "
        "(F-V5-D1)."
    )
    assert "::error file=.github/workflows/smc-databento-production-export.yml" in step_body, (
        "verify_export_bundle: missing clickable `::error file=...::` "
        "annotation pointing at the producer workflow. Without the "
        "`file=` parameter the GHA UI doesn't surface a clickable link "
        "and triage time balloons (F-V5-D1)."
    )
    # Defensive: the old fake-success exit MUST NOT have crept back.
    assert "set +e" not in step_body, (
        "verify_export_bundle: `set +e` re-introduces the silent-failure "
        "mode that F-V5-D1 was raised to fix."
    )
