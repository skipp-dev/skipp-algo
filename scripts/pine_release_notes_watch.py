#!/usr/bin/env python3
"""Watch the TradingView Pine Script release notes and map deltas to our Pine.

Announcement bridge of a two-bridge design. The weekly hand-lib publish +
tv-save chain already compiles the live Pine surface against the real
TradingView compiler (empirical bridge) — a *breaking* language change turns
that chain red. What nothing watched before this script: the release notes
themselves, i.e. the WHY behind a breakage and every non-breaking change
(new built-ins, changed semantics, new parameters) that never fails a
compile but may affect or benefit the deployed scripts.

Mechanics — deliberately dumb and reviewable:

1. Fetch https://www.tradingview.com/pine-script-docs/release-notes/ (public,
   static HTML; there is no official GitHub source for these docs — verified
   404 on 2026-08-16).
2. Extract entries from the semantic structure the page has carried across
   redesigns: ``h2`` = year, ``h3`` = month, ``h4`` = feature, ``p``/``li``
   body text. Code tokens come from ``<code>`` elements and from links into
   ``pine-script-reference`` (the canonical built-in names).
3. Normalize into a committed markdown snapshot
   (``pine/tv_release_notes_snapshot.md``). An entry is keyed by
   ``(month, feature)``; a key missing from the snapshot is NEW, a differing
   body is CHANGED.
4. For every new/changed entry, grep its code tokens over the live Pine
   surface (root ``*.pine``, ``SMC++/``, ``pine/`` minus ``pine/legacy/``,
   minus ``tests/``) so the triage lands with evidence attached.

A docs redesign that breaks extraction must turn the workflow RED, never
produce a near-empty snapshot (which would later report everything as new):
``main`` refuses results below a minimum entry/month count.

No date arithmetic anywhere — the diff is content-based, so this script
cannot rot into a date bomb.
"""

from __future__ import annotations

import argparse
import gzip
import re
import sys
import time
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import ClassVar

from scripts.smc_atomic_write import atomic_write_text

RELEASE_NOTES_URL = "https://www.tradingview.com/pine-script-docs/release-notes/"
DEFAULT_SNAPSHOT = "pine/tv_release_notes_snapshot.md"
_FETCH_ATTEMPTS = 3
_FETCH_TIMEOUT_S = 30
# Below either floor the extraction is considered broken (docs redesign),
# regardless of what it did return: the real page carries years of history.
_MIN_ENTRIES = 10
_MIN_MONTHS = 3

_YEAR_RE = re.compile(r"^\d{4}$")
_TOKEN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
_REFERENCE_HREF_MARK = "pine-script-reference"
# The live surface published to TradingView users. tests/ carries fixtures and
# probe assets, pine/legacy/ is imported historical material — neither ships.
_EXCLUDED_TOP_DIRS = {"tests", "node_modules", ".git"}
_EXCLUDED_PINE_SUBDIR = "legacy"


@dataclass(frozen=True)
class Entry:
    month: str
    feature: str
    body: str  # newline-joined lines; tokens carry backticks
    tokens: tuple[str, ...]

    @property
    def key(self) -> tuple[str, str]:
        return (self.month, self.feature)

    @property
    def normalized_body(self) -> str:
        return " ".join(self.body.split())


