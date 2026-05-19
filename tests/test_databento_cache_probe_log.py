from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCREENER_PATH = ROOT / "databento_volatility_screener.py"
PRODUCER_PATH = ROOT / "scripts/databento_production_export.py"


def _ast(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def test_screener_exports_cache_probe_helpers() -> None:
    tree = _ast(SCREENER_PATH)
    function_names = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }
    assert "enable_cache_probe_log" in function_names
    assert "dump_cache_probe_log" in function_names
    assert "_record_cache_probe" in function_names


def test_read_cached_frame_records_probe_before_cache_miss_return() -> None:
    text = SCREENER_PATH.read_text(encoding="utf-8")
    assert "_record_cache_probe(path, hit=(exists := path.exists()))" in text


def test_producer_main_wires_env_enable_and_dump() -> None:
    text = PRODUCER_PATH.read_text(encoding="utf-8")
    assert 'os.environ.get("DATABENTO_CACHE_PROBE_LOG", "").strip()' in text
    assert "from databento_volatility_screener import enable_cache_probe_log" in text
    assert "from databento_volatility_screener import dump_cache_probe_log" in text
    assert 'print(f"CACHE_PROBE_LOG {n} {_cache_probe_log_path}")' in text
