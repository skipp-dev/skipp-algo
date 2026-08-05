"""Ledger for repo-scoped universal claims — sentences about the WHOLE repository.

A sentence of the form "nothing in the repo does X" is not a remark. It is a claim
about a *set*, and the set is every file here. It is settled by a run over that set,
never by reading the part of it that was easy to find.

2026-08-05 is what this costs when it goes wrong. The docstring of
``scripts/hold_r1_attested_sources.py`` said:

    Nothing in the repo requires consumers to share one pin -- verified 2026-08-04

The verification read two drift *scripts* and generalised to the whole repo without
running the pytest suite. Three tests did require it. The hold shipped, produced its
first real version lag, and every push failed until it was found the next morning
(#4472). The sentence was wrong in its *scope*, not in its wording — and no amount of
re-reading those two scripts could have revealed that.

So each such sentence is registered here with the status of its proof:

``PROVEN``      the population and the pattern are recorded, and the tests below
                RE-RUN the scan. The claim is executable, not prose about prose.
``UNPROVEN``    registered as a hypothesis, with what would settle it. Its count may
                not grow silently, but nobody is forced to resolve a legacy comment
                today. Prose in this state must not read as a finding.
``HISTORICAL``  a past-tense statement about a moment ("no producer *was* emitting"),
                which a scan of today's tree cannot confirm or refute.
``RETRACTED``   a claim withdrawn in place, kept so the correction stays readable.

The counts are counts, not line anchors: a comment that moves does not drift the pin
(same reason the noqa ledger counts per file).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# "nothing in the repo", "no producer in the repo", "nichts im Repo",
# "repo-wide, nothing". Deliberately narrow: a local negative ("this value is never
# read here") is a remark about one function and needs no ledger entry.
_CLAIM_RE = re.compile(
    r"\b(?:nothing|no\s+\w+)\s+(?:else\s+)?in\s+the\s+repo\b"
    r"|\bnichts\s+im\s+repo\b"
    r"|\brepo-wide[,:]?\s+(?:nothing|no)\b",
    re.IGNORECASE,
)

_SCAN_EXT = frozenset({".py", ".sh", ".yml", ".yaml", ".ts"})
_SKIP_PARTS = frozenset({".venv", "node_modules", ".git", "fixtures"})

# This file quotes the very sentences it collects, so scanning it would report its own
# documentation as unregistered claims. The cost of the exemption: a repo-scoped claim
# written INSIDE this file is invisible to the collector. Do not write one here.
_SELF = "tests/test_repo_scoped_claim_ledger.py"

PROVEN, UNPROVEN, HISTORICAL, RETRACTED = "PROVEN", "UNPROVEN", "HISTORICAL", "RETRACTED"

# file -> (claim lines in it, status, population, pattern, expected hits, note)
_LEDGER: dict[str, dict[str, object]] = {
    "smc_core/fvg_quality.py": {
        "count": 1,
        "status": PROVEN,
        "population": "every source file in the repo (the extensions scanned below)",
        # The claim is that no code produces the tier value "INSUFFICIENT". The only
        # occurrence of the quoted literal anywhere is the docstring making the claim.
        # `INSUFFICIENT_SYMBOL_BREADTH` and friends in release_policy.py are different
        # constants and must not count -- hence the quoted form, not the bare word.
        "pattern": r'"INSUFFICIENT"',
        "expected_hits": 1,
        "note": "Re-run below. A producer appearing anywhere turns this red.",
    },
    "scripts/smc_bus_manifest.py": {
        "count": 1,
        "status": UNPROVEN,
        "population": "every consumer of the Session Context script's outputs",
        "note": (
            "Grep does not settle it: the identifier `session_context` appears in 78 "
            "files, almost all of them unrelated to that script's outputs. What would "
            "settle it is the R5 gate's consumer map. Reads as a decision record "
            "(rollout_state = not_deployed BY DECISION), not as a gate input, so it is "
            "carried rather than resolved."
        ),
    },
    "tests/test_c12_trigger_e2e.py": {
        "count": 1,
        "status": HISTORICAL,
        "note": (
            "Past tense: 'no producer in the repo WAS actually emitting that block', "
            "about the 2026-04-27 deep review. The gap it describes was closed by the "
            "test it introduces; a scan of today's tree cannot speak to 2026-04."
        ),
    },
    "scripts/hold_r1_attested_sources.py": {
        "count": 1,
        "status": RETRACTED,
        "note": (
            "The CORRECTION block quoting the claim that turned `main` red on "
            "2026-08-05. Kept in place, naming the three tests that refuted it (#4472)."
        ),
    },
}

_FOUR_QUESTIONS = """
Before this sentence may exist, answer all four with a number from a command:
  1. Which set is it about?  (name it exactly: "every pytest test", not "the tests")
  2. How large is that set?
  3. How much of it did you actually run over?
  4. Is (3) < (2)?  Then it is a hypothesis, not a finding.