class _NotesParser(HTMLParser):
    """Extract (month, feature, body, tokens) from the release-notes page.

    Capture arms at the first ``h2`` whose text is a bare year and disarms at
    ``<footer>`` — everything before/after (nav templates, search widgets,
    scripts) never reaches the snapshot.
    """

    _HEADINGS: ClassVar[frozenset[str]] = frozenset({"h2", "h3", "h4"})
    _BODY_TAGS: ClassVar[frozenset[str]] = frozenset({"p", "li"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.entries: list[Entry] = []
        self._armed = False
        self._done = False
        self._month = ""
        self._feature = ""
        self._body_lines: list[str] = []
        self._tokens: list[str] = []
        self._heading: str | None = None
        self._heading_buf: list[str] = []
        self._body_tag_depth = 0
        self._line_buf: list[str] = []
        self._line_prefix = ""
        self._wrap_depth = 0  # inside <code> or a reference link
        self._skip_depth = 0  # inside <script>/<style>

    # -- tag walk ----------------------------------------------------------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._done:
            return
        if tag in {"script", "style", "svg"}:
            self._skip_depth += 1
            return
        if tag == "footer":
            self._flush_entry()
            self._done = True
            return
        if tag in self._HEADINGS:
            self._heading = tag
            self._heading_buf = []
            return
        if not self._armed:
            return
        if tag in self._BODY_TAGS:
            if self._body_tag_depth == 0:
                self._line_buf = []
                self._line_prefix = "- " if tag == "li" else ""
            self._body_tag_depth += 1
            return
        if self._body_tag_depth and tag == "code":
            self._wrap_depth += 1
            self._line_buf.append("`")
            return
        if self._body_tag_depth and tag == "a":
            href = next((v or "" for k, v in attrs if k == "href"), "")
            if _REFERENCE_HREF_MARK in href:
                self._wrap_depth += 1
                self._line_buf.append("`")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "svg"}:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._done:
            return
        if tag in self._HEADINGS and self._heading == tag:
            self._finish_heading(tag)
            return
        if not self._armed:
            return
        if tag in self._BODY_TAGS and self._body_tag_depth:
            self._body_tag_depth -= 1
            if self._body_tag_depth == 0:
                line = self._line_prefix + " ".join("".join(self._line_buf).split())
                if line.strip("- "):
                    self._body_lines.append(line)
            return
        if self._wrap_depth and tag in {"code", "a"}:
            # Closing whichever wrapper opened last; both emit the same mark,
            # so pairing by tag identity is unnecessary.
            self._wrap_depth -= 1
            self._line_buf.append("`")
            self._register_token()

    def handle_data(self, data: str) -> None:
        if self._done or self._skip_depth:
            return
        if self._heading is not None:
            self._heading_buf.append(data)
        elif self._body_tag_depth:
            self._line_buf.append(data)

    # -- assembly ----------------------------------------------------------
    def _finish_heading(self, tag: str) -> None:
        text = " ".join("".join(self._heading_buf).split())
        self._heading = None
        if tag == "h2":
            if _YEAR_RE.match(text):
                self._flush_entry()
                self._armed = True
            return
        if not self._armed:
            return
        self._flush_entry()
        if tag == "h3":
            self._month = text
        elif tag == "h4":
            self._feature = text

    def _flush_entry(self) -> None:
        # Months before ~2025 (and any future entry written in that style)
        # carry their text DIRECTLY under the month heading with no ``h4``
        # feature block. Those are entries too — dropping them would make a
        # whole publication style invisible to the diff. They get the
        # pseudo-feature "—" so the (month, feature) key stays total.
        if self._body_lines and (self._feature or self._month):
            self.entries.append(
                Entry(
                    month=self._month,
                    feature=self._feature or "—",
                    body="\n".join(self._body_lines),
                    tokens=tuple(dict.fromkeys(self._tokens)),
                )
            )
        self._feature = ""
        self._body_lines = []
        self._tokens = []

    def _register_token(self) -> None:
        # The token is the text between the two most recent backtick marks.
        joined = "".join(self._line_buf)
        inner = joined.rsplit("`", 2)
        if len(inner) == 3:
            token = normalize_token(inner[1])
            if token:
                self._tokens.append(token)

    def close(self) -> None:
        super().close()
        self._flush_entry()


def is_grep_token(token: str) -> bool:
    """Only namespaced/parameter-shaped tokens are worth grepping.

    Release notes routinely mention ``true``, ``high``, ``close`` … — bare
    words that match nearly every Pine file and would fire the affected-gate
    on every single delta, turning the issue into noise. Dotted builtins
    (``array.sort``) and underscored parameters (``sort_field``) are the
    tokens that actually locate affected code. The bare words still appear
    in the report body, just ungrepped.
    """
    return "." in token or "_" in token


def normalize_token(raw: str) -> str | None:
    """``array.sort()`` -> ``array.sort``; drop prose that is not an identifier."""
    token = raw.strip().strip("\"'").removesuffix("()").strip()
    if len(token) >= 3 and _TOKEN_RE.match(token):
        return token
    return None


def extract_entries(html_text: str) -> list[Entry]:
    parser = _NotesParser()
    parser.feed(html_text)
    parser.close()
    # (month, feature) must be UNIQUE or the diff false-alarms forever: with a
    # duplicate key the snapshot dict keeps only the last body, so the first
    # occurrence would compare unequal on every single run. Seen once on the
    # real page (February 2014 has two h4-less blocks split by a feature).
    seen: dict[tuple[str, str], int] = {}
    unique: list[Entry] = []
    for entry in parser.entries:
        count = seen.get(entry.key, 0) + 1
        seen[entry.key] = count
        if count > 1:
            entry = Entry(
                month=entry.month,
                feature=f"{entry.feature} ({count})",
                body=entry.body,
                tokens=entry.tokens,
            )
        unique.append(entry)
    return unique


# -- snapshot ---------------------------------------------------------------
_SNAPSHOT_HEADER = (
    "# TradingView Pine Script release notes — snapshot\n"
    "\n"
    "<!-- Written by scripts/pine_release_notes_watch.py — do NOT edit by hand.\n"
    f"     Source: {RELEASE_NOTES_URL}\n"
    "     Diff unit: a (month, feature) entry. A key missing here is NEW, a\n"
    "     differing body is CHANGED; the weekly pine-release-notes-watch\n"
    "     workflow raises a PR (snapshot currency) and an issue (live-surface\n"
    "     hits) from that delta. -->\n"
)


def render_snapshot(entries: list[Entry]) -> str:
    lines: list[str] = [_SNAPSHOT_HEADER]
    month = None
    for entry in entries:
        if entry.month != month:
            month = entry.month
            lines.append(f"\n## {month}\n")
        lines.append(f"### {entry.feature}\n")
        lines.append(entry.body + "\n")
    return "\n".join(lines)


def parse_snapshot(text: str) -> dict[tuple[str, str], str]:
    """Snapshot markdown -> ``{(month, feature): normalized body}``."""
    result: dict[tuple[str, str], str] = {}
    month = ""
    feature = ""
    body: list[str] = []

    def flush() -> None:
        if feature:
            result[(month, feature)] = " ".join(" ".join(body).split())

    for line in text.splitlines():
        if line.startswith("## "):
            flush()
            month, feature, body = line[3:].strip(), "", []
        elif line.startswith("### "):
            flush()
            feature, body = line[4:].strip(), []
        elif line.startswith(("# ", "<!--")) or line.strip().endswith("-->"):
            continue
        elif feature:
            body.append(line)
    flush()
    return result


@dataclass(frozen=True)
class Delta:
    new: tuple[Entry, ...]
    changed: tuple[Entry, ...]

    @property
    def empty(self) -> bool:
        return not self.new and not self.changed


def diff_entries(snapshot: dict[tuple[str, str], str], current: list[Entry]) -> Delta:
    new: list[Entry] = []
    changed: list[Entry] = []
    for entry in current:
        old_body = snapshot.get(entry.key)
        if old_body is None:
            new.append(entry)
        elif old_body != entry.normalized_body:
            changed.append(entry)
    return Delta(new=tuple(new), changed=tuple(changed))


# -- live Pine surface ------------------------------------------------------
def live_pine_files(repo_root: Path) -> list[Path]:
    """Every ``*.pine`` that ships to TradingView users.

    Excludes ``tests/`` (fixtures/probe assets) and ``pine/legacy/``
    (imported historical scripts, never published).
    """
    files: list[Path] = []
    for path in sorted(repo_root.rglob("*.pine")):
        parts = path.relative_to(repo_root).parts
        if parts[0] in _EXCLUDED_TOP_DIRS:
            continue
        if parts[0] == "pine" and _EXCLUDED_PINE_SUBDIR in parts[1:]:
            continue
        files.append(path)
    return files


def grep_tokens(tokens: set[str], files: list[Path], repo_root: Path) -> dict[str, list[str]]:
    """``token -> ["rel/path.pine:lineno", ...]`` word-boundary matches."""
    patterns = {token: re.compile(r"(?<![A-Za-z0-9_.])" + re.escape(token) + r"(?![A-Za-z0-9_])") for token in tokens}
    hits: dict[str, list[str]] = {}
    for path in files:
        rel = path.relative_to(repo_root).as_posix()
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for token, pattern in patterns.items():
                if pattern.search(line):
                    hits.setdefault(token, []).append(f"{rel}:{lineno}")
    return hits


# -- report -----------------------------------------------------------------
def render_report(delta: Delta, hits: dict[str, list[str]]) -> str:
    lines = [
        f"# Pine release-notes delta — {len(delta.new)} new, {len(delta.changed)} changed",
        "",
        f"Source: {RELEASE_NOTES_URL}",
        f"Snapshot: `{DEFAULT_SNAPSHOT}`",
    ]
    for label, entries in (("NEW", delta.new), ("CHANGED", delta.changed)):
        for entry in entries:
            lines += ["", f"## {label} — {entry.month} — {entry.feature}", "", entry.body]
            entry_hits = {t: hits[t] for t in entry.tokens if hits.get(t)}
            if entry_hits:
                lines += ["", "**Hits in the live Pine surface:**"]
                for token, sites in sorted(entry_hits.items()):
                    shown = ", ".join(f"`{s}`" for s in sites[:10])
                    more = f" (+{len(sites) - 10} more)" if len(sites) > 10 else ""
                    lines.append(f"- `{token}` — {len(sites)} site(s): {shown}{more}")
            else:
                lines += ["", "**Hits in the live Pine surface:** none"]
    lines.append("")
    return "\n".join(lines)


# -- IO ---------------------------------------------------------------------
def fetch_release_notes(url: str = RELEASE_NOTES_URL) -> str:
    """GET the release-notes page; retry transient transport errors."""
    last_error: OSError | None = None
    for attempt in range(1, _FETCH_ATTEMPTS + 1):
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "skipp-algo pine-release-notes-watch",
                    "Accept-Encoding": "identity",
                },
                method="GET",
            )
            with urllib.request.urlopen(request, timeout=_FETCH_TIMEOUT_S) as response:  # nosec B310 - fixed https URL
                raw = response.read()
            if raw[:2] == b"\x1f\x8b":  # server ignored Accept-Encoding
                raw = gzip.decompress(raw)
            return raw.decode("utf-8")
        except OSError as error:
            last_error = error
            if attempt < _FETCH_ATTEMPTS:
                time.sleep(5 * attempt)
    raise SystemExit(f"fetch failed after {_FETCH_ATTEMPTS} attempts: {last_error}")


