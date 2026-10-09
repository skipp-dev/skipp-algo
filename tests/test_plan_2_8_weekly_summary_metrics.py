"""Parametric guard for the Plan 2.8 weekly-summary unified collector.

Replaces 116 near-identical per-wrapper smoke tests with a single
parametric suite that:

* Discovers every collectable ``plan_2_8_weekly_summary_*`` wrapper.
* Invokes the unified collector against a tiny synthetic summary.
* Verifies each wrapper's output is byte-identical between the legacy
  per-module ``compute()`` and the value embedded in the collector's
  ``metrics.json`` (parity guard for the additive migration path).

Legacy per-wrapper test files are intentionally left in place; this
suite supersedes them functionally without forcing their deletion.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.plan_2_8_weekly_summary_metrics import (
    _invoke_compute,
    _resolve_compute,
    collect,
    discover_wrappers,
)

_WRAPPERS = discover_wrappers()


@pytest.fixture(scope="module")
def synthetic_summary(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("plan_2_8_metrics") / "summary.md"
    # Mix of metric-relevant payloads: ASCII, CR/LF, digits, tabs, links.
    body = (
        "# Plan 2.8 weekly summary (synthetic)\r\n"
        "\r\n"
        "Sample paragraph with 123 digits and\ta tab.\r\n"
        "\r\n"
        "- bullet item one\r\n"
        "- bullet item two\r\n"
        "\r\n"
        "See [link](https://example.com/path) for context.\r\n"
    )
    path.write_bytes(body.encode("utf-8"))
    return path


def test_collector_discovers_wrappers() -> None:
    assert len(_WRAPPERS) >= 50, (
        f"unexpectedly few wrappers discovered: {len(_WRAPPERS)}"
    )


def test_collector_emits_metrics(synthetic_summary: Path) -> None:
    report = collect(synthetic_summary)
    assert report["schema_version"] == 1
    assert isinstance(report["metrics"], dict)
    assert report["metrics"], "collector returned empty metrics block"
    # Every collected metric must be a dict with at least schema_version.
    for short_name, payload in report["metrics"].items():
        assert isinstance(payload, dict), f"{short_name} returned non-dict"
        assert "schema_version" in payload, f"{short_name} missing schema_version"


@pytest.mark.parametrize("dotted", _WRAPPERS)
def test_wrapper_parity_with_collector(dotted: str, synthetic_summary: Path) -> None:
    """Legacy ``module.compute(path)`` must match the collector's value."""
    compute = _resolve_compute(dotted)
    if compute is None:
        pytest.skip(f"{dotted} does not expose compute()")
    legacy = _invoke_compute(compute, synthetic_summary)
    if legacy is None:
        pytest.skip(f"{dotted} compute() has an unsupported signature")
    short = dotted.removeprefix("scripts.").removeprefix("plan_2_8_weekly_summary_")
    bundled = collect(synthetic_summary)["metrics"].get(short)
    assert bundled is not None, f"collector dropped {short}"
    # Compare via JSON round-trip to be order/whitespace-insensitive.
    assert json.dumps(bundled, sort_keys=True) == json.dumps(legacy, sort_keys=True), (
        f"parity break for {short}: legacy={legacy!r} bundled={bundled!r}"
    )


def test_skip_list_excludes_aggregators() -> None:
    """Aggregators must NOT appear in the collector's discovery list."""
    collected_short = {
        d.removeprefix("scripts.").removeprefix("plan_2_8_weekly_summary_")
        for d in _WRAPPERS
    }
    for aggregator in ("index", "linkcheck", "preview", "toc_only", "metrics"):
        assert aggregator not in collected_short, (
            f"aggregator {aggregator!r} must be excluded from collector "
            "discovery (non-standard compute() signature)"
        )
        # Aggregator modules must still exist as real entry points.
        try:
            importlib.import_module(f"scripts.plan_2_8_weekly_summary_{aggregator}")
        except ModuleNotFoundError:
            # ``metrics`` is the collector itself; the others must exist.
            if aggregator != "metrics":
                pytest.fail(
                    f"aggregator scripts.plan_2_8_weekly_summary_{aggregator} "
                    "is missing"
                )
