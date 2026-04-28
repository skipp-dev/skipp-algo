from __future__ import annotations

from open_prep.newsstack_status import get_provider_cursor_caption, get_provider_status_notice


def test_get_provider_status_notice_maps_ok_to_caption() -> None:
    notice = get_provider_status_notice(
        {
            "providers": {
                "newsapi_ai": {
                    "provider_status": "ok",
                    "status_detail": "",
                }
            }
        },
        provider_key="newsapi_ai",
        provider_name="NewsAPI.ai",
    )

    assert notice == ("caption", "NewsAPI.ai: ok")


def test_get_provider_status_notice_maps_no_recent_matches_to_info() -> None:
    notice = get_provider_status_notice(
        {
            "providers": {
                "newsapi_ai": {
                    "provider_status": "ok_no_recent_matches",
                    "status_detail": "Event Registry reachable, but no recent items matched.",
                }
            }
        },
        provider_key="newsapi_ai",
        provider_name="NewsAPI.ai",
    )

    assert notice == (
        "info",
        "NewsAPI.ai: ok_no_recent_matches - Event Registry reachable, but no recent items matched.",
    )


def test_get_provider_status_notice_returns_none_without_provider_status() -> None:
    notice = get_provider_status_notice(
        {"providers": {"newsapi_ai": {"status_detail": "detail only"}}},
        provider_key="newsapi_ai",
        provider_name="NewsAPI.ai",
    )

    assert notice is None


def test_get_provider_cursor_caption_formats_epoch_and_uri() -> None:
    caption = get_provider_cursor_caption(
        {
            "cursor": {
                "newsapi_ai_last_seen_epoch": "1775684921.0",
                "newsapi_ai_last_seen_news_uri": "uri-feed-1",
            }
        },
        provider_key="newsapi_ai",
        provider_name="NewsAPI.ai",
    )

    assert caption == "NewsAPI.ai cursor: epoch=2026-04-08T21:48:41Z (1775684921.0) - uri=uri-feed-1"


def test_get_provider_cursor_caption_uses_empty_placeholders() -> None:
    caption = get_provider_cursor_caption(
        {
            "cursor": {
                "newsapi_ai_last_seen_epoch": "",
                "newsapi_ai_last_seen_news_uri": "",
            }
        },
        provider_key="newsapi_ai",
        provider_name="NewsAPI.ai",
    )

    assert caption is None