Then register it in tests/test_repo_scoped_claim_ledger.py::_LEDGER with the status
of its proof. A PROVEN entry records the pattern and hit count and is re-run here.
"""


def _iter_source_files() -> list[Path]:
    return [
        path
        for path in sorted(REPO_ROOT.rglob("*"))
        if path.suffix in _SCAN_EXT
        and path.is_file()
        and not any(part in _SKIP_PARTS for part in path.parts)
    ]


def _scan(pattern: re.Pattern[str]) -> list[tuple[str, int, str]]:
    """Returns [(repo-relative path, line number, line)] for every match."""
    hits: list[tuple[str, int, str]] = []
    for path in _iter_source_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel == _SELF:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                hits.append((rel, lineno, line.strip()))
    return hits


def test_the_collector_still_finds_the_registered_claims() -> None:
    """Non-vacuity: a collector that finds nothing would let every test below pass.

    Checked first and separately, because every other assertion here is a statement
    about a set this function produces.
    """
    found = _scan(_CLAIM_RE)
    assert found, (
        "the repo-scoped-claim collector found NOTHING. Every assertion below is then "
        "empty. Either the regex stopped matching, _SCAN_EXT lost an extension, or "
        "_SKIP_PARTS grew too far."
    )
    assert len(_LEDGER) >= 3, "the ledger itself is nearly empty -- was it truncated?"


def test_every_repo_scoped_claim_is_registered() -> None:
    """Pin: no sentence about the whole repo enters the tree unregistered."""
    counted: dict[str, int] = {}
    lines: dict[str, list[str]] = {}
    for rel, lineno, line in _scan(_CLAIM_RE):
        counted[rel] = counted.get(rel, 0) + 1
        lines.setdefault(rel, []).append(f"{rel}:{lineno}  {line[:100]}")

    registered = {rel: int(entry["count"]) for rel, entry in _LEDGER.items()}  # type: ignore[arg-type]

    new_files = sorted(set(counted) - set(registered))
    assert not new_files, (
        "unregistered repo-scoped claim(s) in:\n  "
        + "\n  ".join(line for rel in new_files for line in lines[rel])
        + "\n"
        + _FOUR_QUESTIONS
    )

    grown = sorted(rel for rel in counted if counted[rel] > registered[rel])
    assert not grown, (
        "more repo-scoped claims than registered in:\n  "
        + "\n  ".join(f"{rel}: {counted[rel]} found, {registered[rel]} registered" for rel in grown)
        + "\n"
        + _FOUR_QUESTIONS
    )

    gone = sorted(rel for rel in registered if counted.get(rel, 0) < registered[rel])
    assert not gone, (
        "fewer repo-scoped claims than registered -- lower or drop the entries for:\n  "
        + "\n  ".join(f"{rel}: {counted.get(rel, 0)} found, {registered[rel]} registered" for rel in gone)
        + "\nA ledger that outlives its claims makes the next reader trust a pin that "
        "guards nothing."
    )


def test_a_proven_claim_records_how_it_was_proven() -> None:
    """A PROVEN entry without a population and a pattern is an UNPROVEN entry with a
    better label. That relabelling is exactly the 2026-08-05 failure."""
    proven = {rel: e for rel, e in _LEDGER.items() if e["status"] == PROVEN}
    assert proven, "no PROVEN entries -- the re-run test below would assert nothing"
    for rel, entry in sorted(proven.items()):
        assert entry.get("population"), f"{rel}: PROVEN without naming the population"
        assert entry.get("pattern"), f"{rel}: PROVEN without a re-runnable pattern"
        assert isinstance(entry.get("expected_hits"), int), f"{rel}: PROVEN without a hit count"


def test_every_proven_claim_still_holds() -> None:
    """Re-run each PROVEN claim's scan. This is the half that makes the ledger a gate
    rather than a comment: the day something produces the value the docstring says
    nothing produces, this goes red."""
    for rel, entry in sorted(_LEDGER.items()):
        if entry["status"] != PROVEN:
            continue
        hits = _scan(re.compile(str(entry["pattern"])))
        assert len(hits) == entry["expected_hits"], (
            f"{rel}: the claim recorded {entry['expected_hits']} hit(s) for "
            f"{entry['pattern']!r} across {entry['population']}, but the tree now has "
            f"{len(hits)}:\n  " + "\n  ".join(f"{f}:{n}  {ln[:100]}" for f, n, ln in hits)
        )


def test_an_unsettled_claim_says_what_would_settle_it() -> None:
    """UNPROVEN/HISTORICAL/RETRACTED carry their reason, so the next reader inherits
    the state of the proof instead of re-deriving it."""
    for rel, entry in sorted(_LEDGER.items()):
        assert entry["status"] in {PROVEN, UNPROVEN, HISTORICAL, RETRACTED}, f"{rel}: unknown status"
        if entry["status"] != PROVEN:
            note = str(entry.get("note", ""))
            assert len(note) > 40, f"{rel}: {entry['status']} without a usable note"
