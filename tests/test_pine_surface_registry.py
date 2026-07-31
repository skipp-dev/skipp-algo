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
from tests.smc_manifest_test_utils import extract_hidden_plot_labels

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


def test_only_planned_surface_sources_may_be_absent() -> None:
    missing = [
        surface
        for surface in SURFACE_DEFINITIONS
        if not (ROOT / surface.file).is_file()
    ]

    assert missing == []
    assert all(surface.lifecycle == "planned" for surface in missing), (
        "only lifecycle=planned surfaces may omit their source: "
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


def test_archived_surfaces_are_isolated_from_active_rollout() -> None:
    rollout = _rollout()
    rollout_sources = {
        target["source"]
        for key in ("saveTargets", "verifyTargets")
        for target in rollout[key]
    }
    archived = [
        surface
        for surface in SURFACE_DEFINITIONS
        if surface.lifecycle == "archived" or surface.archive_state == "archived"
    ]

    for surface in archived:
        assert not (ROOT / surface.file).is_file()
        assert (ROOT / "pine" / "legacy" / Path(surface.file).name).is_file()
        assert surface.file not in rollout_sources
