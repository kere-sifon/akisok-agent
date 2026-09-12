from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langgraph.graph import END, START, StateGraph

from src.bedrock.client import BedrockClient
from src.bedrock.embeddings import EmbeddingClient
from src.config import Settings, load_settings
from src.db.mongo_client import ReviewQueueStore
from src.graph.nodes.classify import classify
from src.graph.nodes.discover import discover
from src.graph.nodes.draft import draft
from src.graph.nodes.guardrail_check import guardrail_check
from src.graph.nodes.queue import queue
from src.graph.nodes.record_run import record_run
from src.graph.state import PipelineState
from src.ops.cost_tracking import RunCostTracker, persist_run_if_needed
from src.tools.web_search import SearchFn, create_web_search

SourceFetchFn = Callable[[str], dict[str, Any]]


@dataclass
class PipelineDeps:
    settings: Settings
    web_search: SearchFn
    bedrock: BedrockClient
    embeddings: EmbeddingClient
    mongo: ReviewQueueStore
    seed_queries: list[str] | None = None
    fetch_source: SourceFetchFn | None = None
    cost_tracker: RunCostTracker | None = None


def build_deps(
    settings: Settings | None = None,
    *,
    web_search: SearchFn | None = None,
    bedrock: BedrockClient | None = None,
    embeddings: EmbeddingClient | None = None,
    mongo: ReviewQueueStore | None = None,
    seed_queries: list[str] | None = None,
    fetch_source: SourceFetchFn | None = None,
    cost_tracker: RunCostTracker | None = None,
) -> PipelineDeps:
    resolved = settings or load_settings()
    return PipelineDeps(
        settings=resolved,
        web_search=web_search or create_web_search(api_key=resolved.search_api_key),
        bedrock=bedrock
        or BedrockClient(
            region=resolved.aws_region,
            model_id=resolved.bedrock_model_id,
        ),
        embeddings=embeddings
        or EmbeddingClient(
            region=resolved.aws_region,
            model_id=resolved.embedding_model_id,
        ),
        mongo=mongo
        or ReviewQueueStore(
            uri=resolved.mongodb_uri,
            db_name=resolved.mongodb_db_name,
        ),
        seed_queries=list(seed_queries) if seed_queries is not None else None,
        fetch_source=fetch_source,
        cost_tracker=cost_tracker or RunCostTracker(),
    )


def build_pipeline(deps: PipelineDeps | None = None):
    """Compile the graph: discover → classify → draft → guardrail_check → queue."""
    resolved = deps or build_deps()

    def discover_node(state: PipelineState) -> dict:
        return discover(
            state,
            bedrock=resolved.bedrock,
            mongo=resolved.mongo,
            web_search=resolved.web_search,
            seed_queries=resolved.seed_queries,
            settings=resolved.settings,
            max_search_calls=resolved.settings.max_search_calls_per_run,
            tracker=resolved.cost_tracker,
        )

    def classify_node(state: PipelineState) -> dict:
        return classify(state, bedrock=resolved.bedrock, tracker=resolved.cost_tracker)

    def draft_node(state: PipelineState) -> dict:
        return draft(
            state,
            bedrock=resolved.bedrock,
            relevance_threshold=resolved.settings.relevance_threshold,
            tracker=resolved.cost_tracker,
        )

    def guardrail_node(state: PipelineState) -> dict:
        return guardrail_check(
            state,
            settings=resolved.settings,
            mongo=resolved.mongo,
            bedrock=resolved.bedrock,
            embeddings=resolved.embeddings,
            fetch_source=resolved.fetch_source,
            tracker=resolved.cost_tracker,
        )

    def queue_node(state: PipelineState) -> dict:
        return queue(
            state,
            mongo=resolved.mongo,
            lga_names=resolved.settings.lga_names,
        )

    def record_run_node(state: PipelineState) -> dict:
        return record_run(state, mongo=resolved.mongo, tracker=resolved.cost_tracker)

    graph = StateGraph(PipelineState)
    graph.add_node("discover", discover_node)
    graph.add_node("classify", classify_node)
    graph.add_node("draft", draft_node)
    graph.add_node("guardrail_check", guardrail_node)
    graph.add_node("queue", queue_node)
    graph.add_node("record_run", record_run_node)
    graph.add_edge(START, "discover")
    graph.add_edge("discover", "classify")
    graph.add_edge("classify", "draft")
    graph.add_edge("draft", "guardrail_check")
    graph.add_edge("guardrail_check", "queue")
    graph.add_edge("queue", "record_run")
    graph.add_edge("record_run", END)
    return graph.compile()


def run_pipeline(deps: PipelineDeps | None = None) -> PipelineState:
    resolved = deps or build_deps()
    tracker = resolved.cost_tracker or RunCostTracker()
    resolved.cost_tracker = tracker
    app = build_pipeline(resolved)
    result: PipelineState = {"run_id": tracker.run_id}
    error: str | None = None
    try:
        for event in app.stream(dict(result)):
            for update in event.values():
                if isinstance(update, dict):
                    result.update(update)
        return result
    except Exception as exc:
        error = str(exc)
        raise
    finally:
        persist_run_if_needed(resolved.mongo, tracker, result, error=error)


def main() -> None:
    result = run_pipeline()
    queued = result.get("queued_ids") or []
    flagged = sum(1 for item in (result.get("guarded_items") or []) if item.get("status") == "flagged")
    print(
        "Pipeline complete: "
        f"{len(result.get('discovered_items') or [])} new items, "
        f"{len(result.get('classified_items') or [])} classified, "
        f"{len(result.get('drafted_items') or [])} drafted, "
        f"{len(queued)} queued ({flagged} flagged)."
    )


if __name__ == "__main__":
    main()
