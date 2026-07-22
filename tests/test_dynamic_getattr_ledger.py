"""Defense ledger for dynamic ``getattr(obj, <non-literal>)`` call sites.

``getattr(obj, "literal_attr")`` is fine — the attribute name is part of
the source and visible to refactoring tools / static analysis. Calls
where the attribute name is a *runtime expression* (variable,
parameter, or computed string) are different:

* they defeat static analysis — Pyright/Pylance can no longer prove
  which attributes are touched, so renaming the underlying field is
  silently broken;
* they widen the attack surface for any caller that controls the name
  argument (CWE-470 — unsafe reflection);
* they hide coupling between modules: ``getattr(state, name)`` quietly
  reaches across whatever the producer of ``name`` chose to emit.

The repository currently has 12 such call sites, all in well-understood
state-layer accessors and scoring helpers. Locking them with a ledger
gives drift detection (line shifts surface here) and a growth gate
(new dynamic-attr lookups must extend the ledger explicitly with a
justification — same pattern as
``test_warnings_simplefilter_ledger.py`` and
``test_os_unlink_remove_ledger.py``).

The ledger also pins each site's *name provenance*, because that is what the
CWE-470 bullet above actually turns on — a ``(path, line)`` pin cannot tell
``getattr(signal, field)`` looping a module constant from
``getattr(signal, payload["attr"])`` on the same line. One site is
``const-loop`` (its name set is statically visible); the other 11 are ``param``,
which is pinned honestly as *"still just a parameter"* — it is not a claim that
the caller is safe.

(The count said 10 until 2026-07-15; there were 12.)
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests._guard_corpus import parse_module

ROOT = Path(__file__).resolve().parents[1]

_DIR_EXCLUDE = {
    ".git",
    ".github",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "node_modules",
    "artifacts",
    "docs",
    "tests",
    "SMC++",
    "scripts",
}


def _iter_py_files() -> list[Path]:
    out: list[Path] = []
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT)
        if any(part in _DIR_EXCLUDE or part.startswith(".") for part in rel.parts):
            continue
        out.append(path)
    return out


def _module_constants(tree: ast.Module) -> set[str]:
    """ALL-CAPS names bound at module level — the statically visible name sets."""
    out: set[str] = set()
    for node in tree.body:
        targets = (
            node.targets
            if isinstance(node, ast.Assign)
            else [node.target]
            if isinstance(node, ast.AnnAssign)
            else []
        )
        for target in targets:
            if isinstance(target, ast.Name) and target.id.isupper():
                out.add(target.id)
    return out


def _name_provenance(
    call: ast.Call, enclosing: ast.AST | None, consts: set[str]
) -> str:
    """Where the attribute name comes from — the thing CWE-470 turns on.

    * ``const-loop`` — bound by ``for x in MODULE_CONST``: the valid name set is
      statically visible at the call site, which is the strongest shape here.
    * ``param`` — a parameter of the enclosing function: provenance is the
      caller's, so this pins *that it is still just a parameter*, not that the
      caller is safe. Named honestly rather than implied to be safe.
    * ``expression`` — an inline expression (``getattr(o, payload["k"])``): the
      unsafe-reflection shape the docstring names, and the one shape that could
      previously appear at a ledgered line with the pin staying green.
    """

    name_arg = call.args[1]
    if not isinstance(name_arg, ast.Name):
        return "expression"
    if enclosing is None:
        return "module-scope"
    args = enclosing.args  # type: ignore[union-attr]  # only function nodes reach here
    params = {a.arg for a in [*args.posonlyargs, *args.args, *args.kwonlyargs]}
    if args.vararg:
        params.add(args.vararg.arg)
    if args.kwarg:
        params.add(args.kwarg.arg)
    if name_arg.id in params:
        return "param"
    for node in ast.walk(enclosing):
        if (
            isinstance(node, ast.For)
            and isinstance(node.target, ast.Name)
            and node.target.id == name_arg.id
        ):
            if isinstance(node.iter, ast.Name) and node.iter.id in consts:
                return "const-loop"
            return "loop"
    return "local"


def _dynamic_getattr_sites() -> set[tuple[str, int, str]]:
    """Return ``{(relpath, lineno, provenance)}`` for every ``getattr(obj, <expr>)``
    call where the second argument is *not* a string literal.

    A literal name (``getattr(obj, "field")``) is treated as safe and
    does not enter the ledger — it is statically analysable and equals
    plain attribute access.

    ``provenance`` is what this ledger's own comments assert per site — e.g.
    "the valid name set is statically visible there" for the ``_FEATURE_FIELDS``
    loop. A ``(path, lineno)`` pin cannot tell that from
    ``getattr(signal, payload["attr"])`` on the same line, so the claim was
    decoration. See :func:`_name_provenance` for what each value means.
    """

    sites: set[tuple[str, int, str]] = set()
    for path in _iter_py_files():
        tree = parse_module(path)
        if tree is None:
            continue
        consts = _module_constants(tree)
        enclosing_of: dict[ast.AST, ast.AST] = {}
        for func_node in ast.walk(tree):
            if isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for child in ast.walk(func_node):
                    enclosing_of[child] = func_node
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Name) or func.id != "getattr":
                continue
            if len(node.args) < 2:
                continue
            name_arg = node.args[1]
            if isinstance(name_arg, ast.Constant) and isinstance(name_arg.value, str):
                continue
            # POSIX form keeps the ledger stable across OSes (#2244).
            sites.add(
                (
                    path.relative_to(ROOT).as_posix(),
                    node.lineno,
                    _name_provenance(node, enclosing_of.get(node), consts),
                )
            )
    return sites


# Locked ledger of every production dynamic-name ``getattr(...)`` site.
# The third element is the name's provenance; it used to sit in these
# comments, where nothing read it (2026-07-15).
# Adding a new caller? Append the (path, line, provenance) tuple in the same PR
# with a justification in the commit message; better yet, prefer a
# small ``Mapping[str, Callable]`` / TypedDict accessor so the set of
# valid names is statically visible.
DYNAMIC_GETATTR_LEDGER: set[tuple[str, int, str]] = {
    # 2026-07-08 signal-event log: event_row() serialises a signal by iterating the
    # module-level constant _FEATURE_FIELDS tuple — the valid name set is statically
    # visible there, and it must accept both dataclass and SimpleNamespace signals.
    ("open_prep/signal_events.py", 66, "const-loop"),  # 2026-07-10 truth-audit docstring: 63->66
    # 2026-06-22 (ingest-stop sentinel wakeup): helper block growth shifted
    # _record_to_bar dynamic getattr site 81 -> 82.
    # 2026-07-03 correctness lane: _feed_connected_at global shifted
    # _record_to_bar dynamic getattr site 101 -> 102.
    ("services/live_overlay_daemon/feed.py", 109, "param"),  # 2026-07-22 (F-2): 104->108; (F-3 VIX retry const): 108->109
    ("smc_core/event_ledger.py", 100, "param"),  # 2026-07-13 schema-v1.1: label relocation + record docstring/field shifted (84->94); schema-v1.2 rename+calibrated_prob (94->100)
    ("smc_core/scoring.py", 339, "param"),  # 2026-07-13 (normalize_sweep_side + calibration-honesty docstrings): 308->339
    ("streamlit_terminal_alerts.py", 41, "param"),
    ("terminal_attention_state.py", 45, "param"),
    ("terminal_catalyst_state.py", 31, "param"),
    ("terminal_live_story_state.py", 41, "param"),  # 2026-07-11 (truth-audit): -1 (removed DEFAULT_LIVE_STORY_COOLDOWN_S)
    ("terminal_poller.py", 1175, "param"),  # 2026-07-20 source-priority config shifted site: 1169->1175
    ("terminal_posture_state.py", 53, "param"),
    ("terminal_reaction_state.py", 49, "param"),
    ("terminal_resolution_state.py", 43, "param"),
}


def test_dynamic_getattr_ledger_exact() -> None:
    sites = _dynamic_getattr_sites()

    unexpected = sites - DYNAMIC_GETATTR_LEDGER
    assert not unexpected, (
        "New / drifted dynamic-name getattr(obj, <expr>) call site "
        "detected. Dynamic reflection defeats static analysis (CWE-470). "
        "Prefer a small ``Mapping[str, Callable]`` / TypedDict accessor "
        "so the set of valid names is statically visible. If the dynamic "
        "lookup is genuinely required, append the (path, line) tuple to "
        "DYNAMIC_GETATTR_LEDGER with a justification in the commit message.\n"
        f"unexpected = {sorted(unexpected)}"
    )

    missing = DYNAMIC_GETATTR_LEDGER - sites
    assert not missing, (
        "DYNAMIC_GETATTR_LEDGER entries no longer present in code. If a "
        "lookup was deliberately removed or refactored to literal "
        "attribute access, drop the matching tuple from the ledger.\n"
        f"missing = {sorted(missing)}"
    )
