#!/usr/bin/env python3
"""Pine Script input surface-area tool.

Capabilities:
  audit   — Inventory inputs across Pine files (counts, groups, display.none).
  regroup — Apply group assignments and display = display.none to inputs.
  lint    — Check for ungrouped inputs, parity between indicator/strategy pairs.

Usage:
    python pine_input_surface.py audit SkippALGO.pine SMC++.pine ...
    python pine_input_surface.py regroup --map MAP_FILE PINE_FILE
    python pine_input_surface.py lint SkippALGO.pine SkippALGO_Strategy.pine
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ── regex patterns ────────────────────────────────────────────────────
# Matches a single-line input declaration:
#   varName = input.type(...)   or   var type varName = input.type(...)
_INPUT_RE = re.compile(
    r"""
    ^(?P<prefix>                       # everything before 'input.'
       (?:var\s+)?                     # optional var/type prefix
       (?:(?:bool|int|float|string|color|ct\.\w+)\s+)?
       (?P<varname>\w+)\s*=\s*
    )
    input(?:\.(?P<kind>\w+))?\(        # input.bool( / input(
    (?P<args>.*)                       # the argument string
    $
    """,
    re.VERBOSE,
)

_GROUP_RE = re.compile(r"""\bgroup\s*=\s*(?P<val>[^\s,)]+|'[^']*'|"[^"]*")""")
_DISPLAY_RE = re.compile(r"""\bdisplay\s*=\s*(?P<val>[^\s,)]+)""")


@dataclass
class InputInfo:
    lineno: int
    varname: str
    kind: str  # bool, int, float, string, ...
    label: str  # the human-readable title
    group: str | None
    has_display_none: bool
    raw: str  # full source line


def _extract_label(args_str: str) -> str:
    """Best-effort extraction of the title string from input args."""
    # title is typically the first or second positional string argument
    m = re.search(r"""(?:,\s*)?['"]([^'"]{2,})['"]""", args_str)
    return m.group(1) if m else ""


def _extract_group(args_str: str) -> str | None:
    m = _GROUP_RE.search(args_str)
    if not m:
        return None
    val = m.group("val").strip("'\"")
    return val


def _has_display_none(args_str: str) -> bool:
    m = _DISPLAY_RE.search(args_str)
    return bool(m and "none" in m.group("val").lower())


def parse_inputs(lines: list[str]) -> list[InputInfo]:
    """Parse all input declarations from Pine source lines."""
    results: list[InputInfo] = []
    for i, line in enumerate(lines, 1):
        stripped = line.rstrip()
        # skip comments
        if stripped.lstrip().startswith("//"):
            continue
        m = _INPUT_RE.match(stripped)
        if not m:
            # also catch bare `input(` without method
            if re.match(r"^\w+\s*=\s*input\(", stripped):
                varname = stripped.split("=")[0].strip().split()[-1]
                args = stripped.split("input(", 1)[1]
                results.append(InputInfo(
                    lineno=i,
                    varname=varname,
                    kind="any",
                    label=_extract_label(args),
                    group=_extract_group(args),
                    has_display_none=_has_display_none(args),
                    raw=stripped,
                ))
            # also catch `var string x = input.string(...)` and `var anchor = input.string(...)`
            m2 = re.match(r"^var\s+(?:\w+\s+)?(\w+)\s*=\s*input(?:\.(\w+))?\((.*)$", stripped)
            if m2:
                results.append(InputInfo(
                    lineno=i,
                    varname=m2.group(1),
                    kind=m2.group(2) or "any",
                    label=_extract_label(m2.group(3)),
                    group=_extract_group(m2.group(3)),
                    has_display_none=_has_display_none(m2.group(3)),
                    raw=stripped,
                ))
            continue
        args = m.group("args")
        results.append(InputInfo(
            lineno=i,
            varname=m.group("varname"),
            kind=m.group("kind") or "any",
            label=_extract_label(args),
            group=_extract_group(args),
            has_display_none=_has_display_none(args),
            raw=stripped,
        ))
    return results


# ── audit command ─────────────────────────────────────────────────────
def cmd_audit(files: list[Path]) -> None:
    print(f"{'File':<45} {'Inputs':>6} {'Grouped':>7} {'None':>5} {'Groups':>6}")
    print("-" * 75)
    for fp in files:
        lines = fp.read_text().splitlines()
        inputs = parse_inputs(lines)
        groups = {inp.group for inp in inputs if inp.group}
        grouped = sum(1 for inp in inputs if inp.group)
        dnone = sum(1 for inp in inputs if inp.has_display_none)
        print(f"{fp.name:<45} {len(inputs):>6} {grouped:>7} {dnone:>5} {len(groups):>6}")
    print()


