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
import math
import os
import sys
from datetime import UTC, datetime
from datetime import date as _date
from pathlib import Path
from typing import Any

from open_prep.market_microstructure import weather_badge_label
from scripts._logging_init import init_cli_logging

PINE_HEADER = "//@version=6"
DEFAULT_OUTPUT = Path("pine/generated/openprep_daily_panel.pine")
DEFAULT_OUTCOMES_DIR = Path("artifacts/open_prep/outcomes")
# C13 setups (cache/live/setups_<DATE>.jsonl) carry the OFFICIAL daily levels
# (entry/stop_loss/take_profit) the paper trader submits. The panel joins them
# per symbol when a date-matched file exists (local generation); in CI no
# setups are committed, so the levels column honestly renders "–" until the
# data plumbing lands (see PR notes).
DEFAULT_SETUPS_DIR = Path("cache/live")
MAX_ROWS = 12  # Pine table stays readable; excess candidates are dropped.
MAX_SYMBOL_LEN = 32
MAX_NAME_LEN = 64


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        f = float(value)
    except (TypeError, ValueError):
        return None
    # NaN/Inf would be emitted verbatim into Pine ("nan"/"inf" are not Pine
    # literals) and fail the fail-closed publisher; treat them as missing.
    return f if math.isfinite(f) else None


def _truncate(value: Any, max_len: int) -> str:
    text = str(value or "")
    return text[:max_len]


def _parse_date_ymd(value: Any) -> tuple[int, int, int]:
    if isinstance(value, _date):
        return value.year, value.month, value.day
    if isinstance(value, str):
        token = value.split("T", 1)[0].split(" ", 1)[0].strip()
        try:
            d = _date.fromisoformat(token)
            return d.year, d.month, d.day
        except ValueError:
            return 0, 0, 0
    return 0, 0, 0


def discover_latest_outcomes(search_dir: Path) -> Path | None:
    """Return the newest ``outcomes_*.json`` by filename (dates sort
    lexicographically), or ``None`` when the directory has none."""
    if not search_dir.is_dir():
        return None
    candidates = sorted(search_dir.glob("outcomes_*.json"))
    return candidates[-1] if candidates else None


def discover_setups_for_date(setups_dir: Path, date: Any) -> Path | None:
    """Return ``setups_<date>.jsonl`` for the panel date, or ``None``.

    Date-matched by construction: a stale setups file from another day can
    never be joined onto today's candidates (wrong levels are worse than no
    levels)."""
    if not date:
        return None
    path = setups_dir / f"setups_{date}.jsonl"
    return path if path.is_file() else None


