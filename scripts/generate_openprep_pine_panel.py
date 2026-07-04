"""Generate ``pine/generated/openprep_daily_panel.pine`` — the daily open-prep
watchlist + market-weather panel (Workstream B1 of
``OPENPREP_PINE_REGIME_IMPLEMENTATION_PLAN.md``).

Pine Script cannot fetch external data, so the panel is a **generated**
indicator with the last open-prep run baked in as constants, published to
TradingView daily. This writer reads one ``outcomes_YYYY-MM-DD.json`` (the
Phase-1 outcome file that now carries ``market_weather`` + the microstructure
metrics per row) and emits a Pine v6 indicator that draws a table:

* a header with the run date, a weather traffic light + plain-language label,
  and the regime;
* one row per watchlist candidate (symbol, playbook, direction, score, tier,
  gap %, RVOL), highlighting the chart's own symbol when it is on the list;
* a footer with the three microstructure metrics;
* a **freshness guard** that greys the panel and shows a warning when the
  baked data is more than one trading day old.

Observe-only: the panel *shows* the run; it never drives scoring or playbook
selection.

Defensive on missing inputs: with no usable outcomes file it writes a
deterministic "awaiting data" stub that still parses as Pine, so the
scheduled publish workflow stays green on a clean checkout.

Exit codes:
* 0 — Pine panel written (even for the empty/stub case)
* 1 — fatal error (cannot read input, cannot write output)
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Bootstrap repo root onto sys.path BEFORE the first-party
# ``from scripts._logging_init`` import so this file works under both
# ``python -m scripts.X`` and ``python scripts/X.py``. The unconditional
# literal ``sys.path.insert`` also satisfies
# tests/test_workflow_invoked_scripts_import_order.py (mirrors
# scripts/emit_fvg_context_pine.py).
import os as _bootstrap_os
import sys as _bootstrap_sys_mod

sys = _bootstrap_sys_mod

_BOOTSTRAP_ROOT = _bootstrap_os.path.dirname(
    _bootstrap_os.path.dirname(_bootstrap_os.path.abspath(__file__))
)
if _BOOTSTRAP_ROOT not in sys.path:
    sys.path.insert(0, _BOOTSTRAP_ROOT)

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from open_prep.market_microstructure import weather_badge_label
from scripts._logging_init import init_cli_logging

PINE_HEADER = "//@version=6"
DEFAULT_OUTPUT = Path("pine/generated/openprep_daily_panel.pine")
DEFAULT_OUTCOMES_DIR = Path("artifacts/open_prep/outcomes")
MAX_ROWS = 12  # Pine table stays readable; excess candidates are dropped.


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def discover_latest_outcomes(search_dir: Path) -> Path | None:
    """Return the newest ``outcomes_*.json`` by filename (dates sort
    lexicographically), or ``None`` when the directory has none."""
    if not search_dir.is_dir():
        return None
    candidates = sorted(search_dir.glob("outcomes_*.json"))
    return candidates[-1] if candidates else None


def extract_panel(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Reduce outcome rows to the panel's data model.

    Market-wide fields (date, regime, weather, microstructure metrics) are
    identical across a run's rows, so they are read from the first row.
    Per-candidate fields become one entry each, sorted by score descending
    and capped at ``MAX_ROWS``.
    """
    if not rows:
        return {"date": None, "candidates": []}

    head = rows[0]
    regime = head.get("regime")
    if regime is None:
        regime = head.get("regime_at_entry")
    candidates: list[dict[str, Any]] = []
    for row in rows:
        symbol = row.get("symbol")
        if not symbol:
            continue
        candidates.append(
            {
                "symbol": str(symbol).upper(),
                "score": _safe_float(row.get("score")) or 0.0,
                "tier": str(row.get("confidence_tier") or "-"),
                "playbook": str(row.get("playbook_name") or "-"),
                "direction": str(row.get("direction") or "-"),
                "gap_pct": _safe_float(row.get("gap_pct")),
                "rvol": _safe_float(row.get("rvol")),
            }
        )
    candidates.sort(key=lambda c: c["score"], reverse=True)

    return {
        "date": head.get("date"),
        "regime": str(regime if regime is not None else "-"),
        "weather": str(head.get("market_weather") or "UNKNOWN").upper(),
        "er_daily": _safe_float(head.get("market_efficiency_ratio")),
        "er_intraday": _safe_float(head.get("intraday_efficiency_ratio")),
        "dispersion": _safe_float(head.get("cs_dispersion")),
        "correlation": _safe_float(head.get("avg_pair_correlation")),
        "candidates": candidates[:MAX_ROWS],
    }


