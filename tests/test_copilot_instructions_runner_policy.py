"""Pins for Copilot/reviewer runner-policy documentation.

The GitHub Copilot Code Review job is a GitHub-managed dynamic workflow, not a
repo-authored workflow that should be routed through our Windows self-hosted
pool. These checks keep `.github/copilot-instructions.md` aligned with the
current runner policy: GitHub-hosted by default; self-hosted only for workloads
that genuinely need local Windows/GPU/cache characteristics.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTRUCTIONS = ROOT / ".github" / "copilot-instructions.md"


def _text() -> str:
    return INSTRUCTIONS.read_text(encoding="utf-8")


def _one_line() -> str:
    return " ".join(_text().split())


def test_copilot_reviewer_is_documented_as_github_managed() -> None:
    text = _one_line()
    assert "GitHub Copilot Code Review / Copilot reviewer" in text
    assert "GitHub-managed dynamic workflow named `Copilot`" in text
    assert "Do **not** create or edit repository workflows to route Copilot review jobs" in text
    assert "The AI reviewer should execute on GitHub-managed infrastructure." in text


def test_smc_gh_hosted_runner_is_not_described_as_self_hosted() -> None:
    text = _text()
    assert "SMC_GH_HOSTED_RUNNER`, currently\n`ubuntu-latest`" in text
    forbidden = [
        "repository uses a Windows self-hosted runner (`SMC_GH_HOSTED_RUNNER`)",
        "SMC_GH_HOSTED_RUNNER`) runner",
    ]
    for phrase in forbidden:
        assert phrase not in text


def test_ci_policy_is_documented_as_hosted_not_routed() -> None:
    text = _text()
    assert "This includes `ci.yml`. CI validate is intentionally GitHub-hosted" in text
    assert "`ci.yml`, `docs-lint.yml`" not in text
    assert "--inventory-unavailable-fallback required-self-hosted" in text
    assert "unless the workflow truly cannot run" in text