"""Pine ``request.security`` discipline pin.

Two invariants for active (non-legacy) Pine files in this repo:

1. **No same-symbol + same-TF security call.** Calling
   ``request.security(syminfo.tickerid, timeframe.period, ...)`` is
   essentially a no-op that costs an entire extra security context — a
   well-known Pine antipattern. Cross-symbol same-TF
   (``request.security(symbol, timeframe.period, ...)``) is allowed
   because the *symbol* is genuinely different.

2. **Every ``request.security[*]`` call must specify ``lookahead=``
   explicitly.** The default differs between Pine versions and silently
   leaking future bars into historical bars is a notorious lookahead-
   bias bug.

Legacy Pine under ``pine/legacy/`` and test fixtures are excluded — the
discipline only applies to currently-shipped indicator/strategy files.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Directories whose Pine files are not subject to the discipline.
_EXCLUDED_DIR_PREFIXES: tuple[str, ...] = (
    "pine/legacy/",
    "tests/",
)

# Match ``request.security`` and ``request.security_lower_tf`` calls.
_CALL_RE = re.compile(r"\brequest\.security[a-zA-Z_]*\s*\(")

# A same-symbol + same-TF call: ``syminfo.tickerid`` immediately followed
# (after a comma + optional whitespace) by ``timeframe.period``. Multi-
# line tolerant because Pine often wraps args.
_SAME_TF_RE = re.compile(
    r"\brequest\.security[a-zA-Z_]*\s*\(\s*syminfo\.tickerid\s*,\s*timeframe\.period\b"
)


# Match a real ``lookahead = ...`` named-argument assignment in the call
# body. Plain substring search would false-positive on identifiers like
# ``use_lookahead_flag`` or on the word appearing inside a comment/string.
_LOOKAHEAD_KWARG_RE = re.compile(r"\blookahead\s*=")


def _active_pine_files() -> list[Path]:
    out: list[Path] = []
    for p in REPO_ROOT.rglob("*.pine"):
        rel = p.relative_to(REPO_ROOT).as_posix()
        if any(rel.startswith(prefix) for prefix in _EXCLUDED_DIR_PREFIXES):
            continue
        out.append(p)
    return sorted(out)


def _balanced_call_body(text: str, open_paren_idx: int) -> tuple[str, int]:
    """Starting at the index of the opening ``(`` of a call, return the
    body up to and including the matching ``)``, plus the index just
    past the closing paren. Strings and comments are not interpreted —
    this is a best-effort paren balancer that's good enough for the
    structurally-simple Pine call sites in this repo."""
    depth = 0
    i = open_paren_idx
    while i < len(text):
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[open_paren_idx : i + 1], i + 1
        i += 1
    return text[open_paren_idx:], len(text)


def test_no_same_symbol_same_timeframe_security_call() -> None:
    offenders: list[str] = []
    for path in _active_pine_files():
        text = path.read_text(encoding="utf-8")
        for match in _SAME_TF_RE.finditer(text):
            line_no = text.count("\n", 0, match.start()) + 1
            offenders.append(f"{path.relative_to(REPO_ROOT).as_posix()}:{line_no}")
    assert not offenders, (
        "Found same-symbol + same-TF request.security() call(s) — these are "
        "essentially no-ops that cost an extra security context (Pine "
        "antipattern):\n  - " + "\n  - ".join(offenders)
        + "\n\nReplace with the corresponding direct expression "
        "(e.g. drop the request.security wrapper, or use a different TF)."
    )


def test_every_active_request_security_call_specifies_lookahead() -> None:
    offenders: list[str] = []
    for path in _active_pine_files():
        text = path.read_text(encoding="utf-8")
        for match in _CALL_RE.finditer(text):
            paren_idx = match.end() - 1  # index of the opening '('
            body, _ = _balanced_call_body(text, paren_idx)
            # ``request.security_lower_tf`` does not accept a ``lookahead``
            # argument in Pine v5/v6 — it always behaves as lookahead_off.
            if "request.security_lower_tf" in match.group(0):
                continue
            if _LOOKAHEAD_KWARG_RE.search(body):
                continue
            line_no = text.count("\n", 0, match.start()) + 1
            offenders.append(f"{path.relative_to(REPO_ROOT).as_posix()}:{line_no}")
    assert not offenders, (
        "Found request.security() call(s) that do not specify lookahead= "
        "explicitly:\n  - " + "\n  - ".join(offenders)
        + "\n\nAdd `lookahead = barmerge.lookahead_off` (or _on with a "
        "comment explaining why future-bar leakage is intended)."
    )
