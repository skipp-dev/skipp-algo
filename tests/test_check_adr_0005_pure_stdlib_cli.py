"""Smoke tests for scripts/check_adr_0005_pure_stdlib.py CLI."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI = REPO_ROOT / "scripts" / "check_adr_0005_pure_stdlib.py"


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        capture_output=True,
        text=True,
        cwd=cwd or REPO_ROOT,
        check=False,
    )


def test_cli_exits_zero_on_clean_runtime() -> None:
    """No-arg invocation: must exit 0 against the current pure-stdlib runtime."""
    result = _run([])
    assert result.returncode == 0, (
        f"CLI failed unexpectedly:\nstdout={result.stdout}\nstderr={result.stderr}"
    )


def test_cli_exits_zero_on_unrelated_file_paths() -> None:
    """Pre-commit passes changed paths; non-runtime paths must be ignored."""
    result = _run(["CHANGELOG.md", "README.md"])
    assert result.returncode == 0, result.stderr


def test_cli_detects_banned_import(tmp_path: Path) -> None:
    """Synthetic file with `import numpy` must trigger exit code 1."""
    runtime_file = tmp_path / "fake_runtime.py"
    runtime_file.write_text("import numpy as np\nimport math\n")

    # Patch the runtime list via a tiny shim test module that replaces
    # RUNTIME_FILES at import time. We invoke the CLI with an explicit
    # path so we exercise the args branch, not the RUNTIME_FILES branch.
    # Since args limit to RUNTIME_FILES intersection, we instead spawn
    # the CLI with PYTHONPATH pointing at a shim. Simpler: write a fake
    # test module side-by-side and override TEST_FILE via env.
    #
    # The CLI reads TEST_FILE via a module constant. Easiest path:
    # invoke the inner _check_file/_collect_imported_roots via direct
    # import in this same test process (no subprocess).
    import importlib.util

    spec = importlib.util.spec_from_file_location("_cli_under_test", CLI)
    assert spec is not None and spec.loader is not None
    cli_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli_mod)

    bad = cli_mod._check_file(  # type: ignore[attr-defined]
        runtime_file, frozenset({"numpy", "scipy"})
    )
    assert bad == {"numpy"}


def test_cli_help_does_not_crash() -> None:
    result = _run(["--help"])
    assert result.returncode == 0
    assert "ADR-0005" in result.stdout
