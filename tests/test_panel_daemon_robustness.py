"""Robustness fixes surfaced by a bug-hunt on the open-prep panel + daemon:
BOM-tolerant setups read, whitespace-tolerant symbol join, and an inline-comment-
tolerant daemon .env parser."""
import json
import os

import pytest

from scripts.generate_openprep_pine_panel import extract_panel, load_setup_levels
from services.live_overlay_daemon import config


# --- #1: a UTF-8 BOM in the setups file must not silently blank the panel ---
def test_load_setup_levels_tolerates_bom_array(tmp_path):
    rows = [{"symbol": "AAPL", "trade_date": "2026-07-09",
             "entry": 100.0, "stop_loss": 98.0, "take_profit": 104.0}]
    p = tmp_path / "setups_2026-07-09.jsonl"
    p.write_text("\ufeff" + json.dumps(rows), encoding="utf-8")  # BOM + JSON array
    levels = load_setup_levels(p, "2026-07-09")
    assert levels.get("AAPL", {}).get("entry") == 100.0


def test_load_setup_levels_tolerates_bom_jsonl(tmp_path):
    row = {"symbol": "MSFT", "trade_date": "2026-07-09",
           "entry": 380.0, "stop_loss": 375.0, "take_profit": 390.0}
    p = tmp_path / "setups.jsonl"
    p.write_text("\ufeff" + json.dumps(row) + "\n", encoding="utf-8")  # BOM + JSONL
    levels = load_setup_levels(p, "2026-07-09")
    assert levels.get("MSFT", {}).get("stop") == 375.0


# --- #3: an outcome symbol with stray whitespace still joins the setups ---
def test_extract_panel_whitespace_symbol_joins_levels():
    rows = [{"symbol": " AAPL ", "score": 5.0, "regime": "R", "market_weather": "SUN"}]
    levels = {"AAPL": {"entry": 100.0, "stop": 98.0, "target": 104.0}}
    cand = extract_panel(rows, levels)["candidates"][0]
    assert cand["symbol"] == "AAPL"
    assert (cand["entry"], cand["stop"], cand["target"]) == (100.0, 98.0, 104.0)


# --- #5: daemon .env parser honours inline comments (keeps bare # and quotes) ---
@pytest.mark.parametrize("raw,expected", [
    ("RBT_PORT=9000 # http port", "9000"),
    ("RBT_PORT=9000\t# tab comment", "9000"),
    ("RBT_TOKEN=ab#cd", "ab#cd"),          # bare # (no leading space) stays in value
    ('RBT_Q="a # b"', "a # b"),            # # inside quotes is preserved
    ('RBT_Q2="val" # trailing note', "val"),  # comment after close-quote dropped
    ("RBT_PLAIN=hello", "hello"),
])
def test_env_inline_comment_parsing(tmp_path, monkeypatch, raw, expected):
    key = raw.split("=", 1)[0]
    envfile = tmp_path / ".env"
    envfile.write_text(raw + "\n", encoding="utf-8")
    monkeypatch.setattr(config, "_ENV_FILE", envfile)
    monkeypatch.delenv(key, raising=False)
    config._load_env()
    assert os.environ.get(key) == expected
