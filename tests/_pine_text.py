"""Shared Pine source-text utilities for tests.

Several Pine static-analysis pins (alert gating, request.security
budget, etc.) need to scan the source ignoring string-literal contents
and ``//`` line comments — otherwise tooltip examples and alert
messages produce false positives or corrupt paren-balance tracking.

Centralising the sanitiser here eliminates the drift risk Copilot
flagged on PR #195: previously the same helper lived (with subtle
behavioural differences) in both
``tests/test_pine_alert_bar_close_gate.py`` and
``tests/test_pine_request_security_per_file_budget.py``.
"""

from __future__ import annotations


def strip_pine_strings_and_line_comments(src: str) -> str:
    """Blank Pine ``// …`` line comments and ``'…'``/``"…"`` string
    contents while preserving:

    * the surrounding quote delimiters (``'`` / ``"``) so paren-balanced
      extractors can still anchor on them if needed,
    * the ``//`` comment marker,
    * all newlines (so line numbers / offsets remain valid for callers
      that emit line-accurate diagnostics).

    Backslash escapes inside strings are consumed as a unit so an
    escaped delimiter does not prematurely terminate the literal.
    """
    out: list[str] = []
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]
        # Line comment — preserve "//", blank the rest of the line.
        if ch == "/" and i + 1 < n and src[i + 1] == "/":
            out.append("//")
            i += 2
            while i < n and src[i] != "\n":
                out.append(" ")
                i += 1
            continue
        # String literal — preserve delimiters, blank contents.
        if ch in ("'", '"'):
            quote = ch
            out.append(quote)
            i += 1
            while i < n and src[i] != quote:
                if src[i] == "\\" and i + 1 < n:
                    out.append("  ")
                    i += 2
                    continue
                out.append("\n" if src[i] == "\n" else " ")
                i += 1
            if i < n:
                out.append(quote)
                i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)
