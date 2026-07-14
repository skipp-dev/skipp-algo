"""Enforce the Pine script naming convention (SSOT: docs/PINE_SCRIPT_NAMING.md).

The naming drifted into chaos once — the engine existed under three disagreeing
names (saved name, code title, legend label) plus a duplicate copy — which made
the dashboard impossible to wire. This test pins the one surface the repo can
assert: the ``indicator()/strategy()`` code title of each main product. The
saved name and legend label are kept equal to it by the operator checklist in
the doc.

Owner of the rule: @preuss_steffen (see the doc's header). This test only
enforces the rule; it does not define it.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
NAMING_DOC = REPO_ROOT / "docs" / "PINE_SCRIPT_NAMING.md"

#: The main long-dip product family: repo file -> canonical code title.
#: These MUST share the "SMC Long-Dip" prefix so the indicator and its strategy
#: read as one family.
CANONICAL_MAIN_PRODUCTS: dict[str, str] = {
    "SMC_Core_Engine.pine": "SMC Long-Dip Suite v7",
    "SMC_Long_Strategy.pine": "SMC Long-Dip Strategy v7",
    "SMC_Dashboard.pine": "SMC Long-Dip Dashboard v7",
    "SMC_Mobile_Dashboard.pine": "SMC Long-Dip Mobile v7",
}

FAMILY_PREFIX = "SMC Long-Dip "

#: Tier 2 (docs/PINE_SCRIPT_NAMING.md): the shorttitle is a fixed, systematic
#: abbreviation "LD <Component>7" — never a third free-form name. TradingView
#: hard-limits it to 10 chars, so it cannot equal the Tier-1 title.
CANONICAL_SHORTTITLES: dict[str, str] = {
    "SMC_Core_Engine.pine": "LD Suite7",
    "SMC_Dashboard.pine": "LD Dash7",
    "SMC_Mobile_Dashboard.pine": "LD Mobile7",
    # SMC_Long_Strategy.pine: strategy() omits the shorttitle.
}

_TITLE_RE = re.compile(r'^\s*(?:indicator|strategy)\(\s*"([^"]*)"', re.MULTILINE)
_SHORTTITLE_RE = re.compile(
    r'^\s*(?:indicator|strategy)\(\s*"[^"]*"\s*,\s*"([^"]*)"', re.MULTILINE
)


def _code_title(pine_file: str) -> str:
    source = (REPO_ROOT / pine_file).read_text(encoding="utf-8")
    match = _TITLE_RE.search(source)
    assert match, f"{pine_file}: no indicator()/strategy() title found"
    return match.group(1)


def _shorttitle(pine_file: str) -> str | None:
    source = (REPO_ROOT / pine_file).read_text(encoding="utf-8")
    match = _SHORTTITLE_RE.search(source)
    return match.group(1) if match else None


def test_main_products_have_canonical_titles() -> None:
    """Each main product's code title must equal its canonical name."""
    problems: list[str] = []
    for pine_file, canonical in sorted(CANONICAL_MAIN_PRODUCTS.items()):
        actual = _code_title(pine_file)
        if actual != canonical:
            problems.append(f"{pine_file}: title {actual!r} != canonical {canonical!r}")
    assert problems == [], "\n".join(problems)


def test_main_product_family_shares_prefix() -> None:
    """Indicator and strategy (and the dashboards) read as one family."""
    for pine_file in sorted(CANONICAL_MAIN_PRODUCTS):
        title = _code_title(pine_file)
        assert title.startswith(FAMILY_PREFIX), (
            f"{pine_file}: title {title!r} must start with {FAMILY_PREFIX!r}"
        )


def test_no_duplicate_titles_across_root_scripts() -> None:
    """Exactly one script per product title — no duplicate copies under a
    different file/name (the 'SMC Core' / 'SMC Core Engine' duplicate was the
    original root of the wiring chaos)."""
    seen: dict[str, str] = {}
    dupes: list[str] = []
    for path in sorted(REPO_ROOT.glob("*.pine")):
        if path.name.startswith("test_"):
            continue
        match = _TITLE_RE.search(path.read_text(encoding="utf-8"))
        if not match:
            continue
        title = match.group(1)
        if title in seen:
            dupes.append(f"title {title!r} used by both {seen[title]} and {path.name}")
        else:
            seen[title] = path.name
    assert dupes == [], "\n".join(dupes)


def test_main_products_have_canonical_shorttitles() -> None:
    """Tier 2: each main product's shorttitle is the systematic 'LD <Component>7'
    abbreviation and within TradingView's 10-char limit."""
    problems: list[str] = []
    for pine_file, expected in sorted(CANONICAL_SHORTTITLES.items()):
        actual = _shorttitle(pine_file)
        if actual != expected:
            problems.append(f"{pine_file}: shorttitle {actual!r} != canonical {expected!r}")
        elif len(expected) > 10:
            problems.append(f"{pine_file}: shorttitle {expected!r} exceeds 10 chars")
    assert problems == [], "\n".join(problems)


def test_naming_doc_is_the_owner_locked_ssot() -> None:
    """The convention lives in one owner-locked document, and it lists every
    canonical name so the doc and this test cannot drift apart."""
    assert NAMING_DOC.exists(), "docs/PINE_SCRIPT_NAMING.md must exist"
    doc = NAMING_DOC.read_text(encoding="utf-8")
    assert "OWNER: @preuss_steffen" in doc, "doc must carry the owner lock"
    missing = [c for c in CANONICAL_MAIN_PRODUCTS.values() if c not in doc]
    assert missing == [], f"naming doc is missing canonical names: {missing}"
    # The doc must spell out the three-tier distinction that keeps the file
    # name, the user-visible identity, and the shorttitle from being conflated.
    for tier in ("Tier 1", "Tier 2", "Tier 3"):
        assert tier in doc, f"naming doc must document {tier}"
