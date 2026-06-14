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
import stat
import tempfile
import threading
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Bug-Hunt 2026-05-01 F-05: ``pandas`` is only referenced in type
    # annotations on ``atomic_write_parquet`` / ``atomic_write_csv``.
    # ``from __future__ import annotations`` defers those annotations to
    # strings, so a runtime ``import pandas`` would only serve to make
    # ``atomic_write_text`` / ``atomic_write_json`` callers (e.g. the
    # ``emit_public_calibration_report`` step in ``c13-daily-cron`` —
    # which deliberately does not install pandas to stay IBKR-free)
    # crash at import time. Restrict pandas to TYPE_CHECKING.
    import pandas as pd  # pragma: no cover

__all__ = [
    "atomic_write_csv",
    "atomic_write_json",
    "atomic_write_parquet",
    "atomic_write_text",
]


# ``os.umask`` is process-global state with no read-only accessor on
# POSIX — the only way to read it is to set a new value and restore
# the old one. If two threads do that concurrently, one can observe
# the other's transient ``0`` and infer ``0o666`` for "any umask".
# Serialise the read window so the racy interval is never visible to
# another thread (Copilot review of PR #195).
_UMASK_LOCK = threading.Lock()


def _default_mode_for_new_file() -> int:
    """Return the mode a fresh ``open(path, 'w')`` would use under the
    current umask (i.e. ``0o666 & ~umask``).

    ``tempfile.mkstemp`` always creates files with mode ``0o600``,
    overriding the user's umask. To keep ``atomic_write_*`` byte-for-byte
    compatible with the historical ``Path.write_text(...)`` behaviour
    (Copilot review of PR #189), we read the umask once at write time
    and chmod the temp file before the ``os.replace``.
    """
    # Serialised under ``_UMASK_LOCK`` so a concurrent caller in this
    # process cannot observe the transient ``0`` umask we set to read
    # the current value. Cross-process umask changes are still racy
    # (no portable cross-process lock), but in that case the next
    # write wins — and cross-process umask churn is not a real
    # production pattern.
    with _UMASK_LOCK:
        umask = os.umask(0)
        os.umask(umask)
    return 0o666 & ~umask


def _resolve_destination_mode(target: Path) -> int:
    """Mode bits to apply to the temp file before ``os.replace``.

    If ``target`` already exists, preserve its mode bits so a directory
    that has explicit permissions (e.g. ``0o644`` for shared dashboard
    output) is not silently downgraded to the ``mkstemp`` default of
    ``0o600``. Otherwise honour the process umask.
    """
    try:
        return stat.S_IMODE(target.stat().st_mode)
    except FileNotFoundError:
        return _default_mode_for_new_file()


def _fsync_file_if_requested(path: Path, *, enabled: bool) -> None:
    if not enabled:
        return
    try:
        fd = os.open(path, os.O_RDWR)
    except PermissionError:
        fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_write(
    df: pd.DataFrame,
    target: Path,
    suffix: str,
    writer_name: str,
    *,
    fsync: bool = False,
    **kwargs: Any,
) -> None:
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = _resolve_destination_mode(target)
    fd, tmp_name = tempfile.mkstemp(prefix=target.name + ".", suffix=suffix, dir=str(target.parent))
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        getattr(df, writer_name)(tmp_path, **kwargs)
        _fsync_file_if_requested(tmp_path, enabled=fsync)
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, target)
    except BaseException:
        with suppress(OSError):
            tmp_path.unlink(missing_ok=True)
        raise


def atomic_write_parquet(
    df: pd.DataFrame,
    target: str | os.PathLike[str],
    *,
    fsync: bool = False,
    **kwargs: Any,
) -> None:
    """Write ``df`` to ``target`` as parquet via tempfile + os.replace."""
    _atomic_write(
        df,
        Path(target),
        suffix=".parquet.tmp",
        writer_name="to_parquet",
        fsync=fsync,
        **kwargs,
    )


def atomic_write_csv(
    df: pd.DataFrame,
    target: str | os.PathLike[str],
    *,
    fsync: bool = False,
    **kwargs: Any,
) -> None:
    """Write ``df`` to ``target`` as CSV via tempfile + os.replace."""
    _atomic_write(
        df,
        Path(target),
        suffix=".csv.tmp",
        writer_name="to_csv",
        fsync=fsync,
        **kwargs,
    )


def atomic_write_text(
    text: str,
    target: str | os.PathLike[str],
    *,
    encoding: str = "utf-8",
    newline: str | None = None,
    fsync: bool = False,
) -> None:
    """Write ``text`` to ``target`` via tempfile + os.replace."""
    target_path = Path(target)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    mode = _resolve_destination_mode(target_path)
    fd, tmp_name = tempfile.mkstemp(
        prefix=target_path.name + ".", suffix=".tmp", dir=str(target_path.parent)
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline=newline) as fh:
            fh.write(text)
        _fsync_file_if_requested(tmp_path, enabled=fsync)
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, target_path)
    except BaseException:
        with suppress(OSError):
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
    fsync: bool = False,
) -> None:
    """Serialize ``payload`` to JSON and write atomically to ``target``."""
    text = json.dumps(
        payload,
        indent=indent,
        sort_keys=sort_keys,
        ensure_ascii=ensure_ascii,
        default=default,
    )
    atomic_write_text(text, target, fsync=fsync)
