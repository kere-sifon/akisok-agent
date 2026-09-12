from __future__ import annotations

from src.bedrock.client import BedrockClient
from src.graph.nodes.draft import draft
from src.graph.state import ClassifiedItem
from tests.conftest import ScriptedBedrockRuntime


def _classified(sample_item, score: float = 0.8) -> ClassifiedItem:
    return {
        **sample_item,
        "pillar": "news",
        "lga": "Uyo",
        "relevance_score": score,
    }


def test_draft_skips_items_below_threshold(sample_item) -> None:
    runtime = ScriptedBedrockRuntime({"draft_curated_post": []})
    bedrock = BedrockClient(region="us-east-1", model_id="test.model-id", runtime_client=runtime)

    result = draft(
        {"classified_items": [_classified(sample_item, score=0.2)]},
        bedrock=bedrock,
        relevance_threshold=0.6,
    )

    assert result["drafted_items"] == []
    assert runtime.calls == []


def test_draft_returns_paraphrased_post_and_source_url(sample_item) -> None:
    runtime = ScriptedBedrockRuntime(
        {
            "draft_curated_post": [
                {
                    "draft_text": "From here, the new Ibom Air routes read as a bet on Uyo staying connected.",
                    "source_url": sample_item["url"],
                }
            ]
        }
    )
    bedrock = BedrockClient(region="us-east-1", model_id="test.model-id", runtime_client=runtime)

    result = draft(
        {"classified_items": [_classified(sample_item)]},
        bedrock=bedrock,
        relevance_threshold=0.6,
    )

    drafted = result["drafted_items"][0]
    assert drafted["source_url"] == sample_item["url"]
    assert "Ibom Air" in drafted["draft_text"]
    assert runtime.calls[0]["toolConfig"]["toolChoice"]["tool"]["name"] == "draft_curated_post"


def test_draft_skips_item_without_valid_source_url() -> None:
    item: ClassifiedItem = {
        "title": "Untitled briefing",
        "url": "not-a-url",
        "snippet": "Notes from a briefing.",
        "discovered_at": "2026-09-11T10:00:00+00:00",
        "pillar": "news",
        "lga": None,
        "relevance_score": 0.9,
    }
    runtime = ScriptedBedrockRuntime(
        {
            "draft_curated_post": [
                {"draft_text": "A draft without a usable citation.", "source_url": ""}
            ]
        }
    )
    bedrock = BedrockClient(region="us-east-1", model_id="test.model-id", runtime_client=runtime)

    result = draft(
        {"classified_items": [item]},
        bedrock=bedrock,
        relevance_threshold=0.6,
    )

    assert result["drafted_items"] == []