def _q(value: str) -> str:
    """Emit a Pine string literal (double-quoted, escaped) from *value*.

    Pine string escaping matches JSON's for the characters we emit, so
    ``json.dumps`` produces a valid Pine literal. ``ensure_ascii=False`` keeps
    the weather emoji as a literal UTF-8 char (Pine renders it; ``\\uXXXX``
    surrogate escapes it would not); the file is written UTF-8.
    """
    return json.dumps(value, ensure_ascii=False)


def _pine_float(value: float | None, nd: int = 4) -> str:
    return "na" if value is None else f"{round(value, nd)}"


def _pine_str_array(name: str, values: list[str]) -> str:
    if not values:
        return f"var array<string> {name} = array.new<string>()"
    body = ", ".join(_q(v) for v in values)
    return f"var array<string> {name} = array.from({body})"


def _pine_float_array(name: str, values: list[float | None]) -> str:
    if not values:
        return f"var array<float> {name} = array.new<float>()"
    body = ", ".join(_pine_float(v) for v in values)
    return f"var array<float> {name} = array.from({body})"


def build_pine(panel: dict[str, Any], *, generated_at: str, source: str,
               commit_sha: str | None) -> str:
    """Render the deterministic Pine v6 panel for *panel*."""
    date = panel.get("date")
    cands = panel.get("candidates", [])
    weather = str(panel.get("weather") or "UNKNOWN").upper()
    badge, weather_label = weather_badge_label(weather)

    # Split the ISO date into ints for the freshness timestamp; fall back to
    # a clearly-stale sentinel so a malformed/absent date greys the panel.
    year = month = day = 0
    if isinstance(date, str) and len(date) >= 10:
        try:
            year, month, day = (int(date[0:4]), int(date[5:7]), int(date[8:10]))
        except ValueError:
            year = month = day = 0

    header = [
        PINE_HEADER,
        "// AUTOGENERATED by scripts/generate_openprep_pine_panel.py — DO NOT EDIT BY HAND.",
        "// Open-Prep daily watchlist + market-weather panel (plan Workstream B1).",
        f"// generated_at: {generated_at}",
        f"// source_outcomes: {source}",
        f"// source_commit_sha: {commit_sha or 'unknown'}",
        f"// candidates: {len(cands)}",
        "",
        'indicator("Open-Prep Daily Panel", overlay = true)',
        "",
    ]

    consts = [
        "// ── Baked-in snapshot from the last open-prep run ──────────────────",
        f"var string PANEL_DATE    = {_q(str(date) if date else 'n/a')}",
        f"var int    PANEL_YEAR    = {year}",
        f"var int    PANEL_MONTH   = {month}",
        f"var int    PANEL_DAY     = {day}",
        f"var string PANEL_REGIME  = {_q(str(panel.get('regime') or '-'))}",
        f"var string PANEL_WEATHER = {_q(weather)}",
        f"var string PANEL_WLABEL  = {_q(badge + ' ' + weather_label)}",
        f"var float  PANEL_ER_D    = {_pine_float(panel.get('er_daily'))}",
        f"var float  PANEL_ER_I    = {_pine_float(panel.get('er_intraday'))}",
        f"var float  PANEL_DISP    = {_pine_float(panel.get('dispersion'))}",
        f"var float  PANEL_CORR    = {_pine_float(panel.get('correlation'))}",
        "",
        _pine_str_array("P_SYM", [c["symbol"] for c in cands]),
        _pine_float_array("P_SCORE", [c["score"] for c in cands]),
        _pine_str_array("P_TIER", [c["tier"] for c in cands]),
        _pine_str_array("P_PLAY", [c["playbook"] for c in cands]),
        _pine_str_array("P_DIR", [c["direction"] for c in cands]),
        _pine_float_array("P_GAP", [c["gap_pct"] for c in cands]),
        _pine_float_array("P_RVOL", [c["rvol"] for c in cands]),
        "",
    ]

    body = [
        "// ── Freshness guard: grey out when data is > 1 trading day old ──────",
        "panel_ts = PANEL_YEAR > 0 ? timestamp(PANEL_YEAR, PANEL_MONTH, PANEL_DAY, 0, 0) : 0",
        "age_days = panel_ts > 0 ? (timenow - panel_ts) / 86400000.0 : 1.0e9",
        "is_stale = age_days > 3.0  // 1 trading day + weekend buffer",
        "",
        "// ── Weather traffic-light colour ───────────────────────────────────",
        "weather_col = PANEL_WEATHER == \"GREEN\" ? color.new(color.green, 0) :"
        " PANEL_WEATHER == \"YELLOW\" ? color.new(color.orange, 0) :"
        " PANEL_WEATHER == \"RED\" ? color.new(color.red, 0) : color.new(color.gray, 0)",
        "weather_col_eff = is_stale ? color.new(color.gray, 40) : weather_col",
        "",
        "// ── Chart-symbol highlight ─────────────────────────────────────────",
        "chart_row = -1",
        "if array.size(P_SYM) > 0",
        "    for i = 0 to array.size(P_SYM) - 1",
        "        if syminfo.ticker == array.get(P_SYM, i)",
        "            chart_row := i",
        "",
        "n = array.size(P_SYM)",
        "rows = n < 1 ? 4 : n + 3  // header + col-headers + candidates + footer",
        "var table t = table.new(position.top_right, 7, rows, border_width = 1)",
        "var array<string> hdrs = array.from(\"Symbol\", \"Playbook\", \"Dir\", \"Score\", \"Tier\", \"Gap%\", \"RVOL\")",
        "",
        "if barstate.islast",
        "    txt_col = is_stale ? color.new(color.gray, 0) : color.white",
        "    hdr_bg = is_stale ? color.new(color.gray, 30) : color.new(color.navy, 20)",
        "",
        "    // Row 0 — header: date, weather badge, regime, freshness",
        "    table.cell(t, 0, 0, \"OPEN-PREP\", text_color = txt_col, bgcolor = hdr_bg, text_size = size.small)",
        "    table.cell(t, 1, 0, PANEL_DATE, text_color = txt_col, bgcolor = hdr_bg, text_size = size.small)",
        "    table.cell(t, 2, 0, PANEL_WLABEL, text_color = color.white, bgcolor = weather_col_eff, text_size = size.small)",
        "    table.cell(t, 3, 0, \"Regime\", text_color = color.gray, bgcolor = hdr_bg, text_size = size.small)",
        "    table.cell(t, 4, 0, PANEL_REGIME, text_color = txt_col, bgcolor = hdr_bg, text_size = size.small)",
        "    table.cell(t, 5, 0, chart_row >= 0 ? \"auf Watchlist\" : \"\", text_color = color.yellow, bgcolor = hdr_bg, text_size = size.small)",
        "    table.cell(t, 6, 0, is_stale ? \"VERALTET\" : \"live\", text_color = is_stale ? color.orange : color.lime, bgcolor = hdr_bg, text_size = size.small)",
        "",
        "    // Row 1 — column headers",
        "    for c = 0 to 6",
        "        table.cell(t, c, 1, array.get(hdrs, c), text_color = color.gray, bgcolor = color.new(color.navy, 40), text_size = size.tiny)",
        "",
        "    // Candidate rows",
        "    if n == 0",
        "        table.cell(t, 0, 2, \"keine Kandidaten heute\", text_color = color.gray, text_size = size.small)",
        "    else",
        "        for i = 0 to n - 1",
        "            r = i + 2",
        "            is_me = i == chart_row",
        "            row_bg = is_me ? color.new(color.yellow, 75) : color.new(color.black, 100)",
        "            dir = array.get(P_DIR, i)",
        "            dir_col = dir == \"long\" ? color.lime : dir == \"short\" ? color.red : color.gray",
        "            gapv = array.get(P_GAP, i)",
        "            rvolv = array.get(P_RVOL, i)",
        "            table.cell(t, 0, r, array.get(P_SYM, i), text_color = is_me ? color.yellow : txt_col, bgcolor = row_bg, text_size = size.small)",
        "            table.cell(t, 1, r, array.get(P_PLAY, i), text_color = txt_col, bgcolor = row_bg, text_size = size.tiny)",
        "            table.cell(t, 2, r, dir, text_color = dir_col, bgcolor = row_bg, text_size = size.tiny)",
        "            table.cell(t, 3, r, str.tostring(array.get(P_SCORE, i), \"#.##\"), text_color = txt_col, bgcolor = row_bg, text_size = size.small)",
        "            table.cell(t, 4, r, array.get(P_TIER, i), text_color = color.gray, bgcolor = row_bg, text_size = size.tiny)",
        "            table.cell(t, 5, r, na(gapv) ? \"n/a\" : str.tostring(gapv, \"#.##\") + \"%\", text_color = txt_col, bgcolor = row_bg, text_size = size.tiny)",
        "            table.cell(t, 6, r, na(rvolv) ? \"n/a\" : str.tostring(rvolv, \"#.##\"), text_color = txt_col, bgcolor = row_bg, text_size = size.tiny)",
        "",
        "    // Footer — microstructure metrics",
        "    fr = n < 1 ? 3 : n + 2",
        "    footer = \"ER_1h \" + (na(PANEL_ER_I) ? \"n/a\" : str.tostring(PANEL_ER_I, \"#.###\")) + \"  Disp \" + (na(PANEL_DISP) ? \"n/a\" : str.tostring(PANEL_DISP, \"#.##\")) + \"  Corr \" + (na(PANEL_CORR) ? \"n/a\" : str.tostring(PANEL_CORR, \"#.##\"))",
        "    table.cell(t, 0, fr, footer, text_color = color.gray, bgcolor = color.new(color.navy, 60), text_size = size.tiny)",
        "",
    ]

    return "\n".join(header + consts + body) + "\n"


