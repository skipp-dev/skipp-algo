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


def test_recorded_property_is_a_claim() -> None:
    """A recording object is a lived idiom, not a hypothetical shape.

    The TypeScript half found ``recording.filterCalls`` to be the *dominant*
    recording shape in ``automation/tradingview/tests`` and had to grow a
    dotted binding to see it. Python's analyzer had the ``ast.Attribute``
    lookup branch from the start but no assignment ever wrote a dotted key,
    so the branch could not be reached and this whole shape reported
    nothing.
    """
    source = """
        def test_every_call_is_scoped():
            rec.calls = [p for p in ROOT.glob("*.py") if p.name]
            for call in rec.calls:
                assert call.scoped
    """
    assert _kinds(source) == {"rec.calls": "local filtered comprehension"}


def test_a_witness_on_the_recorded_property_clears_it() -> None:
    """The dotted binding is a real binding: the normal idiom heals it."""
    source = """
        def test_every_call_is_scoped():
            rec.calls = [p for p in ROOT.glob("*.py") if p.name]
            assert rec.calls
            for call in rec.calls:
                assert call.scoped
    """
    assert _kinds(source) == {}


def test_an_unbound_property_access_is_not_a_claim() -> None:
    """Boundedness, mirroring the TypeScript half exactly.

    Only a property the analyzer *watched* being assigned something
    emptiable is classifiable. Reporting on every attribute access would
    mean claiming that a config object nobody in this file populates might
    be empty — ``CONFIG.targets`` is not evidence of anything, and a
    detector that guesses is a detector nobody trusts.
    """
    source = """
        def test_every_target_is_known():
            for target in CONFIG.targets:
                assert target in KNOWN
    """
    assert _kinds(source) == {}


def test_a_witness_behind_a_condition_is_not_a_witness() -> None:
    """``if cond: assert hits`` may never run, so it proves nothing."""
    source = """
        def test_hits_are_scoped():
            hits = [p for p in ROOT.glob("*.py") if p.name]
            if RUN_EXTRA_CHECK:
                assert hits
            for hit in hits:
                assert hit.name
    """
    assert _kinds(source) == {"hits": "local filtered comprehension"}


def test_a_witness_carried_by_a_neighbouring_loop_is_not_a_witness() -> None:
    """A witness inside a loop cannot cover a claim outside that loop.

    The loop may run zero times, in which case the "witness" never
    executed — a vacuum-prone assertion exonerating another one.
    """
    source = """
        def test_hits_are_scoped():
            hits = [p for p in ROOT.glob("*.py") if p.name]
            for pattern in PATTERNS:
                assert hits
            for hit in hits:
                assert hit.name
    """
    assert _kinds(source) == {"hits": "local filtered comprehension"}


def test_a_witness_under_pytest_raises_is_not_a_witness() -> None:
    """The polarity inversion, and the reason this filter exists.

    Under ``pytest.raises(AssertionError)`` the assertion is *expected to
    fail*. Reading it as proof of non-emptiness inverts its meaning — the
    same mistake the TypeScript analyzer guards against explicitly, latent
    on the Python side until now.
    """
    source = """
        def test_hits_are_scoped():
            hits = [p for p in ROOT.glob("*.py") if p.name]
            with pytest.raises(AssertionError):
                assert hits
            for hit in hits:
                assert hit.name
    """
    assert _kinds(source) == {"hits": "local filtered comprehension"}


def test_a_witness_inside_a_raises_block_does_not_cover_that_block() -> None:
    """The polarity inversion one scope level down.

    Inside ``pytest.raises(AssertionError)`` the ``assert hits`` is
    *expected to fail*: if ``hits`` is empty it raises, the block is
    satisfied, the test goes green and the loop ran zero times. Reading it
    as proof of non-emptiness for a loop in its own block is the same
    mistake as reading it as proof for the block above.
    """
    source = """
        def test_empty_input_is_rejected():
            hits = [p for p in ROOT.glob("*.py") if p.name]
            with pytest.raises(AssertionError):
                assert hits
                for hit in hits:
                    assert hit.rejected
    """
    assert _kinds(source) == {"hits": "local filtered comprehension"}


