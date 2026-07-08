"""Audit guard: the 5-minute ``smc-live-news-refresh`` cron must not
``cancel-in-progress`` — killing an in-flight NewsAPI page-iteration
mid-call wastes the quota spent on the partial fetch and can leave a
half-written snapshot. Serialising the ticks costs at most one delayed
run per overrun.

Audit marker: F-V5-C1 (2026-05-01).
"""
from __future__ import annotations

import pathlib

import yaml

_WORKFLOW = (
    pathlib.Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "smc-live-news-refresh.yml"
)


def test_newsapi_refresh_does_not_cancel_in_progress() -> None:
    data = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    concurrency = data.get("concurrency")
    assert isinstance(concurrency, dict), (
        "smc-live-news-refresh.yml: top-level `concurrency:` block "
        "missing — required to serialise the 5-min cron (F-V5-C1)."
    )
    assert concurrency.get("cancel-in-progress") is False, (
        "smc-live-news-refresh.yml: `cancel-in-progress` must be "
        "`false` for the 5-min cron — killing in-flight NewsAPI fetches "
        "wastes quota and risks half-written snapshots (F-V5-C1)."
    )
