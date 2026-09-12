from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.bedrock.client import BedrockClient
from src.db.mongo_client import ReviewQueueStore
from src.ops.eval_quality import (
    format_quality_summary,
    run_quality_eval,
    sample_recent_items,
    summarize_scores,
)
from tests.conftest import FakeMongoClient, FakeReviewCollection, ScriptedBedrockRuntime


def _item(title: str, *, days_ago: int, now: datetime) -> dict:
    return {
        "title": title,
        "source_url": f"https://example.com/{title}",
        "draft_text": f"Draft for {title}",
        "pillar": "news",
        "lga": "Uyo",
        "created_at": now - timedelta(days=days_ago),
        "guardrail_details": {"reproduction": {"overlap_ratio": 0.01}},
    }


def test_sampling_respects_size_and_days() -> None:
    now = datetime(2026, 9, 11, tzinfo=timezone.utc)
    items = [
        _item("recent-a", days_ago=1, now=now),
        _item("recent-b", days_ago=2, now=now),
        _item("recent-c", days_ago=3, now=now),
        _item("old", days_ago=40, now=now),
    ]
    sampled = sample_recent_items(items, sample_size=2, days=30, now=now)
    assert [item["title"] for item in sampled] == ["recent-a", "recent-b"]


def test_averages_and_pass_rate() -> None:
    summary = summarize_scores(
        [
            {"scores": {"relevance": 5, "originality": 5, "source_quality": 5, "classification_accuracy": 5}},
            {"scores": {"relevance": 2, "originality": 2, "source_quality": 2, "classification_accuracy": 2}},
        ]
    )
    assert summary["sample_size"] == 2
    assert summary["averages"]["relevance"] == 3.5
    assert summary["pass_rate"] == 0.5


def test_run_quality_eval_uses_mocked_judge(settings) -> None:
    now = datetime(2026, 9, 11, tzinfo=timezone.utc)
    docs = [_item("one", days_ago=1, now=now), _item("two", days_ago=2, now=now)]
    mongo = ReviewQueueStore(
        uri=settings.mongodb_uri,
        db_name=settings.mongodb_db_name,
        client=FakeMongoClient(FakeReviewCollection(docs)),
    )
    runtime = ScriptedBedrockRuntime(
        payloads_by_tool={
            "score_draft": [
                {"relevance": 4, "originality": 4, "source_quality": 5, "classification_accuracy": 4},
                {"relevance": 3, "originality": 3, "source_quality": 3, "classification_accuracy": 3},
            ]
        }
    )
    bedrock = BedrockClient(
        region=settings.aws_region,
        model_id=settings.bedrock_model_id,
        runtime_client=runtime,
    )

    document = run_quality_eval(mongo, bedrock, sample_size=2, days=30, now=now)

    assert document["sample_size"] == 2
    assert document["averages"]["relevance"] == 3.5
    assert 0.0 <= document["pass_rate"] <= 1.0
    assert "Samples evaluated" in format_quality_summary(document)
    assert mongo.list_quality_evals(limit=1)