def test_a_witness_inside_a_non_matching_raises_block_still_counts() -> None:
    """Voiding must be narrower than "any raises block", or it fabricates.

    Under ``pytest.raises(ValueError)`` a failing ``assert hits`` raises an
    ``AssertionError`` that does *not* match, so it propagates and the test
    fails loudly — measured, not assumed. The witness is therefore genuine
    and voiding it would invent a claim. Only a context that catches
    ``AssertionError`` itself (or via ``Exception``/``BaseException``)
    inverts the polarity.
    """
    source = """
        def test_bad_input_is_rejected():
            hits = [p for p in ROOT.glob("*.py") if p.name]
            with pytest.raises(ValueError):
                assert hits
                for hit in hits:
                    assert hit.rejected
    """
    assert _kinds(source) == {}


def test_a_witness_before_a_raises_block_still_covers_it() -> None:
    """The honest restructuring, and why voiding is actionable.

    A witness that already ran before the block was entered is unaffected —
    which is exactly the shape the guard's message steers a reader towards.
    """
    source = """
        def test_empty_input_is_rejected():
            hits = [p for p in ROOT.glob("*.py") if p.name]
            assert hits
            with pytest.raises(AssertionError):
                for hit in hits:
                    assert hit.rejected
    """
    assert _kinds(source) == {}


def test_a_claim_inside_a_match_case_is_seen() -> None:
    """``Match.cases`` holds ``match_case``, not statements.

    A traversal that only collects ``list[ast.stmt]`` fields walks straight
    past every ``match`` arm. A guard against unobserved checks must not
    have somewhere it never looks.
    """
    source = """
        def test_modes():
            hits = [p for p in ROOT.glob("*.py") if p.name]
            match mode:
                case "strict":
                    for hit in hits:
                        assert hit.name
    """
    assert _kinds(source) == {"hits": "local filtered comprehension"}


def test_a_claim_inside_a_nested_class_body_is_seen() -> None:
    """A nested class body really does execute when the test runs.

    ``_walk_own`` descends into it (it skips only functions and lambdas),
    so refusing to descend here would have been a blind spot rather than a
    scope rule.
    """
    source = """
        def test_probe():
            hits = [p for p in ROOT.glob("*.py") if p.name]
            class Probe:
                for hit in hits:
                    assert hit.name
    """
    assert _kinds(source) == {"hits": "local filtered comprehension"}


def test_a_claim_inside_a_nested_def_is_not_the_outer_tests() -> None:
    """The one thing the traversal still refuses to enter.

    Pinned because the skip rule was narrowed from "def, class, lambda" to
    "def" alone: a nested helper's loop belongs to that helper, and
    ``scan_source`` visits it in its own right.
    """
    source = """
        def test_probe():
            hits = [p for p in ROOT.glob("*.py") if p.name]
            def check():
                for hit in hits:
                    assert hit.name
    """
    assert _kinds(source) == {}


def test_a_witness_in_the_same_loop_body_still_counts() -> None:
    """The sound in-loop idiom must keep working — it is lived repo code.

    ``tests/test_pytest_marker_bucket_discipline.py`` writes exactly this:
    the witness and the loop it covers share one block, so whenever the
    inner loop runs, the witness ran on the same iteration. Excluding all
    loop-carried asserts (rather than scoping them to their block) would
    turn that healthy site into a false positive.
    """
    source = """
        def test_globs_are_live():
            for pattern in ("test_a*.py", "test_b*.py"):
                matched = sorted(TESTS_DIR.glob(pattern))
                assert matched, "glob matches nothing — dead inventory"
                for match in matched:
                    assert is_fast(match.name)
    """
    assert _kinds(source) == {}


