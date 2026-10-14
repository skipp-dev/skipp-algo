"""Deliberate-fail-soft rationale pin (Bundle D-3 / issue #2422).

Issue #2422 finding A listed 6 ``::warning::`` + ``status=skipped`` rows
in 3 workflows. After operator review (2026-05-29):

  * 3 rows were hardened to ``::error::`` in PRs #2421 + #2426 (Bundle A).
  * 3 rows remain DELIBERATE fail-soft per documented policy:
      - ``promotion-gate-daily.yml`` rolling-bench download missing
        (W1.b advisory — honest red reports during gate adoption)
      - ``promotion-gate-daily.yml`` gate rc=2 (blocked/missing metrics)
        (W1.b advisory — same)
      - ``c13-daily-cron.yml`` backfill=0 despite pending>0
        (Phase 1: warning only; Phase 2 hard-fail after 7-day baseline)
      - ``f2-promotion-gate-daily.yml`` dual-arm artefacts missing
        (L-2 audit 2026-04-24: warn per run, by-design while upstream
        is still producing arms)

Each deliberate row has a rationale comment in-workflow so the next
post-mortem does not re-discover it as a bug. This file pins those
rationale phrases — if someone removes them without re-evaluating the
fail-soft, the test fails loudly.

This is the mechanism that makes "deliberate" durable.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WF_DIR = _REPO_ROOT / ".github" / "workflows"


@dataclass(frozen=True)
class _RationaleRequirement:
    workflow: str
    finding: str   # row label from issue #2422
    must_contain: tuple[str, ...]
    rationale_url_or_id: str  # short tag pointing to the policy doc / audit


_REQUIREMENTS: tuple[_RationaleRequirement, ...] = (
    _RationaleRequirement(
        workflow="promotion-gate-daily.yml",
        finding="A#1 — rolling-bench download missing",
        must_contain=(
            "Advisory strict semantics (W1.b first cut)",
            "missing upstream artifact => status=skipped, exit 0, ::warning::",
            "::warning title=promotion-gate-daily::no recent completed rolling-bench run",
        ),
        rationale_url_or_id="W1.b first cut (header docstring)",
    ),
    _RationaleRequirement(
        workflow="promotion-gate-daily.yml",
        finding="A#2 — PromotionGate rc=2 advisory",
        must_contain=(
            "Exit-code policy (W1.b advisory)",
            "advisory in W1.b first cut",
        ),
        rationale_url_or_id="W1.b advisory rc-policy (gate step body)",
    ),
    _RationaleRequirement(
        workflow="c13-daily-cron.yml",
        finding="A#6 — backfill=0 warning instead of error",
        must_contain=(
            "Phase 1 (here): warning only",
            "Phase 2",
            "before this becomes hard-fail in phase 2",
        ),
        rationale_url_or_id="F-V3-15 Phase 1 (above-step + ::warning:: body)",
    ),
    _RationaleRequirement(
        workflow="f2-promotion-gate-daily.yml",
        finding="A#3 — dual-arm artefacts missing",
        must_contain=(
            "L-2 (audit 2026-04-24",
            "by-design",
            "tests/test_workflow_f2_skip_visibility.py",
            "see audit L-2",
        ),
        rationale_url_or_id="L-2 audit 2026-04-24",
    ),
)


def _read(workflow: str) -> str:
    path = _WF_DIR / workflow
    assert path.is_file(), f"workflow missing: {path}"
    return path.read_text(encoding="utf-8")


def test_workflows_dir_exists() -> None:
    assert _WF_DIR.is_dir()


def test_each_deliberate_fail_soft_has_rationale_intact() -> None:
    failures: list[str] = []
    for req in _REQUIREMENTS:
        text = _read(req.workflow)
        for phrase in req.must_contain:
            if phrase not in text:
                failures.append(
                    f"  {req.workflow} ({req.finding}): missing phrase "
                    f"{phrase!r}\n    rationale tag: {req.rationale_url_or_id}\n"
                    "    If the fail-soft is no longer wanted, FLIP to "
                    "::error:: + exit 1 (do NOT just delete the comment); "
                    "if you flipped it, drop this row from _REQUIREMENTS."
                )
    assert not failures, (
        "Deliberate fail-soft rationale drifted in one or more workflows:\n"
        + "\n".join(failures)
    )
