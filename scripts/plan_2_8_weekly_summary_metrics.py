#!/usr/bin/env python3
"""Unified collector for the Plan 2.8 weekly summary metric wrappers.

Background
==========

The repo currently ships ~120 ``scripts/plan_2_8_weekly_summary_*.py``
modules, each computing a single trivial metric (CRLF count, digit count,
etc.) via a per-module ``compute(path) -> dict`` function. The weekly
digest workflow invokes one step per wrapper, which inflates
``plan-2-8-weekly-digest.yml`` to ~4200 lines and makes wrapper drift the
dominant cost of weekly-digest maintenance.

This collector imports every wrapper that exposes the standard
``compute(path: Path) -> dict`` contract and emits a single JSON document
with all metric outputs keyed by their wrapper module's short name
(e.g. ``crlf_count``, ``digit_count``). Aggregators with a non-standard
shape — ``plan_2_8_weekly_summary_index``, ``...linkcheck``,
``...preview``, ``...toc_only`` — are skipped intentionally.

This entry point is **additive**: the legacy per-wrapper scripts and the
weekly-digest workflow are unchanged. Downstream artifact consumers can
migrate to ``metrics.json`` incrementally; nothing breaks today.

Usage
-----

::

    python scripts/plan_2_8_weekly_summary_metrics.py \\
        --summary docs/plan/plan-2-8-weekly-summary.md \\
        --output artifacts/plan_2_8/weekly_summary_metrics.json
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

REPO_ROOT = Path(__file__).resolve().parent.parent

# Aggregators / non-trivial wrappers that do not expose the standard
# ``compute(path: Path) -> dict`` contract and must NOT be invoked
# through this collector. Each is a real entry point in its own right.
_SKIP_SUFFIXES: frozenset[str] = frozenset(
    {
        "index",
        "linkcheck",
        "link_check",
        "preview",
        "toc_only",
        "metrics",  # this file itself
    }
)


def _wrapper_short_name(module_name: str) -> str:
    """Strip the ``plan_2_8_weekly_summary_`` prefix from a module name."""
    return module_name.removeprefix("plan_2_8_weekly_summary_")


def discover_wrappers() -> list[str]:
    """Return sorted dotted module names of every potentially collectable wrapper."""
    scripts_dir = REPO_ROOT / "scripts"
    out: list[str] = []
    for path in sorted(scripts_dir.glob("plan_2_8_weekly_summary_*.py")):
        short = _wrapper_short_name(path.stem)
        if short in _SKIP_SUFFIXES:
            continue
        out.append(f"scripts.{path.stem}")
    return out


def _resolve_compute(dotted: str) -> Callable[..., dict[str, Any]] | None:
    """Import a wrapper module and return its ``compute`` callable, if any."""
    module = importlib.import_module(dotted)
    fn = getattr(module, "compute", None)
    if callable(fn):
        return fn
    return None


def _invoke_compute(
    fn: Callable[..., dict[str, Any]], summary: Path
) -> dict[str, Any] | None:
    """Call ``fn`` with the right argument shape, or return None if incompatible.

    Three accepted shapes (covers ~112 of the 116 wrappers):

    * ``compute(path: Path)`` / ``compute(summary_path: Path)`` → pass the path
    * ``compute(text: str)`` → pass the summary file contents as text
    * anything that requires additional non-default arguments → skipped
    """
    sig = inspect.signature(fn)
    required = [
        p
        for p in sig.parameters.values()
        if p.default is inspect.Parameter.empty
        and p.kind
        not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
    ]
    if len(required) != 1:
        return None
    only = required[0]
    if only.kind == inspect.Parameter.KEYWORD_ONLY:
        return None
    annotation = only.annotation
    annotation_str = getattr(annotation, "__name__", str(annotation))
    if annotation is str or annotation_str == "str":
        text = summary.read_text(encoding="utf-8") if summary.is_file() else ""
        return fn(text)
    # Default: treat as a path (covers Path, "Path", inspect._empty, etc.).
    return fn(summary)


def collect(summary: Path) -> dict[str, Any]:
    """Invoke every signature-compatible wrapper against ``summary``.

    Returns a dict::

        {
          "schema_version": 1,
          "summary_path": "<path-as-passed>",
          "metrics": { "<short_name>": { ...wrapper output... }, ... },
          "skipped": [ "<dotted-module>", ... ],   # missing or unsupported compute()
        }
    """
    metrics: dict[str, dict[str, Any]] = {}
    skipped: list[str] = []
    for dotted in discover_wrappers():
        compute = _resolve_compute(dotted)
        if compute is None:
            skipped.append(dotted)
            continue
        result = _invoke_compute(compute, summary)
        if result is None:
            skipped.append(dotted)
            continue
        short = _wrapper_short_name(dotted.removeprefix("scripts."))
        metrics[short] = result
    return {
        "schema_version": 1,
        "summary_path": str(summary),
        "metrics": metrics,
        "skipped": skipped,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.summary.exists():
        print(f"ERROR: summary not found: {args.summary}", file=sys.stderr)
        return 1

    report = collect(args.summary)
    body = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(body, args.output)
    print(body, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