def test_a_witness_inside_a_plain_with_block_still_counts() -> None:
    """A non-suppressing context manager does not make an assert conditional."""
    source = """
        def test_written_files_are_named():
            with tempfile.TemporaryDirectory() as directory:
                written = [p for p in Path(directory).glob("*") if p.name]
                assert written
                for path in written:
                    assert path.name
    """
    assert _kinds(source) == {}


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


def test_witness_on_the_base_covers_an_unfiltered_genexp() -> None:
    """``assert xs`` above ``assert all(f(x) for x in xs)`` is a witness.

    The repo's most common pairing, and the one the loop form already
    handles. ``_iterating_asserts`` hands back the *comprehension* for the
    ``all()`` shape, so comparing only the comprehension's own text against
    the witness set can never match a witness written on ``xs`` — the claim
    would be reported although the line directly above proves it wrong.
    """
    source = """
        def test_all_debug():
            records = [r for r in caplog.records if "unreadable" in r.message]
            assert records, "expected at least one matching record"
            assert all(r.levelno == DEBUG for r in records)
    """
    assert _kinds(source) == {}


def test_witness_on_the_base_does_not_cover_a_filtered_genexp() -> None:
    """An ``if`` clause can empty the comprehension while the base is full."""
    source = """
        def test_all_critical_ok():
            results = probe_all()
            assert results, "no probes ran"
            assert all(r.status == "OK" for r in results if r.critical)
    """
    assert _kinds(source) == {
        "r.status == \"OK\" for r in results if r.critical":
            "filtered comprehension",
    }


def test_witness_on_the_outer_base_does_not_cover_a_nested_genexp() -> None:
    """With a second ``for`` clause the inner iterable can still be empty.

    Every panel existing says nothing about any panel having a target, so a
    witness on the outer iterable must not clear the comprehension.
    """
    source = """
        def test_all_scoped():
            panels = [p for p in dashboard if p.get("type")]
            assert panels, "no panels"
            assert all(t.expr for p in panels for t in p.targets)
    """
    assert _kinds(source) == {
        "t.expr for p in panels for t in p.targets":
            "local filtered comprehension",
    }


def test_parametrize_over_a_literal_is_not_a_claim() -> None:
    """A literal argvalues list cannot silently become empty."""
    source = """
        @pytest.mark.parametrize("name", ["a", "b"])
        def test_names(name):
            assert name.islower()
    """
    assert _kinds(source) == {}


def test_parametrize_over_a_frozenset_constant_is_not_a_claim() -> None:
    """``_FROZEN_SITES`` is a literal: emptying it is a visible edit."""
    source = """
        _FROZEN_SITES = frozenset({("a.py", 1), ("b.py", 2)})

        @pytest.mark.parametrize(("rel", "lineno"), sorted(_FROZEN_SITES))
        def test_frozen_site_still_present(rel, lineno):
            assert (ROOT / rel).is_file()
    """
    assert _kinds(source) == {}


def test_parametrize_over_a_discovery_call_is_a_claim() -> None:
    """Zero argvalues collects zero tests — no skip, no failure, no output."""
    source = """
        @pytest.mark.parametrize("path", (REPO_ROOT / "artifacts").glob("*.json"))
        def test_specs(path):
            assert path.read_text()
    """
    assert _kinds(source) == {
        '(REPO_ROOT / "artifacts").glob("*.json")': "parametrize discovery call"
    }


def test_parametrize_over_a_helper_is_a_claim() -> None:
    source = """
        def _iter_workflow_files():
            return sorted((ROOT / ".github" / "workflows").glob("*.yml"))

        @pytest.mark.parametrize("path", _iter_workflow_files())
        def test_workflow_auth(path):
            assert "permissions:" in path.read_text()
    """
    assert _kinds(source) == {
        "_iter_workflow_files()": "parametrize helper returns discovery call"
    }


