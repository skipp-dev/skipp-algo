from __future__ import annotations

from datetime import UTC, datetime, timedelta
from html import escape
import sys
from pathlib import Path
from typing import Any

# Add the project root to sys.path so we can import open_prep
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from open_prep.ai import build_trade_cards
from open_prep.macro import (
    FMPClient,
    filter_us_events,
    filter_us_high_impact_events,
    filter_us_mid_impact_events,
    macro_bias_score,
)
from open_prep.run_open_prep import _event_is_today, _format_macro_events
from open_prep.screen import rank_candidates

DEFAULT_UNIVERSE = ["NVDA", "PLTR", "PWR", "TSLA", "AMD", "META", "MSFT", "AMZN", "GOOGL", "SMCI"]


def table(headers: list[str], rows: list[list[object]]) -> str:
    th = "".join(f"<th>{escape(str(h))}</th>" for h in headers)
    trs: list[str] = []
    for row in rows:
        tds = "".join(f"<td>{escape(str(v))}</td>" for v in row)
        trs.append(f"<tr>{tds}</tr>")
    return (
        '<table border="1" cellspacing="0" cellpadding="6">'
        f"<thead><tr>{th}</tr></thead><tbody>{''.join(trs)}</tbody></table>"
    )


def main() -> None:
    now_utc = datetime.now(UTC)
    version = now_utc.strftime("%Y%m%d_%H%M%SZ")
    run_date = now_utc.date()

    client = FMPClient.from_env()
    macro_events = client.get_macro_calendar(run_date, run_date + timedelta(days=3))
    todays_events = [e for e in macro_events if _event_is_today(e, run_date)]

    bias = macro_bias_score(todays_events)
    quotes = client.get_batch_quotes(DEFAULT_UNIVERSE)
    ranked = rank_candidates(quotes=quotes, bias=bias, top_n=10)
    cards = build_trade_cards(ranked_candidates=ranked, bias=bias, top_n=5)

    result: dict[str, Any] = {
        "run_date_utc": run_date.isoformat(),
        "generated_at_utc": now_utc.isoformat(),
        "macro_bias": round(bias, 4),
        "macro_us_event_count_today": len(filter_us_events(todays_events)),
        "macro_us_high_impact_events_today": _format_macro_events(filter_us_high_impact_events(todays_events), 15),
        "macro_us_mid_impact_events_today": _format_macro_events(filter_us_mid_impact_events(todays_events), 15),
        "ranked_candidates": ranked,
        "trade_cards": cards,
    }

    out_dir = Path(__file__).resolve().parents[1] / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)

    html_path = out_dir / f"open_prep_report_{version}.html"
    xls_path = out_dir / f"open_prep_report_{version}.xls"

    summary_rows = [
        ["Run Date (UTC)", result["run_date_utc"]],
        ["Generated At (UTC)", result["generated_at_utc"]],
        ["Macro Bias", result["macro_bias"]],
        ["US Events Today", result["macro_us_event_count_today"]],
        ["High Impact Events", len(result["macro_us_high_impact_events_today"])],
        ["Mid Impact Events", len(result["macro_us_mid_impact_events_today"])],
    ]

    cand_headers = ["Rank", "Symbol", "Score", "Price", "Gap %", "Volume", "Avg Volume", "Rel Volume", "Macro Bias"]
    cand_rows: list[list[object]] = []
    ranked_candidates: list[dict[str, Any]] = result["ranked_candidates"]
    for i, row in enumerate(ranked_candidates, start=1):
        cand_rows.append(
            [
                i,
                row.get("symbol", ""),
                row.get("score", ""),
                row.get("price", ""),
                row.get("gap_pct", ""),
                row.get("volume", ""),
                row.get("avg_volume", ""),
                row.get("rel_volume", ""),
                row.get("macro_bias", ""),
            ]
        )

    card_headers = [
        "#",
        "Symbol",
        "Setup",
        "Entry Trigger",
        "Invalidation",
        "Risk Mgmt",
        "ATR",
        "Tight",
        "Balanced",
        "Wide",
        "Stop Ref",
        "Stop Ref Px",
        "Stop Tight",
        "Stop Balanced",
        "Stop Wide",
    ]
    card_rows: list[list[object]] = []
    trade_cards: list[dict[str, Any]] = result["trade_cards"]
    for i, card in enumerate(trade_cards, start=1):
        trail = card.get("trail_stop_atr", {}) or {}
        dist = trail.get("distances", {}) or {}
        stops = trail.get("stop_prices", {}) or {}
        card_rows.append(
            [
                i,
                card.get("symbol", ""),
                card.get("setup_type", ""),
                card.get("entry_trigger", ""),
                card.get("invalidation", ""),
                card.get("risk_management", ""),
                trail.get("atr", ""),
                dist.get("tight", ""),
                dist.get("balanced", ""),
                dist.get("wide", ""),
                trail.get("stop_reference_source", ""),
                trail.get("stop_reference_price", ""),
                stops.get("tight", ""),
                stops.get("balanced", ""),
                stops.get("wide", ""),
            ]
        )

    event_headers = ["Date", "Event", "Impact", "Actual", "Consensus", "Previous", "Country", "Currency"]
    high_events: list[dict[str, Any]] = result["macro_us_high_impact_events_today"]
    high_rows = [
        [
            e.get("date", ""),
            e.get("event", ""),
            e.get("impact", ""),
            e.get("actual", ""),
            e.get("consensus", ""),
            e.get("previous", ""),
            e.get("country", ""),
            e.get("currency", ""),
        ]
        for e in high_events
    ]
    mid_events: list[dict[str, Any]] = result["macro_us_mid_impact_events_today"]
    mid_rows = [
        [
            e.get("date", ""),
            e.get("event", ""),
            e.get("impact", ""),
            e.get("actual", ""),
            e.get("consensus", ""),
            e.get("previous", ""),
            e.get("country", ""),
            e.get("currency", ""),
        ]
        for e in mid_events
    ]

    html = f"""<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <title>Open Prep Report {escape(version)}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; }}
    h1, h2 {{ margin: 12px 0; }}
    table {{ margin: 8px 0 20px 0; border-collapse: collapse; }}
    th {{ background: #f0f3f8; }}
    td, th {{ font-size: 12px; vertical-align: top; }}
  </style>
</head>
<body>
  <h1>Macro-aware Long-Breakout Report</h1>
  <p><b>Version:</b> {escape(version)}</p>
  <h2>Summary</h2>
  {table(["Metric", "Value"], summary_rows)}
  <h2>Ranked Candidates</h2>
  {table(cand_headers, cand_rows)}
  <h2>Trade Cards</h2>
  {table(card_headers, card_rows)}
  <h2>US High Impact Events (Today)</h2>
  {table(event_headers, high_rows)}
  <h2>US Mid Impact Events (Today)</h2>
  {table(event_headers, mid_rows)}
</body>
</html>
"""

    html_path.write_text(html, encoding="utf-8")
    # Excel can open HTML content with .xls extension.
    xls_path.write_text(html, encoding="utf-8")

    print(html_path)
    print(xls_path)


if __name__ == "__main__":
    main()
