"""Fail-closed environment configuration for the OPRA shadow daemon."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from databento_dataset_policy import DatasetMode, DatasetRole, resolve_dataset


@dataclass(frozen=True)
class Config:
    mode: str
    api_key: str
    dataset: str
    schema: str
    hotlist: tuple[str, ...]
    hotlist_path: Path | None
    snapshot_path: Path
    ledger_path: Path
    window_seconds: int
    snapshot_interval_seconds: float
    min_premium: float

    @property
    def enabled(self) -> bool:
        return self.mode == "shadow"


def load() -> Config:
    mode = os.getenv("OPRA_LIVE_MODE", "off").strip().lower()
    if mode not in {"off", "shadow"}:
        raise ValueError("OPRA_LIVE_MODE must be 'off' or 'shadow'")
    dataset = resolve_dataset(
        DatasetRole.OPTIONS_LIVE,
        requested_dataset=os.getenv("DATABENTO_OPTIONS_LIVE_DATASET") or "OPRA.PILLAR",
        schema="tcbbo",
        mode=DatasetMode.LIVE,
    )
    hotlist_path_raw = os.getenv("OPRA_LIVE_HOTLIST_PATH", "").strip()
    hotlist_path = Path(hotlist_path_raw) if hotlist_path_raw else None
    hotlist = tuple(
        dict.fromkeys(
            ticker.strip().upper()
            for ticker in os.getenv("OPRA_LIVE_HOTLIST", "SPY,QQQ,AAPL,NVDA,TSLA").split(",")
            if ticker.strip()
        )
    )
    if hotlist_path is not None and hotlist_path.exists():
        hotlist = read_hotlist_file(hotlist_path)
    if mode == "shadow" and not hotlist:
        raise ValueError("OPRA_LIVE_HOTLIST must not be empty in shadow mode")
    key = os.getenv("DATABENTO_API_KEY", "").strip()
    if mode == "shadow" and not key:
        raise ValueError("DATABENTO_API_KEY is required in shadow mode")
    return Config(
        mode=mode,
        api_key=key,
        dataset=dataset,
        schema="tcbbo",
        hotlist=hotlist,
        hotlist_path=hotlist_path,
        snapshot_path=Path(
            os.getenv(
                "OPRA_LIVE_SNAPSHOT_PATH",
                "artifacts/monitoring/opra_live_shadow.json",
            )
        ),
        ledger_path=Path(
            os.getenv(
                "OPRA_SHADOW_LEDGER_PATH",
                "artifacts/monitoring/opra_shadow_ledger.jsonl",
            )
        ),
        window_seconds=max(60, int(os.getenv("OPRA_LIVE_WINDOW_SECONDS", "900"))),
        snapshot_interval_seconds=max(
            1.0, float(os.getenv("OPRA_LIVE_SNAPSHOT_INTERVAL_SECONDS", "5"))
        ),
        min_premium=max(0.0, float(os.getenv("OPRA_LIVE_MIN_PREMIUM", "25000"))),
    )


def read_hotlist_file(path: Path) -> tuple[str, ...]:
    """Read a newline/comma-separated local parent-symbol hotlist."""
    values = path.read_text(encoding="utf-8").replace("\n", ",").split(",")
    return tuple(
        dict.fromkeys(value.strip().upper() for value in values if value.strip())
    )
