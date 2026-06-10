"""Per-chart-TF family hit-rate rollup for Plan 2.8 Phase 1 (W8).

Reads all ``scoring_<symbol>_<timeframe>.json`` artifacts under a
measurement-benchmark output directory and produces:

  * per-TF aggregate event counts + hit rates
  * per-TF x per-family hit rates + event counts
  * the two Phase-E2 verdicts the addendum asks for (W8):
      - FVG TTF hypothesis: is FVG HR on 5m materially different from
        the 15m/1H baseline?
      - BOS 4H stability: is BOS HR on 4H >= 15m/1H baseline?

The tool is deliberately plain-Python stdlib + no mutation of the
scoring artifacts. It is meant to be run manually at the end of
Phase 1 and in CI thereafter as a lightweight trend-watch.

Exit codes
----------
  0 = rollup written
  1 = I/O or config error
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

ROLLUP_SCHEMA_VERSION = 1
DEFAULT_TFS = ("5m", "15m", "1H", "4H")
SCORING_RE = re.compile(r"^scoring_(?P<symbol>[^_]+)_(?P<tf>.+)\.json$")


def _iter_scoring_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("scoring_*.json") if p.is_file())


def _family_metrics(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    fam = payload.get("family_metrics") or {}
    if not isinstance(fam, dict):
        return {}
    return {k: v for k, v in fam.items() if isinstance(v, dict)}


def build_rollup(
    *,
    scoring_root: Path,
    timeframes: tuple[str, ...] = DEFAULT_TFS,
) -> dict[str, Any]:
    """Aggregate per-TF and per-TF x per-family metrics under ``scoring_root``.

    Returns a schema_version=1 manifest.
    """
    scoring_root = Path(scoring_root)
    files = _iter_scoring_files(scoring_root) if scoring_root.exists() else []

    per_tf: dict[str, dict[str, Any]] = {
        tf: {
            "n_events": 0,
            "hit_rate_weighted": 0.0,
            "symbols": [],
            "families": {},
        }
        for tf in timeframes
    }
    unknown_tfs: dict[str, int] = {}

    for path in files:
        m = SCORING_RE.match(path.name)
        if not m:
            continue
        tf = m.group("tf")
        symbol = m.group("symbol")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if tf not in per_tf:
            unknown_tfs[tf] = unknown_tfs.get(tf, 0) + 1
            continue

        n = int(payload.get("n_events") or 0)
        hr = float(payload.get("hit_rate") or 0.0)
        slot = per_tf[tf]
        slot["n_events"] += n
        slot["hit_rate_weighted"] += hr * n
        if symbol not in slot["symbols"]:
            slot["symbols"].append(symbol)

        for fam, metrics in _family_metrics(payload).items():
            fam_n = int(metrics.get("n_events") or 0)
            fam_hr = float(metrics.get("hit_rate") or 0.0)
            fslot = slot["families"].setdefault(
                fam, {"n_events": 0, "hit_rate_weighted": 0.0}
            )
            fslot["n_events"] += fam_n
            fslot["hit_rate_weighted"] += fam_hr * fam_n

    # Normalise weighted sums into hit rates.
    for _tf, slot in per_tf.items():
        n = slot["n_events"]
        slot["hit_rate"] = (slot["hit_rate_weighted"] / n) if n else 0.0
        del slot["hit_rate_weighted"]
        for _fam, fslot in slot["families"].items():
            fn = fslot["n_events"]
            fslot["hit_rate"] = (fslot["hit_rate_weighted"] / fn) if fn else 0.0
            del fslot["hit_rate_weighted"]

    return {
        "schema_version": ROLLUP_SCHEMA_VERSION,
        "scoring_root": str(scoring_root),
        "timeframes": list(timeframes),
        "files_scanned": len(files),
        "per_tf": per_tf,
        "unknown_timeframes": unknown_tfs,
        "phase_e2_verdict": _phase_e2_verdict(per_tf),
    }


def _phase_e2_verdict(per_tf: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Render the two Phase-E2 hypothesis checks from the rollup.

    Both verdicts require ``n_events >= 30`` per TF/family slice before
    the comparison is taken seriously — below that the verdict is
    ``insufficient_data`` so downstream automation does not act on
    noise.

    Aliasing guard (2026-06-10 ADR): when the arm-A slice and *every*
    contributing baseline slice carry pairwise-identical ``n_events``
    and ``hit_rate``, the input slices are clones of the same events
    (e.g. the legacy structure artifact served one timeframe's events
    to all TFs) and the comparison would measure an arm against
    itself. Such verdicts are labelled ``degenerate_aliased_input``
    instead of ``measured``; exact equality is intentional because
    clones are byte-identical, while honest slices differ.
    """
    def fam(tf: str, family: str) -> dict[str, Any] | None:
        return (per_tf.get(tf, {}).get("families") or {}).get(family)

    def _cmp(
        a: dict[str, Any] | None,
        b: dict[str, Any] | None,
        *,
        baseline_slices: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if not a or not b:
            return {"status": "missing"}
        if a["n_events"] < 30 or b["n_events"] < 30:
            return {"status": "insufficient_data",
                    "n_a": a["n_events"], "n_b": b["n_events"]}
        if baseline_slices and all(
            c["n_events"] == a["n_events"] and c["hit_rate"] == a["hit_rate"]
            for c in baseline_slices
        ):
            return {
                "status": "degenerate_aliased_input",
                "n_a": a["n_events"], "hr_a": a["hit_rate"],
                "n_b": b["n_events"], "hr_b": b["hit_rate"],
                "reason": (
                    "arm A and every baseline slice carry identical "
                    "n_events/hit_rate; input slices are aliased copies "
                    "(e.g. cross-TF structure fallback), so delta_hr would "
                    "compare an arm against itself"
                ),
            }
        return {
            "status": "measured",
            "n_a": a["n_events"], "hr_a": a["hit_rate"],
            "n_b": b["n_events"], "hr_b": b["hit_rate"],
            "delta_hr": a["hit_rate"] - b["hit_rate"],
        }

    # Baseline = 15m + 1H merged. Zero-event slices contribute no weight
    # and therefore do not count as contributors for the aliasing guard.
    def contributors(family: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for tf in ("15m", "1H"):
            f = fam(tf, family)
            if f is not None and f["n_events"] > 0:
                out.append(f)
        return out

    def baseline(slices: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not slices:
            return None
        merged_n = sum(s["n_events"] for s in slices)
        weighted = sum(s["hit_rate"] * s["n_events"] for s in slices)
        return {"n_events": merged_n, "hit_rate": weighted / merged_n}

    fvg_slices = contributors("FVG")
    bos_slices = contributors("BOS")
    return {
        "fvg_ttf_5m_vs_baseline": _cmp(
            fam("5m", "FVG"), baseline(fvg_slices), baseline_slices=fvg_slices
        ),
        "bos_stability_4h_vs_baseline": _cmp(
            fam("4H", "BOS"), baseline(bos_slices), baseline_slices=bos_slices
        ),
    }


def render_markdown(rollup: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Chart-TF rollup (Plan 2.8 Phase 1)")
    lines.append("")
    lines.append(f"scoring_root: `{rollup['scoring_root']}`")
    lines.append(f"files_scanned: {rollup['files_scanned']}")
    lines.append("")
    lines.append("## Per-TF aggregate")
    lines.append("")
    lines.append("| TF | events | HR | symbols |")
    lines.append("| --- | ---: | ---: | ---: |")
    for tf, slot in rollup["per_tf"].items():
        lines.append(
            f"| `{tf}` | {slot['n_events']} | {slot['hit_rate']:.3f} | {len(slot['symbols'])} |"
        )
    lines.append("")
    lines.append("## Phase E2 verdicts")
    lines.append("")
    for key, verdict in rollup["phase_e2_verdict"].items():
        status = verdict.get("status", "?")
        extras = " ".join(f"{k}={v}" for k, v in verdict.items() if k != "status")
        lines.append(f"- **{key}**: {status} {extras}")
    return "\n".join(lines)

# F-V6-A1.1 (2026-05-02): bootstrap root logging so the logger.info(...)
# progress messages this entry point emits actually surface in CI logs
# (default WARNING-only handler would drop them). Extends F-V5-A1-2 / #2012
# from the priority entry-point set to plan_2_8 aggregators + showcase.
try:
    from scripts._logging_init import init_cli_logging
except ImportError:  # script-style invocation: `python scripts/X.py`
    import sys as _v6a11_sys
    from pathlib import Path as _v6a11_Path

    _v6a11_sys.path.insert(0, str(_v6a11_Path(__file__).resolve().parents[1]))
    from scripts._logging_init import init_cli_logging  # type: ignore[no-redef]




def main(argv: list[str] | None = None) -> int:
    init_cli_logging()  # F-V6-A1.1 (2026-05-02)
    parser = argparse.ArgumentParser(
        description="Per-TF family hit-rate rollup (Plan 2.8 Phase 1)",
    )
    parser.add_argument("--scoring-root", type=Path, required=True,
                        help="Directory tree containing scoring_<sym>_<tf>.json artifacts.")
    parser.add_argument("--timeframes", default=",".join(DEFAULT_TFS),
                        help="Comma-separated TFs to include (default: 5m,15m,1H,4H).")
    parser.add_argument("--output", type=Path, default=None,
                        help="Optional manifest JSON output path.")
    parser.add_argument("--format", choices=("md", "json"), default="md",
                        help="Stdout format (default: md).")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress stdout body; still writes --output if given.")
    args = parser.parse_args(argv)

    tfs = tuple(t.strip() for t in args.timeframes.split(",") if t.strip())
    try:
        rollup = build_rollup(scoring_root=args.scoring_root, timeframes=tfs)
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(json.dumps(rollup, indent=2) + "\n", args.output)

    if not args.quiet:
        if args.format == "md":
            print(render_markdown(rollup))
        else:
            print(json.dumps(rollup, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
