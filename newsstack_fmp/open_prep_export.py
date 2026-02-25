"""Atomic JSON export for downstream consumers.

Writes scored news candidates to JSON using a tempfile → rename pattern
so readers never see a partially-written file.
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Dict, List


def export_open_prep(
    path: str,
    candidates: List[Dict[str, Any]],
    meta: Dict[str, Any],
) -> None:
    """Atomically write *candidates* + *meta* to *path*."""
    dest_dir = os.path.dirname(path) or "."
    os.makedirs(dest_dir, exist_ok=True)
    payload = {"meta": meta, "candidates": candidates}
    fd, tmp = tempfile.mkstemp(dir=dest_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, default=str, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        # Clean up temp file on any failure
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
