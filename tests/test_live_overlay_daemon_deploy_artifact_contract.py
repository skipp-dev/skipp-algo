"""The daemon's dependencies must be pinned in the file production installs.

Measured on the live container 2026-08-05: Railway does NOT build the daemon
from ``services/live_overlay_daemon/Dockerfile``. ``/app`` carries the whole
repository tree (root-level modules like ``databento_usage.py`` are present)
and ``pip show fastapi`` reports **0.136.1** — the ROOT ``requirements.txt``
pin — while the service file pins 0.141.1. So the service requirements file
is not what runs.

That turned a "safe optional-dependency fallback" into a live defect:
``holidays`` was pinned only in the service file, so the container lacked it,
``market_hours._holidays`` fell back to ``None``, and
``is_us_regular_session_open()`` reported **True on every US market holiday**
(measured in production: Labor Day, Thanksgiving, Christmas). That flag gates
the self-heal supervisor's stall detection, so a holiday looks like a silent
feed stall.

These tests pin the class, not the instance: every third-party module-level
import of the daemon package must be pinned in the root requirements. Guarded
imports (``try: import x / except: x = None``) are included deliberately —
those degrade SILENTLY, which is exactly how the holiday bug survived.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from tests._guard_corpus import iter_production_py_files

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PKG = _REPO_ROOT / "services" / "live_overlay_daemon"
_ROOT_REQUIREMENTS = _REPO_ROOT / "requirements.txt"

# Exemptions, each with the reason it cannot be a root-requirements pin.
_LOCAL_MODULES = frozenset(
    {
        "databento_usage",  # repo-root module (databento_usage.py)
        "scripts",  # repo-root package
        "composio_ops",  # repo-root package, absent by design (optional ChatOps)
    }
)
# Transitive, and verified present in production: fastapi 0.136.1 installs
# pydantic, and the hold-manager receiver route it types is live (the
# governance contract records receiver.accepting = true).
_TRANSITIVE_WITH_EVIDENCE = frozenset({"pydantic"})


class _ModuleLevelImports(ast.NodeVisitor):
    """Collect top-level import names, INCLUDING ones inside ``try:`` blocks.

    Function/class bodies are skipped: a lazy import inside a function cannot
    break process start-up, which is the failure mode this guard is about.
    """

    def __init__(self, names: set[str]) -> None:
        self.names = names

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.names.add(alias.name.split(".")[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level == 0 and node.module:
            self.names.add(node.module.split(".")[0])


def _daemon_third_party_imports() -> set[str]:
    names: set[str] = set()
    for path in iter_production_py_files(frozenset(), root=_PKG, minimum=12):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        _ModuleLevelImports(names).visit(tree)
    return {n for n in names if n not in sys.stdlib_module_names}


def _root_pinned_distributions() -> set[str]:
    pinned: set[str] = set()
    for line in _ROOT_REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        entry = line.split("#", 1)[0].strip()
        if not entry or entry.startswith("-"):
            continue
        for separator in ("==", ">=", "<=", "~=", ">", "<", "["):
            if separator in entry:
                entry = entry.split(separator, 1)[0]
                break
        pinned.add(entry.strip().lower().replace("-", "_"))
    return pinned


def test_every_daemon_import_is_pinned_in_the_file_production_installs() -> None:
    imports = _daemon_third_party_imports()
    exempt = _LOCAL_MODULES | _TRANSITIVE_WITH_EVIDENCE
    pinned = _root_pinned_distributions()
    missing = sorted(n for n in imports if n not in exempt and n.lower() not in pinned)
    assert missing == [], (
        "the daemon imports these at module level but the ROOT requirements.txt "
        f"— the file production actually installs — does not pin them: {missing}. "
        "A guarded import degrades silently (holidays -> every US market holiday "
        "read as an open session, measured in production 2026-08-05); an "
        "unguarded one crashes the process on start."
    )


def test_holidays_stays_pinned_because_its_fallback_is_silent() -> None:
    """Named regression pin for the measured production defect."""
    assert "holidays" in _root_pinned_distributions(), (
        "market_hours falls back to an EMPTY holiday set when the module is "
        "missing, so every US market holiday reads as a regular session and "
        "the supervisor's stall detection arms on a day with no bars."
    )


def test_the_declared_image_copies_every_root_module_the_daemon_imports() -> None:
    """The Dockerfile is not what production builds, but it must still be able
    to start — otherwise the fast-gates ``docker build`` step, the requirements
    dry-run and the railway.toml contract test all guard an image that cannot
    run, and nothing tells anyone."""
    dockerfile = (_PKG / "Dockerfile").read_text(encoding="utf-8")
    copied = [
        line.split()[1]
        for line in dockerfile.splitlines()
        if line.startswith("COPY ") and len(line.split()) >= 3
    ]
    for module in sorted(_LOCAL_MODULES):
        if module == "composio_ops":
            continue  # absent from the repo by design; import is guarded
        if not (_REPO_ROOT / f"{module}.py").exists():
            continue  # package directories are imported lazily, not at module level
        assert any(part.startswith(module) for part in copied), (
            f"{module}.py is imported at module level by the daemon but the "
            "Dockerfile never copies it — the declared image raises "
            "ModuleNotFoundError on start, which `docker build` cannot see."
        )