def write_outputs(snippet: str, panel: dict[str, Any], output_path: Path) -> Path:
    """Atomically write the Pine panel + a JSON sidecar for auditability."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    # ATOMIC-WRITE-EXEMPT: tmp+replace pattern (atomic by construction).
    tmp_path.write_text(snippet, encoding="utf-8")
    tmp_path.replace(output_path)

    sidecar_path = output_path.with_suffix(".json")
    tmp_sidecar = sidecar_path.with_suffix(sidecar_path.suffix + ".tmp")
    # ATOMIC-WRITE-EXEMPT: tmp+replace pattern (atomic by construction).
    tmp_sidecar.write_text(
        json.dumps(panel, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    tmp_sidecar.replace(sidecar_path)
    return sidecar_path


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Emit pine/generated/openprep_daily_panel.pine (plan B1).",
    )
    parser.add_argument(
        "--outcomes-json",
        type=Path,
        default=None,
        help="Explicit outcomes_YYYY-MM-DD.json path. Default: newest under "
             f"{DEFAULT_OUTCOMES_DIR}.",
    )
    parser.add_argument(
        "--outcomes-dir",
        type=Path,
        default=DEFAULT_OUTCOMES_DIR,
        help=f"Directory scanned for the newest outcomes file when "
             f"--outcomes-json is omitted (default: {DEFAULT_OUTCOMES_DIR}).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Destination Pine file (default: {DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "--commit-sha",
        default=os.environ.get("GITHUB_SHA"),
        help="Source commit SHA (default: $GITHUB_SHA).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    init_cli_logging()
    args = _parse_args(argv)

    src_path = args.outcomes_json or discover_latest_outcomes(args.outcomes_dir)

    rows: list[dict[str, Any]] = []
    if src_path is not None and src_path.is_file():
        try:
            loaded = json.loads(src_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"ERROR: cannot read outcomes input {src_path}: {exc}", file=sys.stderr)
            return 1
        if isinstance(loaded, list):
            rows = [r for r in loaded if isinstance(r, dict)]
        else:
            logger.warning("Outcomes file %s is not a list; emitting stub panel.", src_path)
    else:
        logger.warning("No outcomes file found; emitting stub panel.")

    panel = extract_panel(rows)

    snippet = build_pine(
        panel,
        generated_at=datetime.now(UTC).isoformat(),
        source=str(src_path) if src_path else "none",
        commit_sha=args.commit_sha,
    )

    try:
        sidecar = write_outputs(snippet, panel, args.output)
    except OSError as exc:
        print(f"ERROR: cannot write Pine panel to {args.output}: {exc}", file=sys.stderr)
        return 1

    print(
        f"Open-Prep Pine panel: source={src_path} candidates={len(panel['candidates'])} "
        f"weather={panel.get('weather')} pine={args.output} sidecar={sidecar}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        logger.warning("Interrupted by user (SIGINT/KeyboardInterrupt).")
        raise SystemExit(130) from None
    except SystemExit:
        raise
    except Exception:
        logger.exception("Fatal error generating Open-Prep Pine panel.")
        raise SystemExit(1) from None
