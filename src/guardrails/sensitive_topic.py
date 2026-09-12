from __future__ import annotations

from typing import Any

from src.bedrock.client import BedrockClient

SENSITIVE_TOOL = "assess_sensitive_topic"
SENSITIVE_SCHEMA = {
    "type": "object",
    "properties": {
        "sensitive": {
            "type": "boolean",
            "description": "True if the item needs extra human scrutiny.",
        },
        "reason": {
            "type": ["string", "null"],
            "description": "Short explanation when sensitive is true, otherwise null.",
        },
    },
    "required": ["sensitive", "reason"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You assess Akisok drafts for extra-scrutiny topics. Use the assess_sensitive_topic tool. "
    "Mark sensitive=true only when the item touches active political disputes, security incidents, "
    "or unverified claims that a human editor should review before approval. "
    "Ordinary civic news, culture, history, and places coverage is not sensitive by default."
)


def check_sensitive_topic(
    draft_text: str,
    title: str,
    *,
    bedrock: BedrockClient,
) -> dict[str, Any]:
    payload = bedrock.invoke_tool(
        system=_SYSTEM,
        user=f"Title: {title}\n\nDraft:\n{draft_text}",
        tool_name=SENSITIVE_TOOL,
        tool_description="Say whether this draft needs extra scrutiny and why.",
        input_schema=SENSITIVE_SCHEMA,
    )
    sensitive = bool(payload.get("sensitive"))
    reason_raw = payload.get("reason")
    reason = str(reason_raw).strip() if reason_raw else None
    return {"sensitive": sensitive, "reason": reason if sensitive else reason}
