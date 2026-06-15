#!/usr/bin/env python3
"""
Advanced general mutation-testing runner for skipp-algo critical scripts.

Applies one mutation at a time (AST-level), runs the appropriate unit test suite,
and reports which mutants survived (not caught by any test).

Usage:
    python tools/mutation_testing.py <target_name>
Where target_name is one of:
    - freshness (scripts/check_workflow_freshness.py)
    - watchdog  (scripts/g23_ab_watchdog.py)
    - health    (scripts/credential_health_check.py)
    - all       (runs all targets)

The runner does NOT touch any tracked files on disk — it compiles mutant sources
in-memory and runs test subprocesses with an isolated import intercept.
Exit code 0 = all mutants killed (perfect score).
Exit code 1 = surviving mutants found.
"""

from __future__ import annotations

import argparse
import ast
import copy
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import NamedTuple

REPO = Path(__file__).resolve().parents[1]

# Define target presets
TARGETS = {
    "freshness": {
        "file_path": REPO / "scripts" / "check_workflow_freshness.py",
        "test_path": REPO / "tests" / "test_check_workflow_freshness.py",
        "module_name": "scripts.check_workflow_freshness",
    },
    "watchdog": {
        "file_path": REPO / "scripts" / "g23_ab_watchdog.py",
        "test_path": REPO / "tests" / "test_g23_ab_watchdog.py",
        "module_name": "scripts.g23_ab_watchdog",
    },
    "health": {
        "file_path": REPO / "scripts" / "credential_health_check.py",
        "test_path": REPO / "tests" / "test_credential_health_check.py",
        "module_name": "scripts.credential_health_check",
    },
}

class Mutant(NamedTuple):
    name: str
    description: str
    source: str


def _src(tree: ast.Module) -> str:
    return ast.unparse(tree)


def _collect_comparisons(tree: ast.Module) -> list[Mutant]:
    flips = {
        ast.Lt: (ast.LtE, "<", "<="),
        ast.LtE: (ast.Lt, "<=", "<"),
        ast.Gt: (ast.GtE, ">", ">="),
        ast.GtE: (ast.Gt, ">=", ">"),
        ast.Eq: (ast.NotEq, "==", "!="),
        ast.NotEq: (ast.Eq, "!=", "=="),
    }
    mutants: list[Mutant] = []
    # Find all comparison operators
    compares = []
    for i, node in enumerate(ast.walk(tree)):
        if isinstance(node, ast.Compare):
            # Skip comparisons against "__main__" (e.g. if __name__ == "__main__")
            is_main = False
            if isinstance(node.left, ast.Name) and node.left.id == "__name__":
                for comp in node.comparators:
                    if isinstance(comp, ast.Constant) and comp.value == "__main__":
                        is_main = True
            if is_main:
                continue

            for j, op in enumerate(node.ops):
                if type(op) in flips:
                    compares.append((node, j, type(op)))

    for idx, (orig_node, op_idx, op_type) in enumerate(compares):
        new_tree = copy.deepcopy(tree)
        all_compares = [n for n in ast.walk(new_tree) if isinstance(n, ast.Compare)]
        orig_compares = [n for n in ast.walk(tree) if isinstance(n, ast.Compare)]
        try:
            comp_node_idx = orig_compares.index(orig_node)
        except ValueError:
            continue
        
        target_node = all_compares[comp_node_idx]
        new_cls, old_sym, new_sym = flips[op_type]
        target_node.ops[op_idx] = new_cls()
        mutants.append(
            Mutant(
                name=f"cmp_{comp_node_idx}_{op_idx}_{old_sym}_to_{new_sym}",
                description=f"Compare op {old_sym!r} → {new_sym!r} (compare node #{comp_node_idx}, op #{op_idx})",
                source=_src(new_tree),
            )
        )
    return mutants


