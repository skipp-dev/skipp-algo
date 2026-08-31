"""Enforce the Pine script naming convention (SSOT: docs/PINE_SCRIPT_NAMING.md).

The naming drifted into chaos once — the engine existed under several disagreeing
names (saved name, code title, legend label) plus a duplicate copy — which made
the dashboard impossible to wire. The rule: one name shown everywhere — the
``indicator()/strategy()`` title == TV saved name == legend display — achieved by
omitting the shorttitle (so TradingView shows the full title) and keeping the
version out of the name (the visible version is TradingView's own save revision).

Owner of the rule: @preuss_steffen (see the doc's header). This test only
enforces the rule; it does not define it.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
NAMING_DOC = REPO_ROOT / "docs" / "PINE_SCRIPT_NAMING.md"

#: The main long-dip product family: repo file -> canonical name (== code title
#: == TV saved name == legend display). No version string, no shorttitle. These
#: MUST share the "SMC Long-Dip" prefix so the indicator and its strategy read
#: as one family.
CANONICAL_MAIN_PRODUCTS: dict[str, str] = {
    "SMC_Long_Dip_Suite.pine": "SMC Long-Dip Suite",
    "SMC_Long_Dip_Strategy.pine": "SMC Long-Dip Strategy",
    "SMC_Long_Dip_Mobile.pine": "SMC Long-Dip Mobile",
}

#: Companion products (owner decision 2026-08-31): user-facing products that
#: carry their OWN product name and are deliberately outside FAMILY_PREFIX.
#: docs/SMC_PRODUCT_IDENTITY.md sells the Pro companion under its own name, and
#: the prefix rule -- written for the indicator and its strategy -- was never
#: meant to bind it. Every OTHER guarantee still applies: title == filename,
#: no shorttitle, no version string, no duplicate title, listed in the doc.
#:
#: This is the exemption, not a loophole. The family prefix exists so the suite
#: and its strategy read as one product; a separately sold companion is a
#: different promise, and forcing the prefix on it is what pushed its product
#: name out of the code in the first place.
CANONICAL_COMPANION_PRODUCTS: dict[str, str] = {
    "SMC_Decision_Board.pine": "SMC Decision Board",
}

#: Every canonical product, whichever class it belongs to.
CANONICAL_PRODUCTS: dict[str, str] = {
    **CANONICAL_MAIN_PRODUCTS,
    **CANONICAL_COMPANION_PRODUCTS,
}

FAMILY_PREFIX = "SMC Long-Dip "

_TITLE_RE = re.compile(r'^\s*(?:indicator|strategy)\(\s*"([^"]*)"', re.MULTILINE)
#: A second positional string literal right after the title == a shorttitle.
_SHORTTITLE_RE = re.compile(
    r'^\s*(?:indicator|strategy)\(\s*"[^"]*"\s*,\s*"[^"]*"', re.MULTILINE
)
#: Version strings the name must not carry (the visible version is TV's save rev).
_VERSION_IN_NAME_RE = re.compile(r"\bv\d+\b", re.IGNORECASE)


def _code_title(pine_file: str) -> str:
    source = (REPO_ROOT / pine_file).read_text(encoding="utf-8")
    match = _TITLE_RE.search(source)
    assert match, f"{pine_file}: no indicator()/strategy() title found"
    return match.group(1)


def _all_root_products() -> list[Path]:
    return [
        p
        for p in sorted(REPO_ROOT.glob("*.pine"))
        if not p.name.startswith("test_")
    ]


def _title_to_filename(title: str) -> str:
    """Tier-3 transliteration rule (docs/PINE_SCRIPT_NAMING.md): '&' -> 'and',
    then every space and hyphen -> underscore (all-underscore style, no hyphens)."""
    return title.replace("&", "and").replace(" ", "_").replace("-", "_") + ".pine"


def test_root_product_filenames_match_their_titles() -> None:
    """Tier 3: the repo file name is the name in filename form, so there is no
    fourth identifier to drift (the SMC_Core_Engine.pine vs 'SMC Long-Dip Suite'
    mismatch was itself a source of confusion)."""
    problems: list[str] = []
    for path in _all_root_products():
        expected = _title_to_filename(_code_title(path.name))
        if path.name != expected:
            problems.append(f"{path.name}: filename must be {expected!r} to match its title")
    assert problems == [], "\n".join(problems)


def test_main_products_have_canonical_titles() -> None:
    """Each main product's code title must equal its canonical name."""
    problems: list[str] = []
    for pine_file, canonical in sorted(CANONICAL_MAIN_PRODUCTS.items()):
        actual = _code_title(pine_file)
        if actual != canonical:
            problems.append(f"{pine_file}: title {actual!r} != canonical {canonical!r}")
    assert problems == [], "\n".join(problems)


