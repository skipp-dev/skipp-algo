"""Atomic dataframe / text / JSON writes for the SMC pipeline.

Audit finding A-1 (TEMPORAL_NUMERICAL_AUDIT_2026-04-24) and 2026-04-24
system review H-2: production writers previously called
``DataFrame.to_parquet`` / ``DataFrame.to_csv`` / ``json.dump(open(...))``
directly on the destination path. A crash mid-write left a truncated file
behind that propagated silently downstream (Pine export, calibration,
Streamlit UI). This module is the canonical home for the
``tempfile + os.replace`` pattern.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

__all__ = [
    "atomic_write_parquet",
    "atomic_write_csv",
    "atomic_write_text",
    "atomic_write_json",
]


def _atomic_write(df: pd.DataFrame, target: Path, suffix: str, writer_name: str, **kwargs: Any) -> None:
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=target.name + ".", suffix=suffix, dir=str(target.parent))
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        getattr(df, writer_name)(tmp_path, **kwargs)
        os.replace(tmp_path, target)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def atomic_write_parquet(df: pd.DataFrame, target: str | os.PathLike[str], **kwargs: Any) -> None:
    """Write ``df`` to ``target`` as parquet via tempfile + os.replace."""
    _atomic_write(df, Path(target), suffix=".parquet.tmp", writer_name="to_parquet", **kwargs)


def atomic_write_csv(df: pd.DataFrame, target: str | os.PathLike[str], **kwargs: Any) -> None:
    """Write ``df`` to ``target`` as CSV via tempfile + os.replace."""
    _atomic_write(df, Path(target), suffix=".csv.tmp", writer_name="to_csv", **kwargs)


def atomic_write_text(
    text: str,
    target: str | os.PathLike[str],
    *,
    encoding: str = "utf-8",
    newline: str | None = None,
) -> None:
    """Write ``text`` to ``target`` via tempfile + os.replace."""
    target_path = Path(target)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=target_path.name + ".", suffix=".tmp", dir=str(target_path.parent)
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline=newline) as fh:
            fh.write(text)
        os.replace(tmp_path, target_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def atomic_write_json(
    payload: Any,
    target: str | os.PathLike[str],
    *,
    indent: int | None = 2,
    sort_keys: bool = False,
    ensure_ascii: bool = True,
    default: Any = None,
) -> None:
    """Serialize ``payload`` to JSON and write atomically to ``target``."""
    text = json.dumps(
        payload,
        indent=indent,
        sort_keys=sort_keys,
        ensure_ascii=ensure_ascii,
        default=default,
    )
    atomic_write_text(text, target)
