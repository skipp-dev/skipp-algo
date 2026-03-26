from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .types import SmcSnapshot


def _drop_nones(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if item is None:
                continue
            out[key] = _drop_nones(item)
        return out
    if isinstance(value, list):
        return [_drop_nones(item) for item in value]
    return value


def snapshot_to_dict(snapshot: SmcSnapshot) -> dict:
    return _drop_nones(asdict(snapshot))
