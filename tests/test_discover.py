from __future__ import annotations

from datetime import datetime, timezone

from src.bedrock.client import BedrockClient
from src.db.mongo_client import ReviewQueueStore
from src.graph.nodes.discover import discover, is_likely_homepage
from tests.conftest import (
    FakeMongoClient,
    FakeReviewCollection,
    ScriptedBedrockRuntime,
    recording_web_search,
    tool_use_content,
)


def test_discover_respects_search_call_budget(settings) -> None:
    search = recording_web_search(
        [{"title": "Keep looking", "url": "https://example.com/a", "snippet": "more"}]
    )
    runtime = ScriptedBedrockRuntime(
        payloads_by_tool={
            "submit_candidates": [
                {
                    "items": [
                        {
                            "title": "Budgeted find",
                            "url": "https://example.com/found",
                            "snippet": "Akwa Ibom briefing",
                        }
                    ]
                }
            ]
        },
        converse_script=[
            tool_use_content("web_search", {"query": "Akwa Ibom news this week"}, "s1"),
            tool_use_content("web_search", {"query": "Uyo Nigeria culture"}, "s2"),
            tool_use_content("web_search", {"query": "should not run"}, "s3"),
        ],
    )
    settings.max_search_calls_per_run = 2
    mongo = ReviewQueueStore(
        uri=settings.mongodb_uri,
        db_name=settings.mongodb_db_name,
        client=FakeMongoClient(FakeReviewCollection()),
    )

    result = discover(
        {},
        bedrock=BedrockClient(
            region=settings.aws_region,
            model_id=settings.bedrock_model_id,
            runtime_client=runtime,
        ),
        mongo=mongo,
        web_search=search,
        seed_queries=settings.seed_queries,
        max_search_calls=2,
        now=datetime(2026, 9, 11, tzinfo=timezone.utc),
    )

    assert search.calls == ["Akwa Ibom news this week", "Uyo Nigeria culture"]
    assert result["discovered_items"][0]["url"] == "https://example.com/found"
    forced = runtime.calls[-1]["toolConfig"]["toolChoice"]
    assert forced == {"tool": {"name": "submit_candidates"}}


def test_discover_filters_urls_already_in_review_queue(settings, sample_item) -> None:
    new_url = "https://example.gov.ng/news/ikot-ekpene-bridge"
    search = recording_web_search()
    runtime = ScriptedBedrockRuntime(
        converse_script=[
            tool_use_content(
                "submit_candidates",
                {
                    "items": [
                        {
                            "title": sample_item["title"],
                            "url": sample_item["url"],
                            "snippet": sample_item["snippet"],
                        },
                        {
                            "title": "Bridge work begins in Ikot Ekpene",
                            "url": new_url,
                            "snippet": "A new bridge project was flagged off in Ikot Ekpene.",
                        },
                    ]
                },
                "submit-1",
            )
        ]
    )
    collection = FakeReviewCollection([{"source_url": sample_item["url"]}])
    mongo = ReviewQueueStore(
        uri=settings.mongodb_uri,
        db_name=settings.mongodb_db_name,
        client=FakeMongoClient(collection),
    )

    result = discover(
        {},
        bedrock=BedrockClient(
            region=settings.aws_region,
            model_id=settings.bedrock_model_id,
            runtime_client=runtime,
        ),
        mongo=mongo,
        web_search=search,
        seed_queries=settings.seed_queries,
        max_search_calls=settings.max_search_calls_per_run,
        now=datetime(2026, 9, 11, tzinfo=timezone.utc),
    )

    assert [item["url"] for item in result["discovered_items"]] == [new_url]
    assert search.calls == []


def test_is_likely_homepage_is_root_path_only() -> None:
    assert is_likely_homepage("https://example.com") is True
    assert is_likely_homepage("https://example.com/") is True
    assert is_likely_homepage("https://example.com/news/some-article-slug") is False
    # Category indexes are a known follow-up, not filtered yet.
    assert is_likely_homepage("https://example.com/category/tech") is False


def test_discover_drops_homepage_root_urls(settings) -> None:
    article_url = "https://example.com/news/uyo-market-story"
    runtime = ScriptedBedrockRuntime(
        converse_script=[
            tool_use_content(
                "submit_candidates",
                {
                    "items": [
                        {
                            "title": "AkwaIbomTimes | Breaking News, Politics, Business, Technology",
                            "url": "https://akwaibomtimes.com/",
                            "snippet": "Homepage of a news site.",
                        },
                        {
                            "title": "Uyo market story",
                            "url": article_url,
                            "snippet": "A specific market report from Uyo.",
                        },
                    ]
                },
                "submit-1",
            )
        ]
    )
    mongo = ReviewQueueStore(
        uri=settings.mongodb_uri,
        db_name=settings.mongodb_db_name,
        client=FakeMongoClient(FakeReviewCollection()),
    )

    result = discover(
        {},
        bedrock=BedrockClient(
            region=settings.aws_region,
            model_id=settings.bedrock_model_id,
            runtime_client=runtime,
        ),
        mongo=mongo,
        web_search=recording_web_search(),
        seed_queries=settings.seed_queries,
        max_search_calls=settings.max_search_calls_per_run,
        now=datetime(2026, 9, 11, tzinfo=timezone.utc),
    )

    assert [item["url"] for item in result["discovered_items"]] == [article_url]
