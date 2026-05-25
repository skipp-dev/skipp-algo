"""Markdown diff summary between two frozen contextual-calibration artifacts.

Used by ``.github/workflows/f2-frozen-artifact-bootstrap.yml`` to assemble
the PR body when the bot opens a regenerated-artifact PR. Pure stdlib so
the workflow does not need to install extra deps before invoking it.

The two inputs are JSON artifacts produced by
``scripts/smc_zone_priority_calibration.py --frozen`` with the schema
consumed by ``scripts.f2_apply_contextual_calibration`` — relevant keys:
``global_weights``, ``promoted_buckets``, ``frozen_at`` (+ optional
``corpus_manifest_hash`` and ``n_events``). The two manifest paths
(``--old-manifest`` / ``--new-manifest``) point at the sibling
``benchmark_run_manifest.json`` from the rolling benchmark run that
fed each artifact; they supply the ``n_events`` delta.

If ``--old`` is missing or cannot be read (first-bootstrap case), the
helper emits a single ``no prior artifact, full snapshot`` section
instead of a diff and exits 0.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _load_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _fmt_delta(old: float | None, new: float | None) -> str:
    if old is None and new is None:
        return "n/a"
    if old is None:
        return f"(new) {new:.4f}"
    if new is None:
        return f"(removed) was {old:.4f}"
    diff = new - old
    sign = "+" if diff >= 0 else ""
    return f"{old:.4f} → {new:.4f} ({sign}{diff:.4f})"


def _global_weights_section(
    old: dict[str, Any] | None, new: dict[str, Any]
) -> list[str]:
    new_w = {str(k): float(v) for k, v in (new.get("global_weights") or {}).items()}
    old_w = (
        {str(k): float(v) for k, v in (old.get("global_weights") or {}).items()}
        if old
        else {}
    )
    keys = sorted(set(new_w) | set(old_w))
    if not keys:
        return ["_no global_weights present_"]
    lines = ["| family | old → new (Δ) |", "| --- | --- |"]
    for k in keys:
        lines.append(f"| `{k}` | {_fmt_delta(old_w.get(k), new_w.get(k))} |")
    return lines


def _promoted_buckets_section(
    old: dict[str, Any] | None, new: dict[str, Any]
) -> list[str]:
    new_b = set(new.get("promoted_buckets") or [])
    old_b = set((old or {}).get("promoted_buckets") or [])
    added = sorted(new_b - old_b)
    removed = sorted(old_b - new_b)
    kept = sorted(new_b & old_b)
    lines = [
        f"- **added** ({len(added)}): "
        + (", ".join(f"`{b}`" for b in added) if added else "_none_"),
        f"- **removed** ({len(removed)}): "
        + (", ".join(f"`{b}`" for b in removed) if removed else "_none_"),
        f"- **kept** ({len(kept)}): "
        + (", ".join(f"`{b}`" for b in kept) if kept else "_none_"),
    ]
    return lines


def _n_events_line(
    old_manifest: dict[str, Any] | None, new_manifest: dict[str, Any] | None
) -> str:
    def _extract(m: dict[str, Any] | None) -> int | None:
        if m is None:
            return None
        for key in ("n_events", "total_events", "event_count"):
            if key in m and isinstance(m[key], (int, float)):
                return int(m[key])
        return None

    old_n = _extract(old_manifest)
    new_n = _extract(new_manifest)
    if old_n is None and new_n is None:
        return "- **n_events**: n/a (manifests missing or schema differs)"
    if old_n is None:
        return f"- **n_events**: (new) {new_n}"
    if new_n is None:
        return f"- **n_events**: (removed) was {old_n}"
    diff = new_n - old_n
    sign = "+" if diff >= 0 else ""
    return f"- **n_events**: {old_n} → {new_n} ({sign}{diff})"


def _frozen_at_line(old: dict[str, Any] | None, new: dict[str, Any]) -> str:
    new_f = new.get("frozen_at") or "n/a"
    old_f = (old or {}).get("frozen_at") or "n/a"
    return f"- **frozen_at**: `{old_f}` → `{new_f}`"


def build_markdown(
    *,
    old: dict[str, Any] | None,
    new: dict[str, Any],
    old_manifest: dict[str, Any] | None,
    new_manifest: dict[str, Any] | None,
) -> str:
    if old is None:
        body = [
            "## f2 frozen-artifact bootstrap — full snapshot",
            "",
            "_no prior artifact, full snapshot_",
            "",
            "### promoted_buckets",
            *_promoted_buckets_section(None, new),
            "",
            "### global_weights",
            *_global_weights_section(None, new),
            "",
            "### metadata",
            _frozen_at_line(None, new),
            _n_events_line(None, new_manifest),
        ]
        return "\n".join(body) + "\n"

    new_w = {str(k): float(v) for k, v in (new.get("global_weights") or {}).items()}
    old_w = {str(k): float(v) for k, v in (old.get("global_weights") or {}).items()}
    no_change = (
        new_w == old_w
        and set(new.get("promoted_buckets") or []) == set(old.get("promoted_buckets") or [])
        and (new.get("frozen_at") == old.get("frozen_at"))
    )
    header = (
        "## f2 frozen-artifact bootstrap — no change vs. prior artifact"
        if no_change
        else "## f2 frozen-artifact bootstrap — diff vs. prior artifact"
    )
    body = [
        header,
        "",
        "### promoted_buckets",
        *_promoted_buckets_section(old, new),
        "",
        "### global_weights",
        *_global_weights_section(old, new),
        "",
        "### metadata",
        _frozen_at_line(old, new),
        _n_events_line(old_manifest, new_manifest),
    ]
    return "\n".join(body) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--old", type=Path, default=None)
    p.add_argument("--new", type=Path, required=True)
    p.add_argument("--old-manifest", type=Path, default=None)
    p.add_argument("--new-manifest", type=Path, default=None)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)

    new = _load_json(args.new)
    if new is None:
        print(f"::error::cannot read --new artifact: {args.new}", file=sys.stderr)
        return 2

    md = build_markdown(
        old=_load_json(args.old),
        new=new,
        old_manifest=_load_json(args.old_manifest),
        new_manifest=_load_json(args.new_manifest),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(md, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
