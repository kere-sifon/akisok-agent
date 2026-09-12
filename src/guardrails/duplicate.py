from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from src.db.mongo_client import ReviewQueueStore

EmbedFn = Callable[[str], list[float]]


def check_duplicate(
    draft_text: str,
    mongo_client: ReviewQueueStore,
    *,
    embed_text: EmbedFn,
    similarity_threshold: float,
    lookback_days: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    embedding = embed_text(draft_text)
    moment = now or datetime.now(timezone.utc)
    since = moment - timedelta(days=lookback_days)
    max_similarity = mongo_client.nearest_embedding_similarity(embedding, since=since)
    return {
        "max_similarity": max_similarity,
        "flagged": max_similarity > similarity_threshold,
        "embedding": embedding,
    }
