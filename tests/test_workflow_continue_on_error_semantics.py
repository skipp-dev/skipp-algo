"""Pin: every ``continue-on-error: true`` step has advisory-grade naming.

Background
==========

PR #124 introduced a name-allowlist for ``continue-on-error: true``
steps in workflow files. This test extends the discipline with a
*semantic* check: the step's ``name:`` MUST contain at least one
keyword that signals an advisory / best-effort / notification
intent. This stops a future contributor from sneaking a critical
step under ``continue-on-error: true`` (which would silently swallow
real failures).

The acceptable keywords reflect the four legitimate
``continue-on-error: true`` use cases observed in this repo:

1. **Notify** — Telegram/Slack/email side-effect after the gate.
2. **Send** — push artifact/payload to external system.
3. **Publish** — TradingView post-release publish (advisory).
4. **Telegram** — explicit Telegram delivery (Plan M-2).
5. **Probe** — preflight readiness check.
6. **Summary** — end-of-run digest.
7. **Advisory** — explicitly labelled advisory step.
8. **Best-effort** / **Best.effort** — explicit best-effort label.
9. **Download** — fetch prior artifact (404 expected on first run).
10. **Commit** — push snapshot updates (race-tolerant).
11. **Run evidence gate** / **Run TradingView** / **Run deeper** /
    **Run E2E** — gates that are gated downstream by their own
    artifact presence (legacy advisory pattern; see
    /memories/repo/smc-refresh-workflow-status-reporting.md).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

_ADVISORY_KEYWORDS = (
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

_NAME_RE = re.compile(r"^\s*-\s*name:\s*(.+?)\s*$")
_COE_RE = re.compile(r"^\s*continue-on-error:\s*true\s*$", re.IGNORECASE)


def _iter_workflows() -> list[Path]:
    return sorted(WORKFLOWS_DIR.glob("*.yml"))


def _step_pairs(text: str) -> list[tuple[int, str | None]]:
    """Return list of ``(line_no, name)`` for every ``continue-on-error: true``.

    Walks the file forward; for each ``continue-on-error: true`` line,
    looks BACK to the most recent ``- name:`` line (skipping over
    ``with:`` / ``run:`` / etc. blocks). YAML is structurally indented
    so this regex sweep is robust against the formatting variations
    observed in this repo.
    """
    lines = text.splitlines()
    last_name: str | None = None
    last_name_line = -1
    out: list[tuple[int, str | None]] = []
    for idx, line in enumerate(lines):
        m = _NAME_RE.match(line)
        if m:
            last_name = m.group(1).strip().strip('"').strip("'")
            last_name_line = idx
            continue
        if _COE_RE.match(line):
            # Heuristic: a step block does not exceed ~40 lines; if the
            # last name is more than 40 lines back, we must have skipped
            # into another step (defensive — currently not observed).
            if last_name is None or (idx - last_name_line) > 40:
                out.append((idx + 1, None))
            else:
                out.append((idx + 1, last_name))
    return out


def test_continue_on_error_steps_have_advisory_naming() -> None:
    """Every CoE-true step must carry an advisory keyword in its name."""
    failures: list[str] = []
    for workflow in _iter_workflows():
        text = workflow.read_text(encoding="utf-8")
        pairs = _step_pairs(text)
        for line_no, name in pairs:
            if name is None:
                failures.append(
                    f"{workflow.name}:{line_no}: continue-on-error: true "
                    "without a discoverable preceding `- name:` step"
                )
                continue
            lower = name.lower()
            if not any(kw in lower for kw in _ADVISORY_KEYWORDS):
                failures.append(
                    f"{workflow.name}:{line_no}: step name {name!r} on a "
                    "continue-on-error: true line does not match any "
                    f"advisory keyword ({_ADVISORY_KEYWORDS}). Either "
                    "rename the step to express intent or remove the "
                    "continue-on-error flag — silent failure is not OK."
                )
    assert not failures, (
        "Workflow CoE-semantics violations:\n  " + "\n  ".join(failures)
    )


def test_at_least_one_continue_on_error_step_exists() -> None:
    """Belt-and-braces: ensure the heuristic actually finds CoE steps."""
    total = sum(len(_step_pairs(p.read_text(encoding="utf-8"))) for p in _iter_workflows())
    assert total > 0, (
        "No `continue-on-error: true` steps found in any workflow file. "
        "If the discipline was removed deliberately, delete this pin; "
        "otherwise the regex has drifted."
    )
