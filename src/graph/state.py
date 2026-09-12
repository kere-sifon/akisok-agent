from __future__ import annotations

from typing import Any, TypedDict


class SourceItem(TypedDict):
    title: str
    url: str
    snippet: str
    discovered_at: str


class ClassifiedItem(SourceItem):
    pillar: str
    lga: str | None
    relevance_score: float


class DraftedItem(ClassifiedItem):
    draft_text: str
    source_url: str


class GuardedItem(DraftedItem):
    status: str
    guardrail_flags: list[str]
    guardrail_details: dict[str, Any]


class PipelineState(TypedDict, total=False):
    run_id: str
    discovered_items: list[SourceItem]
    classified_items: list[ClassifiedItem]
    drafted_items: list[DraftedItem]
    guarded_items: list[GuardedItem]
    queued_ids: list[str]
