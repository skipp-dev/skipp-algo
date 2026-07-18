"""Entrypoint for the local, shadow-only OPRA sidecar."""

from __future__ import annotations

import json
import logging
import signal
import threading
from pathlib import Path
from typing import Any

import databento_usage
from scripts.smc_atomic_write import atomic_write_json

from .config import load
from .feed import start
from .state import OpraShadowState

logger = logging.getLogger(__name__)


def _append_new_candidates(
    path: Path,
    snapshot: dict[str, Any],
    seen: set[tuple[Any, ...]],
) -> None:
    """Append each processed candidate once to the private local ledger."""
    rows: list[dict[str, Any]] = []
    for candidate in snapshot.get("candidates") or []:
        key = (
            candidate.get("option_symbol"),
            candidate.get("event_ts_ns"),
            candidate.get("size"),
            candidate.get("price"),
        )
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "observed_at": snapshot.get("asof"),
                "session": str(snapshot.get("asof") or "")[:10],
                "ticker": candidate.get("ticker"),
                "event_ts_ns": candidate.get("event_ts_ns"),
                "receive_ts_ns": candidate.get("receive_ts_ns"),
                "data_age_seconds": candidate.get("data_age_seconds"),
                "definition_known": candidate.get("definition_known") is True,
                "aggressor_signed": candidate.get("aggressor_ind") in {"A", "B"},
                "duplicate": False,
                "gap": False,
                "ablation": {
                    "premium": True,
                    "aggressor": candidate.get("aggressor_ind") in {"A", "B"},
                    "cluster": bool(candidate.get("uw_is_sweep")),
                    "full": True,
                },
                "outcome_success": None,
                "shadow_only": True,
            }
        )
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    # A parent-symbol OPRA subscription resolves tens of thousands of option
    # symbols. Databento logs every mapping at INFO, which can exceed Railway's
    # per-replica log limit without adding useful operational evidence.
    logging.getLogger("databento.live.client").setLevel(logging.WARNING)
    config = load()
    if not config.enabled:
        logger.info("OPRA_LIVE_MODE=off; exiting without opening a connection")
        return 0
    state = OpraShadowState(
        hotlist=config.hotlist,
        window_seconds=config.window_seconds,
        min_premium=config.min_premium,
    )
    stop = threading.Event()

    def _stop(_signum: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    thread = start(config, state, stop)
    seen_candidates: set[tuple[Any, ...]] = set()
    try:
        while not stop.wait(config.snapshot_interval_seconds):
            snapshot = state.build_snapshot()
            atomic_write_json(
                snapshot,
                config.snapshot_path,
                sort_keys=True,
            )
            _append_new_candidates(config.ledger_path, snapshot, seen_candidates)
            databento_usage.flush()
    finally:
        stop.set()
        thread.join(timeout=15.0)
        snapshot = state.build_snapshot()
        atomic_write_json(snapshot, config.snapshot_path, sort_keys=True)
        _append_new_candidates(config.ledger_path, snapshot, seen_candidates)
        databento_usage.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
