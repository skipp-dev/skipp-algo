#!/usr/bin/env python3
"""Weekly watch on TradingView's automation house rule (ADR-0034).

The rule "any kind of automatization ... are not allowed. All our features
are for manual use only." lives in the Help-Center article 43000674726, not
in the Terms of Use full text and not on /house-rules/ (that page is a JS
shell; measured 2026-08-31). ADR-0034 accepts the onboarding-automation risk
on the basis of exactly this rule -- so a change to the article must RING.

Deliberately different from pine_release_notes_watch: there is NO --update in
the workflow path. A change fails the job (exit 2) and stays red until the
snapshot is updated together with the ADR-0034 re-evaluation. A watcher that
quietly refreshed its own snapshot would erase the one event it exists for.

Exit codes: 0 unchanged, 2 article changed (diff printed), 3 extraction or
sanity failure (page redesign, fetch trouble) -- both non-zero paths fail the
job; red is the alarm, never a silent skip.
"""

from __future__ import annotations

import argparse
import difflib
import gzip
import sys
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import ClassVar

from scripts.smc_atomic_write import atomic_write_text

HOUSE_RULES_URL = (
    "https://www.tradingview.com/support/solutions/"
    "43000674726-why-is-my-account-banned-due-to-suspicious-activity/"
)
DEFAULT_SNAPSHOT = "docs/tv_house_rules_snapshot.md"
_FETCH_ATTEMPTS = 3
_FETCH_TIMEOUT_S = 30
# Below either floor the extraction is broken (help-center redesign), no
# matter what came back: the measured article carries a dozen paragraphs.
_MIN_PARAGRAPHS = 5
_MIN_CHARS = 500
_TAG = "[house-rules-watch]"


class SanityError(RuntimeError):
    """Extraction returned too little to be the real article."""


class _ArticleParser(HTMLParser):
    """Collect the visible ``p``/``li`` texts of the article.

    Capture arms at the first ``h1`` (the article title) and disarms at
    ``<footer>``; ``script``/``style``/``svg``/``noscript`` are skipped, which
    also drops the embedded JSON state copy of the text (measured: the rule
    sentence appears twice in the raw HTML, once in markup, once in state).
    """

    _BODY_TAGS: ClassVar[frozenset[str]] = frozenset({"p", "li", "h1", "h2", "h3"})
    _SKIP_TAGS: ClassVar[frozenset[str]] = frozenset({"script", "style", "svg", "noscript"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.paragraphs: list[str] = []
        self._armed = False
        self._done = False
        self._skip_depth = 0
        self._buf: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if self._done:
            return
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag == "footer" and self._armed:
            self._done = True
            return
        if self._skip_depth:
            return
        if tag == "h1":
            self._armed = True
        if self._armed and tag in self._BODY_TAGS:
            self._buf = []

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._buf is not None and tag in self._BODY_TAGS:
            text = " ".join(" ".join(self._buf).split())
            if text:
                self.paragraphs.append(text)
            self._buf = None

    def handle_data(self, data: str) -> None:
        if self._buf is not None and not self._skip_depth and not self._done:
            self._buf.append(data)


def extract_article(html: str) -> list[str]:
    parser = _ArticleParser()
    parser.feed(html)
    paragraphs = parser.paragraphs
    if len(paragraphs) < _MIN_PARAGRAPHS or sum(len(p) for p in paragraphs) < _MIN_CHARS:
        raise SanityError(
            f"extraction returned {len(paragraphs)} paragraph(s), "
            f"{sum(len(p) for p in paragraphs)} chars -- page redesign or fetch trouble"
        )
    return paragraphs


def render_snapshot(paragraphs: list[str]) -> str:
    lines = [
        "# TradingView house-rules snapshot (ADR-0034)",
        "#",
        f"# Source: {HOUSE_RULES_URL}",
        "# Updated DELIBERATELY together with an ADR-0034 re-evaluation --",
        "# never by the weekly job, whose only change-path is a red run.",
        "",
    ]
    lines += [f"- {p}" for p in paragraphs]
    return "\n".join(lines) + "\n"


def fetch_house_rules(url: str = HOUSE_RULES_URL) -> str:
    last_error: OSError | None = None
    for _attempt in range(1, _FETCH_ATTEMPTS + 1):
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "skipp-algo house-rules-watch",
                    "Accept-Encoding": "identity",
                },
                method="GET",
            )
            with urllib.request.urlopen(request, timeout=_FETCH_TIMEOUT_S) as response:  # nosec B310
                raw = response.read()
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            return raw.decode("utf-8", errors="replace")
        except OSError as error:
            last_error = error
    raise RuntimeError(f"fetch failed after {_FETCH_ATTEMPTS} attempts: {last_error}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", default=DEFAULT_SNAPSHOT)
    parser.add_argument("--from-file", help="read the page from a file instead of the network")
    parser.add_argument(
        "--update",
        action="store_true",
        help="write the snapshot (seeding / deliberate ADR-0034 re-evaluation only)",
    )
    args = parser.parse_args(argv)

    if args.from_file:
        html = Path(args.from_file).read_text(encoding="utf-8", errors="replace")
    else:
        html = fetch_house_rules()

    try:
        paragraphs = extract_article(html)
    except SanityError as error:
        print(f"{_TAG} broken: {error}")
        return 3

    rendered = render_snapshot(paragraphs)
    snapshot_path = Path(args.snapshot)
    committed = snapshot_path.read_text(encoding="utf-8") if snapshot_path.exists() else ""

    if args.update:
        atomic_write_text(rendered, snapshot_path)

    if rendered == committed:
        print(f"{_TAG} unchanged paragraphs={len(paragraphs)}")
        return 0

    print(f"{_TAG} changed paragraphs={len(paragraphs)}")
    diff = difflib.unified_diff(
        committed.splitlines(), rendered.splitlines(), "snapshot", "live", lineterm=""
    )
    for line in diff:
        print(line)
    print(
        f"{_TAG} a house-rules change re-opens ADR-0034; update "
        f"{args.snapshot} only together with that re-evaluation"
    )
    return 0 if args.update else 2


if __name__ == "__main__":
    sys.exit(main())
