"""Defense pin: every ``request.security(...)`` in a standalone Pine script must
request a higher-timeframe series.

Same-TF ``request.security`` (i.e. passing ``timeframe.period``, ``""`` or
``syminfo.period`` as the timeframe argument) is wasteful, costs against the
script's request quota, and silently introduces repaint risk when callers
forget ``lookahead_off`` — equivalent to a normal series access without any
benefit. Confine the construct to genuine HTF lookups.

Scope, stated precisely: **standalone** ``*.pine`` scripts at the repo root.
The hand-authored ``SMC++/`` libraries are not scanned, and one of them —
``SMC++/smc_utils.pine`` — legitimately passes ``timeframe.period`` in a helper
whose caller supplies the timeframe. This module said "every Pine
request.security call" until 2026-07-15, which that made false.

Layers (defense-only):

1. **Zero-tripwire** — no ``request.security(<sym>, X, ...)`` where ``X`` is
   literally ``timeframe.period``, the empty string ``""``, or
   ``syminfo.period``. This layer only sees literals written inline.
1b. **Resolved-default check** — the only real call passes a *parameter*
   (``trend_tf``), which no literal blacklist can match, so the argument is
   resolved one hop (parameter -> caller argument -> ``input.timeframe(CONST)``
   -> the const's value) and the resulting default must not be same-TF. This is
   what makes layer 1's promise apply to the call the script actually has.
   Bounded honestly: ``input.timeframe`` is a user control, so a user can still
   pick the chart timeframe at runtime. That is not statically decidable; this
   pins the defaults the script ships with.
2. **Frozen total budget** — exactly 1 call site across all standalone
   ``*.pine`` files (in ``SMC_Long_Dip_Suite.pine``). New HTF call sites are
   not banned but every addition must update the ledger and be justified in
   CHANGELOG.
3. **Frozen site ledger** — the existing site is pinned at file-level.

   History: was 3 until 2026-07-14, when the inert HTF-FVG subsystem (2
   ``request.security`` HTF-gap lookups, never rendered or consumed) was
   removed and the OB/FVG/structure engine was extracted into the
   ``smc_engine_private`` library to relieve the CE10117 token budget. The
   surviving site is the HTF structure-trend sample.
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

_FROZEN_TOTAL = 4
_FROZEN_FILE_COUNTS: dict[str, int] = {
    "SMC_HTF_Confluence.pine": 3,
    "SMC_Long_Dip_Suite.pine": 1,
}

# Forbidden timeframe arguments (same-TF aliases).
_FORBIDDEN_TF_LITERALS = frozenset({"timeframe.period", "syminfo.period", '""', "''"})


def _normalise_tf(tf: str) -> str:
    """Strip wrapping parentheses and whitespace before the blacklist compare.

    The blacklist is a SET MEMBERSHIP test on the raw argument text, so it only
    ever matched the four exact spellings. `(timeframe.period)` — the same
    chart-TF request, in parentheses — is a different string and sailed through
    (verified 2026-07-15: all five tests stayed green with the sole pinned site
    rewritten that way). Pine treats the parenthesised form identically, so the
    pin must too. Repeated stripping handles `((timeframe.period))`.
    """
    out = tf.strip()
    while len(out) >= 2 and out.startswith("(") and out.endswith(")"):
        inner = out[1:-1].strip()
        # Only unwrap a genuine wrapper: "(a) + (b)" must stay as-is.
        depth = 0
        wraps = True
        for ch in inner:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth < 0:
                    wraps = False
                    break
        if not wraps or depth != 0:
            break
        out = inner
    return out


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


# ─── resolve the timeframe argument, don't just blacklist literals ───
#
# The tripwire above compares the timeframe argument against four literals. The
# *only* ledgered call passes `trend_tf` — a function parameter:
#
#     get_confirmed_structure_trend(string trend_tf, simple int structure_len) =>
#         request.security(syminfo.tickerid, trend_tf, ...)
#
# A parameter is never one of the four literals, so the blacklist is inert
# exactly where it is supposed to work, and "every request.security must
# request a higher-timeframe series" was unenforced. Resolving the argument one
# hop — parameter -> caller argument -> `input.timeframe(CONST)` -> the const's
# value — is what makes the claim mean something: today those resolve to '240',
# '1D' and '1W', and re-pointing a default at `timeframe.period` or '' now fails.
#
# Honestly bounded: `input.timeframe` is a user control, so a user can still
# select the chart timeframe at runtime. That is not statically decidable and
# this test does not pretend otherwise — it pins the *defaults* the script ships
# with, which is the part source review can own.

_PINE_FUNC_DEF = re.compile(r"^(\w+)\s*\(([^)]*)\)\s*=>")
_PINE_CONST = re.compile(r"^\s*(?:const|var)?\s*string\s+(\w+)\s*=\s*'([^']*)'", re.M)
_PINE_INPUT_TF = re.compile(
    r"""^\s*(?:var\s+)?string\s+(\w+)\s*=\s*input\.timeframe\s*\(\s*
        (\w+|"[^"]*"|'[^']*')""",
    re.M | re.X,
)


