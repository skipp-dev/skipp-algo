"""Pin: float-equality discipline in ``smc_core/`` (regression guard).

Floating-point equality (``x == 0.0``, ``x != 0.5``, ``x == y`` for
two computed floats) is a numerical bug magnet: a value computed via
two different paths can differ by a single ULP and silently fail the
comparison. The repo-wide convention is:

* Use ``math.isclose(a, b, abs_tol=...)`` for "are these the same
  number" checks.
* Use ``abs(x) < epsilon`` for "is this zero" checks.
* Reserve ``==``/``!=`` for *integer* values that happen to be typed
  as ``float`` only by virtue of arithmetic context (e.g. counter
  totals, exact constants from input data).

Discovery (2026-04-24): ``smc_core/`` is currently 100% clean — zero
``== 0.0`` / ``!= 0.0`` / ``== <float-literal>`` patterns. This pin
freezes that state so a future regression cannot introduce a silent
ULP-equality bug into the numerical core.

Scope: only ``smc_core/*.py``. Other modules are not yet held to this
standard (large legacy surface) and are explicitly out of scope for
this pin.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET_DIR = REPO_ROOT / "smc_core"

# Detect equality/inequality against any float literal: 0.0, 1.5, -3.14,
# 2e-3, 1e6, .5, 1., etc. Integer literals are intentionally allowed
# (counters). The float-literal alternation accepts:
#   - decimal-with-optional-fraction (1.5, 1., 0.0) +/- exponent
#   - leading-decimal (.5, .25e-3)
#   - exponent-only (1e6, 2e-3)  — unambiguously float in Python
_FLOAT_EQ_RE = re.compile(
    r"(?:==|!=)\s*-?(?:(?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?|\d+[eE][+-]?\d+)\b"
    r"|"
    r"-?(?:(?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?|\d+[eE][+-]?\d+)\s*(?:==|!=)"
)


def _python_files() -> list[Path]:
    return sorted(p for p in TARGET_DIR.rglob("*.py") if p.is_file())


def _strip_comments_and_strings(text: str) -> str:
    """Best-effort: drop ``# ...`` to end of line, and triple-quoted
    docstrings. Single/double-quoted string literals containing ``==``
    are rare in this codebase; perfect tokenization is not required for
    a tripwire of this scope.

    Replace removed regions with the same number of newlines so reported
    line numbers in violations still match the original source.
    """

    def _preserve_newlines(match: re.Match[str]) -> str:
        return "\n" * match.group(0).count("\n")

    text = re.sub(r"#[^\n]*", "", text)
    text = re.sub(r'"""[\s\S]*?"""', _preserve_newlines, text)
    text = re.sub(r"'''[\s\S]*?'''", _preserve_newlines, text)
    return text


def test_smc_core_is_present() -> None:
    assert TARGET_DIR.is_dir(), f"Expected {TARGET_DIR} to exist."
    assert _python_files(), "smc_core/ must contain at least one .py file."


def test_no_float_literal_equality_in_smc_core() -> None:
    violations: list[tuple[Path, int, str]] = []
    for path in _python_files():
        text = path.read_text(encoding="utf-8")
        cleaned = _strip_comments_and_strings(text)
        # Re-scan original to report accurate line numbers, but only
        # count lines whose cleaned counterpart still matches.
        cleaned_lines = cleaned.splitlines()
        for i, line in enumerate(cleaned_lines):
            if _FLOAT_EQ_RE.search(line):
                violations.append((path.relative_to(REPO_ROOT), i + 1, line.strip()))
    assert not violations, (
        f"Float-literal equality found in smc_core/ "
        f"({len(violations)} violation(s)):\n"
        + "\n".join(f"  {p}:{ln}: {txt}" for p, ln, txt in violations)
        + "\nUse math.isclose(...) for value comparison or "
        "abs(x) < epsilon for zero checks. Integer comparisons typed "
        "as float should use integer literals (e.g. ``n == 0`` not "
        "``n == 0.0``)."
    )