def test_parametrize_over_a_filtered_module_constant_is_a_claim() -> None:
    source = """
        _NK_CASES = [c for c in ALL_CASES if c.n > 0]

        @pytest.mark.parametrize("case", _NK_CASES)
        def test_llr(case):
            assert case.llr > 0
    """
    assert _kinds(source) == {"_NK_CASES": "parametrize local filtered comprehension"}


def test_class_decorated_parametrize_over_a_literal_is_not_a_claim() -> None:
    """A class-level parametrize is as unemptiable as a function-level one.

    ``tests/test_newsstack_retry_after_hygiene.py`` carries this exact
    shape: ``TestParseRetryAfterSeconds`` decorated with a literal list of
    module paths, applied to every method on the class.
    """
    source = """
        @pytest.mark.parametrize("module_path", ["a.mod", "b.mod"])
        class TestParseRetryAfterSeconds:
            def test_accepts_integer_seconds_form(self, module_path):
                assert module_path
    """
    assert _kinds(source) == {}


def test_class_decorated_parametrize_over_a_discovery_call_is_a_claim() -> None:
    """pytest applies a class-level parametrize to every method on it.

    A guard blind to ``ast.ClassDef.decorator_list`` would never see this
    shape at all -- reporting clean while never having looked.
    """
    source = """
        @pytest.mark.parametrize("path", (REPO_ROOT / "specs").glob("*.json"))
        class TestSpecs:
            def test_one(self, path):
                assert path.read_text()

            def test_two(self, path):
                assert path.exists()
    """
    assert _kinds(source) == {
        '(REPO_ROOT / "specs").glob("*.json")': "parametrize discovery call"
    }


def test_class_decorated_parametrize_over_a_helper_is_a_claim() -> None:
    source = """
        def _iter_workflow_files():
            return sorted((ROOT / ".github" / "workflows").glob("*.yml"))

        @pytest.mark.parametrize("path", _iter_workflow_files())
        class TestWorkflows:
            def test_one(self, path):
                assert "permissions:" in path.read_text()
    """
    assert _kinds(source) == {
        "_iter_workflow_files()": "parametrize helper returns discovery call"
    }


def test_empty_list_accumulator_is_a_claim() -> None:
    """The recording idiom: starts empty, stays empty when nothing happens.

    This is the shape the TypeScript half has always caught and the Python
    half never did — ``calls = []``, the code under test appends, and the
    loop asserts. When the code under test does nothing at all, the loop
    runs zero times and the test still reports success.
    """
    source = """
        def test_records():
            calls = []
            run(lambda name: calls.append(name))
            for call in calls:
                assert call.startswith("smc")
    """
    assert _kinds(source) == {"calls": "local empty literal"}


def test_nonempty_list_literal_is_not_a_claim() -> None:
    """A literal with elements cannot be empty, exactly as a tuple cannot."""
    source = """
        def test_flags():
            flags = ["--start-date", "--end-date"]
            for flag in flags:
                assert flag in TEXT
    """
    assert _kinds(source) == {}


def test_empty_dict_accumulator_is_a_claim() -> None:
    source = """
        def test_seen():
            seen = {}
            record(seen)
            for key in seen:
                assert key.isupper()
    """
    assert _kinds(source) == {"seen": "local empty literal"}


def test_zero_argument_list_constructor_is_a_claim() -> None:
    """``list()`` is ``[]`` spelled as a call and must read the same.

    ``_TRANSPARENT_CALLS`` already names ``list``/``set``, but only for the
    argument-carrying form where emptiness passes through. With no argument
    there is nothing to pass through — the result is empty by construction.
    """
    source = """
        def test_records():
            calls = list()
            run(calls.append)
            for call in calls:
                assert call
    """
    assert _kinds(source) == {"calls": "local empty literal"}


def test_a_witness_clears_an_empty_literal_accumulator() -> None:
    """The lived fix must keep working: assert the recording non-empty."""
    source = """
        def test_records():
            calls = []
            run(calls.append)
            assert calls, "nothing recorded — this pin would pass vacuously"
            for call in calls:
                assert call.startswith("smc")
    """
    assert _kinds(source) == {}


