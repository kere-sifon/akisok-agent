from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from src.ops.pricing import estimate_cost, estimate_image_cost


class RunCostTracker:
    def __init__(self, run_id: str | None = None) -> None:
        self.run_id = run_id or str(uuid4())
        self.started_at = datetime.now(timezone.utc)
        self.persisted = False
        self._by_model: dict[str, dict[str, int]] = defaultdict(
            lambda: {"input_tokens": 0, "output_tokens": 0, "calls": 0}
        )
        self._images: dict[str, int] = defaultdict(int)
        self._cost_by_stage: dict[str, float] = defaultdict(float)

    def record(
        self,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        *,
        stage: str | None = None,
    ) -> None:
        del stage
        bucket = self._by_model[model_id]
        bucket["input_tokens"] += int(input_tokens or 0)
        bucket["output_tokens"] += int(output_tokens or 0)
        bucket["calls"] += 1

    def record_image(self, stage: str, model_id: str, count: int = 1) -> None:
        added = int(count or 0)
        self._images[model_id] += added
        cost = estimate_image_cost({model_id: {"count": added}})
        self._cost_by_stage[stage] += cost

    @property
    def cost_by_stage(self) -> dict[str, float]:
        return dict(self._cost_by_stage)

    def image_usage(self) -> dict[str, int]:
        return dict(self._images)

    def token_usage(self) -> dict[str, dict[str, int]]:
        return {
            model_id: {
                "input_tokens": values["input_tokens"],
                "output_tokens": values["output_tokens"],
                "calls": values["calls"],
            }
            for model_id, values in self._by_model.items()
        }


def record_last_usage(tracker: RunCostTracker | None, stage: str, client: Any) -> None:
    if tracker is None:
        return
    usage = getattr(client, "last_usage", None) or {}
    tracker.record(
        getattr(client, "model_id", "unknown"),
        int(usage.get("input_tokens") or 0),
        int(usage.get("output_tokens") or 0),
        stage=stage,
    )


def write_pipeline_run(
    mongo,
    tracker: RunCostTracker,
    state: dict[str, Any] | None = None,
    *,
    finished_at: datetime | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    state = state or {}
    usage = tracker.token_usage()
    guarded = state.get("guarded_items") or []
    document = {
        "run_id": tracker.run_id,
        "started_at": tracker.started_at,
        "finished_at": finished_at or datetime.now(timezone.utc),
        "items_discovered": len(state.get("discovered_items") or []),
        "items_classified": len(state.get("classified_items") or []),
        "items_drafted": len(state.get("drafted_items") or []),
        "items_queued": len(state.get("queued_ids") or []),
        "items_flagged": sum(1 for item in guarded if item.get("status") == "flagged"),
        "token_usage": usage,
        "estimated_cost_usd": estimate_cost(usage),
    }
    if error:
        document["error"] = error
    mongo.insert_pipeline_run(document)
    tracker.persisted = True
    return document


def persist_run_if_needed(
    mongo,
    tracker: RunCostTracker | None,
    state: dict[str, Any] | None = None,
    *,
    error: str | None = None,
) -> dict[str, Any] | None:
    if tracker is None or tracker.persisted:
        return None
    return write_pipeline_run(mongo, tracker, state, error=error)


def record_approve_image_cost(
    mongo,
    *,
    model_id: str,
    public_id: str,
    item_id: str | None = None,
    count: int = 1,
) -> dict[str, Any]:
    tracker = RunCostTracker()
    tracker.record_image("image_generation", model_id, count)
    document = {
        "created_at": datetime.now(timezone.utc),
        "stage": "image_generation",
        "model_id": model_id,
        "public_id": public_id,
        "item_id": item_id,
        "images": int(count or 0),
        "estimated_cost_usd": tracker.cost_by_stage.get("image_generation", 0.0),
    }
    mongo.insert_image_generation_cost(document)
    return document