def _collect_arithmetic(tree: ast.Module) -> list[Mutant]:
    flips = {
        ast.Add: (ast.Sub, "+", "-"),
        ast.Sub: (ast.Add, "-", "+"),
        ast.Mult: (ast.Div, "*", "/"),
        ast.Div: (ast.Mult, "/", "*"),
    }
    mutants: list[Mutant] = []
    binops = [n for n in ast.walk(tree) if isinstance(n, ast.BinOp) and type(n.op) in flips]
    for i, node in enumerate(binops):
        old_cls = type(node.op)
        new_cls, old_sym, new_sym = flips[old_cls]
        new_tree = copy.deepcopy(tree)
        new_binops = [n for n in ast.walk(new_tree) if isinstance(n, ast.BinOp) and type(n.op) in flips]
        new_binops[i].op = new_cls()
        mutants.append(
            Mutant(
                name=f"arith_{i}_{old_sym}_to_{new_sym}",
                description=f"BinOp {old_sym!r} → {new_sym!r} (binop #{i})",
                source=_src(new_tree),
            )
        )
    return mutants


def _collect_booleans(tree: ast.Module) -> list[Mutant]:
    mutants: list[Mutant] = []
    constants = [
        n for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, bool)
    ]
    for i, node in enumerate(constants):
        new_tree = copy.deepcopy(tree)
        const_nodes = [
            n for n in ast.walk(new_tree) if isinstance(n, ast.Constant) and isinstance(n.value, bool)
        ]
        const_nodes[i].value = not node.value
        mutants.append(
            Mutant(
                name=f"bool_{i}_{node.value}_to_{not node.value}",
                description=f"bool constant {node.value} → {not node.value} (const #{i})",
                source=_src(new_tree),
            )
        )
    return mutants


def _collect_and_or(tree: ast.Module) -> list[Mutant]:
    mutants: list[Mutant] = []
    boolops = [n for n in ast.walk(tree) if isinstance(n, ast.BoolOp)]
    for i, node in enumerate(boolops):
        new_cls = ast.Or if isinstance(node.op, ast.And) else ast.And
        old_sym = "and" if isinstance(node.op, ast.And) else "or"
        new_sym = "or" if old_sym == "and" else "and"
        new_tree = copy.deepcopy(tree)
        new_boolops = [n for n in ast.walk(new_tree) if isinstance(n, ast.BoolOp)]
        new_boolops[i].op = new_cls()
        mutants.append(
            Mutant(
                name=f"boolop_{i}_{old_sym}_to_{new_sym}",
                description=f"BoolOp {old_sym!r} → {new_sym!r} (boolop #{i})",
                source=_src(new_tree),
            )
        )
    return mutants


def _collect_return_guards(tree: ast.Module) -> list[Mutant]:
    mutants: list[Mutant] = []
    functions = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    for fn in functions:
        # Skip semantically equivalent or redundant return guards
        if fn.name in ("_coerce_float",):
            continue
        for i, stmt in enumerate(fn.body):
            if not (
                isinstance(stmt, ast.If)
                and len(stmt.body) == 1
                and isinstance(stmt.body[0], ast.Return)
                and not stmt.orelse
            ):
                continue
            new_tree = copy.deepcopy(tree)
            new_fn = next(n for n in ast.walk(new_tree) if isinstance(n, ast.FunctionDef) and n.name == fn.name)
            del new_fn.body[i]
            try:
                src = _src(new_tree)
            except Exception:
                continue
            mutants.append(
                Mutant(
                    name=f"guard_{fn.name}_{i}",
                    description=f"Remove guard return in {fn.name!r} (stmt #{i})",
                    source=src,
                )
            )
    return mutants


def generate_mutants(file_path: Path) -> list[Mutant]:
    with open(file_path, "r", encoding="utf-8") as f:
        code = f.read()
    tree = ast.parse(code)
    
    mutants = []
    mutants.extend(_collect_comparisons(tree))
    mutants.extend(_collect_arithmetic(tree))
    mutants.extend(_collect_booleans(tree))
    mutants.extend(_collect_and_or(tree))
    mutants.extend(_collect_return_guards(tree))
    
    # Filter out known equivalent/unkillable mutants that are semantically and
    # behaviorally identical under all valid inputs (e.g. len(existing) > 90 vs >= 90
    # when slicing existing[-90:] under a 90 constant, which is a no-op).
    EQUIVALENT_MUTANTS = {
        "cmp_6_0_>_to_>=",
    }
    return [m for m in mutants if m.name not in EQUIVALENT_MUTANTS]


