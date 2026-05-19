"""F-V8-cutover (2026-05-18) — pin the canonical producer topology.

After the cron cutover, the daily live producer is the sharded workflow
(`smc-databento-production-export-sharded.yml`). The monolithic
`smc-databento-production-export.yml` workflow is `workflow_dispatch`-only
fallback. The watchdog (`smc-export-cron-watchdog.yml`) backstops the
canonical producer and MUST NOT dispatch the deprecated monolith — doing
so would silently re-introduce the deprecated topology on cron-misfire
recovery.

This module locks all of those invariants so a future "topology cleanup"
or a `#2292` rebase that drags in the old monolith-targeted env cannot
silently regress the cutover.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOWS = _REPO_ROOT / ".github" / "workflows"

CANONICAL_PRODUCER_WORKFLOW = "smc-databento-production-export-sharded.yml"
DEPRECATED_FALLBACK_WORKFLOW = "smc-databento-production-export.yml"
WATCHDOG_WORKFLOW = "smc-export-cron-watchdog.yml"


def _load(name: str) -> dict:
    return yaml.safe_load((_WORKFLOWS / name).read_text(encoding="utf-8"))


def _on_block(workflow: dict) -> dict:
    # PyYAML quirk: bare `on:` parses as the boolean True.
    return workflow.get("on") or workflow.get(True) or {}


def _crons(workflow: dict) -> list[str]:
    sched = (_on_block(workflow) or {}).get("schedule") or []
    return [entry.get("cron", "") for entry in sched]


def test_canonical_producer_owns_live_cron() -> None:
    """Sharded workflow keeps the 12:00 / 16:00 UTC weekday cron."""
    crons = _crons(_load(CANONICAL_PRODUCER_WORKFLOW))
    minutes_hours = []
    for c in crons:
        parts = c.split()
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            minutes_hours.append((int(parts[1]), int(parts[0])))
    # The cutover schedule is exactly two weekday ticks at 12:00 and 16:00.
    assert (12, 0) in minutes_hours and (16, 0) in minutes_hours, (
        f"{CANONICAL_PRODUCER_WORKFLOW}: live cron must include 12:00 and "
        f"16:00 UTC ticks (got {sorted(set(minutes_hours))}). F-V8-cutover "
        "(2026-05-18) promoted this workflow to the canonical schedule; "
        "losing either tick halves daily coverage."
    )


def test_deprecated_monolith_has_no_schedule() -> None:
    """Monolith must remain workflow_dispatch-only after the cutover."""
    triggers = set(_on_block(_load(DEPRECATED_FALLBACK_WORKFLOW)).keys())
    assert "schedule" not in triggers, (
        f"{DEPRECATED_FALLBACK_WORKFLOW}: must not declare a `schedule:` "
        "trigger after F-V8-cutover (2026-05-18). A schedule here would "
        "race the canonical sharded producer and double-publish artifacts."
    )
    assert "workflow_dispatch" in triggers, (
        f"{DEPRECATED_FALLBACK_WORKFLOW}: must keep workflow_dispatch as "
        "the emergency fallback trigger."
    )


def test_watchdog_targets_sharded_canonical_producer() -> None:
    """Watchdog dispatches the sharded workflow and never the monolith."""
    text = (_WORKFLOWS / WATCHDOG_WORKFLOW).read_text(encoding="utf-8")

    # env.TARGET_WORKFLOW assignment must reference the sharded workflow.
    match = re.search(
        r"^\s*TARGET_WORKFLOW:\s*(\S+)\s*$",
        text,
        flags=re.MULTILINE,
    )
    assert match, (
        f"{WATCHDOG_WORKFLOW}: missing env.TARGET_WORKFLOW assignment; "
        "the watchdog cannot decide which workflow to dispatch without it."
    )
    assert match.group(1) == CANONICAL_PRODUCER_WORKFLOW, (
        f"{WATCHDOG_WORKFLOW}: TARGET_WORKFLOW must be "
        f"{CANONICAL_PRODUCER_WORKFLOW!r} (F-V8-cutover 2026-05-18); got "
        f"{match.group(1)!r}. Dispatching the deprecated monolith on cron "
        "misfire would silently re-introduce the pre-cutover topology."
    )

    # Negative guard: the deprecated monolith filename must only appear in
    # comments that explicitly mark it as deprecated (not as the dispatch
    # target).
    for lineno, line in enumerate(text.splitlines(), start=1):
        if DEPRECATED_FALLBACK_WORKFLOW not in line:
            continue
        # `smc-databento-production-export-sharded.yml` contains the
        # monolith filename as a prefix; skip those occurrences.
        if CANONICAL_PRODUCER_WORKFLOW in line:
            continue
        stripped = line.lstrip()
        assert stripped.startswith("#"), (
            f"{WATCHDOG_WORKFLOW}:{lineno}: non-comment reference to the "
            f"deprecated monolith ({DEPRECATED_FALLBACK_WORKFLOW!r}). "
            "The watchdog must not dispatch it as a primary or fallback "
            "target after F-V8-cutover (2026-05-18). Line:\n  " + line
        )


def test_watchdog_dispatch_includes_num_shards() -> None:
    """Backup dispatch must mirror the production shard fan-out (=6).

    A watchdog-recovered run that omitted `num_shards` would fall back to
    the workflow's documented default (also 6 today), but pinning it
    explicitly here means a future default change can't silently halve a
    recovered run's coverage.
    """
    text = (_WORKFLOWS / WATCHDOG_WORKFLOW).read_text(encoding="utf-8")
    assert re.search(r'inputs\[num_shards\]=6', text), (
        f"{WATCHDOG_WORKFLOW}: dispatch payload must pin "
        "`inputs[num_shards]=6` so a backup-recovered run produces the "
        "same artifact shape as the canonical scheduled run."
    )


def test_canonical_producer_compat_artifact_uses_iso_date() -> None:
    """Compat bundle export_date must be `YYYY-MM-DD` (not `YYYYMMDD`).

    The consumer's `REFRESH_DATE` and its `smc-databento-production-export-`
    prefix match the hyphenated ISO form. A compact date would silently
    fall back to the previous day's artifact.
    """
    text = (_WORKFLOWS / CANONICAL_PRODUCER_WORKFLOW).read_text(encoding="utf-8")
    assert "date -u +%Y-%m-%d" in text, (
        f"{CANONICAL_PRODUCER_WORKFLOW}: compat stage must format "
        "EXPORT_DATE as `%Y-%m-%d` to match the consumer's prefix match."
    )
    assert "date -u +%Y%m%d" not in text, (
        f"{CANONICAL_PRODUCER_WORKFLOW}: compact `%Y%m%d` date format "
        "must not be used in the compat stage \u2014 it breaks the "
        "consumer's `smc-databento-production-export-<date>-*` prefix match."
    )


def test_canonical_producer_fails_partial_on_schedule() -> None:
    """Scheduled live ticks must hard-fail when partial_run=true.

    The reducer is permitted to emit `partial_run=true` so diagnostic
    uploads still succeed, but the workflow must refuse to publish a
    degraded canonical artifact on a `schedule` trigger.
    """
    text = (_WORKFLOWS / CANONICAL_PRODUCER_WORKFLOW).read_text(encoding="utf-8")
    assert "Fail scheduled run on partial merged manifest" in text, (
        f"{CANONICAL_PRODUCER_WORKFLOW}: missing scheduled-partial-fail "
        "gate. A scheduled live tick could otherwise succeed with no "
        "downstream-usable artifact, masking the missing data."
    )
    assert "github.event_name == 'schedule'" in text, (
        f"{CANONICAL_PRODUCER_WORKFLOW}: scheduled-partial-fail gate "
        "must restrict itself to `github.event_name == 'schedule'` so "
        "manual dispatches can still produce degraded bundles for debug."
    )


def test_canonical_producer_emits_merged_payloads() -> None:
    """Reducer must produce a real merged bundle, not a manifest-only stub.

    Without `--payload-output-dir`, the merged manifest would have no
    sibling `databento_volatility_production_merged__<frame>.parquet`
    files and the consumer's `load_export_bundle(required_frames=...)`
    would either fail or fall back to a per-shard manifest covering only
    one date slice (silently halving coverage).
    """
    text = (_WORKFLOWS / CANONICAL_PRODUCER_WORKFLOW).read_text(encoding="utf-8")
    assert "--payload-output-dir" in text, (
        f"{CANONICAL_PRODUCER_WORKFLOW}: reducer invocation must pass "
        "`--payload-output-dir` so the canonical merged bundle contains "
        "actual frame parquets, not just the manifest."
    )


def test_canonical_producer_no_symbol_disjoint_claim() -> None:
    """Shards are calendar-day-disjoint, not symbol-disjoint.

    The cutover diff briefly carried a stale comment claiming
    \"partition-disjoint at the symbol level\"; that wording is dangerous
    because it would suggest a hash-by-symbol payload merge is safe (it
    isn't — each shard processes every symbol for its date subset). Pin
    the corrected wording so the misleading claim cannot drift back.
    """
    text = (_WORKFLOWS / CANONICAL_PRODUCER_WORKFLOW).read_text(encoding="utf-8")
    # The dangerous historic wording is the *positive* claim that shards
    # split by symbol. The cutover comments may legitimately *negate* the
    # claim (e.g. "date-disjoint, not symbol-disjoint, so..."), so match
    # only the affirmative phrasings that historically existed.
    stale_phrases = (
        "partition-disjoint at the symbol level",
        "symbol-disjoint at the symbol level",
        "shards are symbol-disjoint",
    )
    offenders = [phrase for phrase in stale_phrases if phrase in text]
    assert not offenders, (
        f"{CANONICAL_PRODUCER_WORKFLOW}: contains stale positive claim(s) "
        f"that shards are symbol-disjoint: {offenders}. Shards are date-"
        "disjoint, not symbol-disjoint; misleading language here invites "
        "incorrect downstream assumptions about payload uniqueness."
    )
