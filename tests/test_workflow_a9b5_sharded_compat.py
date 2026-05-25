"""Guardrail for F-V8-D5 / A9b.5 cutover (2026-05-16).

The sharded production-export workflow MUST keep publishing an
additional `smc-databento-production-export-<DATE>-<RUN_ID>` artifact
under the legacy monolithic naming so existing downstream consumers
(notably ``smc-measurement-benchmark-rolling.yml``'s
``Restore Databento production export bundle`` step, which globs on the
``smc-databento-production-export-`` prefix) keep working after the
cron is moved from the monolithic workflow to the sharded one.

This guard prevents an accidental future edit from dropping the
compat-layer step before the legacy consumer has been migrated.
"""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOWS_DIR = Path(__file__).resolve().parents[1] / ".github" / "workflows"
SHARDED_WORKFLOW = WORKFLOWS_DIR / "smc-databento-production-export-sharded.yml"


def _publish_compat_steps() -> list[dict]:
    """Return steps for the job that publishes the legacy compat artifact.

    WF-026 (2026-05-24): the compat stage/upload were split out of the
    `reduce` job into a dedicated `publish-compat` job so a runner-shutdown
    during the heavy merge can no longer silently drop the legacy
    `smc-databento-production-export-*` artifact downstream consumers
    glob on. The semantic guards in this file still apply — they just
    look at the new job now.
    """
    with SHARDED_WORKFLOW.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    publish_job = (data.get("jobs") or {}).get("publish-compat") or {}
    return [s for s in (publish_job.get("steps") or []) if isinstance(s, dict)]


def test_compat_stage_step_present() -> None:
    names = [s.get("name") for s in _publish_compat_steps()]
    assert "Stage compat export bundle (legacy artifact name)" in names, (
        "A9b.5 compat-layer stage step missing from sharded reduce job; "
        "consumers globbing on smc-databento-production-export- will break."
    )


def test_compat_upload_step_uses_legacy_name_pattern() -> None:
    steps = _publish_compat_steps()
    upload = next(
        (s for s in steps if s.get("name") == "Upload compat export bundle (legacy artifact name)"),
        None,
    )
    assert upload is not None, "compat upload step missing"
    with_block = upload.get("with") or {}
    name_tpl = str(with_block.get("name") or "")
    assert name_tpl.startswith("smc-databento-production-export-"), (
        f"compat upload artifact name must start with the legacy prefix; got {name_tpl!r}"
    )
    assert "${{ steps.compat_stage.outputs.export_date }}" in name_tpl, (
        "compat upload artifact name must embed the staged export date so the "
        "consumer's today-prefix glob matches"
    )
    assert "${{ github.run_id }}" in name_tpl, (
        "compat upload artifact name must embed github.run_id for uniqueness"
    )
    assert with_block.get("retention-days") == 7, (
        "compat upload retention must match monolithic 7-day window"
    )
    assert with_block.get("if-no-files-found") == "error", (
        "compat upload must hard-fail on empty payload to surface staging regressions"
    )


def test_compat_upload_is_gated_on_full_success() -> None:
    steps = _publish_compat_steps()
    upload = next(
        (s for s in steps if s.get("name") == "Upload compat export bundle (legacy artifact name)"),
        None,
    )
    assert upload is not None
    cond = str(upload.get("if") or "")
    # The compat layer publishes the legacy-shaped bundle only when the
    # merged manifest is NOT partial; otherwise consumers (which have no
    # partial_run handling on the legacy path) would silently see degraded
    # data. Guard the gating clause so a future refactor cannot drop it.
    assert "success()" in cond, f"compat upload must be gated on success(); got: {cond!r}"
    assert "skip_compat" in cond, (
        f"compat upload must consult compat_stage.outputs.skip_compat; got: {cond!r}"
    )
