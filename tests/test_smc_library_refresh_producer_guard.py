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
    assert "::error file=.github/workflows/smc-databento-production-export-sharded.yml" in step_body, (
        "verify_export_bundle: missing clickable `::error file=...::` "
        "annotation pointing at the canonical sharded producer workflow. "
        "F-V8-cutover (2026-05-18) moved the live cron to the sharded "
        "workflow; the consumer's hard-fail annotation must point there "
        "so triage opens the right workflow file. Without the `file=` "
        "parameter the GHA UI doesn't surface a clickable link and "
        "triage time balloons (F-V5-D1)."
    )
    # Defensive: the old fake-success exit MUST NOT have crept back.
    assert "set +e" not in step_body, (
        "verify_export_bundle: `set +e` re-introduces the silent-failure "
        "mode that F-V5-D1 was raised to fix."
    )


# ---------------------------------------------------------------------------
# 2026-08-14: the same step in smc-library-publish.yml, and the date it names.
#
# The glob `databento_volatility_production_*_manifest.json` carries no date,
# so it was satisfied by ANY manifest of any age -- while the message the step
# prints names ${REFRESH_DATE}. That gap let the first night runs (once the
# TradingView queue stopped suppressing them) pass here on a day-old bundle and
# then die in the release gates on MISSING_ARTIFACT, which in turn skipped the
# consumer re-pin and the commit behind it: TradingView moved 230 -> 238 in one
# night while the repository stayed on 230.
#
# Executed, not string-matched. A read-only assertion cannot tell the two
# branches apart, and telling them apart is the entire point.
# ---------------------------------------------------------------------------

import json
import os
import subprocess

_PUBLISH = (
    pathlib.Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "smc-library-publish.yml"
)


def _publish_verify_fragment() -> str:
    body = _PUBLISH.read_text(encoding="utf-8")
    assert "id: verify_export_bundle" in body, (
        "smc-library-publish.yml: verify_export_bundle step missing — the "
        "publish half inherited F-V5-D1 when the phases were split (#4679)."
    )
    after = body.split("id: verify_export_bundle", 1)[1]
    step = re.split(r"\n      - name:", after, maxsplit=1)[0]
    run_block = step.split("run: |", 1)[1]
    return "\n".join(line[10:] if line.startswith(" " * 10) else line for line in run_block.splitlines())


def _run_verify(
    tmp_path, *, refresh_date: str, covered: list[str] | None, raw_manifest: str | None = None
):
    exports = tmp_path / "artifacts" / "smc_microstructure_exports"
    exports.mkdir(parents=True)
    if raw_manifest is not None:
        (exports / "databento_volatility_production_merged_manifest.json").write_text(
            raw_manifest, encoding="utf-8"
        )
    elif covered is not None:
        (exports / "databento_volatility_production_merged_manifest.json").write_text(
            json.dumps({"trade_dates_covered": covered}), encoding="utf-8"
        )
    outputs = tmp_path / "gh-output"
    outputs.write_text("", encoding="utf-8")
    done = subprocess.run(
        ["/bin/bash", "-c", _publish_verify_fragment()],
        cwd=tmp_path,
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(tmp_path),
            "GITHUB_OUTPUT": str(outputs),
            "REFRESH_DATE": refresh_date,
        },
        capture_output=True,
        text=True,
    )
    parsed = dict(
        line.split("=", 1)
        for line in outputs.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )
    return done, parsed


def test_a_bundle_that_covers_this_date_is_reported_as_current(tmp_path) -> None:
    done, out = _run_verify(tmp_path, refresh_date="2026-08-14", covered=["2026-08-13", "2026-08-14"])

    assert done.returncode == 0, done.stdout + done.stderr
    assert out["bundle_present"] == "true"
    assert out["bundle_for_date"] == "true"


def test_a_stale_bundle_is_reported_pending_and_does_not_abort(tmp_path) -> None:
    """Outside data hours the producer has simply not run for this date yet.

    Aborting here would be worse than the failure it replaces: the publish has
    already happened by then, so the only thing a hard stop suppresses is the
    repository's own bookkeeping.
    """
    done, out = _run_verify(tmp_path, refresh_date="2026-08-14", covered=["2026-08-12", "2026-08-13"])

    assert done.returncode == 0, "a pending export must not abort the run"
    assert out["bundle_present"] == "true"
    assert out["bundle_for_date"] == "false"


def test_no_bundle_at_all_still_hard_fails(tmp_path) -> None:
    """F-V5-D1 stays intact: absent is not the same as pending."""
    done, out = _run_verify(tmp_path, refresh_date="2026-08-14", covered=None)

    assert done.returncode == 1, "a missing producer bundle must still abort"
    assert out["bundle_present"] == "false"
    assert "bundle_for_date" not in out


def test_a_manifest_without_the_field_fails_loudly_not_into_night_mode(tmp_path) -> None:
    """2026-08-15 sweep finding: with `(.trade_dates_covered // [])` behind
    2>/dev/null, an exporter rename (the writer emits the field
    UNCONDITIONALLY) read as "does not cover yet" -- and every future run,
    including mid-data-hours with a good bundle, ran the release gates in
    --daily-export-absent night mode, forever, green. Absence of the field is
    schema drift and fails the step; only a PRESENT list that misses the date
    is the honest pending-export."""
    done, out = _run_verify(
        tmp_path, refresh_date="2026-08-15",
        covered=None, raw_manifest=json.dumps({"dates": ["2026-08-15"]}),
    )
    assert done.returncode != 0, done.stdout + done.stderr
    assert "carries no trade_dates_covered" in done.stdout
    assert "bundle_for_date" not in out, out


def test_a_corrupt_manifest_fails_loudly_too(tmp_path) -> None:
    done, out = _run_verify(
        tmp_path, refresh_date="2026-08-15", covered=None, raw_manifest="{not json"
    )
    assert done.returncode != 0, done.stdout + done.stderr
    assert "bundle_for_date" not in out, out


def test_the_release_gates_step_relaxes_only_on_a_pending_export() -> None:
    body = _PUBLISH.read_text(encoding="utf-8")
    after = body.split("id: release_gates", 1)[1]
    step = re.split(r"\n      - name:", after, maxsplit=1)[0]

    assert "steps.verify_export_bundle.outputs.bundle_for_date" in step, (
        "the gates step must read the date verdict, not re-derive it"
    )
    assert '"${BUNDLE_FOR_DATE}" = "false"' in step, (
        "only an explicit false may relax the gates — an empty value means the "
        "check did not run and must keep everything blocking"
    )
    assert "--daily-export-absent" in step
