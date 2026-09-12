from __future__ import annotations

from src.bedrock.client import BedrockClient
from src.config import PILLARS
from src.graph.state import ClassifiedItem, PipelineState, SourceItem
from src.ops.cost_tracking import RunCostTracker, record_last_usage

CLASSIFY_TOOL = "classify_item"
CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "pillar": {
            "type": "string",
            "enum": list(PILLARS),
            "description": "Primary Akisok content pillar for this item.",
        },
        "lga": {
            "type": ["string", "null"],
            "description": "Akwa Ibom LGA name if clearly referenced, otherwise null.",
        },
        "relevance_score": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "How relevant this is to an Akwa Ibom-focused audience.",
        },
    },
    "required": ["pillar", "lga", "relevance_score"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You classify news items for Akisok, a curated Akwa Ibom (Nigeria) site. "
    "Use the classify_item tool. Pick exactly one pillar. Set lga only when the "
    "item clearly names a Local Government Area; otherwise null. Score relevance "
    "from 0 to 1 for an Akwa Ibom-focused audience, including the diaspora."
)


def classify(
    state: PipelineState,
    *,
    bedrock: BedrockClient,
    tracker: RunCostTracker | None = None,
) -> dict[str, list[ClassifiedItem]]:
    classified: list[ClassifiedItem] = []
    for item in state.get("discovered_items", []):
        classified.append(_classify_item(item, bedrock=bedrock, tracker=tracker))
    return {"classified_items": classified}


def _classify_item(
    item: SourceItem,
    *,
    bedrock: BedrockClient,
    tracker: RunCostTracker | None = None,
) -> ClassifiedItem:
    payload = bedrock.invoke_tool(
        system=_SYSTEM,
        user=_user_prompt(item),
        tool_name=CLASSIFY_TOOL,
        tool_description="Return pillar, optional LGA, and relevance score for one news item.",
        input_schema=CLASSIFY_SCHEMA,
    )
    record_last_usage(tracker, "classify", bedrock)
    pillar = str(payload.get("pillar", "")).strip().lower()
    if pillar not in PILLARS:
        raise ValueError(f"Invalid pillar from Bedrock: {payload.get('pillar')!r}")
    score = float(payload["relevance_score"])
    if not 0.0 <= score <= 1.0:
        raise ValueError(f"relevance_score out of range: {score}")
    lga_raw = payload.get("lga")
    lga = str(lga_raw).strip() if lga_raw else None
    return {
        **item,
        "pillar": pillar,
        "lga": lga or None,
        "relevance_score": score,
    }


def _user_prompt(item: SourceItem) -> str:
    return (
        f"Title: {item['title']}\n"
        f"URL: {item['url']}\n"
        f"Discovered: {item.get('discovered_at') or 'unknown'}\n"
        f"Snippet: {item.get('snippet') or '(none)'}"
    )
