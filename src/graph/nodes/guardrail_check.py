from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from src.bedrock.client import BedrockClient
from src.bedrock.embeddings import EmbeddingClient
from src.config import Settings
from src.db.mongo_client import ReviewQueueStore
from src.graph.state import DraftedItem, GuardedItem, PipelineState
from src.guardrails.duplicate import check_duplicate
from src.guardrails.reproduction import check_reproduction
from src.guardrails.sensitive_topic import check_sensitive_topic
from src.guardrails.source_link import check_source_link
from src.ops.cost_tracking import RunCostTracker, record_last_usage

SourceFetchFn = Callable[[str], dict[str, Any]]


def guardrail_check(
    state: PipelineState,
    *,
    settings: Settings,
    mongo: ReviewQueueStore,
    bedrock: BedrockClient,
    embeddings: EmbeddingClient,
    fetch_source: SourceFetchFn | None = None,
    tracker: RunCostTracker | None = None,
    now: datetime | None = None,
) -> dict[str, list[GuardedItem]]:
    moment = now or datetime.now(timezone.utc)
    fetcher = fetch_source or check_source_link
    guarded: list[GuardedItem] = []
    for item in state.get("drafted_items", []):
        guarded.append(
            _check_item(
                item,
                settings=settings,
                mongo=mongo,
                bedrock=bedrock,
                embeddings=embeddings,
                fetch_source=fetcher,
                tracker=tracker,
                now=moment,
            )
        )
    return {"guarded_items": guarded}


def _check_item(
    item: DraftedItem,
    *,
    settings: Settings,
    mongo: ReviewQueueStore,
    bedrock: BedrockClient,
    embeddings: EmbeddingClient,
    fetch_source: SourceFetchFn,
    tracker: RunCostTracker | None = None,
    now: datetime,
) -> GuardedItem:
    source = fetch_source(item["source_url"])
    source_ok = bool(source.get("ok")) and _is_2xx(source.get("status_code"))
    flag_broken = source.get("flag_broken")
    if flag_broken is None:
        flag_broken = not source_ok
    source_result = {
        "ok": source_ok,
        "status_code": source.get("status_code"),
        "likely_bot_blocked": bool(source.get("likely_bot_blocked")),
    }

    reproduction = check_reproduction(
        item["draft_text"],
        source.get("content") if source_ok else None,
        overlap_threshold=settings.reproduction_overlap_threshold,
    )
    duplicate = check_duplicate(
        item["draft_text"],
        mongo,
        embed_text=embeddings.embed_text,
        similarity_threshold=settings.dedup_similarity_threshold,
        lookback_days=settings.dedup_lookback_days,
        now=now,
    )
    record_last_usage(tracker, "guardrail_check", embeddings)
    sensitive = check_sensitive_topic(
        item["draft_text"],
        item["title"],
        bedrock=bedrock,
    )
    record_last_usage(tracker, "guardrail_check", bedrock)

    flags: list[str] = []
    if flag_broken:
        flags.append("broken_source_link")
    if reproduction.get("flagged"):
        flags.append("high_reproduction_overlap")
    if duplicate.get("flagged"):
        flags.append("likely_duplicate")
    if sensitive.get("sensitive"):
        flags.append("sensitive_topic")

    details = {
        "source_link": source_result,
        "reproduction": {
            "overlap_ratio": reproduction["overlap_ratio"],
            "flagged": reproduction["flagged"],
            "skipped": reproduction.get("skipped", False),
        },
        "duplicate": {
            "max_similarity": duplicate["max_similarity"],
            "flagged": duplicate["flagged"],
        },
        "sensitive_topic": {
            "sensitive": sensitive["sensitive"],
            "reason": sensitive.get("reason"),
        },
    }

    embedding = duplicate.get("embedding")
    if isinstance(embedding, list) and embedding:
        mongo.insert_embedding(
            source_url=item["source_url"],
            embedding=embedding,
            pillar=item["pillar"],
            created_at=now,
        )

    return {
        **item,
        "status": "flagged" if flags else "pending",
        "guardrail_flags": flags,
        "guardrail_details": details,
    }


def _is_2xx(status_code: object) -> bool:
    return isinstance(status_code, int) and 200 <= status_code < 300
