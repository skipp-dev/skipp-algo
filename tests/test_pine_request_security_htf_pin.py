"""Defense pin: every Pine ``request.security(...)`` call must request a
higher-timeframe series.

Same-TF ``request.security`` (i.e. passing ``timeframe.period``, ``""`` or
``syminfo.period`` as the timeframe argument) is wasteful, costs against the
script's request quota, and silently introduces repaint risk when callers
forget ``lookahead_off`` — equivalent to a normal series access without any
benefit. Confine the construct to genuine HTF lookups.

Layers (defense-only):

1. **Zero-tripwire** — no ``request.security(<sym>, X, ...)`` where ``X`` is
   ``timeframe.period``, the empty string ``""``, or ``syminfo.period``.
2. **Frozen total budget** — exactly 3 call sites across all standalone
   ``*.pine`` files (all in ``SMC_Core_Engine.pine``). New HTF call sites are
   not banned but every addition must update the ledger and be justified in
   CHANGELOG.
3. **Frozen site ledger** — the existing 3 sites are pinned at file-level.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Top-level standalone Pine files only — repo convention.
_PINE_GLOB = "*.pine"

# Generated/snippet fragments to skip.
_PINE_EXCLUDE = frozenset({"_snippet.pine"})

_RS_CALL = re.compile(r"\brequest\.security\s*\(")
# Captures the timeframe argument: 2nd positional arg in
# request.security(symbol, timeframe, expr, ...). Symbol may itself contain
# parens (e.g. syminfo.tickerid), but the lexical pattern is robust enough
# for a defense-only scan: split on the first top-level comma after the
# opening paren.

_FROZEN_TOTAL = 3
_FROZEN_FILE_COUNTS: dict[str, int] = {
    "SMC_Core_Engine.pine": 3,
}

# Forbidden timeframe arguments (same-TF aliases).
_FORBIDDEN_TF_LITERALS = frozenset({"timeframe.period", "syminfo.period", '""', "''"})


def _iter_pine_files() -> Iterable[Path]:
    for p in sorted(ROOT.glob(_PINE_GLOB)):
        if p.name in _PINE_EXCLUDE:
            continue
        yield p


def _extract_tf_arg(call_text: str) -> str | None:
    """Return the second positional arg from a request.security(...) call body.

    ``call_text`` is the substring starting at ``(`` after ``request.security``.
    Returns the trimmed argument, or None if it cannot be located (defense
    accepts the call as opaque and skips it for the literal-tripwire test;
    the count layer still pins it).
    """
    if not call_text.startswith("("):
        return None
    depth = 0
    args: list[str] = []
    cur: list[str] = []
    for ch in call_text[1:]:
        if ch == "(":
            depth += 1
            cur.append(ch)
        elif ch == ")":
            if depth == 0:
                args.append("".join(cur).strip())
                break
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            args.append("".join(cur).strip())
            cur = []
            if len(args) >= 2:
                break
        else:
            cur.append(ch)
    if len(args) < 2:
        return None
    return args[1]


def _scan_calls() -> list[tuple[str, int, str | None]]:
    """Return list of (relpath, lineno, tf_arg_or_None)."""
    out: list[tuple[str, int, str | None]] = []
    for p in _iter_pine_files():
        rel = p.name
        text = p.read_text(encoding="utf-8")
        # Strip line comments to avoid false hits inside `// request.security(...)`.
        # Pine line comments start with `//`.
        for ln, raw in enumerate(text.splitlines(), 1):
            # Drop everything after first `//` not inside a string. Naive but
            # adequate for defense scan (Pine has no `//` literals in code).
            in_str = False
            quote = ""
            cut = len(raw)
            i = 0
            while i < len(raw):
                c = raw[i]
                if in_str:
                    if c == quote and raw[i - 1] != "\\":
                        in_str = False
                elif c in ("'", '"'):
                    in_str = True
                    quote = c
                elif c == "/" and i + 1 < len(raw) and raw[i + 1] == "/":
                    cut = i
                    break
                i += 1
            line = raw[:cut]
            for m in _RS_CALL.finditer(line):
                tf = _extract_tf_arg(line[m.end() - 1 :])
                out.append((rel, ln, tf))
    return out


def test_pine_inventory_sane() -> None:
    files = list(_iter_pine_files())
    assert len(files) >= 15, f"Pine inventory shrank: {len(files)}"


def test_no_same_tf_request_security() -> None:
    bad: list[str] = []
    for rel, ln, tf in _scan_calls():
        if tf is None:
            continue
        if tf in _FORBIDDEN_TF_LITERALS:
            bad.append(f"{rel}:{ln}: same-TF request.security (tf={tf!r})")
    assert not bad, (
        "request.security must request an HTF — same-TF calls are wasteful "
        "and add silent repaint risk:\n  - " + "\n  - ".join(bad)
    )


def test_request_security_total_count_frozen() -> None:
    calls = _scan_calls()
    assert len(calls) == _FROZEN_TOTAL, (
        f"request.security site count changed: got {len(calls)}, "
        f"frozen {_FROZEN_TOTAL}. New HTF call sites are allowed but require "
        f"updating _FROZEN_TOTAL + _FROZEN_FILE_COUNTS and a CHANGELOG entry."
    )


def test_request_security_file_ledger_frozen() -> None:
    by_file: dict[str, int] = {}
    for rel, _ln, _tf in _scan_calls():
        by_file[rel] = by_file.get(rel, 0) + 1
    assert by_file == _FROZEN_FILE_COUNTS, (
        f"request.security per-file ledger drift: got {by_file}, "
        f"frozen {_FROZEN_FILE_COUNTS}"
    )


def test_ledger_files_exist() -> None:
    for rel in _FROZEN_FILE_COUNTS:
        assert (ROOT / rel).is_file(), f"ledger file missing: {rel}"
