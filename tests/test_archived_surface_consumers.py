"""Unit gates for the archived-surface consumer detection.

`test_archived_surfaces_are_isolated_from_active_rollout` in
`test_pine_surface_registry.py` runs against the live registry — where the
archived population is currently **empty**, so it proves nothing about the logic
it applies. That is the whole reason these exist: the rule has to be shown to
work on data, or the day something is archived the gate would engage untested.

Both directions are pinned — it must catch a real stranded consumer, and it must
not fire on the ways a binding can legitimately look similar.
"""

from __future__ import annotations

from tests.smc_manifest_test_utils import (
    extract_bound_source_labels,
    extract_hidden_plot_labels,
    find_active_label_consumers,
)

ARCHIVED = "SMC_Old_Context.pine"


def _consumer(label: str) -> str:
    return f'src_x = input.source(close, "{label}", group = g_ctx)\n'


def test_a_stranded_consumer_is_found() -> None:
    findings = find_active_label_consumers(
        archived_labels={ARCHIVED: ("CTX OldSignal", "CTX OldLevel")},
        active_sources={"SMC_Context_Overlay.pine": _consumer("CTX OldSignal")},
        labels_still_published_by_active=frozenset(),
    )
    assert findings == {ARCHIVED: {"SMC_Context_Overlay.pine": ["CTX OldSignal"]}}


def test_a_clean_tree_reports_nothing() -> None:
    findings = find_active_label_consumers(
        archived_labels={ARCHIVED: ("CTX OldSignal",)},
        active_sources={"SMC_Context_Overlay.pine": _consumer("CTX LiveSignal")},
        labels_still_published_by_active=frozenset(),
    )
    assert findings == {}


def test_a_label_an_active_producer_still_publishes_is_not_a_stranded_binding() -> None:
    # The archived script happened to publish the same name; the binding is
    # served by the live producer. Counting it would make archiving impossible
    # for any surface that shared a single label with the engine.
    findings = find_active_label_consumers(
        archived_labels={ARCHIVED: ("BUS SchemaVersion",)},
        active_sources={"SMC_Decision_Board.pine": _consumer("BUS SchemaVersion")},
        labels_still_published_by_active=frozenset({"BUS SchemaVersion"}),
    )
    assert findings == {}


def test_several_consumers_of_several_labels_are_all_reported() -> None:
    findings = find_active_label_consumers(
        archived_labels={ARCHIVED: ("CTX A", "CTX B")},
        active_sources={
            "One.pine": _consumer("CTX A") + _consumer("CTX B"),
            "Two.pine": _consumer("CTX B"),
            "Three.pine": _consumer("CTX Unrelated"),
        },
        labels_still_published_by_active=frozenset(),
    )
    assert findings == {ARCHIVED: {"One.pine": ["CTX A", "CTX B"], "Two.pine": ["CTX B"]}}


def test_an_archived_surface_that_published_nothing_cannot_strand_anyone() -> None:
    findings = find_active_label_consumers(
        archived_labels={ARCHIVED: ()},
        active_sources={"One.pine": _consumer("CTX A")},
        labels_still_published_by_active=frozenset(),
    )
    assert findings == {}


# --- extractor -------------------------------------------------------------


def test_the_extractor_ignores_commented_out_bindings() -> None:
    source = '// src_dead = input.source(close, "CTX Dead", group = g)\n' + _consumer("CTX Live")
    assert extract_bound_source_labels(source) == ("CTX Live",)


def test_the_extractor_reads_both_families_and_quote_styles() -> None:
    source = (
        'a = input.source(close, "BUS SchemaVersion", group = g)\n'
        "b = input.source(hlc3, 'CTX SessionCode')\n"
    )
    assert extract_bound_source_labels(source) == ("BUS SchemaVersion", "CTX SessionCode")


def test_the_extractor_does_not_require_a_group() -> None:
    # extract_input_bindings does; a consumer gate that inherited that
    # requirement would miss every ungrouped binding.
    assert extract_bound_source_labels('a = input.source(close, "CTX Loose")\n') == ("CTX Loose",)


def test_the_extractor_finds_nothing_in_a_producer() -> None:
    source = "plot(7001, 'BUS SchemaVersion', display = display.none)\n"
    assert extract_bound_source_labels(source) == ()


# --- wiring, on real repo content ------------------------------------------


def test_the_rule_finds_a_real_consumer_when_a_real_producer_is_treated_as_archived() -> None:
    """Prove the whole path on actual sources, not just on fixtures.

    The synthetic gates above prove the logic; this proves the WIRING —
    registry file -> source text -> published labels -> active bindings —
    against files that really exist. Without it the extraction could quietly
    stop matching the repo's Pine style and every archival check would pass by
    finding nothing.

    Context Bus is used as the stand-in because it is a real producer with a
    real consumer (Context Overlay binds its channels). Nothing is archived
    here; the surface is merely treated as if it were.
    """
    from tests.smc_manifest_test_utils import ROOT

    producer = ROOT / "SMC_Context_Bus.pine"
    consumer = ROOT / "SMC_Context_Overlay.pine"
    assert producer.is_file() and consumer.is_file()

    active = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(ROOT.glob("SMC_*.pine"))
        if path.name != producer.name
    }
    still_published = set()
    for source in active.values():
        still_published.update(extract_hidden_plot_labels(source))

    published = extract_hidden_plot_labels(producer.read_text(encoding="utf-8"))
    assert published, "the stand-in producer publishes nothing; pick another"

    found = find_active_label_consumers(
        {producer.name: published}, active, frozenset(still_published)
    )

    assert producer.name in found, "the rule missed a consumer that demonstrably exists"
    assert consumer.name in found[producer.name]
    # Every channel the producer publishes is bound by the overlay, so the rule
    # must report all of them — a partial match would mean the extractor is
    # dropping bindings.
    assert found[producer.name][consumer.name] == sorted(published)
