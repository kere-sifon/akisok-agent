from __future__ import annotations

from src.db.mongo_client import ReviewQueueStore
from src.graph.state import PipelineState
from src.ops.cost_tracking import RunCostTracker, write_pipeline_run


def record_run(
    state: PipelineState,
    *,
    mongo: ReviewQueueStore,
    tracker: RunCostTracker | None,
) -> dict:
    if tracker is None:
        return {}
    write_pipeline_run(mongo, tracker, dict(state))
    return {}
