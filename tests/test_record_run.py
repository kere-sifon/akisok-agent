from __future__ import annotations

import pytest

from src.bedrock.client import BedrockClient
from src.db.mongo_client import ReviewQueueStore
from src.graph.pipeline import PipelineDeps, run_pipeline
from src.ops.cost_tracking import RunCostTracker
from tests.conftest import (
    FakeEmbeddings,
    FakeMongoClient,
    FakeReviewCollection,
    ScriptedBedrockRuntime,
    fake_fetch,
    recording_web_search,
    tool_use_content,
)


def _deps(settings, sample_item, *, runtime, tracker=None, classify_boom=False):
    collection = FakeReviewCollection()
    mongo = ReviewQueueStore(
        uri=settings.mongodb_uri,
        db_name=settings.mongodb_db_name,
        client=FakeMongoClient(collection),
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
        mongo=mongo,
        cost_tracker=tracker or RunCostTracker(),
    )
    if classify_boom:
        original = deps.bedrock.invoke_tool

        def boom(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("classify exploded")

        deps.bedrock.invoke_tool = boom  # type: ignore[method-assign]
    return deps, mongo


def test_successful_run_writes_pipeline_runs_document(settings, sample_item) -> None:
    runtime = ScriptedBedrockRuntime(
        payloads_by_tool={
            "classify_item": [{"pillar": "news", "lga": "Uyo", "relevance_score": 0.9}],
            "draft_curated_post": [
                {"draft_text": "A diaspora take on Uyo routes.", "source_url": sample_item["url"]}
            ],
            "assess_sensitive_topic": [{"sensitive": False, "reason": None}],
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
    tracker = RunCostTracker()
    tracker.record(settings.bedrock_model_id, 120, 40)
    deps, mongo = _deps(settings, sample_item, runtime=runtime, tracker=tracker)

    result = run_pipeline(deps)

    runs = mongo.list_pipeline_runs(limit=5)
    assert len(runs) == 1
    document = runs[0]
    assert document["run_id"] == tracker.run_id
    assert document["items_discovered"] == 1
    assert document["items_classified"] == 1
    assert document["items_drafted"] == 1
    assert document["items_queued"] == 1
    assert "estimated_cost_usd" in document
    assert settings.bedrock_model_id in document["token_usage"]
    assert result["queued_ids"]


def test_partial_run_still_writes_pipeline_run(settings, sample_item) -> None:
    runtime = ScriptedBedrockRuntime(
        payloads_by_tool={
            "classify_item": [{"pillar": "news", "lga": "Uyo", "relevance_score": 0.9}],
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
    tracker = RunCostTracker()
    deps, mongo = _deps(settings, sample_item, runtime=runtime, tracker=tracker, classify_boom=True)

    with pytest.raises(RuntimeError, match="classify exploded"):
        run_pipeline(deps)

    runs = mongo.list_pipeline_runs(limit=5)
    assert len(runs) == 1
    assert runs[0]["run_id"] == tracker.run_id
    assert runs[0]["error"] == "classify exploded"
    assert runs[0]["items_discovered"] == 1
    assert runs[0]["items_classified"] == 0
    assert "estimated_cost_usd" in runs[0]