# ── regroup command ───────────────────────────────────────────────────
def load_map(map_path: Path) -> dict:
    """Load a JSON classification map.

    Format:
    {
      "groups_order": ["Core", "Risk Management", ...],
      "assignments": {
        "config":   {"group": "Core"},
        "engine":   {"group": "Core"},
        "stopATR":  {"group": "Risk Management", "display_none": true},
        ...
      },
      "defaults": {
        "display_none": false
      }
    }
    """
    return json.loads(map_path.read_text())


def _inject_group(line: str, group_varname: str) -> str:
    """Add group = g_xxx to a line that has no group assignment."""
    if _GROUP_RE.search(line):
        return line  # already has group
    # Insert before the closing paren
    # Find the last closing paren
    idx = line.rfind(")")
    if idx == -1:
        return line
    return line[:idx] + f", group = {group_varname}" + line[idx:]


def _inject_display_none(line: str) -> str:
    """Add display = display.none if not already present."""
    if _DISPLAY_RE.search(line):
        return line  # already has display
    idx = line.rfind(")")
    if idx == -1:
        return line
    return line[:idx] + ", display = display.none" + line[idx:]


def cmd_regroup(pine_path: Path, map_path: Path, dry_run: bool = False) -> None:
    cmap = load_map(map_path)
    assignments = cmap.get("assignments", {})
    groups_order = cmap.get("groups_order", [])
    group_var_prefix = cmap.get("group_var_prefix", "g_")

    lines = pine_path.read_text().splitlines(keepends=True)
    inputs = parse_inputs([l.rstrip("\n") for l in lines])

    # Build group variable name map: "Core" -> "g_core"
    gvar_map: dict[str, str] = {}
    for g in groups_order:
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", g).strip("_").lower()
        gvar_map[g] = f"{group_var_prefix}{slug}"

    changes = 0
    modified_lines = list(lines)

    for inp in inputs:
        assignment = assignments.get(inp.varname)
        if not assignment:
            continue

        line_idx = inp.lineno - 1
        original = modified_lines[line_idx]

        new_group = assignment.get("group")
        add_dnone = assignment.get("display_none", False)

        modified = original
        if new_group and not inp.group:
            gvar = gvar_map.get(new_group, f'"{new_group}"')
            modified = _inject_group(modified.rstrip("\n"), gvar) + "\n"
        if add_dnone and not inp.has_display_none:
            modified = _inject_display_none(modified.rstrip("\n")) + "\n"

        if modified != original:
            if dry_run:
                print(f"  L{inp.lineno}: {inp.varname} -> group={new_group or inp.group}, dnone={add_dnone}")
            modified_lines[line_idx] = modified
            changes += 1

    # Insert group variable declarations if needed
    if groups_order and changes > 0:
        # Find insertion point: after last existing group var, or after first input
        insert_lines = []
        for g in groups_order:
            gvar = gvar_map[g]
            decl = f'var string {gvar} = "{g}"\n'
            # Check if already declared
            if not any(gvar in l for l in modified_lines):
                insert_lines.append(decl)

        if insert_lines:
            # Find the line just before the first ungrouped input
            first_input_line = min(inp.lineno for inp in inputs) - 1
            # Insert after any existing group var declarations near the top
            insert_at = first_input_line
            for i in range(first_input_line, min(first_input_line + 5, len(modified_lines))):
                if modified_lines[i].strip().startswith("var string g_") or modified_lines[i].strip().startswith("grp_"):
                    insert_at = i + 1

            # Only insert group vars that are actually used
            used_gvars = set()
            for inp in inputs:
                a = assignments.get(inp.varname)
                if a and a.get("group"):
                    used_gvars.add(gvar_map.get(a["group"]))

            insert_lines = [l for l in insert_lines if l.split("=")[0].strip().split()[-1] in used_gvars]
            if insert_lines:
                insert_lines.insert(0, "\n// ── Input Groups ─────────────────────────────────────────\n")
                insert_lines.append("\n")
                for il in reversed(insert_lines):
                    modified_lines.insert(insert_at, il)

    if dry_run:
        print(f"\n  {changes} inputs would be modified")
    else:
        pine_path.write_text("".join(modified_lines))
        print(f"  {changes} inputs modified in {pine_path.name}")


