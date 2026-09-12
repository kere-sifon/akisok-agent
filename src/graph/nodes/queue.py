from __future__ import annotations

from src.db.mongo_client import ReviewQueueStore
from src.graph.state import PipelineState
from src.ops.lga_coverage import record_queued_lgas


def queue(
    state: PipelineState,
    *,
    mongo: ReviewQueueStore,
    lga_names: list[str] | None = None,
) -> dict[str, list[str]]:
    documents = []
    for item in state.get("guarded_items", []):
        documents.append(
            {
                "source_url": item["source_url"],
                "title": item["title"],
                "pillar": item["pillar"],
                "lga": item.get("lga"),
                "relevance_score": item["relevance_score"],
                "draft_text": item["draft_text"],
                "status": item.get("status") or "pending",
                "guardrail_flags": list(item.get("guardrail_flags") or []),
                "guardrail_details": dict(item.get("guardrail_details") or {}),
            }
        )
    queued_ids = mongo.insert_review_items(documents)
    record_queued_lgas(mongo, documents, lga_names=lga_names)
    return {"queued_ids": queued_ids}
