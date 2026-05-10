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


def snapshot_to_dict(snapshot: SmcSnapshot, *, product_cut: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = _drop_nones(asdict(snapshot))
    if product_cut is not None:
        payload["product_cut"] = _drop_nones(dict(product_cut))
    return payload
