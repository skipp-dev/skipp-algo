"""Pin: every plan_2_8_*.py + generate_showcase_summary.py entry point bootstraps logging.

Audit follow-up to **F-V6-A1.1 (2026-05-02)**: extends the priority-20
entry-point logging pin from F-V5-A1-2 / PR #2012 to the full set of 402
``plan_2_8_*`` aggregator scripts plus ``generate_showcase_summary.py``.

These scripts are invoked from:

* ``.github/workflows/plan-2-8-status-daily.yml``
* ``.github/workflows/plan-2-8-weekly-digest.yml``
* ``.github/workflows/plan-2-8-monthly-digest.yml``
* ``.github/workflows/plan-2-8-q4-gate-dryrun.yml``

Without ``init_cli_logging()`` at the top of ``main()``, all
``logger.info(...)`` progress lines go nowhere (Python's root logger is
WARNING-only by default), making CI debugging blind. F-V5-A1-2 fixed
this for the priority 20; this pin closes the long tail of 402.

The pin enforces by AST that:

1. The file imports ``init_cli_logging`` from ``scripts._logging_init``.
2. The first non-docstring statement of ``main()`` is a call to
   ``init_cli_logging()``.

Discovery list is enumerated dynamically from the filesystem so adding a
new ``plan_2_8_*.py`` script picks up the contract automatically.
"""
from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = _REPO_ROOT / "scripts"


def _enumerate_targets() -> list[Path]:
    """Return all plan_2_8_*.py + generate_showcase_summary.py files with `def main`."""
    targets: list[Path] = []
    for path in sorted(_SCRIPTS_DIR.glob("plan_2_8_*.py")):
        if _has_main(path):
            targets.append(path)
    showcase = _SCRIPTS_DIR / "generate_showcase_summary.py"
    if showcase.exists() and _has_main(showcase):
        targets.append(showcase)
    return targets


def _has_main(path: Path) -> bool:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return False
    return any(
        isinstance(node, ast.FunctionDef) and node.name == "main"
        for node in ast.iter_child_nodes(tree)
    )


def _find_main(tree: ast.AST) -> ast.FunctionDef | None:
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            return node
    return None


def _first_non_docstring_call(fn: ast.FunctionDef) -> ast.Call | None:
    body = list(fn.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    if not body:
        return None
    first = body[0]
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Call):
        return first.value
    return None


def test_helper_module_exists() -> None:
    helper = _SCRIPTS_DIR / "_logging_init.py"
    assert helper.exists(), (
        f"Helper {helper} missing \u2014 either PR #2012 has not landed yet "
        "or this PR has dropped the cherry-picked helper file."
    )
    text = helper.read_text(encoding="utf-8")
    assert "def init_cli_logging" in text, (
        f"Helper {helper} does not define init_cli_logging."
    )


def test_plan28_and_showcase_entry_points_bootstrap_logging() -> None:
    targets = _enumerate_targets()
    assert len(targets) >= 350, (
        f"Pin only saw {len(targets)} plan_2_8/showcase entry points "
        "\u2014 expected \u2265350. Did the script set move?"
    )
    missing_import: list[str] = []
    bad_first_call: list[str] = []
    for path in targets:
        text = path.read_text(encoding="utf-8")
        if "from scripts._logging_init import init_cli_logging" not in text:
            missing_import.append(path.name)
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:  # pragma: no cover - syntax bug surfaces elsewhere
            bad_first_call.append(f"{path.name}: parse error: {exc}")
            continue
        main_fn = _find_main(tree)
        assert main_fn is not None, (
            f"{path.name}: lost its main() between enumeration and AST parse"
        )
        call = _first_non_docstring_call(main_fn)
        if call is None:
            bad_first_call.append(f"{path.name}: main() empty or first stmt not a call")
            continue
        if not (isinstance(call.func, ast.Name) and call.func.id == "init_cli_logging"):
            func_repr = ast.unparse(call.func) if hasattr(ast, "unparse") else "<func>"
            bad_first_call.append(
                f"{path.name}: first main() call is `{func_repr}`, expected `init_cli_logging`"
            )

    assert not missing_import, (
        f"{len(missing_import)} entry points are missing the "
        "`from scripts._logging_init import init_cli_logging` import "
        "(F-V6-A1.1, 2026-05-02). First 10:\n  " + "\n  ".join(missing_import[:10])
    )
    assert not bad_first_call, (
        f"{len(bad_first_call)} entry points do not call `init_cli_logging()` "
        "as the first statement of main() (F-V6-A1.1, 2026-05-02). First 10:\n  "
        + "\n  ".join(bad_first_call[:10])
    )
