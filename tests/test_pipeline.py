from __future__ import annotations

from src.bedrock.client import BedrockClient
from src.db.mongo_client import ReviewQueueStore
from src.graph.pipeline import PipelineDeps, run_pipeline
from tests.conftest import (
    FakeEmbeddings,
    FakeMongoClient,
    FakeReviewCollection,
    ScriptedBedrockRuntime,
    fake_fetch,
    recording_web_search,
    tool_use_content,
)


def test_pipeline_skips_already_queued_urls_and_inserts_pending_drafts(settings, sample_item) -> None:
    new_item = {
        "title": "Bridge work begins in Ikot Ekpene",
        "url": "https://example.gov.ng/news/ikot-ekpene-bridge",
        "snippet": "A new bridge project was flagged off in Ikot Ekpene.",
    }
    collection = FakeReviewCollection([{"source_url": sample_item["url"]}])
    runtime = ScriptedBedrockRuntime(
        payloads_by_tool={
            "classify_item": [
                {"pillar": "places", "lga": "Ikot Ekpene", "relevance_score": 0.88}
            ],
            "draft_curated_post": [
                {
                    "draft_text": "The Ikot Ekpene bridge story is really about how people get home.",
                    "source_url": new_item["url"],
                }
            ],
            "assess_sensitive_topic": [{"sensitive": False, "reason": None}],
        },
        converse_script=[
            tool_use_content(
                "web_search",
                {"query": "Akwa Ibom news this week"},
                "search-1",
            ),
            tool_use_content(
                "submit_candidates",
                {
                    "items": [
                        {
                            "title": sample_item["title"],
                            "url": sample_item["url"],
                            "snippet": sample_item["snippet"],
                        },
                        new_item,
                    ]
                },
                "submit-1",
            ),
        ],
    )
    search = recording_web_search(
        [
            {
                "title": new_item["title"],
                "url": new_item["url"],
                "snippet": new_item["snippet"],
            }
        ]
    )
    deps = PipelineDeps(
        settings=settings,
        web_search=search,
        seed_queries=settings.seed_queries,
        bedrock=BedrockClient(
            region=settings.aws_region,
            model_id=settings.bedrock_model_id,
            runtime_client=runtime,
        ),
        embeddings=FakeEmbeddings(),
        fetch_source=fake_fetch(),
        mongo=ReviewQueueStore(
            uri=settings.mongodb_uri,
            db_name=settings.mongodb_db_name,
            client=FakeMongoClient(collection),
        ),
    )

    result = run_pipeline(deps)

    assert search.calls == ["Akwa Ibom news this week"]
    assert [item["url"] for item in result["discovered_items"]] == [new_item["url"]]
    assert result["classified_items"][0]["pillar"] == "places"
    assert len(result["queued_ids"]) == 1
    queued = collection.docs[-1]
    assert queued["status"] == "pending"
    assert queued["source_url"] == new_item["url"]
    assert queued["guardrail_flags"] == []
    assert queued["guardrail_details"]["sensitive_topic"]["sensitive"] is False
    assert queued["draft_text"]
    assert queued["lga"] == "Ikot Ekpene"


def test_pipeline_does_not_queue_low_relevance_items(settings, sample_item) -> None:
    collection = FakeReviewCollection()
    runtime = ScriptedBedrockRuntime(
        payloads_by_tool={
            "classify_item": [
                {"pillar": "opinion", "lga": None, "relevance_score": 0.1}
            ],
            "draft_curated_post": [],
        },
        converse_script=[
            tool_use_content(
                "submit_candidates",
                {
                    "items": [
                        {
                            "title": sample_item["title"],
                            "url": sample_item["url"],
                            "snippet": sample_item["snippet"],
                        }
                    ]
                },
                "submit-1",
            )
        ],
    )
    deps = PipelineDeps(
        settings=settings,
        web_search=recording_web_search(),
        seed_queries=settings.seed_queries,
        bedrock=BedrockClient(
            region=settings.aws_region,
            model_id=settings.bedrock_model_id,
            runtime_client=runtime,
        ),
        embeddings=FakeEmbeddings(),
        fetch_source=fake_fetch(),
        mongo=ReviewQueueStore(
            uri=settings.mongodb_uri,
            db_name=settings.mongodb_db_name,
            client=FakeMongoClient(collection),
        ),
    )

    result = run_pipeline(deps)

    assert result["drafted_items"] == []
    assert result["queued_ids"] == []
    assert collection.docs == []