def test_main_product_family_shares_prefix() -> None:
    """Indicator and strategy read as one family. Companions are exempt by
    owner decision (2026-08-31) — see CANONICAL_COMPANION_PRODUCTS."""
    for pine_file in sorted(CANONICAL_MAIN_PRODUCTS):
        title = _code_title(pine_file)
        assert title.startswith(FAMILY_PREFIX), (
            f"{pine_file}: title {title!r} must start with {FAMILY_PREFIX!r}"
        )


def test_companion_products_have_canonical_titles() -> None:
    """A companion is exempt from the family prefix and from NOTHING else."""
    problems: list[str] = []
    for pine_file, canonical in sorted(CANONICAL_COMPANION_PRODUCTS.items()):
        actual = _code_title(pine_file)
        if actual != canonical:
            problems.append(f"{pine_file}: title {actual!r} != canonical {canonical!r}")
    assert problems == [], "\n".join(problems)


def test_no_product_is_declared_in_both_classes() -> None:
    """A file in both maps would satisfy the prefix rule and be exempt from it
    at the same time — the exemption must be a decision, not an accident."""
    both = sorted(set(CANONICAL_MAIN_PRODUCTS) & set(CANONICAL_COMPANION_PRODUCTS))
    assert both == [], f"declared as main AND companion: {both}"


def test_every_declared_product_file_exists() -> None:
    """The maps are hand-maintained; a rename that forgets one leaves a ghost
    entry that silently checks nothing (hardcoded lists cannot catch their own
    drift — so at least prove every entry still points at a real file)."""
    missing = [f for f in sorted(CANONICAL_PRODUCTS) if not (REPO_ROOT / f).exists()]
    assert missing == [], f"declared products with no file: {missing}"


def test_no_root_product_has_a_shorttitle() -> None:
    """One name everywhere: no shorttitle, so TradingView shows the full title in
    the legend (title == saved name == display)."""
    problems: list[str] = []
    for path in _all_root_products():
        if _SHORTTITLE_RE.search(path.read_text(encoding="utf-8")):
            problems.append(f"{path.name}: must not declare a shorttitle")
    assert problems == [], "\n".join(problems)


def test_no_version_string_in_root_product_names() -> None:
    """No 'v7'/'v1' in the name — the visible version is TradingView's own
    auto-incrementing save revision, not a manual string."""
    problems: list[str] = []
    for path in _all_root_products():
        match = _TITLE_RE.search(path.read_text(encoding="utf-8"))
        if match and _VERSION_IN_NAME_RE.search(match.group(1)):
            problems.append(f"{path.name}: title {match.group(1)!r} carries a version string")
    assert problems == [], "\n".join(problems)


def test_no_duplicate_titles_across_root_scripts() -> None:
    """Exactly one script per name — no duplicate copies under a different
    file/name (the 'SMC Core' / 'SMC Core Engine' duplicate was the original
    root of the wiring chaos)."""
    seen: dict[str, str] = {}
    dupes: list[str] = []
    for path in _all_root_products():
        match = _TITLE_RE.search(path.read_text(encoding="utf-8"))
        if not match:
            continue
        title = match.group(1)
        if title in seen:
            dupes.append(f"title {title!r} used by both {seen[title]} and {path.name}")
        else:
            seen[title] = path.name
    assert dupes == [], "\n".join(dupes)


def test_naming_doc_is_the_owner_locked_ssot() -> None:
    """The convention lives in one owner-locked document, and it lists every
    canonical name so the doc and this test cannot drift apart."""
    assert NAMING_DOC.exists(), "docs/PINE_SCRIPT_NAMING.md must exist"
    doc = NAMING_DOC.read_text(encoding="utf-8")
    assert "OWNER: @preuss_steffen" in doc, "doc must carry the owner lock"
    missing = [c for c in CANONICAL_PRODUCTS.values() if c not in doc]
    assert missing == [], f"naming doc is missing canonical names: {missing}"
    # The exemption itself must be written down, not only encoded here. Pin the
    # HEADING, not the phrase: the words also occur in the prose above, so a
    # substring check stayed green when the section was renamed away (caught by
    # the mutation probe on 2026-08-31 — the assertion, not the doc, was wrong).
    assert "## Companion products" in doc, (
        "the naming doc must keep the companion-product section that documents the exemption"
    )
