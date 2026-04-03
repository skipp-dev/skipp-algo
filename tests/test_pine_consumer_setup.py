from __future__ import annotations

import pathlib
import re


ROOT = pathlib.Path(__file__).resolve().parents[1]
DASHBOARD_PATH = ROOT / "SMC_Dashboard.pine"
STRATEGY_PATH = ROOT / "SMC_Long_Strategy.pine"

_SOURCE_RE = re.compile(
    r'^\s*(?P<varname>\w+)\s*=\s*input\.source\([^,]+,\s*"(?P<label>[^"]+)"(?P<args>.*)\)$'
)
_GROUP_RE = re.compile(r'\bgroup\s*=\s*(?P<group>\w+)')


EXPECTED_DASHBOARD_LABELS = [
    "BUS ZoneActive",
    "BUS Armed",
    "BUS Confirmed",
    "BUS Ready",
    "BUS EntryBest",
    "BUS EntryStrict",
    "BUS Trigger",
    "BUS Invalidation",
    "BUS QualityScore",
    "BUS SourceKind",
    "BUS StateCode",
    "BUS TrendPack",
    "BUS MetaPack",
    "BUS HardGatesPackA",
    "BUS HardGatesPackB",
    "BUS EventRiskRow",
    "BUS QualityPackA",
    "BUS QualityPackB",
    "BUS QualityBoundsPack",
    "BUS ModulePackA",
    "BUS ModulePackB",
    "BUS ModulePackC",
    "BUS ModulePackD",
    "BUS EnginePack",
    "BUS StopLevel",
    "BUS Target1",
    "BUS Target2",
    "BUS LeanPackA",
    "BUS LeanPackB",
]

EXPECTED_DASHBOARD_GROUPS = (
    ["g_bus_lifecycle"] * 13
    + ["g_bus_diag"] * 11
    + ["g_bus_plan"] * 3
    + ["g_bus_lean"] * 2
)

EXPECTED_STRATEGY_LABELS = [
    "BUS Armed",
    "BUS Confirmed",
    "BUS Ready",
    "BUS EntryBest",
    "BUS EntryStrict",
    "BUS QualityScore",
    "BUS Trigger",
    "BUS Invalidation",
]

EXPECTED_STRATEGY_GROUPS = ["g_bus_entry"] * 6 + ["g_bus_plan"] * 2


def _extract_source_inputs(path: pathlib.Path) -> list[tuple[str, str, str | None]]:
    rows: list[tuple[str, str, str | None]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        match = _SOURCE_RE.match(raw_line.strip())
        if not match:
            continue
        args = match.group("args")
        group_match = _GROUP_RE.search(args)
        rows.append((match.group("varname"), match.group("label"), group_match.group("group") if group_match else None))
    return rows


def test_dashboard_bus_inputs_stay_ordered_and_grouped() -> None:
    rows = _extract_source_inputs(DASHBOARD_PATH)

    assert [label for _, label, _ in rows] == EXPECTED_DASHBOARD_LABELS
    assert [group for _, _, group in rows] == EXPECTED_DASHBOARD_GROUPS


def test_strategy_bus_inputs_stay_ordered_and_grouped() -> None:
    rows = _extract_source_inputs(STRATEGY_PATH)

    assert [label for _, label, _ in rows] == EXPECTED_STRATEGY_LABELS
    assert [group for _, _, group in rows] == EXPECTED_STRATEGY_GROUPS