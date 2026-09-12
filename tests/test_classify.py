from __future__ import annotations

from src.bedrock.client import BedrockClient
from src.graph.nodes.classify import classify
from src.graph.state import PipelineState
from tests.conftest import ScriptedBedrockRuntime


def test_classify_uses_bedrock_tool_payload(sample_item) -> None:
    runtime = ScriptedBedrockRuntime(
        {
            "classify_item": [
                {
                    "pillar": "news",
                    "lga": "Uyo",
                    "relevance_score": 0.91,
                }
            ]
        }
    )
    bedrock = BedrockClient(region="us-east-1", model_id="test.model-id", runtime_client=runtime)
    state: PipelineState = {"discovered_items": [sample_item]}

    result = classify(state, bedrock=bedrock)

    classified = result["classified_items"][0]
    assert classified["pillar"] == "news"
    assert classified["lga"] == "Uyo"
    assert classified["relevance_score"] == 0.91
    assert classified["url"] == sample_item["url"]
    assert runtime.calls[0]["modelId"] == "test.model-id"
    assert runtime.calls[0]["toolConfig"]["toolChoice"]["tool"]["name"] == "classify_item"


def test_classify_treats_blank_lga_as_null(sample_item) -> None:
    runtime = ScriptedBedrockRuntime(
        {
            "classify_item": [
                {"pillar": "culture", "lga": "", "relevance_score": 0.4}
            ]
        }
    )
    bedrock = BedrockClient(region="us-east-1", model_id="test.model-id", runtime_client=runtime)

    result = classify({"discovered_items": [sample_item]}, bedrock=bedrock)

    assert result["classified_items"][0]["lga"] is None
    assert result["classified_items"][0]["pillar"] == "culture"
