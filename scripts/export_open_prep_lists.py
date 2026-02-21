from __future__ import annotations

import csv
import json
import sys
from datetime import UTC, datetime, timedelta
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from open_prep.macro import FMPClient, macro_bias_score
from open_prep.run_open_prep import _atr14_by_symbol, _event_is_today
from open_prep.screen import rank_candidates
from open_prep.trade_cards import build_trade_cards


DEFAULT_UNIVERSE = ["NVDA", "PLTR", "PWR", "TSLA", "AMD", "META", "MSFT", "AMZN", "GOOGL", "SMCI"]


def _table(headers: list[str], rows: list[list[object]]) -> str:
    th = "".join(f"<th>{escape(str(h))}</th>" for h in headers)
    trs = []
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
    atr_by_symbol, _ = _atr14_by_symbol(client=client, symbols=DEFAULT_UNIVERSE, as_of=run_date)
    for q in quotes:
        sym = str(q.get("symbol") or "").strip().upper()
        if sym:
            q["atr"] = atr_by_symbol.get(sym, 0.0)
    ranked = rank_candidates(quotes=quotes, bias=bias, top_n=10)
    cards = build_trade_cards(ranked_candidates=ranked, bias=bias, top_n=5)

    out_dir = Path(__file__).resolve().parents[1] / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)

    ranked_csv = out_dir / f"open_prep_ranked_candidates_{version}.csv"
    cards_csv = out_dir / f"open_prep_trade_cards_{version}.csv"
    html_path = out_dir / f"open_prep_lists_{version}.html"

    ranked_headers = [
        "rank",
        "symbol",
        "score",
        "price",
        "gap_pct",
        "volume",
        "avg_volume",
        "rel_volume",
        "macro_bias",
        "news_catalyst_score",
        "long_allowed",
        "no_trade_reason",
    ]
    ranked_rows: list[list[object]] = []
    for i, row in enumerate(ranked, start=1):
        ranked_rows.append(
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
                row.get("news_catalyst_score", ""),
                row.get("long_allowed", ""),
                "|".join(row.get("no_trade_reason", []) or []),
            ]
        )

    with ranked_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(ranked_headers)
        writer.writerows(ranked_rows)

    cards_headers = [
        "rank",
        "symbol",
        "setup_type",
        "entry_trigger",
        "invalidation",
        "risk_management",
        "atr",
        "tight",
        "mid",
        "wide",
        "stop_reference_source",
        "stop_reference_price",
        "stop_tight",
        "stop_mid",
        "stop_wide",
    ]
    cards_rows: list[list[object]] = []
    for i, card in enumerate(cards, start=1):
        trail = card.get("trail_stop_atr", {}) or {}
        dist = trail.get("distances", {}) or {}
        stops = trail.get("stop_prices", {}) or {}
        cards_rows.append(
            [
                i,
                card.get("symbol", ""),
                card.get("setup_type", ""),
                card.get("entry_trigger", ""),
                card.get("invalidation", ""),
                card.get("risk_management", ""),
                trail.get("atr", ""),
                dist.get("tight", ""),
                dist.get("mid", dist.get("balanced", "")),
                dist.get("wide", ""),
                trail.get("stop_reference_source", ""),
                trail.get("stop_reference_price", ""),
                stops.get("tight", ""),
                stops.get("mid", stops.get("balanced", "")),
                stops.get("wide", ""),
            ]
        )

    with cards_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(cards_headers)
        writer.writerows(cards_rows)

    html = f"""<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <title>Open Prep Lists {escape(version)}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; }}
    h1, h2 {{ margin: 12px 0; }}
    table {{ margin: 8px 0 20px 0; border-collapse: collapse; }}
    th {{ background: #f0f3f8; }}
    td, th {{ font-size: 12px; vertical-align: top; }}
  </style>
</head>
<body>
  <h1>Open Prep Lists</h1>
  <p><b>Version:</b> {escape(version)}</p>
  <p><b>Run Date (UTC):</b> {escape(run_date.isoformat())}</p>
  <h2>Ranked Candidates</h2>
  {_table(ranked_headers, ranked_rows)}
  <h2>Trade Cards</h2>
  {_table(cards_headers, cards_rows)}
</body>
</html>
"""
    html_path.write_text(html, encoding="utf-8")

    print(json.dumps(
        {
            "ranked_csv": str(ranked_csv),
            "trade_cards_csv": str(cards_csv),
            "html": str(html_path),
            "ranked_candidates": ranked,
            "trade_cards": cards,
        },
        indent=2,
    ))


if __name__ == "__main__":
    main()