def _enclosing_pine_func(lines: list[str], lineno: int) -> tuple[str, list[str]] | None:
    """Return ``(name, params)`` of the function definition above ``lineno``."""
    for i in range(lineno - 1, -1, -1):
        m = _PINE_FUNC_DEF.match(lines[i])
        if m:
            params = [p.strip().split()[-1] for p in m.group(2).split(",") if p.strip()]
            return m.group(1), params
    return None


def _resolve_tf_defaults(text: str, tf: str, lineno: int) -> list[str]:
    """Resolve a timeframe argument to the literal default(s) it can carry.

    Returns the resolved literals, or ``[tf]`` when ``tf`` is already a literal.
    An empty list means "could not resolve" — the caller fails closed on that.
    """

    tf = _normalise_tf(tf)  # `(timeframe.period)` is the same request as bare
    if tf.startswith(("'", '"')):
        return [tf.strip("'\"")]
    if "." in tf or not tf.isidentifier():
        return [tf]  # timeframe.period & friends — the literal tripwire owns these

    lines = text.splitlines()
    consts = dict(_PINE_CONST.findall(text))
    inputs = dict(_PINE_INPUT_TF.findall(text))

    def _resolve_name(name: str) -> list[str]:
        if name in inputs:  # var string X = input.timeframe(CONST, ...)
            input_default = inputs[name]
            if input_default.startswith(("'", '"')):
                return [input_default.strip("'\"")]
            const_name = input_default
            return [consts[const_name]] if const_name in consts else []
        if name in consts:
            return [consts[name]]
        return []

    enclosing = _enclosing_pine_func(lines, lineno)
    if enclosing and tf in enclosing[1]:
        # A parameter: resolve every caller's corresponding argument.
        name, params = enclosing
        idx = params.index(tf)
        call_re = re.compile(rf"(?<![\w.]){re.escape(name)}\s*\(")
        out: list[str] = []
        for i, raw in enumerate(lines):
            if i == lineno - 1 or _PINE_FUNC_DEF.match(raw):
                continue  # the definition itself
            for m in call_re.finditer(raw):
                arg = _extract_positional(raw[m.end() - 1 :], idx)
                if arg is None:
                    return []
                arg = _normalise_tf(arg)
                resolved = _resolve_name(arg) if arg.isidentifier() else [arg]
                if not resolved:
                    return []
                out.extend(resolved)
        return out
    return _resolve_name(tf)


def _extract_positional(call_text: str, index: int) -> str | None:
    """Return the ``index``-th positional argument of a ``(...)`` call body."""
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
        else:
            cur.append(ch)
    return args[index] if len(args) > index else None


def test_request_security_timeframe_resolves_to_an_htf_default() -> None:
    """Resolve each timeframe argument; no resolved default may be same-TF."""
    forbidden_bare = {lit.strip("'\"") for lit in _FORBIDDEN_TF_LITERALS} | {""}
    problems: list[str] = []
    for p in _iter_pine_files():
        text = p.read_text(encoding="utf-8")
        for rel, ln, tf in _scan_calls():
            if rel != p.name or tf is None:
                continue
            resolved = _resolve_tf_defaults(text, tf, ln)
            if not resolved:
                problems.append(
                    f"  - {rel}:{ln}: timeframe {tf!r} could not be resolved to a "
                    "literal default; the blacklist cannot see it either"
                )
                continue
            for value in resolved:
                if value in forbidden_bare:
                    problems.append(
                        f"  - {rel}:{ln}: timeframe {tf!r} resolves to {value!r} "
                        "— same-TF"
                    )

    assert not problems, (
        "request.security must request an HTF. The literal tripwire above only "
        "sees `timeframe.period` / `syminfo.period` / '' written inline; the one "
        "real call passes a parameter, so the argument is resolved through its "
        "caller to the input default it ships with. A default pointing at the "
        "chart timeframe is the same-TF waste + repaint risk this module "
        "exists to prevent:\n" + "\n".join(problems)
    )


def test_pine_inventory_sane() -> None:
    files = list(_iter_pine_files())
    assert len(files) >= 15, f"Pine inventory shrank: {len(files)}"


def test_no_same_tf_request_security() -> None:
    bad: list[str] = []
    for rel, ln, tf in _scan_calls():
        if tf is None:
            continue
        if _normalise_tf(tf) in _FORBIDDEN_TF_LITERALS:
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
