"""Unit tests for the vacuity analyzer.

Fixtures are inline source strings, not repo files: the analyzer's contract
is about *shapes*, and pinning it to real files would make every unrelated
edit in the repo a failure here. The repo-wide scan lives in
``tests/test_vacuous_claim_guard.py``.
"""

from __future__ import annotations

import textwrap

from scripts.detect_vacuous_claims import scan_source


def _kinds(source: str) -> dict[str, str]:
    """Return ``iterable-source -> kind`` for every claim in *source*."""
    claims = scan_source(textwrap.dedent(source), "tests/example.py")
    return {claim.iterable: claim.kind for claim in claims}


def test_literal_tuple_loop_is_not_a_claim() -> None:
    """A literal cannot be empty at runtime, so it cannot be vacuous."""
    source = """
        def test_flags():
            for flag in ("--start-date", "--end-date"):
                assert flag in TEXT
    """
    assert _kinds(source) == {}


def test_range_loop_is_not_a_claim() -> None:
    source = """
        def test_repeats():
            for i in range(2):
                assert compute(i) == i
    """
    assert _kinds(source) == {}


def test_discovery_call_is_a_claim() -> None:
    source = """
        def test_every_file():
            for path in ROOT.glob("*.py"):
                assert path.is_file()
    """
    assert _kinds(source) == {'ROOT.glob("*.py")': "discovery call"}


def test_filtered_comprehension_bound_locally_is_a_claim() -> None:
    """The shape of the archive gate: a filter can filter everything away."""
    source = """
        def test_archived():
            archived = [s for s in SURFACES if s.lifecycle == "archived"]
            for surface in archived:
                assert not (ROOT / surface.file).is_file()
    """
    assert _kinds(source) == {"archived": "local filtered comprehension"}


def test_helper_returning_a_filtered_set_is_a_claim() -> None:
    source = """
        def _archived_surfaces():
            return [s for s in SURFACES if s.lifecycle == "archived"]

        def test_archived():
            for surface in _archived_surfaces():
                assert not (ROOT / surface.file).is_file()
    """
    assert _kinds(source) == {
        "_archived_surfaces()": "helper returns filtered comprehension"
    }


def test_helper_yielding_from_discovery_is_a_claim() -> None:
    """``_iter_workflow_files()`` shape: a generator over a glob."""
    source = """
        def _iter_workflow_files():
            for path in (ROOT / ".github" / "workflows").glob("*.yml"):
                yield path

        def test_workflows():
            for path in _iter_workflow_files():
                assert path.read_text()
    """
    assert _kinds(source) == {
        "_iter_workflow_files()": "helper yields discovery call"
    }


def test_method_call_on_self_resolves_to_the_helper() -> None:
    """``self._spec_paths()`` must classify like the bare helper name."""
    source = """
        class TestSpecs:
            def _spec_paths(self):
                return list(SPEC_DIR.glob("*.json"))

            def test_specs(self):
                for path in self._spec_paths():
                    assert path.suffix == ".json"
    """
    assert _kinds(source) == {
        "self._spec_paths()": "helper returns discovery call"
    }


def test_loop_without_an_assert_is_not_a_claim() -> None:
    """The guard rates assertions, not iteration."""
    source = """
        def test_collects():
            names = [p.name for p in ROOT.glob("*.py") if p.name]
            for name in names:
                print(name)
            assert names
    """
    assert _kinds(source) == {}


def test_assert_all_over_a_filtered_genexp_is_a_claim() -> None:
    """``all()`` over an empty iterable is True — the same failure, no loop."""
    source = """
        def test_all_typed():
            assert all(line.startswith("export") for line in LINES if line.strip())
    """
    assert _kinds(source) == {
        'line.startswith("export") for line in LINES if line.strip()':
            "filtered comprehension",
    }


def test_assert_not_any_over_a_filtered_genexp_is_a_claim() -> None:
    """``not any()`` over an empty iterable is True as well."""
    source = """
        def test_no_bools():
            assert not any("True" in line for line in LINES if "bool" in line)
    """
    assert _kinds(source) == {
        '"True" in line for line in LINES if "bool" in line':
            "filtered comprehension",
    }


def test_assert_any_alone_is_not_a_claim() -> None:
    """``any()`` over an empty iterable is False — it fails loudly, not silently."""
    source = """
        def test_some_match():
            assert any(line.startswith("export") for line in LINES if line.strip())
    """
    assert _kinds(source) == {}


def test_multiline_iterable_is_rendered_single_line() -> None:
    """The ``label.new`` shape: a wrapped genexp must not become a multi-line key.

    ``ast.get_source_segment`` preserves the original newlines and
    indentation verbatim when the iterated expression spans several source
    lines. Left unnormalised that breaks two promises: ``main()`` prints
    one line per claim, and ``VacuousClaim.key`` is supposed to be a stable
    identity, not a blob of raw whitespace that shifts on reformatting.
    """
    source = """
        def test_wrapped():
            assert all(
                not flag.startswith("--")
                for flag in flags
                if flag
            )
    """
    assert _kinds(source) == {
        'not flag.startswith("--") for flag in flags if flag':
            "filtered comprehension",
    }
