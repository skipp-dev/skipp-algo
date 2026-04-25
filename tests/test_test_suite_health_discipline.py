"""Test-suite health discipline pin.

Audit findings (skipp-algo, 2026-04-24):
  * 0 non-strict xfail decorators in the entire ``tests/`` tree.
  * Every skip / skipif marker carries a reason= argument.

This pin freezes that healthy state:

1. No xfail without strict=True. Non-strict xfail silently passes once
   a bug is fixed, hiding the green and accumulating confusion. Strict
   xfail is allowed (it forces the author to remove the marker when the
   underlying bug is resolved).

2. Every skip/skipif must have a non-empty reason= argument. Bare skips
   are review-hostile and tend to outlive the condition that justified
   them.

If you legitimately need a non-strict xfail (e.g. flaky platform-
dependent test), add the file path to _XFAIL_ALLOWLIST below with a
written justification.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = REPO_ROOT / "tests"

# Files allowed to use non-strict xfail. Empty by default — add entries
# only with a written justification.
_XFAIL_ALLOWLIST: frozenset[str] = frozenset()

# Look-ahead window (in lines) for finding the marker's body — enough to
# cover multi-line decorators with nested parens.
_LOOKAHEAD = 12

_DECORATOR_RE = re.compile(
    r"^[ \t]*@pytest\.mark\.(skipif|skip|xfail)\b", re.MULTILINE
)

# Module-level marker assignments such as
#   pytestmark = pytest.mark.skipif(...)
#   pytestmark = [pytest.mark.skip(reason=...), ...]
# are NOT decorators and would otherwise slip past _DECORATOR_RE. We
# additionally scan for any ``pytest.mark.(skip|skipif|xfail)(`` call
# expression so the discipline applies to module/class-level markers too.
_PYTESTMARK_CALL_RE = re.compile(
    r"\bpytest\.mark\.(skipif|skip|xfail)\s*\(", re.MULTILINE
)

# A reason argument is considered non-empty if it is followed by a
# non-empty string literal. ``reason=\"\"``, ``reason=''``, ``reason=None``
# all count as empty/missing for the purposes of this pin.
_NONEMPTY_REASON_RE = re.compile(
    r"reason\s*=\s*(?:[rRbBuU]{0,2}((?:\"\"\"|'''|\"|'))(?P<body>.*?)\1)",
    re.DOTALL,
)

# Skip this file itself: its docstring necessarily contains the literal
# strings we are forbidding elsewhere, which would otherwise cause a
# false self-trigger.
_SELF = Path(__file__).resolve()


def _python_test_files() -> list[Path]:
    return sorted(
        p
        for p in TESTS_DIR.rglob("test_*.py")
        if p.is_file() and p.resolve() != _SELF
    )


def _decorator_body(text_lines: list[str], start_line_idx: int) -> str:
    """Return the decorator body starting at start_line_idx (0-based),
    accumulating lines until parenthesis balance returns to zero or the
    look-ahead window is exhausted."""
    body: list[str] = []
    depth = 0
    started = False
    for i in range(start_line_idx, min(start_line_idx + _LOOKAHEAD, len(text_lines))):
        line = text_lines[i]
        body.append(line)
        for ch in line:
            if ch == "(":
                depth += 1
                started = True
            elif ch == ")":
                depth -= 1
        if started and depth <= 0:
            break
    return "\n".join(body)


def _iter_markers(path: Path):
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    seen: set[tuple[int, str]] = set()
    for match in _DECORATOR_RE.finditer(text):
        line_no = text.count("\n", 0, match.start()) + 1
        marker = match.group(1)
        key = (line_no, marker)
        if key in seen:
            continue
        seen.add(key)
        body = _decorator_body(lines, line_no - 1)
        yield line_no, marker, body
    # Also catch module/class-level pytestmark assignments and any other
    # ``pytest.mark.<skip|skipif|xfail>(...)`` call sites that aren't
    # introduced by an ``@`` decorator.
    for match in _PYTESTMARK_CALL_RE.finditer(text):
        line_no = text.count("\n", 0, match.start()) + 1
        marker = match.group(1)
        key = (line_no, marker)
        if key in seen:
            continue
        seen.add(key)
        body = _decorator_body(lines, line_no - 1)
        yield line_no, marker, body


def test_no_non_strict_xfail_in_test_suite() -> None:
    offenders: list[str] = []
    for path in _python_test_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in _XFAIL_ALLOWLIST:
            continue
        for line_no, marker, body in _iter_markers(path):
            if marker != "xfail":
                continue
            if "strict=True" in body:
                continue
            offenders.append(f"{rel}:{line_no}")
    assert not offenders, (
        "Found xfail decorator without strict=True in:\n  - "
        + "\n  - ".join(offenders)
        + "\n\nNon-strict xfail silently passes once the underlying bug is "
        "fixed, hiding the green. Either add strict=True (preferred) or "
        "add the file path to _XFAIL_ALLOWLIST in "
        f"{_SELF.name} with a written justification."
    )


def test_every_skip_marker_has_a_reason() -> None:
    offenders: list[str] = []
    for path in _python_test_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        for line_no, marker, body in _iter_markers(path):
            if marker not in ("skip", "skipif"):
                continue
            match = _NONEMPTY_REASON_RE.search(body)
            if match is not None and match.group("body").strip():
                continue
            offenders.append(f"{rel}:{line_no} ({marker})")
    assert not offenders, (
        "Found skip/skipif marker without an explicit non-empty reason= in:\n  - "
        + "\n  - ".join(offenders)
        + "\n\nEvery skip must explain why it is skipped so reviewers can "
        "tell whether the condition still applies. ``reason=\"\"``, "
        "``reason=''`` and ``reason=None`` do NOT satisfy this pin."
    )
