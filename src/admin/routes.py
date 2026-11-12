from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from calendar import monthrange

from src.admin.publish import publish_item
from src.config import load_settings
from src.db.mongo_client import ReviewQueueStore
from src.ops.cost_report import summarize_month
from src.ops.eval_guardrails import evaluate_guardrails

PublishFn = Callable[[dict[str, Any]], dict[str, Any]]


def get_store() -> ReviewQueueStore:
    settings = load_settings()
    return ReviewQueueStore(uri=settings.mongodb_uri, db_name=settings.mongodb_db_name)


def get_publish() -> PublishFn:
    return publish_item


def build_router(templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    @router.get("/")
    def status(request: Request, store: ReviewQueueStore = Depends(get_store)):
        last_runs = store.list_pipeline_runs(limit=1)
        return templates.TemplateResponse(
            request,
            "status.html",
            {
                "counts": {
                    "pending": store.count_review_items(["pending"]),
                    "flagged": store.count_review_items(["flagged"]),
                    "approved": store.count_review_items(["approved"]),
                    "rejected": store.count_review_items(["rejected"]),
                },
                "last_run": last_runs[0] if last_runs else None,
            },
        )

    @router.get("/eval-scores")
    def eval_scores(request: Request, store: ReviewQueueStore = Depends(get_store)):
        evals = store.list_quality_evals(limit=1)
        return templates.TemplateResponse(
            request,
            "eval_scores.html",
            {
                "quality": evals[0] if evals else None,
                "guardrails": evaluate_guardrails(store.list_review_items()),
            },
        )

    @router.get("/cost")
    def cost(request: Request, store: ReviewQueueStore = Depends(get_store)):
        now = datetime.now(timezone.utc)
        start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
        end = datetime(now.year, now.month, monthrange(now.year, now.month)[1], 23, 59, 59, tzinfo=timezone.utc)
        runs = store.list_pipeline_runs_between(start, end)
        image_costs = store.list_image_generation_costs_between(start, end)
        totals = summarize_month(
            store.list_all_pipeline_runs(),
            store.list_all_image_generation_costs(),
        )
        return templates.TemplateResponse(
            request,
            "cost.html",
            {
                "month": now.strftime("%Y-%m"),
                "stats": summarize_month(runs, image_costs),
                "totals": totals,
                "runs": runs,
            },
        )

    @router.get("/queue")
    def queue_list(request: Request, store: ReviewQueueStore = Depends(get_store)):
        items = [_public_item(item) for item in store.list_review_items()]
        return templates.TemplateResponse(
            request,
            "queue.html",
            {"items": items, "notice": request.query_params.get("notice")},
        )

    @router.get("/items/{item_id}")
    def item_detail(
        request: Request,
        item_id: str,
        store: ReviewQueueStore = Depends(get_store),
    ):
        item = store.get_review_item(item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Item not found")
        return templates.TemplateResponse(
            request,
            "item_detail.html",
            {
                "item": _public_item(item),
                "notice": request.query_params.get("notice"),
            },
        )

    @router.post("/items/{item_id}/approve")
    def approve_item(
        item_id: str,
        store: ReviewQueueStore = Depends(get_store),
        publish: PublishFn = Depends(get_publish),
    ):
        item = store.get_review_item(item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Item not found")
        updated = store.update_review_item(
            item_id,
            {"status": "approved", "approved_at": datetime.now(timezone.utc)},
        )
        publish(updated or item)
        return RedirectResponse(f"/items/{item_id}?notice=approved", status_code=303)

    @router.post("/items/{item_id}/reject")
    def reject_item(
        item_id: str,
        reason: str = Form(""),
        store: ReviewQueueStore = Depends(get_store),
    ):
        item = store.get_review_item(item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Item not found")
        store.update_review_item(
            item_id,
            {
                "status": "rejected",
                "rejected_at": datetime.now(timezone.utc),
                "rejection_reason": reason,
            },
        )
        return RedirectResponse(f"/items/{item_id}?notice=rejected", status_code=303)

    @router.post("/items/{item_id}/edit")
    def edit_item(
        item_id: str,
        draft_text: str = Form(...),
        store: ReviewQueueStore = Depends(get_store),
    ):
        item = store.get_review_item(item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Item not found")
        store.update_review_item(
            item_id,
            {"draft_text": draft_text, "edited_at": datetime.now(timezone.utc)},
        )
        return RedirectResponse(f"/items/{item_id}?notice=edited", status_code=303)

    return router


def _public_item(item: dict[str, Any]) -> dict[str, Any]:
    public = dict(item)
    public["id"] = str(item.get("_id"))
    public["created_at_label"] = _format_dt(item.get("created_at"))
    return public


def _format_dt(value: object) -> str:
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return moment.strftime("%Y-%m-%d %H:%M UTC")
    return str(value or "")
