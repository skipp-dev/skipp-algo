from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.smc_bus_manifest import ACTIVE_VALIDATION_PINE_FILES  # noqa: E402
from scripts.smc_bus_manifest import DASHBOARD_GROUP_TITLES  # noqa: E402
from scripts.smc_bus_manifest import ENGINE_BUS_LABELS  # noqa: E402
from scripts.smc_bus_manifest import STRATEGY_GROUP_TITLES  # noqa: E402


RUNBOOK_PATH = ROOT / 'docs/tradingview-manual-validation-runbook.md'


def _read_runbook() -> str:
    return RUNBOOK_PATH.read_text(encoding = 'utf-8')


def test_runbook_references_canonical_bus_manifest() -> None:
    text = _read_runbook()

    assert '[../scripts/smc_bus_manifest.py](../scripts/smc_bus_manifest.py)' in text


def test_runbook_references_active_validation_files_in_order() -> None:
    text = _read_runbook()

    positions = [text.index(f'[../{name}](../{name})') for name in ACTIVE_VALIDATION_PINE_FILES]
    assert positions == sorted(positions)


def test_runbook_lists_engine_bus_labels_in_manifest_order() -> None:
    text = _read_runbook()

    positions = [text.index(f'- `{label}`') for label in ENGINE_BUS_LABELS]
    assert positions == sorted(positions)


def test_runbook_describes_manifest_consumer_groups() -> None:
    text = _read_runbook()

    for title in DASHBOARD_GROUP_TITLES:
        assert title in text

    for title in STRATEGY_GROUP_TITLES:
        assert title in text