from __future__ import annotations

import json
from pathlib import Path

from scripts.run_terminal_candidate_mirror import MirrorConfig, mirror_once
from terminal_internal_feed import candidate_to_classified_item

NOW = 1_750_000_000.0


class FakeSource:
    def __init__(self) -> None:
        self.reset_count = 0

    def reset(self) -> None:
        self.reset_count += 1

    def fetch(self):
        candidate = candidate_to_classified_item(
            {
                "ticker": "TSLA",
                "headline": "Tesla raises full-year guidance after record profit",
                "snippet": "Management expects stronger revenue and margins.",
                "news_provider": "fixture",
                "news_source": "Example Wire",
                "news_url": "https://example.test/tsla",
                "published_ts": NOW - 30,
                "updated_ts": NOW - 20,
                "news_score": 0.91,
                "impact": 0.9,
                "clarity": 0.9,
                "polarity": 0.8,
                "relevance": 0.95,
                "category": "earnings",
            },
            generated_ts=NOW,
        )
        return [candidate], str(NOW)


def test_mirror_materializes_active_candidate_without_browser(tmp_path: Path) -> None:
    source = FakeSource()
    output = tmp_path / "terminal_candidates.jsonl"
    result = mirror_once(
        source,
        MirrorConfig(output_path=output),
        now=NOW,
        market_hours=False,
    )

    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert source.reset_count == 1
    assert result.source_items == result.retained_items == 1
    assert result.active_symbols == 1
    assert rows[0]["ticker"] == "TSLA"
    assert rows[0]["attention_state"] in {"ALERT", "FOCUS", "MONITOR"}
    assert rows[0]["attention_active"] is True


def test_start_script_supervises_candidate_mirror() -> None:
    source = (Path(__file__).resolve().parents[1] / "scripts/start_terminal_service.sh").read_text(
        encoding="utf-8"
    )
    assert "python -m scripts.run_terminal_candidate_mirror" in source
    assert 'wait -n "$streamlit_pid" "$candidate_mirror_pid" "$proxy_pid"' in source
