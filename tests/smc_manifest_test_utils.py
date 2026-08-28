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
        # Both quote styles: the Alerts companion declares its labels
        # single-quoted, a double-quote-only pattern saw 0 of its 4 rows
        # (measured 2026-08-28 when the consumer contracts were registered).
        label_match = re.search(r"""input\.source\(close,\s*(["'])([^"']+)\1""", stripped)
        group_match = re.search(r'group\s*=\s*([A-Za-z_][A-Za-z0-9_]*)', stripped)
        if label_match and group_match:
            bindings.append((label_match.group(2), group_match.group(1)))
    return tuple(bindings)


def extract_group_titles(text: str) -> dict[str, str]:
    """Every top-level string assignment that can name a settings group.

    `var` is optional (Alerts/Breakout/Hold Manager declare groups bare), both
    quote styles count, and the name arm is deliberately broad — lookups go by
    known group variable, so extra string constants in the map are harmless
    while a missed declaration style silently empties a contract check.
    """
    group_titles: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        match = re.match(
            r"""(?:var\s+)?(?:string\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(["'])([^"']+)\2\s*$""",
            stripped,
        )
        if match:
            group_titles[match.group(1)] = match.group(3)
    return group_titles


def extract_bound_source_labels(text: str) -> tuple[str, ...]:
    """Every label bound via ``input.source()``, whatever its family or group.

    Deliberately broader than :func:`extract_input_bindings`, which requires the
    literal ``close`` default and a ``group =``. This one feeds the archived-
    surface consumer gate, where a miss is worse than a false hit: an unnoticed
    binding certifies an archived script as consumer-free while a chart still
    reads it, whereas a false hit is a loud failure a human resolves in minutes.
    Comment lines are skipped so a commented-out binding is not a consumer.
    """
    labels: list[str] = []
    pattern = re.compile(r"""input\.source\(\s*[^,\n]+,\s*(["'])(?P<label>[^"']+)\1""")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('//'):
            continue
        labels.extend(match.group('label') for match in pattern.finditer(stripped))
    return tuple(labels)


def find_active_label_consumers(
    archived_labels: dict[str, tuple[str, ...]],
    active_sources: dict[str, str],
    labels_still_published_by_active: frozenset[str],
) -> dict[str, dict[str, list[str]]]:
    """Which active surfaces still bind labels only an archived surface published.

    Returns ``{archived_file: {consumer_file: [labels]}}`` — empty when clean.

    A label that an ACTIVE producer also publishes is not evidence of a stale
    consumer: the binding is served by the live producer, and the archived
    script merely happened to publish the same name. Only labels unique to the
    archived surface can strand a consumer, so those are the only ones counted.
    """
    findings: dict[str, dict[str, list[str]]] = {}
    for archived_file, labels in archived_labels.items():
        unique = [label for label in labels if label not in labels_still_published_by_active]
        if not unique:
            continue
        for consumer_file, source in active_sources.items():
            bound = extract_bound_source_labels(source)
            stranded = sorted({label for label in unique if label in bound})
            if stranded:
                findings.setdefault(archived_file, {})[consumer_file] = stranded
    return findings
