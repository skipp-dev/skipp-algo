from __future__ import annotations

import importlib.util
import pathlib
import sys
from types import ModuleType


ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / 'scripts' / 'smc_bus_manifest.py'


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


def read_text(path: pathlib.Path) -> str:
    return path.read_text(encoding = 'utf-8')