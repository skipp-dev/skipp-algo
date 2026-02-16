import re
from pathlib import Path


BASE_DIR = Path(__file__).parent.parent
INDICATOR_FILE = BASE_DIR / "SkippALGO.pine"
STRATEGY_FILE = BASE_DIR / "SkippALGO_Strategy.pine"
CHANGELOG_FILE = BASE_DIR / "CHANGELOG.md"
README_FILE = BASE_DIR / "README.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_version_from_indicator(text: str) -> str:
    m = re.search(r'indicator\("SkippALGO\s+v(\d+\.\d+\.\d+)"', text)
    assert m, "Indicator version string not found"
    return m.group(1)


def _extract_version_from_strategy(text: str) -> str:
    m = re.search(r'strategy\("SkippALGO Strategy\s+v(\d+\.\d+\.\d+)"', text)
    assert m, "Strategy version string not found"
    return m.group(1)


def _extract_latest_changelog_version(text: str) -> str:
    m = re.search(r"## \[v(\d+\.\d+\.\d+)\] - ", text)
    assert m, "No versioned changelog entry found"
    return m.group(1)


def _extract_latest_readme_version(text: str) -> str:
    m = re.search(r"- \*\*Latest \(v(\d+\.\d+\.\d+)\s+—", text)
    assert m, "README latest version entry not found"
    return m.group(1)


def test_release_version_sync():
    indicator = _read(INDICATOR_FILE)
    strategy = _read(STRATEGY_FILE)
    changelog = _read(CHANGELOG_FILE)
    readme = _read(README_FILE)

    v_indicator = _extract_version_from_indicator(indicator)
    v_strategy = _extract_version_from_strategy(strategy)
    v_changelog = _extract_latest_changelog_version(changelog)
    v_readme = _extract_latest_readme_version(readme)

    assert v_indicator == v_strategy, (
        f"Indicator/Strategy version mismatch: {v_indicator} vs {v_strategy}"
    )
    assert v_indicator == v_changelog, (
        f"Code vs CHANGELOG mismatch: {v_indicator} vs {v_changelog}"
    )
    assert v_indicator == v_readme, (
        f"Code vs README mismatch: {v_indicator} vs {v_readme}"
    )


def test_changelog_latest_verification_has_pass_count():
    changelog = _read(CHANGELOG_FILE)
    latest_block = re.split(r"## \[v\d+\.\d+\.\d+\] - ", changelog, maxsplit=2)
    assert len(latest_block) >= 2, "Cannot parse latest changelog block"
    # Section after first version heading
    content_after_first_heading = latest_block[1]
    assert re.search(r"\*\*\d+ passed\*\*", content_after_first_heading), (
        "Latest changelog entry should include a '**N passed**' verification line"
    )