# ── lint command ──────────────────────────────────────────────────────
def cmd_lint(files: list[Path]) -> int:
    """Check Pine files for input hygiene issues."""
    errors = 0

    for fp in files:
        lines = fp.read_text().splitlines()
        inputs = parse_inputs(lines)
        file_errors: list[str] = []

        # 1. Check for ungrouped inputs
        ungrouped = [inp for inp in inputs if not inp.group]
        if ungrouped:
            file_errors.append(
                f"{len(ungrouped)} ungrouped input(s): "
                + ", ".join(f"{inp.varname}@L{inp.lineno}" for inp in ungrouped[:5])
                + ("..." if len(ungrouped) > 5 else "")
            )

        # 2. Check for inputs with default < minval
        for inp in inputs:
            m = re.search(r"input\.(?:int|float)\(([^,]+),", inp.raw)
            if m:
                try:
                    defval = float(m.group(1).strip())
                except ValueError:
                    continue
                m2 = re.search(r"minval\s*=\s*([0-9.eE+-]+)", inp.raw)
                if m2:
                    try:
                        minval = float(m2.group(1))
                        if defval < minval:
                            file_errors.append(
                                f"L{inp.lineno}: {inp.varname} default {defval} < minval {minval}"
                            )
                    except ValueError:
                        pass

        # 3. Balanced parens/brackets (input declarations only — skip full-file check
        #    because Pine `=>` closures can create false-positive unmatched parens)
        for inp in inputs:
            depth_p = 0
            depth_b = 0
            for c in inp.raw:
                if c == "(":
                    depth_p += 1
                elif c == ")":
                    depth_p -= 1
                elif c == "[":
                    depth_b += 1
                elif c == "]":
                    depth_b -= 1
            if depth_p != 0:
                file_errors.append(f"L{inp.lineno}: unbalanced parens in input {inp.varname}")
            if depth_b != 0:
                file_errors.append(f"L{inp.lineno}: unbalanced brackets in input {inp.varname}")

        # 4. Version tag
        if not re.search(r"//@version=[56]", "\n".join(lines)):
            file_errors.append("Missing //@version=5 or //@version=6")

        if file_errors:
            print(f"❌ {fp.name}: {len(file_errors)} issue(s)")
            for e in file_errors:
                print(f"   • {e}")
            errors += len(file_errors)
        else:
            print(f"✅ {fp.name}: all checks passed")

    return errors


def cmd_lint_parity(files: list[Path]) -> int:
    """Check input parity between indicator/strategy pairs."""
    if len(files) < 2:
        print("Need at least 2 files for parity check")
        return 1

    all_inputs: dict[str, list[InputInfo]] = {}
    for fp in files:
        lines = fp.read_text().splitlines()
        all_inputs[fp.name] = parse_inputs(lines)

    errors = 0
    names = list(all_inputs.keys())
    ref_name = names[0]
    ref_vars = {inp.varname for inp in all_inputs[ref_name]}

    for other_name in names[1:]:
        other_vars = {inp.varname for inp in all_inputs[other_name]}
        only_ref = ref_vars - other_vars
        only_other = other_vars - ref_vars

        # Filter out strategy-specific vars (strategy.entry etc.)
        strategy_specific = {"allowLong", "allowShort", "tradeDirection", "cashBufferPct",
                             "roundQty", "qtyStep", "initial_capital", "commission_value"}
        only_ref -= strategy_specific
        only_other -= strategy_specific

        if only_ref or only_other:
            print(f"⚠  Parity drift: {ref_name} vs {other_name}")
            if only_ref:
                print(f"   Only in {ref_name}: {', '.join(sorted(only_ref)[:10])}")
            if only_other:
                print(f"   Only in {other_name}: {', '.join(sorted(only_other)[:10])}")
            errors += len(only_ref) + len(only_other)
        else:
            print(f"✅ {ref_name} ↔ {other_name}: input names match ({len(ref_vars)} vars)")

    return errors


# ── main ──────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="Pine Script input surface-area tool")
    sub = parser.add_subparsers(dest="cmd")

    p_audit = sub.add_parser("audit", help="Inventory inputs across Pine files")
    p_audit.add_argument("files", nargs="+", type=Path)

    p_regroup = sub.add_parser("regroup", help="Apply group assignments to inputs")
    p_regroup.add_argument("--map", required=True, type=Path, help="JSON classification map")
    p_regroup.add_argument("--dry-run", action="store_true")
    p_regroup.add_argument("file", type=Path)

    p_lint = sub.add_parser("lint", help="Check input hygiene")
    p_lint.add_argument("files", nargs="+", type=Path)
    p_lint.add_argument("--parity", action="store_true", help="Check parity between files")

    args = parser.parse_args()
    if args.cmd == "audit":
        cmd_audit(args.files)
    elif args.cmd == "regroup":
        cmd_regroup(args.file, args.map, dry_run=args.dry_run)
    elif args.cmd == "lint":
        if args.parity:
            sys.exit(cmd_lint_parity(args.files))
        else:
            sys.exit(cmd_lint(args.files))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
