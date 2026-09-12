from __future__ import annotations

from src.bedrock.client import BedrockClient
from src.db.mongo_client import ReviewQueueStore
from src.graph.nodes.guardrail_check import guardrail_check
from src.graph.state import DraftedItem
from tests.conftest import (
    FakeDedupCollection,
    FakeEmbeddings,
    FakeMongoClient,
    FakeReviewCollection,
    ScriptedBedrockRuntime,
    fake_fetch,
)

OVERLAP_PHRASE = (
    "the state owned carrier announced additional flights from uyo this morning "
    "and passengers gathered early"
)


def _drafted(sample_item, draft_text: str = "From here the new routes feel like a bet on Uyo.") -> DraftedItem:
    return {
        **sample_item,
        "pillar": "news",
        "lga": "Uyo",
        "relevance_score": 0.9,
        "draft_text": draft_text,
        "source_url": sample_item["url"],
    }


def _run(
    settings,
    sample_item,
    *,
    fetch,
    matches=None,
    sensitive=False,
    reason=None,
    draft_text: str | None = None,
):
    dedup = FakeDedupCollection(matches=matches)
    mongo = ReviewQueueStore(
        uri=settings.mongodb_uri,
        db_name=settings.mongodb_db_name,
        client=FakeMongoClient(FakeReviewCollection(), dedup=dedup),
    )
    runtime = ScriptedBedrockRuntime(
        payloads_by_tool={
            "assess_sensitive_topic": [{"sensitive": sensitive, "reason": reason}]
        }
    )
    embeddings = FakeEmbeddings()
    result = guardrail_check(
        {"drafted_items": [_drafted(sample_item, draft_text or "From here the new routes feel like a bet on Uyo.")]},
        settings=settings,
        mongo=mongo,
        bedrock=BedrockClient(
            region=settings.aws_region,
            model_id=settings.bedrock_model_id,
            runtime_client=runtime,
        ),
        embeddings=embeddings,
        fetch_source=fetch,
    )
    return result["guarded_items"][0], dedup, embeddings


def test_clean_item_stays_pending(settings, sample_item) -> None:
    item, dedup, embeddings = _run(settings, sample_item, fetch=fake_fetch())

    assert item["status"] == "pending"
    assert item["guardrail_flags"] == []
    assert embeddings.calls
    assert len(dedup.docs) == 1


def test_403_source_link_flags_and_tags_bot_block(settings, sample_item) -> None:
    item, _, _ = _run(
        settings,
        sample_item,
        fetch=fake_fetch(
            ok=False,
            status_code=403,
            content=None,
            flag_broken=True,
            likely_bot_blocked=True,
        ),
    )

    assert "broken_source_link" in item["guardrail_flags"]
    assert item["guardrail_details"]["source_link"]["status_code"] == 403
    assert item["guardrail_details"]["source_link"]["likely_bot_blocked"] is True


def test_broken_source_link_flags_item(settings, sample_item) -> None:
    item, dedup, _ = _run(
        settings,
        sample_item,
        fetch=fake_fetch(ok=False, status_code=404, content=None),
    )

    assert item["status"] == "flagged"
    assert "broken_source_link" in item["guardrail_flags"]
    assert item["guardrail_details"]["source_link"]["status_code"] == 404
    assert item["guardrail_details"]["reproduction"]["skipped"] is True
    assert len(dedup.docs) == 1


def test_high_reproduction_overlap_flags_item(settings, sample_item) -> None:
    item, dedup, _ = _run(
        settings,
        sample_item,
        fetch=fake_fetch(content=OVERLAP_PHRASE),
        draft_text=OVERLAP_PHRASE,
    )

    assert "high_reproduction_overlap" in item["guardrail_flags"]
    assert item["status"] == "flagged"
    assert item["guardrail_details"]["reproduction"]["overlap_ratio"] > 0.15
    assert len(dedup.docs) == 1


def test_high_embedding_similarity_flags_duplicate(settings, sample_item) -> None:
    item, dedup, _ = _run(
        settings,
        sample_item,
        fetch=fake_fetch(),
        matches=[{"similarity": 0.97, "source_url": "https://example.com/old"}],
    )

    assert "likely_duplicate" in item["guardrail_flags"]
    assert item["status"] == "flagged"
    assert item["guardrail_details"]["duplicate"]["max_similarity"] == 0.97
    assert len(dedup.docs) == 1
    assert dedup.aggregate_calls


def test_sensitive_topic_flag_includes_reason(settings, sample_item) -> None:
    item, dedup, _ = _run(
        settings,
        sample_item,
        fetch=fake_fetch(),
        sensitive=True,
        reason="Unverified security incident in Uyo.",
    )

    assert item["guardrail_flags"] == ["sensitive_topic"]
    assert item["status"] == "flagged"
    assert item["guardrail_details"]["sensitive_topic"]["reason"] == "Unverified security incident in Uyo."
    assert len(dedup.docs) == 1


def test_multiple_flags_all_appear(settings, sample_item) -> None:
    item, dedup, embeddings = _run(
        settings,
        sample_item,
        fetch=fake_fetch(ok=False, status_code=500, content=None),
        matches=[{"similarity": 0.99, "source_url": "https://example.com/old"}],
        sensitive=True,
        reason="Active political dispute.",
    )

    assert item["status"] == "flagged"
    assert set(item["guardrail_flags"]) == {
        "broken_source_link",
        "likely_duplicate",
        "sensitive_topic",
    }
    assert embeddings.calls
    assert len(dedup.docs) == 1


def test_embedding_inserted_regardless_of_flags(settings, sample_item) -> None:
    _, dedup, embeddings = _run(
        settings,
        sample_item,
        fetch=fake_fetch(ok=False, status_code=None, content=None),
        sensitive=True,
        reason="Needs scrutiny.",
    )

    assert embeddings.calls
    assert dedup.docs[0]["source_url"] == sample_item["url"]
    assert dedup.docs[0]["embedding"] == [0.1, 0.2, 0.3]
    assert dedup.docs[0]["pillar"] == "news"
