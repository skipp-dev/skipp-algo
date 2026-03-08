#!/usr/bin/env python3
"""Basic Pine Script v6 lint checks for USI.pine."""
import re, sys

def lint_pine(path):
    with open(path) as f:
        lines = f.readlines()
    src = "".join(lines)
    errors = []

    # 1. version tag
    if not re.search(r'//@version=6', src):
        errors.append("Missing //@version=6")

    # 2. Balanced parens / brackets
    for ch_open, ch_close, name in [('(', ')', 'parentheses'), ('[', ']', 'brackets')]:
        depth = 0
        for i, c in enumerate(src):
            if c == ch_open: depth += 1
            elif c == ch_close: depth -= 1
            if depth < 0:
                ln = src[:i].count('\n') + 1
                errors.append(f"Unmatched closing {name} at line {ln}")
                break
        if depth > 0:
            errors.append(f"Unclosed {name} (depth={depth})")

    # 3. Defined vs used variables — simple scan
    defined = {}
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith('//'):
            continue
        # input assignments
        m = re.match(r'^(\w+)\s*=\s*input\.', stripped)
        if m:
            defined[m.group(1)] = i
        # simple assignments (must start at column 0 — skip indented named params)
        m = re.match(r'^(?:var\s+)?(?:bool|int|float|string|color)?\s*(\w+)\s*=\s*(?!input)', stripped)
        if m and not stripped.startswith('if') and not stripped.startswith('for') and not line[0].isspace():
            defined[m.group(1)] = i

    for var, defline in defined.items():
        # skip known Pine built-ins used as plotshape params
        if var in ('grpUsi', 'grpFilt', 'grpStable', 'grpVis'):
            # group vars — used inline in input() calls
            uses = [i for i, l in enumerate(lines, 1) if var in l and i != defline]
            if not uses:
                errors.append(f"Variable '{var}' defined at line {defline} but never referenced")
            continue
        # count references outside definition line
        uses = [i for i, l in enumerate(lines, 1) if var in l and i != defline]
        if not uses:
            errors.append(f"Variable '{var}' defined at line {defline} but never referenced")

    # 4. ta.* calls inside ternary / short-circuit (Pine v6 warning)
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith('//'):
            continue
        if re.search(r'\b(and|or|\?)\s*ta\.(rising|falling|ema|rsi|sma|atr)', stripped):
            errors.append(f"Line {i}: ta.*() call may be conditional — risk of inconsistent evaluation")

    # 5. Input minval for RSI lengths (should be >= 1)
    for i, line in enumerate(lines, 1):
        m = re.search(r'input\.int\((\d+),.*minval\s*=\s*(\d+)', line)
        if m:
            defval, minv = int(m.group(1)), int(m.group(2))
            if defval < minv:
                errors.append(f"Line {i}: default {defval} < minval {minv}")

    # 6. Check all preset values >= their respective minvals
    # (can't fully automate without parsing ternary chains — skip)

    return errors

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "USI.pine"
    errs = lint_pine(path)
    if errs:
        print(f"❌ {len(errs)} issue(s) found in {path}:")
        for e in errs:
            print(f"  • {e}")
        sys.exit(1)
    else:
        print(f"✅ {path}: all checks passed")
        sys.exit(0)
