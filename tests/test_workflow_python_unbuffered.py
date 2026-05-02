"""Pin: every workflow that invokes Python must set ``PYTHONUNBUFFERED=1``.

Audit follow-up to **F-V6-A2.1 (2026-05-02)**: previously only
``run-open-prep-daily.yml`` set ``PYTHONUNBUFFERED``. Long-running scripts
(databento exports, feature-importance, drift-watchdog) buffered their
``logger.info`` progress output until process exit, so when the GHA runner
was evicted mid-job the entire log tail was lost — the workflow log just
stopped silently with no indication of where the script had been.

This pin enforces, at a YAML level, that every workflow file that invokes
``python`` (or ``python3``) declares ``env.PYTHONUNBUFFERED = "1"`` at the
top-level. Job-level ``env:`` is **not** sufficient — it would leave the
``setup-python`` and ``pip install`` steps still buffered, which is exactly
where pip-resolution hangs are most invisible.

Workflows that do not invoke Python at all (pure shell, deploy-only, etc.)
are skipped automatically.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOW_DIR = _REPO_ROOT / ".github" / "workflows"

# Match `python ` or `python3 ` (anywhere — usually inside a `run:` block).
# We deliberately do NOT match the bare word `python` (no space) to avoid
# false positives on filenames like `python-version`.
_PYTHON_INVOKE_RE = re.compile(r"\bpython3?\s")


def _iter_workflow_files() -> list[Path]:
    return sorted(
        list(_WORKFLOW_DIR.glob("*.yml")) + list(_WORKFLOW_DIR.glob("*.yaml"))
    )


def _invokes_python(text: str) -> bool:
    return bool(_PYTHON_INVOKE_RE.search(text))


def test_python_workflows_set_pythonunbuffered() -> None:
    violations: list[str] = []
    for path in _iter_workflow_files():
        text = path.read_text(encoding="utf-8")
        if not _invokes_python(text):
            continue
        try:
            doc = yaml.safe_load(text)
        except yaml.YAMLError as exc:  # pragma: no cover - syntax bug surfaces elsewhere
            violations.append(f"{path.name}: YAML parse error: {exc}")
            continue
        env = (doc or {}).get("env") or {}
        value = env.get("PYTHONUNBUFFERED")
        if value not in ("1", 1, "true", True):
            violations.append(
                f"{path.name}: top-level env.PYTHONUNBUFFERED missing or not '1' "
                f"(got {value!r})"
            )
    assert not violations, (
        "Every workflow that invokes Python MUST set top-level "
        "`env.PYTHONUNBUFFERED: \"1\"` (F-V6-A2.1, 2026-05-02). "
        "Job-level env is not enough \u2014 it leaves setup-python / pip "
        "install steps buffered.\nViolations:\n  " + "\n  ".join(violations)
    )


def test_pin_actually_scans_python_workflows() -> None:
    """Sanity: this pin must actually be exercising at least 10 workflows.

    If we ever rename or move workflows, the pin should not silently pass
    by simply not seeing any python-invoking workflow files.
    """
    n = sum(
        1 for p in _iter_workflow_files()
        if _invokes_python(p.read_text(encoding="utf-8"))
    )
    assert n >= 10, (
        f"Pin only saw {n} python-invoking workflows under {_WORKFLOW_DIR} "
        "\u2014 expected \u226510. Did the workflow set move?"
    )
