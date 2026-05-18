#!/usr/bin/env python3
"""Fail-fast lint: every ``.github/workflows/*.yml`` must declare ``defaults.run.shell: bash``.

The repo runs on a Windows self-hosted runner (``SMC_GH_HOSTED_RUNNER``);
without this declaration every ``run:`` step defaults to PowerShell, which
cannot parse bash syntax (``[[ ]]``, ``set -o pipefail``, heredocs). On
``ubuntu-latest`` the block is a no-op, so the check is safe to enforce
globally.

Replaces the previous ``grep -q 'shell: bash'`` loop in
``.github/workflows/smc-fast-pr-gates.yml`` which false-passed when the
string appeared inside a comment, an unrelated step's ``shell:``, or a
``defaults.run.shell:`` mapping nested elsewhere.

Exit code 0 on success, 1 on at least one offending workflow. Emits one
``::error file=<path>::`` annotation per failure so GitHub surfaces them
inline.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"


def _shell_value(data: object) -> object:
    if not isinstance(data, dict):
        return None
    defaults = data.get("defaults")
    if not isinstance(defaults, dict):
        return None
    run = defaults.get("run")
    if not isinstance(run, dict):
        return None
    return run.get("shell")


def main() -> int:
    if not WORKFLOWS_DIR.is_dir():
        print(f"::error::workflows directory not found: {WORKFLOWS_DIR}", file=sys.stderr)
        return 1

    files = sorted(WORKFLOWS_DIR.glob("*.yml")) + sorted(WORKFLOWS_DIR.glob("*.yaml"))
    failures: list[str] = []
    for path in files:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            rel = path.relative_to(REPO_ROOT).as_posix()
            print(f"::error file={rel}::YAML parse error: {exc}")
            failures.append(rel)
            continue

        shell = _shell_value(data)
        rel = path.relative_to(REPO_ROOT).as_posix()
        if shell != "bash":
            if shell is None:
                msg = "missing 'defaults: run: shell: bash' block"
            else:
                msg = f"defaults.run.shell must be 'bash', found {shell!r}"
            print(f"::error file={rel}::{msg}")
            failures.append(rel)

    if failures:
        print(
            f"\nlint_workflow_defaults: {len(failures)} workflow(s) violate the rule.",
            file=sys.stderr,
        )
        return 1

    print(f"OK: {len(files)} workflow(s) declare defaults.run.shell: bash")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
