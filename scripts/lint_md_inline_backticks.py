#!/usr/bin/env python3
"""Lint Markdown files for unbalanced inline backtick spans across source lines.

Background — P5.4 deep-review (2026-05-13)
==========================================

The Copilot review on PR #2178 (docs/PHASE_5.4_SCOPING.md) caught two
markdown lines where an inline ``code`` span had been auto-wrapped onto two
source lines, leaving an opening backtick on line N and a closing backtick
on line N+1. GitHub renders this as a broken span and copy-paste of the
quoted command no longer works.

A whole-`docs/` sweep (deep-review § C2 with user-corrected count) found
**48 such lines**. This lint reproduces the sweep so the same finding-class
cannot regress.

Edge cases handled (per deep-review CORR-4)
-------------------------------------------

1. **Tilde fences** (``~~~lang`` … ``~~~``) — tracked alongside backtick fences.
2. **Triple-backtick groups not at line start** — only an opening fence at
   the start of a line (with optional indent) toggles fence state. A
   triple-backtick run mid-line is treated as inline content and balanced
   per the same single-backtick logic.
3. **CommonMark §6.1 multi-line code spans** — technically valid Markdown.
   We *report* them as warnings (warn-mode) but do not fail unless run with
   ``--strict``. Use ``--strict`` only after the bulk-fix PR is merged and
   the known-good corpus has zero false positives.

Usage
-----

::

    python scripts/lint_md_inline_backticks.py docs/
    python scripts/lint_md_inline_backticks.py --strict docs/
    python scripts/lint_md_inline_backticks.py path/to/file.md

Exit codes:

* ``0`` — no findings, or warn-mode (any number of findings).
* ``1`` — ``--strict`` mode and at least one finding.
* ``2`` — usage / IO error.

Refs: docs/COPILOT_REVIEW_TRIAGE_PROTOCOL.md (Phase B).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Iterable, NamedTuple

# A code-fence opener at line start (after optional indent) — both ``` and ~~~.
# We deliberately match \s* (not [ \t]) so list-item-prefixed code blocks are
# tolerated by hand-counting indent in the caller if ever needed.
_FENCE_OPENER_RE = re.compile(r"^\s*(?P<token>`{3,}|~{3,})")

# Blockquote prefix — CommonMark §5.1 allows fences and inline code spans inside
# blockquotes (`> ```bash`, `> some `code` here`). We strip the leading
# `>`-prefix(es) before fence/inline-balance checks so blockquote-nested fences
# are recognized correctly.
_BLOCKQUOTE_PREFIX_RE = re.compile(r"^(?:\s*>\s?)+")

# Strip *any* fully-balanced inline span on a single line first, including
# spans delimited by 1, 2, or 3+ backticks. CommonMark §6 says a span is
# delimited by matching runs of the same length, so we walk runs greedily.
_RUN_RE = re.compile(r"`+")


class Finding(NamedTuple):
    path: Path
    line: int
    column: int
    snippet: str
    rule: str  # "unbalanced-inline-backticks"

    def format(self) -> str:
        return (
            f"{self.path}:{self.line}:{self.column}: [{self.rule}] "
            f"{self.snippet}"
        )


def _strip_balanced_inline_runs(line: str) -> str:
    """Remove every balanced backtick-run inline span from ``line``.

    Walks backtick-runs left-to-right. Whenever two runs of equal length
    occur on the same line, treats the bytes between them (and the runs
    themselves) as a balanced span and removes them.

    Leftover backtick-runs after this pass indicate an *unbalanced* span,
    which is what we want to report.
    """
    runs = list(_RUN_RE.finditer(line))
    if not runs:
        return line

    used: set[int] = set()
    spans_to_remove: list[tuple[int, int]] = []
    i = 0
    while i < len(runs):
        if i in used:
            i += 1
            continue
        opener = runs[i]
        opener_len = len(opener.group())
        # Find the next same-length run not already used.
        j = i + 1
        while j < len(runs):
            if j in used:
                j += 1
                continue
            if len(runs[j].group()) == opener_len:
                spans_to_remove.append((opener.start(), runs[j].end()))
                used.add(i)
                used.add(j)
                break
            j += 1
        i += 1

    if not spans_to_remove:
        return line

    # Stitch line back together skipping the balanced regions.
    out: list[str] = []
    cursor = 0
    for start, end in spans_to_remove:
        if start > cursor:
            out.append(line[cursor:start])
        cursor = end
    if cursor < len(line):
        out.append(line[cursor:])
    return "".join(out)


def lint_file(path: Path) -> list[Finding]:
    findings: list[Finding] = []
    in_fence = False
    fence_token: str | None = None  # "`" or "~"

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"warning: cannot read {path}: {exc}", file=sys.stderr)
        return findings

    for lineno, raw in enumerate(text.splitlines(), start=1):
        # Strip leading blockquote markers (`> `, `>> `, etc.) before checking
        # for fence opener / inline balance. CommonMark §5.1 allows fences and
        # inline-code inside blockquotes; without this strip both a `> ```bash`
        # opener and a `> ` ` `` `` `inline` ` `` ` span are mis-flagged.
        prefix_match = _BLOCKQUOTE_PREFIX_RE.match(raw)
        prefix_len = prefix_match.end() if prefix_match is not None else 0
        line = raw[prefix_len:]
        m = _FENCE_OPENER_RE.match(line)
        if m is not None:
            tok = m.group("token")[0]
            if not in_fence:
                in_fence = True
                fence_token = tok
                continue
            if fence_token is not None and tok == fence_token:
                in_fence = False
                fence_token = None
                continue
            # Different fence-token while inside a fence — leave as content.
        if in_fence:
            continue

        stripped = _strip_balanced_inline_runs(line)
        leftover = _RUN_RE.search(stripped)
        if leftover is None:
            continue

        snippet = raw.rstrip()[:120]
        findings.append(
            Finding(
                path=path,
                line=lineno,
                column=leftover.start() + 1 + prefix_len,
                snippet=snippet,
                rule="unbalanced-inline-backticks",
            )
        )
    return findings


def iter_markdown_files(targets: Iterable[Path]) -> Iterable[Path]:
    for t in targets:
        if t.is_file():
            if t.suffix.lower() == ".md":
                yield t
            continue
        if t.is_dir():
            yield from sorted(t.rglob("*.md"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="Markdown files or directories to scan",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 on any finding (default: warn-only, exit 0).",
    )
    parser.add_argument(
        "--format",
        choices=("plain", "github"),
        default="plain",
        help="Output format. 'github' emits ::warning::/::error:: GHA annotations.",
    )
    args = parser.parse_args(argv)

    files = list(iter_markdown_files(args.paths))
    if not files:
        print("no markdown files found", file=sys.stderr)
        return 2

    findings: list[Finding] = []
    for f in files:
        findings.extend(lint_file(f))

    if not findings:
        print(f"OK: 0 findings across {len(files)} markdown file(s)")
        return 0

    severity = "error" if args.strict else "warning"
    for fnd in findings:
        if args.format == "github":
            print(
                f"::{severity} file={fnd.path},line={fnd.line},col={fnd.column}"
                f"::[{fnd.rule}] {fnd.snippet}"
            )
        else:
            print(fnd.format())

    print(
        f"\n{len(findings)} finding(s) across {len(files)} file(s) "
        f"[mode: {'strict' if args.strict else 'warn'}]",
        file=sys.stderr,
    )
    return 1 if args.strict else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