def test_dict_with_keyword_args_is_not_a_claim() -> None:
    """``dict(a=1)`` is not ``{}`` spelled as a call — it has content.

    ``_EMPTY_CONSTRUCTORS`` only checked ``node.args``, so a keyword-only
    call like ``dict(a=1)`` or ``dict(**other)`` had nothing in ``args`` and
    misclassified as empty even though it plainly is not.
    """
    source = """
        def test_records():
            calls = dict(a=1)
            for call in calls:
                assert call
    """
    assert _kinds(source) == {}


def test_a_property_of_a_produced_object_is_a_claim() -> None:
    """The analyzer watched this object being made, so its fields are data.

    It cannot see inside ``run_walk_forward``, but it does not need to: the
    object is a runtime result, not source text, so ``out.folds`` can be
    empty and the loop can run zero times.
    """
    source = """
        def test_folds():
            out = run_walk_forward(returns)
            for fold in out.folds:
                assert fold.n_train == 80
    """
    assert _kinds(source) == {"out.folds": "property of a produced object"}


def test_a_property_of_an_imported_module_is_not_a_claim() -> None:
    """A module constant is source the analyzer never watched being produced.

    Measured 2026-08-04: every ``<module alias>.<CONST>`` iterated in
    ``tests/`` resolves to a non-empty tuple or frozenset literal, so
    classifying these would report false positives rather than defects.
    """
    source = """
        import scripts.pine_library_freshness as plf

        def test_scope():
            for name in plf.SHARED_LIBRARIES:
                assert name.startswith("skipp_")
    """
    assert _kinds(source) == {}


def test_a_produced_object_itself_is_not_a_claim() -> None:
    """Only the *properties* are classified, never the object.

    ``for row in load_rows()`` is already covered by the helper and
    discovery rules; making the bare name emptiable would classify every
    local that happens to hold a call result.
    """
    source = """
        def test_object():
            out = run_walk_forward(returns)
            for fold in out:
                assert fold.n_train == 80
    """
    assert _kinds(source) == {}


def test_a_length_witness_clears_a_produced_property() -> None:
    source = """
        def test_folds():
            out = run_walk_forward(returns)
            assert len(out.folds) == 4
            for fold in out.folds:
                assert fold.n_train == 80
    """
    assert _kinds(source) == {}


def test_a_nonempty_subset_witnesses_the_base_it_was_drawn_from() -> None:
    """A non-empty subset proves the set it came from non-empty.

    Lived at ``tests/test_smc_volume_profile.py:69-73``: the test filters
    ``profile.rows`` into ``nonzero_rows``, asserts that is non-empty, then
    loops over ``profile.rows``. Without this rule that loop reports as
    unwitnessed even though the proof is two lines above it.
    """
    source = """
        def test_rows():
            profile = compute_volume_profile(bars)
            nonzero = [row for row in profile.rows if row.total > 0.0]
            assert len(nonzero) > 1
            for row in profile.rows:
                assert row.total > 0.0
    """
    assert _kinds(source) == {}


def test_a_bare_truth_check_on_a_subset_also_witnesses_its_base() -> None:
    source = """
        def test_rows():
            profile = compute_volume_profile(bars)
            nonzero = [row for row in profile.rows if row.total > 0.0]
            assert nonzero
            for row in profile.rows:
                assert row.total > 0.0
    """
    assert _kinds(source) == {}


def test_the_subset_rule_does_not_run_backwards() -> None:
    """The inverse stays refused: a non-empty base proves nothing about a subset.

    This is the direction :func:`_witness_candidates` already rejects, and
    the subset rule must not reopen it — the filter can empty the result
    while the base is full.
    """
    source = """
        def test_rows():
            profile = compute_volume_profile(bars)
            assert len(profile.rows) > 1
            nonzero = [row for row in profile.rows if row.total > 0.0]
            for row in nonzero:
                assert row.total > 0.0
    """
    assert _kinds(source) == {"nonzero": "local filtered comprehension"}


