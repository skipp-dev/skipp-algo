from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import sys
from types import ModuleType

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / 'scripts' / 'smc_bus_manifest.py'
LIBRARY_RELEASE_MANIFEST_PATH = (
    ROOT / 'artifacts' / 'tradingview' / 'library_release_manifest.json'
)


def load_manifest() -> ModuleType:
    existing = sys.modules.get('smc_bus_manifest')
    if existing is not None:
        return existing

    spec = importlib.util.spec_from_file_location('smc_bus_manifest', MANIFEST_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def published_micro_profiles_import_line(alias: str = 'mp') -> str:
    payload = json.loads(
        LIBRARY_RELEASE_MANIFEST_PATH.read_text(encoding='utf-8')
    )
    library = payload['library']
    import_path = library['importPath']
    canonical_path = (
        f"{library['owner']}/{library['scriptName']}/"
        f"{library['publishedVersion']}"
    )
    assert import_path == canonical_path
    return f'import {import_path} as {alias}'


def read_text(path: pathlib.Path) -> str:
    return path.read_text(encoding = 'utf-8')


def extract_hidden_plot_labels(text: str) -> tuple[str, ...]:
    labels: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith('plot(') or 'display = display.none' not in stripped:
            continue
        matches = re.findall(r"['\"]([^'\"]+)['\"]", stripped)
        if matches:
            labels.append(matches[-1])
    return tuple(labels)


def extract_input_bindings(text: str) -> tuple[tuple[str, str], ...]:
    bindings: list[tuple[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if 'input.source(' not in stripped:
            continue
        label_match = re.search(r'input\.source\(close,\s*"([^"]+)"', stripped)
        group_match = re.search(r'group\s*=\s*([A-Za-z_][A-Za-z0-9_]*)', stripped)
        if label_match and group_match:
            bindings.append((label_match.group(1), group_match.group(1)))
    return tuple(bindings)


def extract_group_titles(text: str) -> dict[str, str]:
    group_titles: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        match = re.match(r'var(?:\s+string)?\s+([A-Za-z_][A-Za-z0-9_]*) = "([^"]+)"', stripped)
        if match:
            group_titles[match.group(1)] = match.group(2)
    return group_titles
