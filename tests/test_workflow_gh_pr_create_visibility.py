"""Pin: ``gh pr create`` / ``gh pr merge`` failures must not be silently swallowed.

Audit follow-up to **F-V6-I2.1 (2026-05-02)**: the daily ``open-prep`` and
``run-open-prep`` workflows previously suffixed their ``gh pr create`` and
``gh pr merge`` calls with ``|| true``. When the PR-creation API call failed
(auth issues, branch-protection refusal, transient GitHub API errors), the
workflow stayed green and the daily artifact was lost without any signal.

This pin is intentionally narrow: it does **not** ban ``|| true`` in general
(legitimate uses include diagnostic ``git diff`` and ``grep`` calls). It only
forbids ``|| true`` directly attached to ``gh pr create`` or ``gh pr merge``,
because both commands have a hard side-effect that we always want to observe
when it fails.

The accepted alternative pattern is::

    if ! gh pr create ...; then
      echo "::error::...gh pr create failed..."
      exit 1
    fi

For ``gh pr merge`` (auto-merge), a ``|| echo "::warning::..."`` fallback is
acceptable because the PR is already open and reviewable; the job's contract
is "PR exists", not "PR auto-merged".
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOW_DIR = _REPO_ROOT / ".github" / "workflows"

# Match ``gh pr create`` or ``gh pr merge`` followed (possibly across line
# continuations) by ``|| true``. We collapse line-continuations first so the
# regex is single-line.
_BANNED_RE = re.compile(r"gh\s+pr\s+(?:create|merge)\b[^\n]*?\|\|\s*true\b")


def _iter_workflow_files() -> list[Path]:
    return sorted(
        list(_WORKFLOW_DIR.glob("*.yml")) + list(_WORKFLOW_DIR.glob("*.yaml"))
    )


def _collapse_continuations(text: str) -> str:
    # Replace ``\\\n`` (shell line continuation) with a single space so a
    # multi-line ``gh pr create ... \\\n  --body ... || true`` is matched as
    # one logical line.
    return re.sub(r"\\\n\s*", " ", text)


def test_no_silent_gh_pr_create_or_merge() -> None:
    violations: list[str] = []
    for path in _iter_workflow_files():
        text = path.read_text(encoding="utf-8")
        collapsed = _collapse_continuations(text)
        for match in _BANNED_RE.finditer(collapsed):
            # Best-effort: report file (line numbers post-collapse are not
            # meaningful, so we cite the file and the offending snippet).
            snippet = match.group(0)[:120]
            violations.append(f"{path.name}: {snippet}")
    assert not violations, (
        "`gh pr create` and `gh pr merge` MUST NOT be suffixed with `|| true` "
        "(F-V6-I2.1, 2026-05-02). Failures here silently lose daily PRs.\n"
        "Replace with `if ! gh pr create ...; then echo '::error::...'; "
        "exit 1; fi`. For auto-merge, prefer `|| echo '::warning::...'`.\n"
        "Violations:\n  " + "\n  ".join(violations)
    )


def test_workflows_dir_has_files_to_scan() -> None:
    assert _iter_workflow_files(), (
        f"No workflow files found under {_WORKFLOW_DIR} \u2014 pin would "
        "silently pass."
    )
