"""The export must produce the session minute detail the base runtime needs.

2026-07-22 incident: `session_minute_detail_full_universe` is consumed by
`smc_microstructure_base_runtime.build_base_snapshot_from_bundle_payload` but no
workflow ever produced it — `git log -S collect_full_universe_session_minute_detail`
over `.github/workflows/` is empty. The library refresh runs the `--bundle` path,
which cannot collect it, so the frame silently resolved to empty: every
minute-derived metric fell back to 0.0, no symbol cleared a membership threshold,
and five published library versions shipped seven empty ticker lists.

These are source contracts rather than behavioural tests because exercising the
real collection means paying for a full-universe Databento pull. They pin the
wiring so it cannot silently disappear again.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_EXPORT = _REPO / "scripts" / "databento_production_export.py"
_FRAME = "session_minute_detail_full_universe"


def _export_source() -> str:
    return _EXPORT.read_text(encoding="utf-8")


def test_export_collects_full_universe_session_minute_detail() -> None:
    source = _export_source()
    assert "collect_full_universe_session_minute_detail" in source, (
        "databento_production_export no longer calls "
        "collect_full_universe_session_minute_detail; the microstructure base "
        "runtime would fall back to zeroed minute metrics"
    )


def test_export_registers_the_frame_as_a_parquet_target() -> None:
    source = _export_source()
    assert re.search(rf'"{_FRAME}"\s*:', source), (
        f"{_FRAME} is not registered in additional_parquet_targets; the merge "
        "globs per-frame parquets, so an unregistered frame never reaches the bundle"
    )


def test_the_collection_is_not_fail_soft() -> None:
    """A swallowed failure here is indistinguishable from healthy-but-empty.

    The neighbouring benchmark-1m collection is deliberately fail-soft. This one
    must not be: an empty frame silently zeroes every minute-derived metric, which
    is exactly the failure mode that went unnoticed for five library versions.
    """
    tree = ast.parse(_export_source())

    offenders: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        calls_collector = any(
            isinstance(inner, ast.Call)
            and isinstance(inner.func, ast.Name)
            and inner.func.id == "collect_full_universe_session_minute_detail"
            for inner in ast.walk(node)
        )
        if not calls_collector:
            continue
        # A try/except that re-raises is fine; one that swallows is not.
        for handler in node.handlers:
            reraises = any(isinstance(inner, ast.Raise) for inner in ast.walk(handler))
            if not reraises:
                offenders.append(handler.lineno)

    assert not offenders, (
        "collect_full_universe_session_minute_detail sits inside an except block "
        f"that does not re-raise (line(s) {offenders}). An empty session minute "
        "frame zeroes every minute-derived metric silently — this collection must "
        "fail closed."
    )
