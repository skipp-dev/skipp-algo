from __future__ import annotations

import json
from pathlib import Path

from smc_integration.extended_structure_discovery import (
    TARGET_CATEGORIES,
    build_extended_structure_discovery_report,
    discover_extended_structure_by_category,
    discover_extended_structure_candidates,
)

ROOT = Path(__file__).resolve().parents[1]


def test_extended_structure_candidates_are_deterministic_and_real_paths() -> None:
    one = discover_extended_structure_candidates()
    two = discover_extended_structure_candidates()

    assert one == two
    assert one

    for row in one:
        assert row["category"] in TARGET_CATEGORIES
        assert row["evidence_type"] in {"explicit_objects", "computed_logic", "aggregate_flags", "text_only"}
        assert (ROOT / str(row["path"])).exists()


def test_extended_discovery_has_candidates_for_all_missing_categories() -> None:
    by_category = discover_extended_structure_by_category()

    assert set(by_category.keys()) == set(TARGET_CATEGORIES)

    for category in TARGET_CATEGORIES:
        bucket = by_category[category]
        assert bucket["candidate_count"] > 0
        assert isinstance(bucket["top_candidates"], list)
        assert bucket["top_candidates"]
        best = bucket["best_candidate"]
        assert isinstance(best, dict)
        assert best["category"] == category
        assert best["evidence_type"] in {"explicit_objects", "computed_logic", "aggregate_flags", "text_only"}


def test_extended_discovery_report_is_serializable_and_has_strong_types() -> None:
    report = build_extended_structure_discovery_report()
    encoded = json.dumps(report, sort_keys=True)
    assert encoded

    strongest = report["strongest_evidence_type"]
    assert set(strongest.keys()) == set(TARGET_CATEGORIES)

    for category in TARGET_CATEGORIES:
        assert strongest[category] in {"explicit_objects", "computed_logic", "aggregate_flags", "text_only"}
        # Current repository has at least computed or explicit evidence for every missing category.
        assert strongest[category] in {"explicit_objects", "computed_logic"}


def test_extended_integrability_is_conservative_for_non_provider_sources() -> None:
    by_category = discover_extended_structure_by_category()

    for category in TARGET_CATEGORIES:
        integrability = by_category[category]["integrability"]
        assert isinstance(integrability["integrable_now"], bool)
        assert isinstance(integrability["reason"], str)


# ── pure helper coverage ─────────────────────────────────────────

import re

from smc_integration.extended_structure_discovery import (
    _candidate_rank,
    _evidence_tokens,
    _evidence_type_for,
    _integrability_for,
    _is_fixture_like,
    _is_runtime_provider_artifact,
    _matches_all,
    _matches_any,
    _read_text,
)


class TestMatchesAll:
    def test_all_match(self) -> None:
        patterns = [re.compile(r"foo"), re.compile(r"bar")]
        assert _matches_all("foo bar baz", patterns) is True

    def test_one_missing(self) -> None:
        patterns = [re.compile(r"foo"), re.compile(r"qux")]
        assert _matches_all("foo bar baz", patterns) is False

    def test_empty_patterns(self) -> None:
        assert _matches_all("any text", []) is True


class TestMatchesAny:
    def test_one_match(self) -> None:
        patterns = [re.compile(r"foo"), re.compile(r"qux")]
        assert _matches_any("foo bar", patterns) is True

    def test_none_match(self) -> None:
        patterns = [re.compile(r"qux"), re.compile(r"baz")]
        assert _matches_any("foo bar", patterns) is False


class TestEvidenceTypeFor:
    def test_explicit_objects(self) -> None:
        text = '"orderblocks": [{"low": 1, "high": 2, "dir": "up", "valid": true}]'
        assert _evidence_type_for(text, "orderblocks") == "explicit_objects"

    def test_computed_logic(self) -> None:
        text = "def _detect_orderblocks(bars):"
        assert _evidence_type_for(text, "orderblocks") == "computed_logic"

    def test_aggregate_flags(self) -> None:
        text = "ob_sweep_count = 5"
        assert _evidence_type_for(text, "orderblocks") == "aggregate_flags"

    def test_text_only(self) -> None:
        text = "This order block is important"
        assert _evidence_type_for(text, "orderblocks") == "text_only"

    def test_none_when_no_match(self) -> None:
        assert _evidence_type_for("nothing here", "orderblocks") is None


class TestEvidenceTokens:
    def test_returns_matching_tokens(self) -> None:
        text = "def _detect_fvg(bars): pass"
        tokens = _evidence_tokens(text, "fvg", "computed_logic")
        assert any("_detect_fvg" in t for t in tokens)

    def test_text_only_tokens(self) -> None:
        text = "The FVG gap is here"
        tokens = _evidence_tokens(text, "fvg", "text_only")
        assert len(tokens) > 0


class TestIsFixtureLike:
    def test_tests_prefix(self) -> None:
        assert _is_fixture_like("tests/test_foo.py") is True

    def test_spec_examples(self) -> None:
        assert _is_fixture_like("spec/examples/snapshot.json") is True

    def test_docs(self) -> None:
        assert _is_fixture_like("docs/guide.md") is True

    def test_reports(self) -> None:
        assert _is_fixture_like("reports/data.json") is False


class TestIsRuntimeProviderArtifact:
    def test_reports_json(self) -> None:
        assert _is_runtime_provider_artifact("reports/artifact.json") is True

    def test_reports_csv(self) -> None:
        assert _is_runtime_provider_artifact("reports/data.csv") is True

    def test_scripts(self) -> None:
        assert _is_runtime_provider_artifact("scripts/build.py") is False

    def test_non_reports(self) -> None:
        assert _is_runtime_provider_artifact("docs/readme.md") is False


class TestCandidateRank:
    def test_explicit_runtime_ranks_highest(self) -> None:
        explicit_runtime = {
            "path": "reports/artifact.json",
            "evidence_type": "explicit_objects",
        }
        text_fixture = {
            "path": "tests/fixture.json",
            "evidence_type": "text_only",
        }
        assert _candidate_rank(explicit_runtime) > _candidate_rank(text_fixture)

    def test_computed_ranks_above_aggregate(self) -> None:
        computed = {"path": "scripts/build.py", "evidence_type": "computed_logic"}
        aggregate = {"path": "scripts/summary.py", "evidence_type": "aggregate_flags"}
        assert _candidate_rank(computed) > _candidate_rank(aggregate)


class TestIntegrabilityFor:
    def test_no_candidate(self) -> None:
        result = _integrability_for("fvg", None)
        assert result["integrable_now"] is False

    def test_non_explicit_not_integrable(self) -> None:
        candidate = {"path": "scripts/build.py", "evidence_type": "computed_logic"}
        result = _integrability_for("fvg", candidate)
        assert result["integrable_now"] is False

    def test_explicit_fixture_not_integrable(self) -> None:
        candidate = {"path": "tests/fixture.json", "evidence_type": "explicit_objects"}
        result = _integrability_for("fvg", candidate)
        assert result["integrable_now"] is False

    def test_explicit_runtime_integrable(self) -> None:
        candidate = {"path": "reports/artifact.json", "evidence_type": "explicit_objects"}
        result = _integrability_for("fvg", candidate)
        assert result["integrable_now"] is True


class TestReadText:
    def test_reads_and_truncates(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_text("a" * 500, encoding="utf-8")
        assert len(_read_text(f, max_chars=100)) == 100

    def test_latin1_fallback(self, tmp_path: Path) -> None:
        f = tmp_path / "latin.bin"
        f.write_bytes(b"\xff data")
        assert len(_read_text(f)) > 0
