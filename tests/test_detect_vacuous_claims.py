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


def test_bare_truth_check_witnesses_its_own_iterable() -> None:
    """The lived idiom from the repo: ``assert xs, "…would pass vacuously"``."""
    source = """
        def test_no_python_booleans():
            bool_lines = [ln for ln in TEXT.splitlines() if "const bool " in ln]
            assert bool_lines, "generator emitted no 'const bool' export"
            for line in bool_lines:
                assert "True" not in line
    """
    assert _kinds(source) == {}


def test_a_witness_for_one_iterable_does_not_cover_its_neighbour() -> None:
    """The strongest single piece of evidence in the repo, in one fixture.

    Someone recognised the class, healed ``bool_lines`` and left the
    identically shaped ``export_lines`` directly above it alone.
    """
    source = """
        def test_pine_syntax_valid():
            export_lines = [ln for ln in TEXT.splitlines() if ln.startswith("export")]
            bool_lines = [ln for ln in TEXT.splitlines() if "const bool " in ln]
            assert bool_lines
            for line in export_lines:
                assert TYPE_PAT.match(line)
    """
    assert _kinds(source) == {"export_lines": "local filtered comprehension"}


def test_len_check_is_a_witness() -> None:
    source = """
        def test_ledgers_are_gated():
            ledgers = [p for p in TEST_DIR.glob("test_*.py") if "pin_registry" in p.read_text()]
            assert len(ledgers) >= 15, "discovery found nothing"
            for ledger in ledgers:
                assert ledger.name in STEP
    """
    assert _kinds(source) == {}


def test_equality_with_a_nonempty_literal_is_a_witness() -> None:
    source = """
        def test_exact_set():
            found = [n for n in NAMES if n.startswith("smc_")]
            assert found == ["smc_a", "smc_b"]
            for name in found:
                assert name.islower()
    """
    assert _kinds(source) == {}


def test_equality_with_an_empty_literal_is_not_a_witness() -> None:
    """``assert xs == []`` proves emptiness — the opposite of a witness."""
    source = """
        def test_nothing_left():
            found = [n for n in NAMES if n.startswith("smc_")]
            assert found == []
            for name in found:
                assert name.islower()
    """
    assert _kinds(source) == {"found": "local filtered comprehension"}


def test_raise_after_the_loop_is_a_witness() -> None:
    """The ``frozen site`` idiom: exhausting the loop is itself a failure."""
    source = """
        def test_frozen_site_still_present():
            for path in ROOT.rglob("*.py"):
                if path.name == "target.py":
                    assert path.read_text()
                    return
            raise AssertionError("target.py no longer present — pin is stale")
    """
    assert _kinds(source) == {}


def test_for_else_raise_is_a_witness() -> None:
    source = """
        def test_frozen_site_still_present():
            for path in ROOT.rglob("*.py"):
                if path.name == "target.py":
                    assert path.read_text()
                    break
            else:
                raise AssertionError("target.py no longer present")
    """
    assert _kinds(source) == {}


def test_pytest_fail_after_the_loop_is_a_witness() -> None:
    source = """
        def test_frozen_site_still_present():
            for path in ROOT.rglob("*.py"):
                if path.name == "target.py":
                    assert path.read_text()
                    return
            pytest.fail("target.py no longer present")
    """
    assert _kinds(source) == {}


def test_a_witness_in_a_different_test_does_not_count() -> None:
    """Cross-test witnesses are a registry decision, not a detector heuristic.

    ``tests/test_spec_constant_drift.py`` is the real instance: a separate
    ``test_at_least_one_spec_exists`` proves the glob non-empty, but at a
    different expression instance that no static rule can tie to this one.
    Such cases get a dated exemption, so the reasoning stays visible.
    """
    source = """
        def test_at_least_one_spec_exists():
            assert list(SPEC_DIR.glob("*.json"))

        def test_specs_are_valid():
            for path in SPEC_DIR.glob("*.json"):
                assert path.read_text()
    """
    assert _kinds(source) == {'SPEC_DIR.glob("*.json")': "discovery call"}


def test_non_raising_fail_lookalike_is_not_a_witness() -> None:
    """Only an exact ``.fail`` attribute call counts — not a look-alike name.

    A helper like ``logger.softfail(...)`` may log or record a failure
    without raising. The earlier, broader implementation matched it because
    ``ast.unparse(...).endswith("fail")`` is true for ``logger.softfail``
    too — that would fabricate a witness and let a genuinely vacuous claim
    pass silently. The real ``pytest.fail`` idiom must stay recognised;
    see ``test_pytest_fail_after_the_loop_is_a_witness`` above.
    """
    source = """
        def test_frozen_site_still_present():
            for path in ROOT.rglob("*.py"):
                if path.name == "target.py":
                    assert path.read_text()
                    return
            logger.softfail("target.py no longer present")
    """
    assert _kinds(source) == {'ROOT.rglob("*.py")': "discovery call"}


def test_bare_fail_name_call_is_not_a_witness() -> None:
    """A bare ``fail(...)`` name call is deliberately not treated as raising.

    Unlike ``pytest.fail(...)`` / ``self.fail(...)``, a bare name gives no
    evidence about what it does without resolving the import it came from;
    accepting it on faith risks fabricating a witness for a helper that
    merely records a failure instead of raising one.
    """
    source = """
        def test_frozen_site_still_present():
            for path in ROOT.rglob("*.py"):
                if path.name == "target.py":
                    assert path.read_text()
                    return
            fail("target.py no longer present")
    """
    assert _kinds(source) == {'ROOT.rglob("*.py")': "discovery call"}


def test_witness_key_uses_the_same_renderer_as_the_iterable() -> None:
    """A witness must match through ``_render``, not ``ast.unparse``.

    ``ast.unparse`` normalises string quoting: the double-quoted source
    ``ROOT.glob("*.py")`` round-trips as ``ROOT.glob('*.py')``. If
    ``witness_keys`` rendered its keys with ``ast.unparse`` while the
    iterable is compared through ``_render`` (which preserves the source
    segment verbatim), this witness would never match its own loop and the
    claim would be reported despite being witnessed — silently, because
    each side's own tests only exercise its own renderer.
    """
    source = """
        def test_everything_typed():
            assert ROOT.glob("*.py")
            for path in ROOT.glob("*.py"):
                assert path.suffix == ".py"
    """
    assert _kinds(source) == {}
