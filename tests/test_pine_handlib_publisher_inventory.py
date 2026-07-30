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
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ORCHESTRATOR = REPO_ROOT / "scripts" / "tv_publish_hand_authored_libraries.ts"
SMCPP_DIR = REPO_ROOT / "SMC++"
ENGINE_PUBLISHER = REPO_ROOT / "scripts" / "tv_publish_engine_library.ts"

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


def test_context_engine_publisher_defaults_are_coherent() -> None:
    """The publisher's own defaults must agree with the library and each other.

    The version appears twice (``--import-path`` and ``--version``); they are the
    published identity and drift silently if only one is bumped.
    """
    entry = _hand_libs().get("smc_context_engine_private")
    assert entry, "smc_context_engine_private is not in HAND_LIBS"
    publisher_path = entry["publisher"]
    assert publisher_path, "smc_context_engine_private has no publisher"
    text = (REPO_ROOT / str(publisher_path)).read_text(encoding="utf-8")

    def _default(flag: str) -> str:
        m = re.search(rf'getFlag\("{re.escape(flag)}",\s*"([^"]+)"\)', text)
        assert m, f"{flag} default not found in {publisher_path}"
        return m.group(1)

    assert _default("--library") == str(entry["source"])
    script_name = _default("--script-name")
    assert script_name == "smc_context_engine_private"

    import_path = _default("--import-path")
    m = re.fullmatch(r"preuss_steffen/" + re.escape(script_name) + r"/(\d+)", import_path)
    assert m, f"--import-path {import_path!r} does not address this library"
    assert _default("--version") == m.group(1), (
        f"--version default ({_default('--version')}) disagrees with the version "
        f"in --import-path ({m.group(1)}). Both name the published identity."
    )


def test_core_types_publisher_defaults_match_current_consumer_pin() -> None:
    """The scheduled hand-lib publisher must target the checked-in live pin."""
    text = (REPO_ROOT / "scripts/tv_publish_core_types_library.ts").read_text(
        encoding="utf-8"
    )
    import_match = re.search(
        r'getFlag\("--import-path",\s*"preuss_steffen/smc_core_types/(\d+)"\)',
        text,
    )
    version_match = re.search(r'getFlag\("--version",\s*"(\d+)"\)', text)
    assert import_match and version_match
    assert import_match.group(1) == version_match.group(1) == "5"
    assert "import preuss_steffen/smc_core_types/5 as ct" in (
        REPO_ROOT / "SMC_Long_Dip_Suite.pine"
    ).read_text(encoding="utf-8")


def test_context_engine_publisher_checks_pins_across_every_consumer() -> None:
    """The pin check must scan all repo .pine, not just the core.

    Two failure modes to avoid at once:

    * Requiring a pin at all makes an unpublished library unpublishable — the
      bootstrap deadlock (publishing needs a pin, a pin needs a published
      version). Every sibling publisher has that shape.
    * Checking only ``SMC_Long_Dip_Suite.pine`` goes blind exactly when the
      library IS wired: the planned consumer is ``SMC_Context_Bus.pine``
      (docs/smc-bus-roadmap.md), so the Suite would still not pin it and a
      Context-Bus pin at the wrong version would sail through.

    So: zero pins is a legal bootstrap, and every pin that exists must name the
    version being published.
    """
    entry = _hand_libs()["smc_context_engine_private"]
    text = (REPO_ROOT / str(entry["publisher"])).read_text(encoding="utf-8")

    assert "function consumerPins(" in text, (
        "the publisher no longer enumerates consumer pins; a core-only check "
        "cannot see the planned SMC_Context_Bus consumer"
    )
    assert 'path.join(repoRoot, "SMC++")' in text, (
        "the consumer scan does not cover SMC++/, so a library-to-library pin "
        "would be invisible — it must mirror the surface the orchestrator repins"
    )
    assert re.search(
        r"consumerPins\(cli\.repoRoot, cli\.scriptName\)\s*\.filter\(\s*\n?\s*"
        r"\(pin\) => pin\.version !== cli\.version",
        text,
    ), (
        "the publisher no longer rejects consumer pins naming a version other "
        "than the one being published"
    )
    assert "Consumer pin mismatch" in text, "the mismatch error message is gone"
    assert "if (!coreText.includes(expectedImportLine))" not in text, (
        "the unconditional core-import requirement is back — that reintroduces "
        "the bootstrap deadlock this library is currently in"
    )


def test_engine_publisher_requires_exact_facade_version() -> None:
    """A facade result for another version must not verify the expected pin."""
    text = ENGINE_PUBLISHER.read_text(encoding="utf-8")
    assert "publishedVersion = facadeVersion;" in text
    assert "exactVersionVerified = facadeVersion === details.version;" in text
    assert "exactVersionVerified = true;" not in text


def test_context_engine_publisher_preflights_and_verifies_exact_versions() -> None:
    """An intended /3 publish must abort before mutation when TV is already /3."""
    publisher = (
        REPO_ROOT / "scripts" / "tv_publish_context_engine_library.ts"
    ).read_text(encoding="utf-8")

    assert 'getFlag("--expected-current-version", "2")' in publisher
    auth_probe = publisher.index(
        "const pageAuthState = await collectTradingViewPageAuthState"
    )
    preflight = publisher.index(
        "preflightPublishedVersion = await fetchPublishedLibraryVersionViaFacade"
    )
    editor_mutation = publisher.index("await setEditorContent(session.page, code)")
    assert auth_probe < preflight < editor_mutation
    assert "if (!pageAuthenticated)" in publisher
    assert "rejected the configured auth source as anonymous" in publisher
    assert "preflightPublishedVersion === details.expectedCurrentVersion" in publisher
    assert "No editor or publish mutation was attempted." in publisher
    assert "exactVersionVerified = facadeVersion === details.version;" in publisher
    assert "exactVersionVerified = true;" not in publisher


def test_engine_publisher_rejects_incoherent_publish_identity() -> None:
    """The expected version must be integral and match the consumer import."""
    text = ENGINE_PUBLISHER.read_text(encoding="utf-8")
    assert "!Number.isInteger(cli.version) || cli.version < 1" in text
    assert "cli.importPath.match(/^([^/]+)\\/([^/]+)\\/(\\d+)$/)" in text
    assert "importIdentity[2] !== cli.scriptName" in text
    assert "Number(importIdentity[3]) !== cli.version" in text
    assert "Engine import path must name" in text
