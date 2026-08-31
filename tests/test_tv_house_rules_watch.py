"""Unit contract for scripts/tv_house_rules_watch.py (ADR-0034 watcher).

The script must be suite-importable so its logic is provable offline; only
the weekly fetch itself lives in the workflow (job_log witness, proof ledger
entry house-rules-watch).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.tv_house_rules_watch import (
    SanityError,
    extract_article,
    main,
    render_snapshot,
)

_RULE = (
    "Please note that the use of any data mining/extraction tools, any kind of "
    "automatization and optimization via external software, tools, scripts, bots "
    "and extensions are not allowed. All our features are for manual use only."
)


def _page(*paragraphs: str) -> str:
    body = "".join(f"<p>{p}</p>" for p in paragraphs)
    return (
        "<html><head><script>var state={\"copy\":\"" + _RULE + "\"};</script></head>"
        "<body><nav><p>shell nav text that must not be captured</p></nav>"
        "<h1>Why is my account banned due to suspicious activity?</h1>"
        + body
        + "<footer><p>footer boilerplate</p></footer></body></html>"
    )


_FILLER = [f"Paragraph {i} with enough text to clear the sanity floors easily." for i in range(6)]


def test_extractor_takes_the_article_and_drops_shell_state_and_footer():
    paragraphs = extract_article(_page(_RULE, *_FILLER))
    joined = "\n".join(paragraphs)
    assert _RULE in joined
    # The <script> JSON copy and the pre-h1 nav text must not be captured:
    assert joined.count("manual use only") == 1
    assert "shell nav text" not in joined
    assert "footer boilerplate" not in joined


def test_sanity_floor_refuses_a_redesigned_page():
    with pytest.raises(SanityError):
        extract_article("<html><h1>t</h1><p>tiny</p></html>")


def test_change_detection_is_exit_2_and_never_rewrites_the_snapshot(tmp_path: Path):
    page = tmp_path / "page.html"
    snap = tmp_path / "snap.md"
    page.write_text(_page(_RULE, *_FILLER), encoding="utf-8")
    assert main(["--from-file", str(page), "--snapshot", str(snap), "--update"]) == 0
    committed = snap.read_text(encoding="utf-8")
    # The rule sentence changes -> exit 2, snapshot untouched (no self-heal).
    page.write_text(_page(_RULE.replace("manual use only", "manual use"), *_FILLER), encoding="utf-8")
    assert main(["--from-file", str(page), "--snapshot", str(snap)]) == 2
    assert snap.read_text(encoding="utf-8") == committed
    # Unchanged page -> exit 0.
    page.write_text(_page(_RULE, *_FILLER), encoding="utf-8")
    assert main(["--from-file", str(page), "--snapshot", str(snap)]) == 0


def test_broken_extraction_is_exit_3(tmp_path: Path):
    page = tmp_path / "page.html"
    page.write_text("<html><h1>t</h1><p>tiny</p></html>", encoding="utf-8")
    assert main(["--from-file", str(page), "--snapshot", str(tmp_path / "s.md")]) == 3


def test_the_committed_snapshot_carries_the_rule_this_adr_rests_on():
    """ADR-0034 rests on the 'manual use only' sentence. If a deliberate
    snapshot update ever drops it, the decision needs re-evaluation -- this
    pin makes that impossible to miss."""
    snapshot = Path(__file__).resolve().parents[1] / "docs" / "tv_house_rules_snapshot.md"
    text = snapshot.read_text(encoding="utf-8")
    assert "for manual use only" in text
    assert "43000674726" in text


def test_render_is_deterministic():
    paragraphs = ["a b", "c"]
    assert render_snapshot(paragraphs) == render_snapshot(list(paragraphs))