def test_a_value_derived_from_a_produced_property_is_a_claim() -> None:
    """A local holding a produced property carries that property's emptiness.

    ``keys = list(module._DERIVED_KEYS)`` is the lived shape at
    ``tests/test_streamlit_terminal_session_schema_invalidation.py:44``.
    Merging the produced properties *after* :func:`_bind_assignments` would
    lose this: the assignment is classified while the produced properties
    are not yet in the binding dict, so ``keys`` binds to nothing and the
    loop below reports clean. They are seeded in *before* instead.
    """
    source = """
        def test_derived():
            module = reload_terminal()
            keys = list(module._DERIVED_KEYS)
            for key in keys:
                assert key not in state
    """
    assert _kinds(source) == {"keys": "local property of a produced object"}


def test_an_assignment_wins_over_the_produced_property_kind() -> None:
    """Seeding must not let the coarse kind mask a specific one.

    ``rec.calls`` is both a property of a produced object *and* a dotted
    name the function was watched assigning a filtered comprehension to.
    The assignment is the more specific fact and has to survive the seed.
    """
    source = """
        def test_recording():
            rec = make_recorder()
            rec.calls = [c for c in observed if c]
            for call in rec.calls:
                assert call
    """
    assert _kinds(source) == {"rec.calls": "local filtered comprehension"}


def test_assert_any_witnesses_the_iterable_it_ranges_over() -> None:
    """``any(())`` is ``False``, so a passing ``assert any(...)`` proves the base.

    Lived at ``tests/test_realtime_active_signal_lifecycle.py:98-99``: the
    test asserts ``any(s.symbol == "AAPL" ...)`` and then ``all(s.symbol !=
    "NVDA" ...)`` over the same list. The first assertion goes red on an
    empty list, so the second cannot be vacuous — reporting it was a false
    positive, and a false positive is fixed here, never waived.
    """
    source = """
        def test_active():
            eng = make_engine()
            assert any(s.symbol == "AAPL" for s in eng.active)
            assert all(s.symbol != "NVDA" for s in eng.active)
    """
    assert _kinds(source) == {}


def test_assert_not_any_does_not_witness_its_iterable() -> None:
    """The negation proves nothing: ``not any(())`` is ``True``.

    This is the polarity half of the rule above and the reason it is keyed
    to the un-negated form only.
    """
    source = """
        def test_active():
            eng = make_engine()
            assert not any(s.symbol == "NVDA" for s in eng.active)
            for s in eng.active:
                assert s.ok
    """
    assert _kinds(source) == {
        's.symbol == "NVDA" for s in eng.active': "property of a produced object",
        "eng.active": "property of a produced object",
    }


def test_a_membership_check_witnesses_its_container() -> None:
    """``x in y`` cannot be true of an empty ``y``.

    Lived at ``tests/test_realtime_signals_uplift_b.py:396-398``: two
    ``assert "…" in s._cache`` lines directly above a loop over
    ``s._cache``.
    """
    source = """
        def test_cache():
            s = make_scorer()
            assert "FRESH:1D" in s._cache
            assert all(not k.startswith("S") for k in s._cache)
    """
    assert _kinds(source) == {}


def test_a_negative_membership_check_does_not_witness_its_container() -> None:
    """``x not in y`` is true of an empty ``y``, so it proves nothing."""
    source = """
        def test_cache():
            s = make_scorer()
            assert "GONE:1D" not in s._cache
            for k in s._cache:
                assert k
    """
    assert _kinds(source) == {"s._cache": "property of a produced object"}


