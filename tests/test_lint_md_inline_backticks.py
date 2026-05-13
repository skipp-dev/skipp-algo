"""Tests for scripts/lint_md_inline_backticks.py — P5.4 deep-review B1."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "lint_md_inline_backticks.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "md_lint"


@pytest.fixture(scope="module")
def lint_module():
    spec = importlib.util.spec_from_file_location("lint_md_inline_backticks", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["lint_md_inline_backticks"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize(
    "fixture_name",
    [
        "commonmark_inline.md",
        "tilde_fences.md",
        "backtick_fence.md",
        "blockquote_fences.md",
        "long_open_fence.md",
    ],
)
def test_known_good_fixtures_have_zero_findings(lint_module, fixture_name):
    """Edge-case corpus must produce no false positives.

    Per deep-review CORR-4: tilde-fences, triple-backtick inline runs,
    and intra-fence content must not be flagged.
    """
    path = FIXTURES / "known_good" / fixture_name
    assert path.exists(), f"missing fixture: {path}"
    findings = lint_module.lint_file(path)
    assert findings == [], (
        f"false positives in known-good fixture {fixture_name!r}:\n"
        + "\n".join(f.format() for f in findings)
    )


@pytest.mark.parametrize(
    "fixture_name,expected_first_line",
    [
        ("cross_line_inline_span.md", 1),
        ("single_stray_backtick.md", 1),
    ],
)
def test_known_bad_fixtures_have_findings(lint_module, fixture_name, expected_first_line):
    """Each known-bad fixture must produce at least one finding."""
    path = FIXTURES / "known_bad" / fixture_name
    assert path.exists(), f"missing fixture: {path}"
    findings = lint_module.lint_file(path)
    assert findings, f"expected at least one finding in {fixture_name!r}"
    assert findings[0].line == expected_first_line, (
        f"first finding in {fixture_name!r} expected at line {expected_first_line}, "
        f"got {findings[0].line}"
    )
    assert findings[0].rule == "unbalanced-inline-backticks"


def test_strip_balanced_inline_runs_handles_triple_backticks(lint_module):
    """Triple-backtick *inline* runs (mid-line) must be treated as balanced."""
    line = "see ```py code``` here"
    stripped = lint_module._strip_balanced_inline_runs(line)
    assert "`" not in stripped, f"triple-backtick inline span not stripped: {stripped!r}"


def test_strip_balanced_inline_runs_handles_double_backticks(lint_module):
    """Double-backtick spans (CommonMark allows backtick inside) must balance."""
    line = "double ``a`b`` end"
    stripped = lint_module._strip_balanced_inline_runs(line)
    assert "`" not in stripped


def test_strip_balanced_inline_runs_leaves_unbalanced(lint_module):
    """A genuinely unmatched backtick must remain after stripping."""
    line = "broken `start of span and no closer"
    stripped = lint_module._strip_balanced_inline_runs(line)
    assert "`" in stripped


def test_main_warn_mode_returns_zero_even_with_findings(lint_module, capsys):
    """warn-mode (default) must return 0 even when findings exist (B1 ships warn-only)."""
    rc = lint_module.main([str(FIXTURES / "known_bad" / "single_stray_backtick.md")])
    assert rc == 0


def test_main_strict_mode_returns_one_on_findings(lint_module, capsys):
    """--strict must return 1 when any finding exists."""
    rc = lint_module.main(
        ["--strict", str(FIXTURES / "known_bad" / "single_stray_backtick.md")]
    )
    assert rc == 1


def test_main_returns_zero_on_clean_corpus(lint_module, capsys):
    """Clean corpus must return 0 in either mode."""
    rc = lint_module.main([str(FIXTURES / "known_good")])
    assert rc == 0
    rc_strict = lint_module.main(["--strict", str(FIXTURES / "known_good")])
    assert rc_strict == 0


def test_github_format_emits_annotation(lint_module, capsys):
    """--format github must emit ::warning::/::error:: annotations for GHA."""
    lint_module.main(
        [
            "--format",
            "github",
            str(FIXTURES / "known_bad" / "single_stray_backtick.md"),
        ]
    )
    out = capsys.readouterr().out
    assert out.startswith("::warning ") or "::warning " in out