# -- main -------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--html", type=Path, help="parse this file instead of fetching")
    parser.add_argument("--snapshot", type=Path, default=None)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--report", type=Path, help="write a markdown delta report here")
    parser.add_argument("--update", action="store_true", help="rewrite the snapshot to the current page")
    parser.add_argument("--seed", action="store_true", help="allow creating a missing snapshot")
    parser.add_argument("--min-entries", type=int, default=_MIN_ENTRIES, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    repo_root = (args.repo_root or Path(__file__).resolve().parents[1]).resolve()
    snapshot_path = args.snapshot or repo_root / DEFAULT_SNAPSHOT

    html_text = args.html.read_text(encoding="utf-8") if args.html else fetch_release_notes()
    entries = extract_entries(html_text)
    months = {entry.month for entry in entries}
    if len(entries) < args.min_entries or len(months) < _MIN_MONTHS:
        print(
            f"extraction sanity failed: {len(entries)} entries / {len(months)} months "
            f"(floors: {args.min_entries}/{_MIN_MONTHS}) — page redesign? Refusing to "
            "diff against a broken extraction.",
            file=sys.stderr,
        )
        return 1

    if not snapshot_path.is_file():
        if not args.seed:
            print(
                f"snapshot missing: {snapshot_path} (run with --seed once)",
                file=sys.stderr,
            )
            return 1
        atomic_write_text(render_snapshot(entries), snapshot_path)
        print(f"seeded {snapshot_path} with {len(entries)} entries")
        print("changed=false\nnew_entries=0\nchanged_entries=0\naffected_files=0")
        return 0

    snapshot = parse_snapshot(snapshot_path.read_text(encoding="utf-8"))
    delta = diff_entries(snapshot, entries)

    hits: dict[str, list[str]] = {}
    if not delta.empty:
        tokens = {
            t for e in (*delta.new, *delta.changed) for t in e.tokens if is_grep_token(t)
        }
        hits = grep_tokens(tokens, live_pine_files(repo_root), repo_root)
        if args.report:
            atomic_write_text(render_report(delta, hits), args.report)
        if args.update:
            atomic_write_text(render_snapshot(entries), snapshot_path)

    affected = {site.rsplit(":", 1)[0] for sites in hits.values() for site in sites}
    print(
        f"changed={'true' if not delta.empty else 'false'}\n"
        f"new_entries={len(delta.new)}\n"
        f"changed_entries={len(delta.changed)}\n"
        f"affected_files={len(affected)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
