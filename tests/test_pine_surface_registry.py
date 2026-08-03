"""Governance contract for root SMC Pine surfaces and TradingView rollout.

The registry in :mod:`scripts.smc_bus_manifest` is the single source of truth.
This suite intentionally cross-checks it against the physical root sources and
the rollout config so that a script cannot silently become orphaned, deployed,
or retired by changing only one of those surfaces.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from scripts.smc_bus_manifest import (
    ENGINE_BUS_LABELS,
    SURFACE_DEFINITIONS,
)
from tests.smc_manifest_test_utils import (
    extract_hidden_plot_labels,
    find_active_label_consumers,
)

ROOT = Path(__file__).resolve().parents[1]
ROLLOUT_CONFIG = ROOT / "automation" / "tradingview" / "config" / "consumer-rollout.json"


def _rollout() -> dict:
    return json.loads(ROLLOUT_CONFIG.read_text(encoding="utf-8"))


def _bus_input_labels(path: Path) -> tuple[str, ...]:
    """Return the literal ``BUS …`` labels used by input.source bindings."""
    source = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"""input\.source\(\s*[^,\n]+,\s*(?P<quote>["'])(?P<label>BUS [^"']+)(?P=quote)""",
    )
    return tuple(match.group("label") for match in pattern.finditer(source))


def _declared_script_name(path: Path) -> str:
    """Return the literal title from the root indicator/strategy declaration."""
    source = path.read_text(encoding="utf-8")
    match = re.search(
        r"""(?m)^\s*(?:indicator|strategy)\(\s*(?P<quote>["'])(?P<title>[^"']+)(?P=quote)""",
        source,
    )
    assert match is not None, f"{path.name}: no literal indicator/strategy title"
    return match.group("title")


def test_every_root_smc_source_is_registered_exactly_once() -> None:
    observed = {path.name for path in ROOT.glob("SMC_*.pine")}
    counts = Counter(surface.file for surface in SURFACE_DEFINITIONS)
    duplicates = sorted(file for file, count in counts.items() if count != 1)
    registered_present = {
        surface.file
        for surface in SURFACE_DEFINITIONS
        if (ROOT / surface.file).is_file()
    }

    assert duplicates == [], f"surface registry entries must be unique: {duplicates}"
    assert registered_present == observed, (
        "root SMC source classification drift: "
        f"unregistered={sorted(observed - registered_present)}, "
        f"registered-outside-root={sorted(registered_present - observed)}"
    )


def test_physical_surface_titles_match_unique_registry_names() -> None:
    physical = [
        surface
        for surface in SURFACE_DEFINITIONS
        if (ROOT / surface.file).is_file()
    ]
    names = [surface.script_name for surface in SURFACE_DEFINITIONS]

    assert len(names) == len(set(names)), "registry script_name values must be unique"
    assert {
        surface.file: _declared_script_name(ROOT / surface.file)
        for surface in physical
    } == {
        surface.file: surface.script_name
        for surface in physical
    }


def test_every_surface_ships_its_source() -> None:
    """Every surface ships its source today, so the allowance is unexercised.

    Named for what it asserts. It used to be called
    ``test_only_planned_surface_sources_may_be_absent``, which promised the
    lifecycle *allowance* — the opposite of the strict rule below.

    2026-08-03: this used to assert ``missing == []`` and then loop the
    lifecycle rule over ``missing`` — an iteration the line above had just
    proven runs zero times, so the rule the test is named after had never
    once been evaluated. Two surfaces *are* ``planned``
    (SMC_Hold_Manager.pine, SMC_Volume_Profile_Overlay.pine) and would
    therefore be allowed to omit their source, but both ship one, so the
    stricter fact is the one that actually holds. Anything that does go
    missing is reported with its lifecycle, which is what tells the reader
    whether the allowance was meant to cover it.
    """
    missing = [
        surface
        for surface in SURFACE_DEFINITIONS
        if not (ROOT / surface.file).is_file()
    ]

    assert missing == [], (
        "every surface must ship its source; only lifecycle=planned ones may "
        "omit it: "
        f"{[(surface.file, surface.lifecycle) for surface in missing]}"
    )


def test_rollout_save_targets_are_exactly_the_eleven_deployed_surfaces() -> None:
    # 2026-07-31: 10 -> 11. SMC_HTF_Confluence.pine deployed after R5-REBUILD
    # completed (all 11 cases) and the Pro HTF preset decision (#4257) put it
    # in; owner-ordered rollout. It is a standalone request.security companion
    # (no engine_v2 dependency), so verifyTargets stays at nine below.
    rollout = _rollout()
    save_targets = rollout["saveTargets"]
    deployed = {
        surface.file: surface
        for surface in SURFACE_DEFINITIONS
        if surface.rollout_state == "deployed"
    }

    assert len(save_targets) == 11
    assert len({target["source"] for target in save_targets}) == 11
    assert {target["source"] for target in save_targets} == set(deployed)
    assert {
        target["source"]: target["scriptName"]
        for target in save_targets
    } == {
        file: surface.script_name
        for file, surface in deployed.items()
    }


def test_rollout_verify_targets_are_exactly_the_nine_deployed_bus_consumers() -> None:
    rollout = _rollout()
    verify_targets = rollout["verifyTargets"]
    deployed_consumers = {
        surface.file: surface
        for surface in SURFACE_DEFINITIONS
        if surface.rollout_state == "deployed"
        and "engine_v2" in surface.bus_dependencies
        and surface.consumer_role != "producer"
    }

    assert len(verify_targets) == 9
    assert len({target["source"] for target in verify_targets}) == 9
    assert {target["source"] for target in verify_targets} == set(deployed_consumers)
    assert {
        target["source"]: target["scriptName"]
        for target in verify_targets
    } == {
        file: surface.chart_instance_name
        for file, surface in deployed_consumers.items()
    }


def test_deployed_engine_bus_consumers_bind_only_published_unique_labels() -> None:
    producer = ROOT / "SMC_Long_Dip_Suite.pine"
    published = extract_hidden_plot_labels(producer.read_text(encoding="utf-8"))

    assert published == ENGINE_BUS_LABELS
    assert len(published) == len(set(published))

    for surface in SURFACE_DEFINITIONS:
        if (
            surface.rollout_state != "deployed"
            or "engine_v2" not in surface.bus_dependencies
            or surface.consumer_role == "producer"
        ):
            continue
        labels = _bus_input_labels(ROOT / surface.file)
        duplicates = sorted(
            label
            for label, count in Counter(labels).items()
            if count > 1
        )
        unknown = sorted(set(labels) - set(published))
        assert labels, f"{surface.file}: deployed BUS consumer has no BUS bindings"
        assert duplicates == [], (
            f"{surface.file}: duplicate BUS input labels: {duplicates}"
        )
        assert unknown == [], (
            f"{surface.file}: BUS labels not published by the engine: {unknown}"
        )


def test_non_deployed_surfaces_are_absent_from_rollout_targets() -> None:
    rollout = _rollout()
    rollout_sources = {
        target["source"]
        for key in ("saveTargets", "verifyTargets")
        for target in rollout[key]
    }
    non_deployed = {
        surface.file
        for surface in SURFACE_DEFINITIONS
        if surface.rollout_state != "deployed"
    }

    assert rollout_sources.isdisjoint(non_deployed)


def _archived_surfaces() -> list:
    return [
        surface
        for surface in SURFACE_DEFINITIONS
        if surface.lifecycle == "archived" or surface.archive_state == "archived"
    ]


def test_the_archived_population_is_declared_rather_than_incidental() -> None:
    """A gate that silently applies to nothing is not a passing gate.

    2026-07-31: the archived population is EMPTY. Every check below therefore
    loops zero times and reports green while proving nothing — which is exactly
    the shape of failure the R0 gates exist to prevent, so the count is pinned
    instead of left to chance. The five snapshot-era context scripts are
    `replacement_pending`, not archived; archiving them is what will make this
    number move, and moving it is a deliberate edit with a reason.

    The rule itself is proven on data in `test_archived_surface_consumers.py`,
    because it cannot be proven here while the set is empty.
    """
    assert [surface.file for surface in _archived_surfaces()] == []
    assert sorted(
        surface.file
        for surface in SURFACE_DEFINITIONS
        if surface.lifecycle == "replacement_pending"
    ) == [
        "SMC_Imbalance_Context.pine",
        "SMC_Liquidity_Context.pine",
        "SMC_Liquidity_Structure.pine",
        "SMC_Profile_Context.pine",
        "SMC_Structure_Context.pine",
    ]


def test_archived_surfaces_are_isolated_from_active_rollout() -> None:
    rollout = _rollout()
    rollout_sources = {
        target["source"]
        for key in ("saveTargets", "verifyTargets")
        for target in rollout[key]
    }

    for surface in _archived_surfaces():
        assert not (ROOT / surface.file).is_file()
        assert (ROOT / "pine" / "legacy" / Path(surface.file).name).is_file()
        assert surface.file not in rollout_sources


def test_archived_surfaces_have_no_active_consumers() -> None:
    """The half of the rule the gate above never checked.

    "Archivierte Skripte dürfen keine aktiven Consumer mehr haben" is about
    BINDINGS, not rollout membership: a chart can still read an archived
    producer's outputs long after it left `saveTargets`. Absence from the
    rollout says nothing about that.

    Two ways an archived surface can still be consumed are checked — a live
    binding of a label only it published, and any surviving reference to its
    filename.
    """
    archived = _archived_surfaces()
    active_files = sorted(
        surface.file
        for surface in SURFACE_DEFINITIONS
        if surface.lifecycle != "archived"
        and surface.archive_state != "archived"
        and (ROOT / surface.file).is_file()
    )
    active_sources = {
        file: (ROOT / file).read_text(encoding="utf-8") for file in active_files
    }

    # Labels an ACTIVE producer still publishes are served by that producer, so
    # a binding to one of them does not strand anybody.
    still_published: set[str] = set()
    for source in active_sources.values():
        still_published.update(extract_hidden_plot_labels(source))

    archived_labels = {}
    for surface in archived:
        legacy = ROOT / "pine" / "legacy" / Path(surface.file).name
        archived_labels[surface.file] = extract_hidden_plot_labels(
            legacy.read_text(encoding="utf-8")
        ) if legacy.is_file() else ()

    stranded = find_active_label_consumers(
        archived_labels, active_sources, frozenset(still_published)
    )
    assert stranded == {}, f"archived surfaces still bound by active scripts: {stranded}"

    # A filename reference is the cruder leak: a config, manifest or script that
    # still names the archived source at all.
    searchable = dict(active_sources)
    searchable["consumer-rollout.json"] = ROLLOUT_CONFIG.read_text(encoding="utf-8")
    for surface in archived:
        for where, text in searchable.items():
            assert surface.file not in text, f"{where} still references archived {surface.file}"


# --- bus_schema --------------------------------------------------------------
#
# `bus_dependencies` records only the family a surface CONSUMES, so the two
# producers carried no version at all and nothing tied the registry to the
# number their Pine source declares. 7001 had no name in Python either — it sat
# as a bare literal in four fixture/replay modules. These gates close both: the
# field must agree with the family it consumes, and with the source that
# defines the contract.


def test_every_bus_participant_records_the_schema_it_speaks() -> None:
    from scripts.smc_bus_manifest import BUS_SCHEMA_BY_FAMILY

    for surface in SURFACE_DEFINITIONS:
        for family in surface.bus_dependencies:
            assert family in BUS_SCHEMA_BY_FAMILY, f"{surface.file}: unknown BUS family {family}"
            assert surface.bus_schema == BUS_SCHEMA_BY_FAMILY[family], (
                f"{surface.file} consumes {family} but records schema {surface.bus_schema}"
            )


def test_surfaces_outside_any_bus_record_no_schema() -> None:
    """A schema on a surface that speaks no BUS is a claim nothing backs."""
    producers = {"SMC_Long_Dip_Suite.pine", "SMC_Context_Bus.pine"}

    for surface in SURFACE_DEFINITIONS:
        if surface.bus_dependencies or surface.file in producers:
            continue
        assert surface.bus_schema is None, (
            f"{surface.file} has no BUS dependency and is not a producer, "
            f"but records schema {surface.bus_schema}"
        )


def test_producers_record_the_schema_their_source_declares() -> None:
    """The registry number must come from the Pine source, not from memory.

    This is the gate the stale channel-count note showed was missing: two
    surfaces described the same contract and only one was kept current.
    """
    from scripts.smc_bus_manifest import (
        CONTEXT_BUS_SCHEMA_VERSION,
        ENGINE_BUS_SCHEMA_VERSION,
        SURFACE_DEFINITIONS_BY_FILE,
    )

    engine = (ROOT / "SMC_Long_Dip_Suite.pine").read_text(encoding="utf-8")
    declared_engine = re.search(r"plot\(\s*(\d+)\s*,\s*'BUS SchemaVersion'", engine)
    assert declared_engine, "the engine producer no longer declares BUS SchemaVersion"
    assert int(declared_engine.group(1)) == ENGINE_BUS_SCHEMA_VERSION
    assert SURFACE_DEFINITIONS_BY_FILE["SMC_Long_Dip_Suite.pine"].bus_schema == ENGINE_BUS_SCHEMA_VERSION

    context = (ROOT / "SMC_Context_Bus.pine").read_text(encoding="utf-8")
    declared_context = re.search(r"const int SCHEMA_VERSION\s*=\s*(\d+)", context)
    assert declared_context, "the context producer no longer declares SCHEMA_VERSION"
    assert int(declared_context.group(1)) == CONTEXT_BUS_SCHEMA_VERSION
    assert SURFACE_DEFINITIONS_BY_FILE["SMC_Context_Bus.pine"].bus_schema == CONTEXT_BUS_SCHEMA_VERSION


def test_the_context_producer_note_is_derived_from_the_contract() -> None:
    """The note that drifted must now be impossible to state wrongly.

    It read "60 direct domain channels with four ... reserved" while the
    contract had moved to 62/2 (#4263). Counting at import time is what makes a
    repeat structurally impossible; this pins that it is still counted.
    """
    from scripts.smc_bus_manifest import SURFACE_DEFINITIONS_BY_FILE
    from scripts.smc_context_bus_manifest import (
        CONTEXT_BUS_CHANNELS,
        TRADINGVIEW_PLOT_LIMIT,
    )

    note = " ".join(SURFACE_DEFINITIONS_BY_FILE["SMC_Context_Bus.pine"].notes)
    channels = len(CONTEXT_BUS_CHANNELS)
    reserved = TRADINGVIEW_PLOT_LIMIT - channels

    assert f"{channels} direct domain channels" in note
    assert f"{reserved} TradingView plot slots reserved" in note
    # The numbers that were wrong must not reappear as literals.
    assert "60 direct domain channels" not in note
    assert "four TradingView plot" not in note


def test_the_hold_manager_note_reports_the_open_shadow_window_from_evidence() -> None:
    """The registry must surface a running shadow window, not only the end state.

    `deployment_mode` records the target tier and has never been changed on any
    surface; `rollout_state` deliberately stayed 'planned' when the window
    opened (#4180, which touched ten files but left this registry alone). So
    neither field can express "a shadow observation window is open right now",
    and a reader of the canonical registry could not tell that one was —
    the fact lived only in the traceability artifact, the activation evidence
    and the architecture doc. The note carries it; this pins the note to the
    evidence so the timestamp cannot drift away from it.
    """
    from scripts.smc_bus_manifest import SURFACE_DEFINITIONS_BY_FILE

    activation = json.loads(
        (
            ROOT
            / "artifacts"
            / "governance"
            / "smc_hold_manager_shadow_activation_2026-07-28.json"
        ).read_text(encoding="utf-8")
    )
    surface = SURFACE_DEFINITIONS_BY_FILE["SMC_Hold_Manager.pine"]
    note = " ".join(surface.notes)

    activated_at = activation["activatedAtUtc"]
    assert activated_at, "activation evidence no longer records activatedAtUtc"
    assert activated_at in note, (
        "the Hold Manager note no longer states the activation timestamp from "
        f"the evidence artifact ({activated_at})"
    )
    assert "shadow observation window open" in note

    # The note explains why the state fields read the way they do. If either
    # field is ever changed on purpose, this pin must be revisited WITH it —
    # that is the point: the two cannot drift apart silently.
    assert surface.rollout_state == "planned"
    assert surface.deployment_mode == "standard"


def test_the_surface_payload_omits_unset_fields_instead_of_emitting_null() -> None:
    """A null in the payload silently breaks the delivery bundle.

    `smc_core.serialization.snapshot_to_dict` runs the product cut through
    `_drop_nones` before embedding it in a bundle that ALSO carries the raw
    payload, so a null present in one copy and absent from the other makes the
    two unequal and trips
    `test_delivery_bundle_snapshot_dashboard_pine_alignment`.

    That test lives in the fast SMC integration lane, which the local ledger
    guard does not run — so `bus_schema` shipped a null, passed every local
    check, and only turned red in CI. This pin catches the whole class next to
    the registry it comes from, where it is cheap to run.
    """
    from scripts.smc_bus_manifest import build_product_cut_manifest_payload
    from smc_core.serialization import _drop_nones

    payload = build_product_cut_manifest_payload()
    assert _drop_nones(dict(payload)) == payload, (
        "the product-cut payload carries null values; optional fields must be "
        "omitted when unset"
    )

    nulls = {
        surface["file"]: sorted(key for key, value in surface.items() if value is None)
        for surface in payload["surfaceRoles"]
        if any(value is None for value in surface.values())
    }
    assert nulls == {}, f"surfaces emitting null fields: {nulls}"
