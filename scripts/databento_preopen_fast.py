from __future__ import annotations

from pathlib import Path


def run_preopen_fast_refresh(*, export_dir: Path, bundle: Path, scope_days=None, **kwargs) -> dict[str, object]:
    export_dir.mkdir(parents=True, exist_ok=True)
    bundle.mkdir(parents=True, exist_ok=True)
    return {
        "mode": "preopen_fast_reduced_scope",
        "scope_days": scope_days,
        "scope_symbol_count": 0,
        "scope_days_mode": "manual" if scope_days else "auto",
        "user_warnings": [],
    }