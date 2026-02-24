"""Atomic JSON export for downstream consumers.

Writes scored news candidates to JSON using a tmp → rename pattern
so readers never see a partially-written file.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List


def export_open_prep(
    path: str,
    candidates: List[Dict[str, Any]],
    meta: Dict[str, Any],
) -> None:
    """Atomically write *candidates* + *meta* to *path*."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = {"meta": meta, "candidates": candidates}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp, path)