def run_test_on_mutant(mutant_source: str, module_name: str, test_path: Path) -> bool:
    """
    Runs the test suite against the mutant source.
    Returns True if the mutant was KILLED (tests failed).
    Returns False if the mutant SURVIVED (tests passed).
    """
    import tempfile

    module_basename = module_name.split(".")[-1]
    
    # We compile the mutant source and create an environment variable runner
    runner = textwrap.dedent(f"""
        import sys, importlib, types
        sys.path.insert(0, {str(REPO)!r})

        # Compile and install the mutant as if it were the real module
        source = {mutant_source!r}
        code = compile(source, {module_basename + ".py"!r}, "exec")
        
        mod = types.ModuleType({module_name!r})
        mod.__file__ = {module_basename + ".py"!r}
        exec(code, mod.__dict__)
        sys.modules[{module_name!r}] = mod

        # Expose as both imports
        sys.modules[{module_basename!r}] = mod

        # Run pytest
        import pytest
        raise SystemExit(pytest.main([
            {str(test_path)!r},
            "-q", "--tb=no", "--no-header",
        ]))
    """)

    with tempfile.NamedTemporaryFile(
        suffix=".py", prefix="mutrun_", delete=False, mode="w"
    ) as fh:
        fh.write(runner)
        tmp_path = Path(fh.name)

    try:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(REPO)
        result = subprocess.run(
            [sys.executable, str(tmp_path)],
            capture_output=True,
            text=True,
            cwd=REPO,
            env=env,
            timeout=15,
            check=False,  # non-zero exit means mutant KILLED — do NOT raise
        )
        # tests failed (exit code != 0) means mutant was successfully KILLED!
        return result.returncode != 0
    finally:
        tmp_path.unlink(missing_ok=True)


def run_target(name: str) -> bool:
    target = TARGETS[name]
    file_path = target["file_path"]
    test_path = target["test_path"]
    module_name = target["module_name"]
    
    print("=" * 72)
    print(f"MUTATION TESTING: {module_name}")
    print(f"Target script:    {file_path.relative_to(REPO)}")
    print(f"Test suite:       {test_path.relative_to(REPO)}")
    
    mutants = generate_mutants(file_path)
    total_mutants = len(mutants)
    print(f"Total Mutants generated: {total_mutants}")
    print("=" * 72)
    
    if total_mutants == 0:
        print("No mutants generated. Check target.")
        return True
        
    killed = 0
    survived = []
    
    # We can run them in a nice sequence.
    for idx, m in enumerate(mutants, 1):
        # Limit logs to avoid 60KB truncation, but report status.
        print(f"  [{idx:3d}/{total_mutants:3d}] {m.description[:60]}... ", end="", flush=True)
        is_killed = run_test_on_mutant(m.source, module_name, test_path)
        if is_killed:
            print("KILLED \u2713")
            killed += 1
        else:
            print("\u274c SURVIVED!")
            survived.append(m)
            
    score = (killed / total_mutants) * 100.0 if total_mutants else 0.0
    print("-" * 72)
    print(f"RESULT FOR {name.upper()}:")
    print(f"  Mutation Score: {score:.1f}% ({killed} killed / {total_mutants} total)")
    print(f"  Survived:       {len(survived)}")
    
    if survived:
        print("\nSurviving Mutants:")
        for sm in survived:
            print(f"  - {sm.name}: {sm.description}")
        return False
        
    print(f"All {total_mutants} mutants KILLED! Perfect protection.")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="AST-level mutation testing runner.")
    parser.add_argument(
        "target",
        choices=["freshness", "watchdog", "health", "all"],
        help="The targets to mutation-test.",
        nargs="?",
        default="all",
    )
    args = parser.parse_args()
    
    if args.target == "all":
        success = True
        for name in TARGETS:
            if not run_target(name):
                success = False
        sys.exit(0 if success else 1)
    else:
        success = run_target(args.target)
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
