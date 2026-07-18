from scripts.build_databento_usage_baseline import _classification, _markdown


def test_inventory_classification_is_total_for_known_surfaces() -> None:
    assert _classification("tests/test_x.py") == "test_fixture"
    assert _classification(".github/workflows/x.yml") == "workflow_configuration"
    assert _classification("docs/x.md") == "documentation"
    assert _classification("scripts/probe_x.py") == "research_or_cli"
    assert _classification("databento_client.py") == "runtime_or_library"


def test_markdown_calls_missing_external_usage_unknown() -> None:
    text = _markdown(
        {
            "revision": "abc",
            "subscriptions": [
                {
                    "name": "Example",
                    "monthly_cost_usd": 1,
                    "renews_on": "2026-08-01",
                    "exchange_or_distribution_fees_usd": None,
                }
            ],
            "classification_counts": {"runtime_or_library": 1},
        }
    )
    assert "unknown" in text
    assert "not zero" in text
    assert "| Example | $1 | unknown |" in text
