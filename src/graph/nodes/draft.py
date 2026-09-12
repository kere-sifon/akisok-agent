from __future__ import annotations

from urllib.parse import urlparse

from src.bedrock.client import BedrockClient
from src.graph.state import ClassifiedItem, DraftedItem, PipelineState
from src.ops.cost_tracking import RunCostTracker, record_last_usage

DRAFT_TOOL = "draft_curated_post"
DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "draft_text": {
            "type": "string",
            "description": "150-400 word original framing of the item.",
        },
        "source_url": {
            "type": "string",
            "description": "Exact original item URL. Must match the provided source.",
        },
    },
    "required": ["draft_text", "source_url"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You write short curated posts for Akisok, aimed at an Akwa Ibom diaspora audience. "
    "Use the draft_curated_post tool. Write 150-400 words in a personal, essay-like voice. "
    "Paraphrase only: never reproduce source sentences verbatim. Always return the original "
    "source_url unchanged. This draft is for human review and will not be auto-published."
)


def draft(
    state: PipelineState,
    *,
    bedrock: BedrockClient,
    relevance_threshold: float,
    tracker: RunCostTracker | None = None,
) -> dict[str, list[DraftedItem]]:
    drafted: list[DraftedItem] = []
    for item in state.get("classified_items", []):
        if item["relevance_score"] < relevance_threshold:
            continue
        drafted_item = _draft_item(item, bedrock=bedrock, tracker=tracker)
        if drafted_item is not None:
            drafted.append(drafted_item)
    return {"drafted_items": drafted}


def _draft_item(
    item: ClassifiedItem,
    *,
    bedrock: BedrockClient,
    tracker: RunCostTracker | None = None,
) -> DraftedItem | None:
    payload = bedrock.invoke_tool(
        system=_SYSTEM,
        user=_user_prompt(item),
        tool_name=DRAFT_TOOL,
        tool_description="Return an original draft and the source URL for human review.",
        input_schema=DRAFT_SCHEMA,
    )
    record_last_usage(tracker, "draft", bedrock)
    source_url = _valid_source_url(payload.get("source_url"), fallback=item["url"])
    draft_text = str(payload.get("draft_text") or "").strip()
    if source_url is None or not draft_text:
        return None
    return {
        **item,
        "draft_text": draft_text,
        "source_url": source_url,
    }


def _valid_source_url(candidate: object, *, fallback: str) -> str | None:
    raw = str(candidate or fallback).strip()
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return raw


def _user_prompt(item: ClassifiedItem) -> str:
    return (
        f"Title: {item['title']}\n"
        f"Source URL (return unchanged): {item['url']}\n"
        f"Pillar: {item['pillar']}\n"
        f"LGA: {item.get('lga') or 'none'}\n"
        f"Relevance: {item['relevance_score']}\n"
        f"Source snippet (paraphrase; do not copy): {item.get('snippet') or '(none)'}"
    )