def test_a_literal_equality_on_a_comprehension_witnesses_its_base() -> None:
    """A comprehension equal to a non-empty literal had a non-empty base.

    Lived at ``tests/test_smc_integration_measurement_evidence.py:145``:
    ``assert [e.family for e in evidence.scored_events] == ["BOS", ...]``
    sits directly above four ``assert all(... for e in
    evidence.scored_events)`` lines. The list it is compared to has four
    entries, so the loop underneath it demonstrably ran.
    """
    source = """
        def test_events():
            evidence = build_evidence()
            assert [e.family for e in evidence.scored_events] == ["BOS", "OB"]
            assert all(e.outcome is True for e in evidence.scored_events)
    """
    assert _kinds(source) == {}


def test_an_empty_literal_equality_does_not_witness_a_comprehension_base() -> None:
    """``[... for x in xs] == []`` is exactly the empty case, not a witness."""
    source = """
        def test_events():
            evidence = build_evidence()
            assert [e.family for e in evidence.scored_events] == []
            assert all(e.outcome is True for e in evidence.scored_events)
    """
    assert _kinds(source) == {
        "e.outcome is True for e in evidence.scored_events": (
            "property of a produced object"
        )
    }


def test_a_bare_generator_subset_does_not_witness_its_base() -> None:
    """A generator object is always truthy, so ``assert gen`` proves nothing.

    The subset rule credits the base of a comprehension that was asserted
    non-empty. For a *generator* expression the assertion is vacuously true
    whatever the base held, so crediting it would fabricate the witness this
    module treats as the worse failure. List and set comprehensions are
    real containers and keep the rule.
    """
    source = """
        def test_rows():
            profile = compute_volume_profile(bars)
            nonzero = (row for row in profile.rows if row.total > 0.0)
            assert nonzero
            for row in profile.rows:
                assert row.total > 0.0
    """
    assert _kinds(source) == {"profile.rows": "property of a produced object"}


def test_a_rebound_subset_credits_no_base_at_all() -> None:
    """Two comprehensions on one name: neither may be credited.

    ``_subset_bindings`` is flow-insensitive — it cannot know which
    assignment was live when the witness ran. Unioning both bases lets
    ``assert nonzero`` prove a set it was never drawn from, and taking the
    last one is no better: the witness may sit *above* the later
    assignment, which would credit it retroactively. A name assigned more
    than once is therefore dropped entirely.
    """
    source = """
        def test_rows():
            profile = compute_volume_profile(bars)
            other = load_other()
            nonzero = [row for row in other.rows if row.total > 0.0]
            nonzero = [row for row in profile.rows if row.total > 0.0]
            assert nonzero
            for row in other.rows:
                assert row.total > 0.0
    """
    assert _kinds(source) == {"other.rows": "property of a produced object"}


def test_a_subset_bound_in_two_branches_credits_no_base() -> None:
    """Neither branch is known to have run, so neither base is proven."""
    source = """
        def test_rows():
            profile = compute_volume_profile(bars)
            other = load_other()
            if flag:
                subset = [row for row in profile.rows if row.ok]
            else:
                subset = [row for row in other.rows if row.ok]
            assert subset
            for row in profile.rows:
                assert row.ok
    """
    assert _kinds(source) == {"profile.rows": "property of a produced object"}


def test_a_witness_does_not_credit_a_later_assignment_retroactively() -> None:
    """The witness runs against the *first* binding, not the last one.

    Order matters and the analyzer does not track it, so a name reassigned
    below its own witness must not lend that witness the later base. This
    is the shape a last-write-wins rule gets wrong.
    """
    source = """
        def test_rows():
            profile = compute_volume_profile(bars)
            other = load_other()
            subset = [row for row in other.rows if row.ok]
            assert subset
            for row in profile.rows:
                assert row.ok
            subset = [row for row in profile.rows if row.ok]
    """
    assert _kinds(source) == {"profile.rows": "property of a produced object"}


