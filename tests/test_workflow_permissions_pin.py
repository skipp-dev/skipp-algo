"""Pin: every GitHub Actions workflow must declare explicit ``permissions``.

Rationale
---------
GitHub Actions defaults the ``GITHUB_TOKEN`` to *write* permissions on
``contents``, ``issues``, ``pull-requests``, ``checks`` and several other
scopes when the repository setting "Workflow permissions" is left at the
permissive default. A compromised dependency action can then push code,
delete branches, dismiss reviews, etc.

Defense: every workflow file must opt into least-privilege via a
``permissions:`` block — either at the **top level** of the workflow,
or on **every job** inside it.

This pin enforces that contract. Codebase status at 2026-04-25:
- 23 workflow files total
- 21 with top-level ``permissions:``
- 1 with job-level ``permissions:`` only (``smc-release-gates.yml``)
- 0 missing (``manifest-pytest-poison-scan.yml`` fixed in same PR)

OWASP A05 (Security Misconfiguration) + supply-chain hardening.
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOWS_DIR = _REPO_ROOT / ".github" / "workflows"


def _iter_workflows() -> list[Path]:
    if not _WORKFLOWS_DIR.is_dir():
        return []
    return sorted(p for p in _WORKFLOWS_DIR.iterdir() if p.suffix in {".yml", ".yaml"})


def _has_top_level_permissions(src: str) -> bool:
    """True if a top-level (column-0) ``permissions:`` key exists."""
    return bool(re.search(r"^permissions:\s*$|^permissions:\s+\S", src, re.MULTILINE))


def _job_blocks(src: str) -> list[str]:
    """Return the YAML body of every job under top-level ``jobs:``.

    Heuristic: a job header is a line starting with two spaces, followed
    by an identifier and ``:``. A job body extends until the next job
    header or end of file. Robust enough for this repo's workflow style
    (no PyYAML dependency in tests).
    """
    # Locate `jobs:` block (must be at column 0)
    m = re.search(r"^jobs:\s*$", src, re.MULTILINE)
    if not m:
        return []
    body = src[m.end():]
    # Job headers: exactly 2-space indented `id:` lines
    headers = list(re.finditer(r"^  (\w[\w\-]*):\s*$", body, re.MULTILINE))
    blocks: list[str] = []
    for i, h in enumerate(headers):
        start = h.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(body)
        blocks.append(body[start:end])
    return blocks


def _job_has_permissions(job_body: str) -> bool:
    """True if a job body contains a ``permissions:`` key (4-space indent)."""
    return bool(
        re.search(r"^    permissions:\s*$|^    permissions:\s+\S", job_body, re.MULTILINE)
    )


def _workflow_is_ok(path: Path) -> tuple[bool, str]:
    src = path.read_text(encoding="utf-8")
    if _has_top_level_permissions(src):
        return True, "top-level"
    jobs = _job_blocks(src)
    if not jobs:
        return False, "no jobs found / no permissions"
    missing = [i for i, j in enumerate(jobs) if not _job_has_permissions(j)]
    if missing:
        return False, f"jobs missing permissions: indices {missing}"
    return True, "every job has permissions"


def test_every_workflow_declares_permissions() -> None:
    """Each ``.github/workflows/*.{yml,yaml}`` must declare ``permissions:``.

    Either at the top level (preferred for least-privilege as a default)
    or on every job (acceptable for jobs needing different scopes).
    """
    workflows = _iter_workflows()
    assert workflows, "expected at least one workflow file under .github/workflows/"
    offenders: list[tuple[str, str]] = []
    for wf in workflows:
        ok, reason = _workflow_is_ok(wf)
        if not ok:
            offenders.append((wf.name, reason))
    assert offenders == [], (
        "Workflow(s) without explicit `permissions:` declaration — "
        "GITHUB_TOKEN defaults are too permissive. Add a top-level "
        "`permissions: { contents: read }` block (or per-job permissions). "
        f"Offenders: {offenders}"
    )
