"""A0-Fast degraded states must be alerted by the DEPLOYED rule file.

History (Doppelgaenger-Sweep A#5, 2026-08-19). This file used to read
``services/a0_fast_detector/alert-rules.yml`` and assert that rule names
appeared in its text. That file had no deploy path -- no Prometheus read it,
its only consumers were this test and its pre-a0 sibling -- so the assertions
bought confidence in alerts that could never fire. Seven of its sixteen rules
existed nowhere else; the class had already cost 13h of blocked evidence on
2026-08-17. The rules were ported into the published Grafana file and the two
source files deleted.

Two lessons are pinned below:

* A rule is identified by what it MEASURES, not by its uid or title. The
  deployed ``pre-a0-shadow-data-missing`` carried a title about PRE-A0
  snapshots while its expression only ever looked at ``a0_fast_evidence_ready``
  -- and the old uid-only assertion stayed green through all of it.
* A rule file that nothing publishes is the defect. The last test derives the
  population of rule files from the tree and requires a publishing workflow for
  each, so a re-added orphan file fails instead of quietly accruing.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
DEPLOYED_RULES = REPO / "services/live_overlay_daemon/infra/grafana/alert-rules.yaml"

# uid -> metric names the rule's expression MUST reference. Pinning the metric
# rather than the title is the whole point: a title can drift away from its
# expression (and did), a metric reference cannot.
_REQUIRED_A0_FAST_RULES: dict[str, tuple[str, ...]] = {
    "a0-fast-stream-disconnected": ("a0_fast_stream_connected",),
    "a0-fast-slow-reader-drops": ("a0_fast_queue_dropped_total",),
    "a0-fast-record-rejections": ("a0_fast_records_rejected_total",),
    "a0-fast-queue-pressure": ("a0_fast_queue_depth", "a0_fast_queue_capacity"),
    # 2026-08-22: the stale pair. The 8s rule is gated on the REGULAR session
    # (that is where 8s carries: p95 1.7s), the 30-minute rule watches the
    # whole product window so a stream dying after the close is caught the
    # same day. The session gauges are pinned as metric references here for
    # the same reason as everything else in this table: a rule that silently
    # loses its gate goes back to burning 56.8h per 5 days, and one that
    # loses the gate the OTHER way stops watching the window entirely.
    "a0-fast-stream-stale": (
        "a0_fast_stream_connected",
        "a0_fast_last_record_age_seconds",
        "live_overlay_market_us_open",
    ),
    "a0-fast-stream-silent-extended": (
        "a0_fast_stream_connected",
        "a0_fast_last_record_age_seconds",
        "live_overlay_market_us_extended_open",
    ),
    "pre-a0-shadow-resync-stuck": ("a0_fast_resync_required_symbols",),
    "pre-a0-shadow-data-missing": (
        "a0_fast_records_received_total",
        "a0_fast_evidence_ready",
    ),
}


def _deployed_rules() -> dict[str, dict]:
    document = yaml.safe_load(DEPLOYED_RULES.read_text(encoding="utf-8"))
    return {
        rule["uid"]: rule
        for group in document["groups"]
        for rule in group["rules"]
    }


def _expressions(rule: dict) -> str:
    return "\n".join(node["model"].get("expr", "") for node in rule["data"])


def test_every_a0_fast_degraded_state_has_a_deployed_rule() -> None:
    rules = _deployed_rules()
    missing = sorted(uid for uid in _REQUIRED_A0_FAST_RULES if uid not in rules)
    assert not missing, (
        "A0-Fast degraded states without a rule in the PUBLISHED alert file: "
        f"{missing}. Adding them to an unpublished file does not alert anyone."
    )


@pytest.mark.parametrize("uid", sorted(_REQUIRED_A0_FAST_RULES))
def test_deployed_rule_measures_what_its_name_claims(uid: str) -> None:
    rule = _deployed_rules()[uid]
    expressions = _expressions(rule)
    absent = [
        metric
        for metric in _REQUIRED_A0_FAST_RULES[uid]
        if metric not in expressions
    ]
    assert not absent, (
        f"rule {uid} no longer references {absent} -- its expression drifted "
        "away from the state it is named for. This is the exact failure the "
        "old uid-only assertion missed on pre-a0-shadow-data-missing."
    )


def test_every_alert_rule_file_has_a_publishing_workflow() -> None:
    """A rule file nobody publishes is decoration that reads as protection."""
    # --others --exclude-standard so an untracked (not yet committed) rule file
    # is caught too. Found by the mutation proof: with a plain `git ls-files`
    # this tripwire stayed GREEN while an unpublished rule file sat in the
    # tree, because staging had not happened yet -- the same blindness that
    # makes the pre-push ledger guard pass on unstaged work.
    candidates = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    rule_files = [
        path
        for path in candidates
        # .github/workflows/ holds the PUBLISHERS, whose own filenames contain
        # "alert-rules" -- they are not rule files.
        if not path.startswith(".github/")
        and re.search(r"alert-rules[a-z0-9_-]*\.ya?ml$", path)
    ]
    assert rule_files, "no alert rule files discovered -- the scan broke"

    workflow_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((REPO / ".github/workflows").glob("*.yml"))
    )
    unpublished = sorted(path for path in rule_files if path not in workflow_text)
    assert not unpublished, (
        "alert rule file(s) that no workflow publishes: "
        f"{unpublished}. Either wire a publisher or delete the file -- an "
        "unpublished rule file cannot alert anyone, and tests over it read as "
        "coverage (2026-08-19: two such files carried 7 rules that existed "
        "nowhere deployed)."
    )