def test_a_subset_rebound_to_a_non_comprehension_credits_nothing() -> None:
    """``nonzero = [...]`` then ``nonzero = f()`` leaves the base unproven."""
    source = """
        def test_rows():
            profile = compute_volume_profile(bars)
            nonzero = [row for row in profile.rows if row.ok]
            nonzero = recompute()
            assert nonzero
            for row in profile.rows:
                assert row.ok
    """
    assert _kinds(source) == {"profile.rows": "property of a produced object"}


def test_a_nested_comprehension_witness_credits_only_the_outer_iterable() -> None:
    """Regression pin for ``generators[0]`` in :func:`_comprehension_base`.

    The inner generator's iterable is written in terms of the
    comprehension's *own* loop variable, so its rendered text can collide
    with an unrelated expression in the enclosing scope. Crediting it would
    clear a claim the witness says nothing about.
    """
    source = """
        def test_items():
            group = load_group()
            a = load_a()
            assert len([x for a in group.rows for x in a.items]) > 0
            for x in a.items:
                assert x
    """
    assert _kinds(source) == {"a.items": "property of a produced object"}


def test_a_nested_subset_credits_only_the_outer_iterable() -> None:
    """Regression pin for ``generators[0]`` in :func:`_subset_bindings`."""
    source = """
        def test_items():
            group = load_group()
            a = load_a()
            flat = [x for a in group.rows for x in a.items]
            assert flat
            for x in a.items:
                assert x
    """
    assert _kinds(source) == {"a.items": "property of a produced object"}


def test_a_parameter_shadowed_by_a_later_comprehension_credits_nothing() -> None:
    """A fixture parameter is a binding, and an uncounted one re-opens the hole.

    ``assert subset`` here witnesses the *parameter* — the comprehension is
    assigned below it. Unless the parameter is counted as a binding, the
    name looks singly-bound and the witness is credited to
    ``profile.rows``, which it says nothing about. A pytest fixture name
    colliding with a local comprehension name is ordinary code.
    """
    source = """
        def test_rows(subset):
            profile = compute_volume_profile(bars)
            assert subset
            for row in profile.rows:
                assert row.ok
            subset = [row for row in profile.rows if row.ok]
    """
    assert _kinds(source) == {"profile.rows": "property of a produced object"}


def test_a_starred_or_keyword_parameter_also_counts_as_a_binding() -> None:
    """``*args``/``**kwargs`` bind names too, and so do keyword-only params."""
    source = """
        def test_rows(*subset, **rest):
            profile = compute_volume_profile(bars)
            assert subset
            for row in profile.rows:
                assert row.ok
            subset = [row for row in profile.rows if row.ok]
    """
    assert _kinds(source) == {"profile.rows": "property of a produced object"}


def test_an_except_alias_shadowed_by_a_comprehension_credits_nothing() -> None:
    """``except … as subset`` binds — and unbinds — the same name."""
    source = """
        def test_rows():
            profile = compute_volume_profile(bars)
            try:
                run()
            except ValueError as subset:
                pass
            subset = [row for row in profile.rows if row.ok]
            assert subset
            for row in profile.rows:
                assert row.ok
    """
    assert _kinds(source) == {"profile.rows": "property of a produced object"}


def test_an_import_alias_shadowed_by_a_comprehension_credits_nothing() -> None:
    """``import x as subset`` is a binding like any other."""
    source = """
        def test_rows():
            import collections as subset

            profile = compute_volume_profile(bars)
            subset = [row for row in profile.rows if row.ok]
            assert subset
            for row in profile.rows:
                assert row.ok
    """
    assert _kinds(source) == {"profile.rows": "property of a produced object"}


def test_a_match_capture_shadowed_by_a_comprehension_credits_nothing() -> None:
    """A ``match`` capture pattern binds its name in the enclosing scope."""
    source = """
        def test_rows(command):
            profile = compute_volume_profile(bars)
            match command:
                case [subset]:
                    pass
            subset = [row for row in profile.rows if row.ok]
            assert subset
            for row in profile.rows:
                assert row.ok
    """
    assert _kinds(source) == {"profile.rows": "property of a produced object"}