def load_setup_levels(path: Path, date: Any) -> dict[str, dict[str, float | None]]:
    """Map ``symbol -> {entry, stop, target}`` from a C13 setups file.

    The file is a JSON array (despite the .jsonl suffix); one-object-per-line
    JSONL is tolerated for forward-compat. Rows whose ``trade_date`` differs
    from the panel date are dropped (second layer of the date guard); garbage
    rows and non-numeric levels degrade to ``None``, never raise.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    rows: list[Any] = []
    try:
        loaded = json.loads(text)
        rows = loaded if isinstance(loaded, list) else [loaded]
    except json.JSONDecodeError:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    levels: dict[str, dict[str, float | None]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_date = str(row.get("trade_date") or "")
        if date and row_date and row_date != str(date):
            continue
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        levels[symbol] = {
            "entry": _safe_float(row.get("entry")),
            "stop": _safe_float(row.get("stop_loss")),
            "target": _safe_float(row.get("take_profit")),
        }
    return levels


def extract_panel(
    rows: list[dict[str, Any]],
    levels: dict[str, dict[str, float | None]] | None = None,
) -> dict[str, Any]:
    """Reduce outcome rows to the panel's data model.

    Market-wide fields (date, regime, weather, microstructure metrics) are
    identical across a run's rows, so they are read from the first row.
    Per-candidate fields become one entry each, sorted by score descending
    (ties broken by symbol ascending) and capped at ``MAX_ROWS``.

    ``levels`` (from :func:`load_setup_levels`) joins the official C13
    entry/stop/target per symbol; candidates without a setup keep ``None``.
    """
    if not rows:
        return {"date": None, "candidates": []}

    head = rows[0]
    regime = head.get("regime")
    if regime is None:
        regime = head.get("regime_at_entry")
    levels = levels or {}
    candidates: list[dict[str, Any]] = []
    for row in rows:
        symbol = row.get("symbol")
        if not symbol:
            continue
        panel_symbol = _truncate(symbol, MAX_SYMBOL_LEN).upper()
        row_levels = levels.get(panel_symbol) or {}
        candidates.append(
            {
                "symbol": panel_symbol,
                "score": _safe_float(row.get("score")) or 0.0,
                "tier": str(row.get("confidence_tier") or "-"),
                "playbook": _truncate(row.get("playbook_name") or "-", MAX_NAME_LEN),
                "direction": str(row.get("direction") or "-"),
                "gap_pct": _safe_float(row.get("gap_pct")),
                "rvol": _safe_float(row.get("rvol")),
                "entry": row_levels.get("entry"),
                "stop": row_levels.get("stop"),
                "target": row_levels.get("target"),
            }
        )
    # Secondary key (symbol asc) makes the order — and therefore which
    # candidates survive the MAX_ROWS cap — deterministic when scores tie.
    # Without it, the daily-published panel depends on incoming row order.
    candidates.sort(key=lambda c: (-c["score"], c["symbol"]))

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
    if value is None or not math.isfinite(value):
        return "na"
    # Fixed-point (never scientific notation — "1e+16" is not a Pine literal).
    return f"{value:.{nd}f}"


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
               commit_sha: str | None, source_setups: str = "none") -> str:
    """Render the deterministic Pine v6 panel for *panel*."""
    date = panel.get("date")
    cands = panel.get("candidates", [])
    weather = str(panel.get("weather") or "UNKNOWN").upper()
    badge, weather_label = weather_badge_label(weather)

    # Split the ISO date into ints for the freshness timestamp; fall back to
    # a clearly-stale sentinel so a malformed/absent date greys the panel.
    year, month, day = _parse_date_ymd(date)

    header = [
        PINE_HEADER,
        "// AUTOGENERATED by scripts/generate_openprep_pine_panel.py — DO NOT EDIT BY HAND.",
        "// Open-Prep daily watchlist + market-weather panel (plan Workstream B1).",
        f"// generated_at: {generated_at}",
        f"// source_outcomes: {source}",
        f"// source_setups: {source_setups}",
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
        # Official C13 levels from the date-matched setups file (na without one).
        _pine_float_array("P_ENTRY", [c.get("entry") for c in cands]),
        _pine_float_array("P_STOP", [c.get("stop") for c in cands]),
        _pine_float_array("P_TGT", [c.get("target") for c in cands]),
        "",
    ]

    body = [
        "// ── Freshness guard: grey out when the snapshot is > 3 calendar days old ──",
        "panel_ts = PANEL_YEAR > 0 ? timestamp(PANEL_YEAR, PANEL_MONTH, PANEL_DAY, 0, 0) : 0",
        "age_days = panel_ts > 0 ? (timenow - panel_ts) / 86400000.0 : 1.0e9",
        # Comment fixed 2026-07-08: this is NOT "1 trading day" — measured from
        # the snapshot date's midnight, a Friday panel greys from Monday 00:00
        # (VERALTET on Monday morning until the new run lands) and a weekday
        # panel tolerates up to two missed runs before greying.
        "is_stale = age_days > 3.0  // 3 calendar days from the snapshot's midnight (Fri panel greys Mon 00:00; up to 2 missed weekday runs stay un-greyed)",
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
        "var table t = table.new(position.top_right, 8, rows, border_width = 1)",
        "var array<string> hdrs = array.from(\"Symbol\", \"Playbook\", \"Dir\", \"Score\", \"Tier\", \"Gap%\", \"RVOL\", \"L1 e/s/t\")",
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
        "    for c = 0 to 7",
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
        "            // Official C13 levels (setups join); \"–\" when no setup for this symbol/date.",
        "            entryv = array.get(P_ENTRY, i)",
        "            stopv = array.get(P_STOP, i)",
        "            tgtv = array.get(P_TGT, i)",
        "            lev_txt = na(entryv) ? \"–\" : str.tostring(entryv, \"#.##\") + \"/\" + (na(stopv) ? \"–\" : str.tostring(stopv, \"#.##\")) + \"/\" + (na(tgtv) ? \"–\" : str.tostring(tgtv, \"#.##\"))",
        "            table.cell(t, 7, r, lev_txt, text_color = txt_col, bgcolor = row_bg, text_size = size.tiny)",
        "",
        "    // Footer — microstructure metrics",
        "    fr = n < 1 ? 3 : n + 2",
        "    footer = \"ER_1h \" + (na(PANEL_ER_I) ? \"n/a\" : str.tostring(PANEL_ER_I, \"#.###\")) + \"  Disp \" + (na(PANEL_DISP) ? \"n/a\" : str.tostring(PANEL_DISP, \"#.##\")) + \"  Corr \" + (na(PANEL_CORR) ? \"n/a\" : str.tostring(PANEL_CORR, \"#.##\"))",
        "    table.cell(t, 0, fr, footer, text_color = color.gray, bgcolor = color.new(color.navy, 60), text_size = size.tiny)",
        "",
    ]

    lines = header + consts + body
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


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
        "--setups-json",
        type=Path,
        default=None,
        help="Explicit C13 setups_<DATE>.jsonl path (official entry/stop/target "
             "levels). Default: date-matched file under --setups-dir.",
    )
    parser.add_argument(
        "--setups-dir",
        type=Path,
        default=DEFAULT_SETUPS_DIR,
        help=f"Directory searched for setups_<panel-date>.jsonl when "
             f"--setups-json is omitted (default: {DEFAULT_SETUPS_DIR}).",
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

    # Official C13 levels: explicit --setups-json wins; otherwise discover the
    # file date-matched to the panel date (a stale setups file never joins).
    panel_date = rows[0].get("date") if rows else None
    setups_path = args.setups_json or discover_setups_for_date(args.setups_dir, panel_date)
    levels: dict[str, dict[str, float | None]] = {}
    if setups_path is not None and setups_path.is_file():
        levels = load_setup_levels(setups_path, panel_date)
    elif args.setups_json is not None:
        print(f"ERROR: setups file not found: {args.setups_json}", file=sys.stderr)
        return 1

    panel = extract_panel(rows, levels=levels)

    # Absolute setups paths would bake a machine-local path into the committed
    # artifact; the basename (carrying the date) is the provenance that matters.
    if setups_path is None:
        setups_label = "none"
    else:
        setups_label = setups_path.name if setups_path.is_absolute() else str(setups_path)

    snippet = build_pine(
        panel,
        generated_at=datetime.now(UTC).isoformat(),
        source=str(src_path) if src_path else "none",
        commit_sha=args.commit_sha,
        source_setups=setups_label,
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
