"""Pin: every hand-authored SMC++ library is publishable from the repo.

Background
==========

``scripts/tv_publish_hand_authored_libraries.ts`` is the repo→TV direction of
truth for the ``SMC++/`` set: it topologically orders the libraries, runs each
one's publisher, and repins consumers to the facade-verified version.

Nothing checked that the table was COMPLETE. ``smc_context_engine_private``
existed from bus-v3 phase 3.2a and was simply absent, so the only way to get it
onto TradingView was a manual paste into the Pine Editor — which is how it shipped
CE10132 (a const used as a parameter default) without anyone noticing that the
library had never compiled. A missing row here is invisible: the orchestrator
publishes the nine it knows about and reports success.

These pins make the omission loud instead.

What they do NOT do
-------------------
They do not run a publisher and they do not compile Pine. Publishing is a live
TradingView action behind an authenticated session; compiling is a manual
operator gate. This is an inventory and coherence contract, nothing more.

2026-08-14 (handlib-publisher-dedup): the ten hand-authored publishers were
converted from self-contained ~419-line files into thin descriptor wrappers
over the shared ``runHandLibPublish`` body in
``automation/tradingview/lib/tv_publish_hand_lib.ts``. Several assertions below
used to read a specific wrapper's own source (its hardcoded ``--version``
default, its inline facade-verification logic); those properties now live in
the shared module instead, so the assertions were retargeted at
``SHARED_MODULE`` rather than deleted. Two properties that were themselves
hardcoded-literal snapshots of "the current pin is /5" or "the current
predecessor is /2" became moot by construction once the wrapper stopped
carrying a literal to drift against — see ``test_no_wrapper_freezes_a_library_version``,
which guards against that literal reappearing.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ORCHESTRATOR = REPO_ROOT / "scripts" / "tv_publish_hand_authored_libraries.ts"
SMCPP_DIR = REPO_ROOT / "SMC++"
SHARED_MODULE = REPO_ROOT / "automation" / "tradingview" / "lib" / "tv_publish_hand_lib.ts"

_ENTRY_RE = re.compile(
    r'\{\s*name:\s*"(?P<name>[^"]+)",\s*source:\s*"(?P<source>[^"]+)",\s*'
    r"publisher:\s*(?P<publisher>null|\"[^\"]+\")\s*,?\s*\}"
)


def _hand_libs() -> dict[str, dict[str, str | None]]:
    text = ORCHESTRATOR.read_text(encoding="utf-8")
    block = re.search(
        r"export const HAND_LIBS: HandLib\[\] = \[(?P<body>.*?)\n\];", text, re.DOTALL
    )
    assert block, "HAND_LIBS table not found in the orchestrator"
    out: dict[str, dict[str, str | None]] = {}
    for m in _ENTRY_RE.finditer(block.group("body")):
        pub = m.group("publisher")
        out[m.group("name")] = {
            "source": m.group("source"),
            "publisher": None if pub == "null" else pub.strip('"'),
        }
    assert out, "HAND_LIBS parsed empty — the entry shape changed"
    return out


def _smcpp_libraries() -> dict[str, Path]:
    """Every SMC++/*.pine that declares a Pine ``library(...)`` header."""
    found: dict[str, Path] = {}
    for path in sorted(SMCPP_DIR.glob("*.pine")):
        m = re.search(r'^library\(\s*"(?P<name>[^"]+)"', path.read_text(encoding="utf-8"), re.MULTILINE)
        if m:
            found[m.group("name")] = path
    return found


# Population for the wrapper-shape checks below: the HAND_LIBS table itself,
# never a filesystem glob. `scripts/tv_publish_*_library.ts` matches TWELVE
# files, including tv_publish_micro_library.ts and tv_publish_overlay_library.ts
# — the two GENERATED-library publishers the spec lists as explicit non-goals.
# They keep their publish logic inline and must not be held to wrapper rules
# (`overlay` in particular still carries its own `--version` default). Deriving
# from HAND_LIBS is also what
# automation/tradingview/tests/hand_authored_publisher_facade_authority.test.ts
# does on the TypeScript side, for the same reason.
PUBLISHERS = sorted(
    REPO_ROOT / entry["publisher"]
    for entry in _hand_libs().values()
    if entry["publisher"] is not None
)

_FROZEN_VERSION_RE = re.compile(r'getFlag\(\s*"--(?:version|import-path)"')

# For SHARED_MODULE only (never PUBLISHERS): a getFlag("--version"/"--import-path", ...)
# call is legitimate there — parseArgs uses an EMPTY-string fallback and derives the
# real default from resolveDefaultVersion/consumer pins. What must never come back is
# a non-empty literal fallback, i.e. a frozen default one layer below the wrappers.
_FROZEN_SHARED_DEFAULT_RE = re.compile(
    r'getFlag\(\s*"--(?:version|import-path)"\s*,\s*"[^"]+"\s*\)'
)


def test_every_smcpp_library_is_in_hand_libs() -> None:
    """A library missing from the table can only be published by hand.

    That is exactly how smc_context_engine_private went out with CE10132: it was
    never in this table, so it was never in an ordered publish, so nothing ever
    established that it compiled.
    """
    declared = set(_hand_libs())
    on_disk = set(_smcpp_libraries())
    missing = sorted(on_disk - declared)
    assert not missing, (
        f"SMC++ libraries absent from HAND_LIBS: {missing}\n"
        "They cannot be published or repinned by "
        "scripts/tv_publish_hand_authored_libraries.ts, leaving a manual Pine "
        "Editor paste as the only route to TradingView. Add a row (and a "
        "publisher, or an explicit `publisher: null`)."
    )


def test_hand_libs_has_no_phantom_entries() -> None:
    """The reverse: a row whose source no longer exists would fail mid-publish."""
    on_disk = set(_smcpp_libraries())
    phantom = sorted(set(_hand_libs()) - on_disk)
    assert not phantom, (
        f"HAND_LIBS names libraries with no SMC++ source declaring them: {phantom}"
    )


@pytest.mark.parametrize("name", sorted(_hand_libs()))
def test_hand_lib_source_and_publisher_resolve(name: str) -> None:
    entry = _hand_libs()[name]
    source = REPO_ROOT / str(entry["source"])
    assert source.is_file(), f"{name}: source {entry['source']} does not exist"
    publisher = entry["publisher"]
    if publisher is None:
        # Supported, but it means "cannot republish, will only repin".
        return
    assert (REPO_ROOT / publisher).is_file(), (
        f"{name}: publisher {publisher} does not exist — the orchestrator would "
        "spawn a missing script"
    )


def test_no_wrapper_freezes_a_library_version() -> None:
    """The treadmill this refactor removed must not grow back.

    Pre-refactor, each hand-lib publisher hardcoded its own
    ``--version``/``--import-path`` default. A hardcoded default drifts from
    the checked-in consumer pin the moment that pin advances — the wrapper
    keeps publishing the OLD version until a human edits the constant, which
    is exactly the shape of omission that let smc_context_engine_private ship
    CE10132 unnoticed. The flags themselves stay supported (an operator may
    still pass ``--version``/``--import-path`` explicitly, and the shared
    module derives a live default from ``consumerPins()`` when they are
    absent — see ``resolveDefaultVersion``); only a FROZEN FALLBACK baked
    into a wrapper's own source is the regression this guards against.
    """
    assert PUBLISHERS, "PUBLISHERS is empty — this test would pass vacuously"
    offenders = [
        p.relative_to(REPO_ROOT).as_posix()
        for p in PUBLISHERS
        if _FROZEN_VERSION_RE.search(p.read_text(encoding="utf-8"))
    ]
    assert not offenders, (
        "these publishers froze a library version again: " + ", ".join(offenders)
    )


def test_shared_module_derives_version_instead_of_freezing_it() -> None:
    """The treadmill guard above scans the wrappers; this scans where the logic now lives.

    ``test_no_wrapper_freezes_a_library_version`` iterates ``PUBLISHERS`` — the
    ten thin wrapper files, derived from ``_hand_libs()`` — for a frozen
    ``getFlag("--version"/"--import-path", ...)`` default. It cannot see a
    regression in ``parseArgs``/``resolveDefaultVersion``
    (tv_publish_hand_lib.ts:293-337) themselves, because ``SHARED_MODULE`` is
    deliberately not in that population (see the module docstring above).
    Neither function is referenced by any test in either lane otherwise —
    mutation-proved (final whole-branch review): replacing

        const version = versionExplicit
          ? Number(getFlag("--version", ""))
          : resolveDefaultVersion(descriptor, repoRoot);

    with ``const version = Number(getFlag("--version", "3"));`` — reintroducing
    the exact frozen-default treadmill this refactor removes, one layer below
    the wrappers this file already watches — left the required gate at 29
    passed and the TypeScript guards at 51 passed. Zero signal. This is that
    seat, proved against the same mutation
    (scratchpad/sdd/task-7-mutation-proof-transcript.txt).
    """
    text = SHARED_MODULE.read_text(encoding="utf-8")
    frozen = _FROZEN_SHARED_DEFAULT_RE.search(text)
    assert not frozen, (
        "the shared module froze a literal --version/--import-path default "
        f"again ({frozen.group(0) if frozen else ''}) — this reintroduces the "
        "exact treadmill test_no_wrapper_freezes_a_library_version guards the "
        "wrappers against, just moved into the module every wrapper delegates to"
    )
    assert "resolveDefaultVersion(descriptor, repoRoot)" in text, (
        "parseArgs no longer derives the default --version via "
        "resolveDefaultVersion — a frozen literal could stand in unnoticed, "
        "since neither parseArgs nor resolveDefaultVersion is referenced by "
        "any other test in either lane"
    )


def test_every_hand_lib_publisher_is_a_thin_wrapper() -> None:
    """No wrapper may regrow its own inline publish logic.

    ``fast-gates`` is the ONLY required check on this repo (ADR-0011), and
    this file is what sits inside it — the TypeScript equivalent
    (``hand_authored_publisher_facade_authority.test.ts``'s delegation check)
    runs only in the verification lane. Without a seat *inside* the required
    gate, a wrapper that regrew ``newTradingViewSession(``/
    ``publishPrivateScript(``/``addCurrentScriptToChart(`` inline would leave
    this entire file green: the shared-module assertions above read the
    shared module, not the wrapper; the frozen-version check only looks for
    ``getFlag`` literals; and the descriptor checks only look for
    ``scriptName``/``source`` strings. None of them would notice a wrapper
    that ALSO still carries its own publish path.
    """
    assert PUBLISHERS, "PUBLISHERS is empty — this test would pass vacuously"
    inline_markers = ("newTradingViewSession(", "publishPrivateScript(", "addCurrentScriptToChart(")
    fat = [
        p.relative_to(REPO_ROOT).as_posix()
        for p in PUBLISHERS
        if any(marker in p.read_text(encoding="utf-8") for marker in inline_markers)
    ]
    assert not fat, "these publishers still contain inline publish logic: " + ", ".join(fat)


def test_pin_check_runs_across_every_consumer_from_the_shared_module() -> None:
    """The pin check must scan all repo .pine, not just the core.

    Migrated from a smc_context_engine_private-only test: every hand-lib
    publisher now runs this check via ``verifyHandLibPublishContract`` in the
    shared module, not just the one whose bootstrap motivated it. Two failure
    modes to avoid at once:

    * Requiring a pin at all makes an unpublished library unpublishable — the
      bootstrap deadlock (publishing needs a pin, a pin needs a published
      version). Every hand lib has that shape at first publish.
    * Checking only ``SMC_Long_Dip_Suite.pine`` goes blind exactly when a
      library IS wired through a sibling SMC++ file instead — e.g. the
      planned smc_context_engine_private consumer, ``SMC_Context_Bus.pine``
      (docs/smc-bus-roadmap.md): the Suite would still not pin it, and a
      wrong-version pin on the Bus side would sail through unseen.

    So: zero pins is a legal bootstrap, and every pin that exists — anywhere
    under the repo root or SMC++/ — must name the version being published.
    """
    text = SHARED_MODULE.read_text(encoding="utf-8")

    assert "function consumerPins(" in text, (
        "the cross-consumer pin scan is gone from the shared module; a "
        "core-only check cannot see a sibling-library consumer"
    )
    assert 'path.join(repoRoot, "SMC++")' in text, (
        "the scan no longer covers SMC++/, so a library-to-library pin would "
        "be invisible — it must mirror the surface the orchestrator repins"
    )
    assert re.search(
        r"consumerPins\(cli\.repoRoot, cli\.scriptName\)\s*\.filter\(\s*\n?\s*"
        r"\(pin\) => pin\.version !== cli\.version",
        text,
    ), (
        "the publisher no longer rejects consumer pins naming a version "
        "other than the one being published"
    )
    assert "Consumer pin mismatch" in text, "the mismatch error message is gone"
    assert "if (!coreText.includes(expectedImportLine))" not in text, (
        "the unconditional core-import requirement is back — that "
        "reintroduces the bootstrap deadlock this check exists to avoid"
    )


def test_acceptance_rule_rejects_a_version_below_the_expectation() -> None:
    """A facade-verified version may exceed the expectation but must never fall below it.

    Pre-refactor, engine's AND context_engine's publishers pinned exact
    equality (``exactVersionVerified = facadeVersion === details.version``) —
    measured over the whole population at ``8a8a9b87a``
    (``git show 8a8a9b87a:scripts/tv_publish_*_library.ts``): eight of the
    ten set ``exactVersionVerified = true;`` unconditionally once the facade
    answered, but ``tv_publish_engine_library.ts`` and
    ``tv_publish_context_engine_library.ts`` used this stricter comparison
    instead. For those two, a facade answer naming any version other than
    the exact expectation failed the publish, even one that only advanced
    further than expected. That equality was itself the treadmill this
    refactor removes, and was deliberately relaxed (controller ruling,
    2026-08-14): a facade-verified version is now
    authoritative and MAY exceed the expectation. What must never happen is
    acceptance of a version BELOW the expectation — that means the wrong
    script, or a stale draft, was addressed, not that content changed.
    """
    text = SHARED_MODULE.read_text(encoding="utf-8")
    assert "export function resolveVersionAcceptance(" in text
    assert "is below the expected" in text, (
        "the below-expectation rejection is gone; a wrong-script publish would pass"
    )
    assert re.search(r"published\s*<\s*expected", text), (
        "the below-expectation comparison is gone from resolveVersionAcceptance"
    )
    assert "publish advanced" in text and re.search(r"published\s*>\s*expected", text), (
        "the may-exceed acceptance path is gone; a facade-verified advance would "
        "now be wrongly rejected, reintroducing the equality treadmill"
    )
    assert "exactVersionVerified = facadeVersion === details.version;" not in text, (
        "the old exact-equality gate is back; a facade-verified advance beyond "
        "the expectation would be rejected again"
    )


def test_facade_answer_overrides_ui_text_evidence_before_verification() -> None:
    """A facade answer must override weaker UI-text evidence, before verification runs.

    Migrated from ``test_engine_publisher_requires_exact_facade_version``'s
    ``"publishedVersion = facadeVersion;" in text`` assertion. This fell out
    of the original migration; fix round 1 only recorded that
    ``hand_authored_publisher_facade_authority.test.ts:138-159`` covers the
    property functionally in TypeScript. But that is the verification lane,
    not ``fast-gates`` — the only required check (ADR-0011) — and this file
    is what sits inside it. By the same reasoning that put
    ``test_every_hand_lib_publisher_is_a_thin_wrapper`` inside the gate (fix
    round 1, Edit 1), this property belongs here too: a redundant seat inside
    the required gate beats a unique seat outside it.

    Chosen anchors: the assignment itself (the pine-facade filter=published
    listing becomes the recorded ``publishedVersion``, superseding whatever
    the UI-text evidence guessed) and its position strictly before the
    verification throw (an override arriving after the throw could never
    rescue a successful-but-unverified publish, which is the whole reason
    #3603/#3606 wired it in). The TS test additionally pins the probe target
    (``details.scriptName``) and the ``"facade_list"`` mode label; those are
    evidence-provenance details, not "does the override win and does it
    arrive in time" — the two questions this assertion is chosen to answer.
    They are not covered elsewhere in this file today; left out here as a
    deliberate scope choice, not because they are redundant.
    """
    text = SHARED_MODULE.read_text(encoding="utf-8")
    assert "publishedVersion = facadeVersion;" in text, (
        "the facade override no longer becomes the recorded published version"
    )
    facade_override = text.index("publishedVersion = facadeVersion;")
    verification_throw = text.index("if (!exactScriptVerified || !versionAcceptance.accepted) {")
    assert facade_override < verification_throw, (
        "the facade override no longer precedes the verification throw — it could "
        "no longer rescue a successful-but-unverified publish"
    )


def test_shared_module_preflights_before_any_editor_mutation() -> None:
    """The advance-contract's source ordering must never regress.

    This is a SOURCE-ORDERING check, not a claim that these steps run on
    every publish. The two are gated independently, and on different things:
    the live page-auth probe runs whenever the descriptor opts into
    ``requiresExplicitVersionAdvance`` (tv_publish_hand_lib.ts:503) — a
    descriptor-only condition, not ``--version``-dependent — while the
    pre-mutation facade preflight runs only on top of that, when
    ``--version`` was passed explicitly AND the advance contract resolves to
    ``"enforced"`` (:516). On the orchestrator's own call path
    (``tv_publish_hand_authored_libraries.ts`` passes only
    ``--out``/``--no-allow-create``; ``--version`` is always derived from
    consumer pins), the auth probe DOES run for smc_context_engine_private —
    its condition only inspects the descriptor, which the orchestrator never
    touches. What is skipped on that path is only the preflight:
    ``versionAdvanceContract`` resolves to ``"skipped_derived_version"``
    whenever ``--version`` was not explicit (tv_publish_hand_lib.ts:438-440),
    which is unconditionally true for every orchestrator-driven publish.

    What this protects: WHEN both run, the auth probe must precede the
    preflight, and the preflight must precede the first editor mutation, or
    a stale operator assumption about the current published version could
    silently turn an intended /3 publish into /4 (or overwrite a newer
    private release) by mutation. Migrated from a
    smc_context_engine_private-only test onto the shared module: this is the
    one hand lib whose descriptor opts into the contract today, and the
    shared module is the ONLY place this sequencing exists in source — no
    TypeScript test covers the Playwright ordering.
    """
    text = SHARED_MODULE.read_text(encoding="utf-8")

    auth_probe = text.index("const pageAuthState = await collectTradingViewPageAuthState")
    preflight = text.index("preflightPublishedVersion = await fetchPublishedLibraryVersionViaFacade")
    editor_mutation = text.index("await setEditorContent(session.page, code)")
    assert auth_probe < preflight < editor_mutation

    assert "if (!pageAuthenticated)" in text
    assert "rejected the configured auth source as anonymous" in text
    assert "preflightPublishedVersion === details.expectedCurrentVersion" in text
    assert "No editor or publish mutation was attempted." in text
    assert "publish requires --expected-current-version when --version is passed explicitly." in text, (
        "the advance contract no longer requires an explicit predecessor version; "
        "a frozen default here would recreate the same drift risk the removed "
        "--version literal had"
    )


def test_shared_module_rejects_incoherent_publish_identity() -> None:
    """The expected version must be integral and match the consumer import.

    Migrated from smc_engine_private's publisher onto the shared module: this
    coherence check used to run for exactly one of the ten hand-authored
    publishers (engine scored 1/10 pre-conversion; every sibling scored 0/10
    — see the shared module's own comment directly above this check).
    Converting to the shared module means every hand lib gets it now, not
    just engine.
    """
    text = SHARED_MODULE.read_text(encoding="utf-8")
    assert "!Number.isInteger(cli.version) || cli.version < 1" in text
    assert "cli.importPath.match(/^([^/]+)\\/([^/]+)\\/(\\d+)$/)" in text
    assert "importIdentity[2] !== cli.scriptName" in text
    assert "Number(importIdentity[3]) !== cli.version" in text
    assert "import path must name" in text, "the incoherent-identity error message is gone"


@pytest.mark.parametrize("name", sorted(_hand_libs()))
def test_descriptor_script_name_matches_the_hand_libs_entry(name: str) -> None:
    """Every HAND_LIBS row must have a publisher, and it must declare a matching scriptName and source.

    "A hand-authored library must be publishable from the repo" is this
    file's whole premise (see the module docstring). ``entry["publisher"]``
    being ``None`` is a schema the orchestrator supports ("cannot republish,
    will only repin" — see ``test_hand_lib_source_and_publisher_resolve``),
    but no row exercises it today (measured: zero ``publisher: null`` rows in
    ``scripts/tv_publish_hand_authored_libraries.ts``), and this file should
    not just skip past that case rather than assert it. A row landing with
    ``publisher: null`` — accidentally or otherwise — silently strips the
    library of the one guard this whole file exists to provide: nothing else
    here checks the descriptor of a library with no publisher, because there
    is no file to check.

    The orchestrator dispatches each publisher by spawning its file and
    trusting that the descriptor inside addresses the library HAND_LIBS says
    it does. A copy-paste wrapper (new file, stale descriptor) would publish
    the WRONG library under the RIGHT row's name, and nothing else here would
    catch it — ``test_hand_lib_source_and_publisher_resolve`` only proves the
    files exist, not that they agree on identity.

    ``source`` is checked too: HAND_LIBS' ``source`` (used by the
    orchestrator to topo-sort by parsing imports) and the descriptor's own
    ``source`` (used by the shared module to read the file it actually
    publishes) are two independent string literals with nothing comparing
    them. Repointing HAND_LIBS' ``source`` at a different existing SMC++ file
    would still pass every other assertion in this file while the
    orchestrator topo-ordered on one file's imports and the publisher
    published another.
    """
    entry = _hand_libs()[name]
    publisher = entry["publisher"]
    assert publisher is not None, (
        f"{name} has no publisher — a hand-authored library must be publishable "
        "from the repo (this file's whole premise); add a publisher script, or "
        "confirm `publisher: null` is intentional before landing it"
    )
    text = (REPO_ROOT / publisher).read_text(encoding="utf-8")
    assert f'scriptName: "{name}"' in text, (
        f"{publisher} does not declare scriptName {name!r}"
    )
    assert f'source: "{entry["source"]}"' in text, (
        f"{publisher} does not declare source {entry['source']!r} — HAND_LIBS and the "
        "descriptor disagree about which SMC++ file this publisher addresses"
    )
