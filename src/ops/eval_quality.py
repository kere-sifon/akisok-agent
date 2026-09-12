from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from typing import Any

from src.bedrock.client import BedrockClient
from src.config import load_settings
from src.db.mongo_client import ReviewQueueStore

QUALITY_TOOL = "score_draft"
QUALITY_SCHEMA = {
    "type": "object",
    "properties": {
        "relevance": {"type": "integer", "minimum": 0, "maximum": 5},
        "originality": {"type": "integer", "minimum": 0, "maximum": 5},
        "source_quality": {"type": "integer", "minimum": 0, "maximum": 5},
        "classification_accuracy": {"type": "integer", "minimum": 0, "maximum": 5},
    },
    "required": ["relevance", "originality", "source_quality", "classification_accuracy"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You score Akisok curated drafts for a diaspora audience. Use the score_draft tool. "
    "Score each dimension 0-5. Be strict: 5 is rare."
)
PASS_THRESHOLD = 3.5
DIMENSIONS = ("relevance", "originality", "source_quality", "classification_accuracy")


def _created_at(item: dict[str, Any]) -> datetime | None:
    value = item.get("created_at")
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return None


def sample_recent_items(
    items: list[dict[str, Any]],
    *,
    sample_size: int,
    days: int,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    moment = now or datetime.now(timezone.utc)
    cutoff = moment - timedelta(days=days)
    recent = []
    for item in items:
        created = _created_at(item)
        if created is None or created < cutoff:
            continue
        if not item.get("draft_text"):
            continue
        recent.append(item)
    recent.sort(key=lambda item: _created_at(item) or cutoff, reverse=True)
    return recent[:sample_size]


def score_item(item: dict[str, Any], *, bedrock: BedrockClient) -> dict[str, int]:
    overlap = (item.get("guardrail_details") or {}).get("reproduction") or {}
    payload = bedrock.invoke_tool(
        system=_SYSTEM,
        user=(
            f"Title: {item.get('title')}\n"
            f"Pillar: {item.get('pillar')}\n"
            f"LGA: {item.get('lga')}\n"
            f"Source: {item.get('source_url')}\n"
            f"Reproduction overlap: {overlap.get('overlap_ratio', 'n/a')}\n\n"
            f"Draft:\n{item.get('draft_text')}"
        ),
        tool_name=QUALITY_TOOL,
        tool_description="Score one curated draft on four quality dimensions.",
        input_schema=QUALITY_SCHEMA,
    )
    return {name: int(payload.get(name) or 0) for name in DIMENSIONS}


def summarize_scores(per_item: list[dict[str, Any]]) -> dict[str, Any]:
    if not per_item:
        averages = {name: 0.0 for name in DIMENSIONS}
        return {"averages": averages, "pass_rate": 0.0, "sample_size": 0}
    averages = {
        name: sum(float(item["scores"][name]) for item in per_item) / len(per_item)
        for name in DIMENSIONS
    }
    passed = 0
    for item in per_item:
        mean = sum(item["scores"].values()) / len(DIMENSIONS)
        if mean >= PASS_THRESHOLD:
            passed += 1
    return {
        "averages": averages,
        "pass_rate": passed / len(per_item),
        "sample_size": len(per_item),
    }


def run_quality_eval(
    mongo,
    bedrock: BedrockClient,
    *,
    sample_size: int = 20,
    days: int = 30,
    now: datetime | None = None,
) -> dict[str, Any]:
    sampled = sample_recent_items(
        mongo.list_review_items(),
        sample_size=sample_size,
        days=days,
        now=now,
    )
    per_item = []
    for item in sampled:
        scores = score_item(item, bedrock=bedrock)
        per_item.append(
            {
                "source_url": item.get("source_url"),
                "title": item.get("title"),
                "scores": scores,
            }
        )
    summary = summarize_scores(per_item)
    document = {
        "created_at": now or datetime.now(timezone.utc),
        "sample_size": summary["sample_size"],
        "days": days,
        "per_item": per_item,
        "averages": summary["averages"],
        "pass_rate": summary["pass_rate"],
    }
    mongo.insert_quality_eval(document)
    return document


def format_quality_summary(document: dict[str, Any]) -> str:
    averages = document.get("averages") or {}
    return (
        f"Samples evaluated:      {document.get('sample_size', 0)}\n"
        f"Avg relevance:          {averages.get('relevance', 0):.1f} / 5\n"
        f"Avg originality:        {averages.get('originality', 0):.1f} / 5\n"
        f"Avg source quality:     {averages.get('source_quality', 0):.1f} / 5\n"
        f"Avg classification acc: {averages.get('classification_accuracy', 0):.1f} / 5\n"
        f"Overall pass rate (>=3.5 avg): {float(document.get('pass_rate') or 0) * 100:.0f}%\n"
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="LLM-judge quality eval over recent review_queue items.")
    parser.add_argument("--sample-size", type=int, default=20)
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args(argv)
    settings = load_settings()
    store = ReviewQueueStore(uri=settings.mongodb_uri, db_name=settings.mongodb_db_name)
    bedrock = BedrockClient(region=settings.aws_region, model_id=settings.bedrock_model_id)
    document = run_quality_eval(store, bedrock, sample_size=args.sample_size, days=args.days)
    print(format_quality_summary(document), end="")


if __name__ == "__main__":
    main()
