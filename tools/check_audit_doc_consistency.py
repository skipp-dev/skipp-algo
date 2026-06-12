#!/usr/bin/env python3
"""R12 (audit-L-1, 2026-05-12) — audit-doc cross-reference consistency check.

Background
==========
Audit retrospectives in ``docs/AUDIT_*_2026-*.md`` routinely cite section
headers across documents (e.g. "see audit-L-1 \xa7R7" or
"per the retrospective \xa7R5"). When a retrospective is renamed or a
section header is later renumbered, those cross-references silently rot.

This script walks every ``docs/AUDIT_*_2026-*.md`` (and the active
``docs/AUDIT_L1_REVIEW_RETROSPECTIVE_2026-05-12.md``), extracts every
``\xa7R<N>`` reference from the body text, and asserts the cited section
header (``## R<N>`` or ``### R<N>``, optionally prefixed with the literal
``\xa7R<N>``) actually exists in the same doc.

Cross-doc references in the form ``audit-X-Y \xa7R<N>`` resolve to the
matching audit-X-Y doc when present; if the referenced doc is missing
entirely, the warning surface that.

Warn-only by default. Use ``--strict`` to make CI fail on warnings.

See ``docs/AUDIT_L1_REVIEW_RETROSPECTIVE_2026-05-12.md`` \xa7R12.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterator
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DOCS_DIR = _REPO_ROOT / "docs"

# Section ref:  \xa7R7  or  \xa7R12
_SECTION_REF_RE = re.compile(r"\xa7R(\d+)\b")

# Audit-tag ref:  audit-L-1  or  audit-L1  or  audit-A-3
# Tolerant of optional dash (audit-L-1 vs audit-L1).
_AUDIT_TAG_RE = re.compile(
    r"\baudit-([A-Z])-?(\d+)(?:\s*\xa7R(\d+))?", re.IGNORECASE
)

# Section headers in the doc:  ## R7  /  ### R7  /  ## \xa7R7  /  ### \xa7R7
_SECTION_HEADER_RE = re.compile(
    r"^#{2,4}\s+(?:\xa7)?R(\d+)\b", re.MULTILINE
)


def _audit_docs() -> list[Path]:
    return sorted(_DOCS_DIR.glob("AUDIT_*_2026-*.md"))


def _section_numbers_in(doc: Path) -> set[int]:
    text = doc.read_text(encoding="utf-8", errors="replace")
    return {int(m.group(1)) for m in _SECTION_HEADER_RE.finditer(text)}


def _audit_doc_for_tag(letter: str, number: str) -> Path | None:
    """Best-effort lookup: ``audit-L-1`` \u2192 ``AUDIT_L1_REVIEW_*.md``."""

    letter_u = letter.upper()
    candidates = sorted(_DOCS_DIR.glob(f"AUDIT_{letter_u}{number}_*.md"))
    if candidates:
        return candidates[0]
    candidates = sorted(_DOCS_DIR.glob(f"AUDIT_{letter_u}_{number}_*.md"))
    return candidates[0] if candidates else None


def _scan(doc: Path) -> Iterator[str]:
    text = doc.read_text(encoding="utf-8", errors="replace")
    own_sections = _section_numbers_in(doc)
    rel = doc.relative_to(_REPO_ROOT)

    # 1. Same-doc ``\xa7R<N>`` refs (no audit-tag prefix in the same line).
    for line_no, line in enumerate(text.splitlines(), 1):
        # Skip lines that ALSO contain an audit-tag (cross-doc ref handled below).
        has_audit_tag = bool(_AUDIT_TAG_RE.search(line))
        for m in _SECTION_REF_RE.finditer(line):
            n = int(m.group(1))
            if has_audit_tag:
                continue
            if n not in own_sections:
                yield f"  {rel}:{line_no}  \xa7R{n} cited but no `## R{n}` / `### R{n}` header in same doc"

    # 2. Cross-doc ``audit-X-Y \xa7R<N>`` refs.
    for line_no, line in enumerate(text.splitlines(), 1):
        for m in _AUDIT_TAG_RE.finditer(line):
            letter, number, ref_n = m.group(1), m.group(2), m.group(3)
            target = _audit_doc_for_tag(letter, number)
            if target is None:
                yield f"  {rel}:{line_no}  audit-{letter.upper()}-{number} cited but no matching docs/AUDIT_{letter.upper()}{number}_*.md"
                continue
            if ref_n is None:
                continue
            if int(ref_n) not in _section_numbers_in(target):
                yield (
                    f"  {rel}:{line_no}  audit-{letter.upper()}-{number} \xa7R{ref_n} cited but no "
                    f"`## R{ref_n}` header in {target.relative_to(_REPO_ROOT)}"
                )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 on warnings (default: warn-only, exit 0).",
    )
    args = parser.parse_args(argv)

    docs = _audit_docs()
    print(f"Scanned {len(docs)} audit doc(s) under docs/AUDIT_*_2026-*.md.")

    warnings: list[str] = []
    for doc in docs:
        warnings.extend(_scan(doc))

    if not warnings:
        print("OK \u2014 all cross-references resolved.")
        return 0

    print(f"\n{len(warnings)} warning(s):")
    for w in warnings:
        print(w)

    if args.strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
