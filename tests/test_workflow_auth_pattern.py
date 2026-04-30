"""F-11 prevention: every workflow ``git push`` must be safe.

Background — audit findings F-02 and F-05 both shipped a bare
``git push`` to ``main`` inside ``run:`` blocks. The protected-branch
ruleset rejects those pushes with ``GH013`` and the workflow turns
permanently red. The fix in PRs #1931 / #1932 was to either:

* push to a branch under ``auto/*`` (``git push -u origin "HEAD:${BRANCH}"``)
* OR tolerate the rejection (``git push 2>&1 || echo "::warning::..."`` /
  ``if git push; then ... else ... fi``)

This regression test enforces that pattern repository-wide so a
new workflow that ships bare ``git push`` cannot land silently.
Would have caught F-02 (`fvg-context-pine-refresh.yml`) and F-05
(`fvg-quality-quartile-gate.yml`) at PR-time.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = ROOT / ".github" / "workflows"

# A ``git push`` call is considered SAFE if its line — or the line
# immediately above it (the ``if git push`` opener) — matches one of
# these patterns.
_SAFE_LINE_PATTERNS: tuple[re.Pattern[str], ...] = (
    # 1) Graceful fallback on the same line.
    re.compile(r"git\s+push\b[^\n]*\|\|"),
    # 2) Conditional opener: ``if git push ... ; then``.
    re.compile(r"\bif\s+git\s+push\b"),
    # 3) Explicit non-main target via shell var (BRANCH / TARGET_BRANCH /
    #    auto/* literal).
    re.compile(r"git\s+push\b[^\n]*(?:\$\{?BRANCH|\$\{?TARGET_BRANCH|auto/|HEAD:\$\{?BRANCH)"),
)

_PUSH_RE = re.compile(r"\bgit\s+push\b")


def _iter_workflow_files() -> list[Path]:
    return sorted(p for p in WORKFLOWS_DIR.glob("*.yml") if p.is_file())


def _iter_run_blocks(wf_path: Path) -> list[tuple[str, str]]:
    """Return ``(job_step_label, run_text)`` tuples for every ``run:`` step."""
    try:
        doc = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        pytest.fail(f"{wf_path.name}: invalid YAML: {exc}")
    if not isinstance(doc, dict):
        return []
    out: list[tuple[str, str]] = []
    jobs = doc.get("jobs") or {}
    if not isinstance(jobs, dict):
        return []
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps") or []
        if not isinstance(steps, list):
            continue
        for idx, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            run = step.get("run")
            if isinstance(run, str) and run.strip():
                step_name = step.get("name") or f"step[{idx}]"
                out.append((f"{job_name} :: {step_name}", run))
    return out


def _classify_push(run_text: str) -> list[tuple[int, str]]:
    """Return list of ``(line_number, line_text)`` for unsafe pushes."""
    lines = run_text.splitlines()
    unsafe: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        # Skip comments.
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        if not _PUSH_RE.search(line):
            continue
        prev_line = lines[i - 1] if i > 0 else ""
        # Window: this line + previous (catches multi-line ``if git push \\``
        # and the comment-above ``# F-02:`` style is irrelevant — we look
        # at executable context only).
        window = f"{prev_line}\n{line}"
        if any(p.search(window) for p in _SAFE_LINE_PATTERNS):
            continue
        unsafe.append((i + 1, line.rstrip()))
    return unsafe


@pytest.mark.parametrize(
    "wf_path",
    _iter_workflow_files(),
    ids=lambda p: p.name,
)
def test_workflow_git_push_is_safe(wf_path: Path) -> None:
    """Every ``git push`` in a workflow ``run:`` step must be wrapped.

    ``Safe`` means one of:
      * has ``||`` graceful fallback on the same line, or
      * is the head of an ``if git push ... ; then`` block, or
      * targets a non-main ref (``$BRANCH``, ``$TARGET_BRANCH``,
        ``HEAD:$BRANCH``, or a literal ``auto/...``).

    A bare ``git push`` to ``main`` will be rejected by the
    protected-branch ruleset (GH013) and the workflow turns red — see
    audit findings F-02 and F-05.
    """
    offenders: list[str] = []
    for label, run_text in _iter_run_blocks(wf_path):
        for line_no, line in _classify_push(run_text):
            offenders.append(f"  [{label}] line {line_no}: {line}")
    assert not offenders, (
        f"Unsafe ``git push`` in {wf_path.name}.\n"
        "Wrap with ``|| echo '::warning::...'`` or ``if git push; then ... fi``,\n"
        "or push to a non-main branch (``HEAD:${BRANCH}`` with BRANCH=auto/*).\n"
        "Audit findings F-02 / F-05 — see PRs #1931 and #1932 for the fix pattern.\n"
        "Offending lines:\n" + "\n".join(offenders)
    )


def test_inventory_contains_known_workflows() -> None:
    """Sanity guard: the parametrized test would silently skip if the
    glob ever returned an empty list. Pin a lower bound."""
    files = _iter_workflow_files()
    assert len(files) >= 10, f"workflow inventory shrank: {len(files)}"
