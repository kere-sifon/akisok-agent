from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Protocol

from bson import ObjectId
from pymongo import MongoClient
from pymongo.collection import Collection

DEDUP_COLLECTION = "dedup_embeddings"
DEDUP_VECTOR_INDEX = "dedup_embeddings_index"
PIPELINE_STATE_COLLECTION = "pipeline_state"
PIPELINE_RUNS_COLLECTION = "pipeline_runs"
QUALITY_EVALS_COLLECTION = "quality_evals"
GUARDRAIL_EVALS_COLLECTION = "guardrail_evals"
LGA_COVERAGE_COLLECTION = "lga_coverage"
IMAGE_GENERATION_COSTS_COLLECTION = "image_generation_costs"
LGA_ROTATION_STATE_ID = "lga_rotation"


class MongoLike(Protocol):
    def __getitem__(self, name: str) -> Any: ...


class ReviewQueueStore:
    collection_name = "review_queue"

    def __init__(
        self,
        *,
        uri: str,
        db_name: str,
        client: MongoLike | None = None,
    ) -> None:
        self._client: MongoLike = client or MongoClient(uri)
        self._db = self._client[db_name]
        self.collection: Collection[Mapping[str, Any]] = self._db[self.collection_name]
        self.dedup: Collection[Mapping[str, Any]] = self._db[DEDUP_COLLECTION]
        self.pipeline_state: Collection[Mapping[str, Any]] = self._db[PIPELINE_STATE_COLLECTION]
        self.pipeline_runs: Collection[Mapping[str, Any]] = self._db[PIPELINE_RUNS_COLLECTION]
        self.quality_evals: Collection[Mapping[str, Any]] = self._db[QUALITY_EVALS_COLLECTION]
        self.guardrail_evals: Collection[Mapping[str, Any]] = self._db[GUARDRAIL_EVALS_COLLECTION]
        self.lga_coverage: Collection[Mapping[str, Any]] = self._db[LGA_COVERAGE_COLLECTION]
        self.image_generation_costs: Collection[Mapping[str, Any]] = self._db[
            IMAGE_GENERATION_COSTS_COLLECTION
        ]
        self.ensure_indexes()

    def ensure_indexes(self) -> None:
        self.collection.create_index("source_url", unique=True)

    def existing_urls(self, urls: list[str]) -> set[str]:
        if not urls:
            return set()
        cursor = self.collection.find({"source_url": {"$in": urls}}, {"source_url": 1})
        return {doc["source_url"] for doc in cursor if doc.get("source_url")}

    def insert_review_items(self, documents: list[dict[str, Any]]) -> list[str]:
        if not documents:
            return []
        stamped = []
        now = datetime.now(timezone.utc)
        for document in documents:
            stamped.append(
                {
                    **document,
                    "status": document.get("status", "pending"),
                    "created_at": document.get("created_at", now),
                    "guardrail_flags": document.get("guardrail_flags", []),
                    "guardrail_details": document.get("guardrail_details", {}),
                }
            )
        result = self.collection.insert_many(stamped)
        return [str(inserted_id) for inserted_id in result.inserted_ids]

    def nearest_embedding_similarity(
        self,
        embedding: list[float],
        *,
        since: datetime,
        limit: int = 1,
    ) -> float:
        pipeline = [
            {
                "$vectorSearch": {
                    "index": DEDUP_VECTOR_INDEX,
                    "path": "embedding",
                    "queryVector": embedding,
                    "numCandidates": max(50, limit * 20),
                    "limit": limit,
                    "filter": {"created_at": {"$gte": since}},
                }
            },
            {"$addFields": {"similarity": {"$meta": "vectorSearchScore"}}},
            {"$project": {"similarity": 1, "source_url": 1}},
        ]
        matches = list(self.dedup.aggregate(pipeline))
        if not matches:
            return 0.0
        return float(matches[0].get("similarity") or 0.0)

    def insert_embedding(
        self,
        *,
        source_url: str,
        embedding: list[float],
        pillar: str,
        created_at: datetime | None = None,
    ) -> str:
        document = {
            "source_url": source_url,
            "embedding": embedding,
            "pillar": pillar,
            "created_at": created_at or datetime.now(timezone.utc),
        }
        result = self.dedup.insert_one(document)
        return str(result.inserted_id)

    def get_lga_rotation_index(self) -> int:
        document = self.pipeline_state.find_one({"_id": LGA_ROTATION_STATE_ID})
        if not document:
            return 0
        try:
            return int(document.get("last_index") or 0)
        except (TypeError, ValueError):
            return 0

    def set_lga_rotation_index(self, last_index: int) -> None:
        self.pipeline_state.update_one(
            {"_id": LGA_ROTATION_STATE_ID},
            {"$set": {"last_index": last_index}},
            upsert=True,
        )

    def list_review_items(self) -> list[dict[str, Any]]:
        items = [dict(doc) for doc in self.collection.find({})]
        return sorted(items, key=_review_sort_key)

    def get_review_item(self, item_id: str) -> dict[str, Any] | None:
        oid = _as_object_id(item_id)
        if oid is None:
            return None
        document = self.collection.find_one({"_id": oid})
        return dict(document) if document else None

    def update_review_item(self, item_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        oid = _as_object_id(item_id)
        if oid is None:
            return None
        self.collection.update_one({"_id": oid}, {"$set": fields})
        return self.get_review_item(item_id)

    def count_review_items(self, statuses: list[str] | None = None) -> int:
        query: dict[str, Any] = {}
        if statuses:
            query["status"] = {"$in": statuses}
        return int(self.collection.count_documents(query))

    def insert_pipeline_run(self, document: dict[str, Any]) -> str:
        result = self.pipeline_runs.insert_one(document)
        return str(result.inserted_id)

    def list_pipeline_runs(self, limit: int = 10) -> list[dict[str, Any]]:
        return _newest(self.pipeline_runs.find({}), "finished_at", limit)

    def list_all_pipeline_runs(self) -> list[dict[str, Any]]:
        return [dict(document) for document in self.pipeline_runs.find({})]

    def list_pipeline_runs_between(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        rows = []
        for document in self.list_all_pipeline_runs():
            started = document.get("started_at")
            if not isinstance(started, datetime):
                continue
            moment = started if started.tzinfo else started.replace(tzinfo=timezone.utc)
            if start <= moment <= end:
                rows.append(document)
        return rows

    def insert_quality_eval(self, document: dict[str, Any]) -> str:
        result = self.quality_evals.insert_one(document)
        return str(result.inserted_id)

    def list_quality_evals(self, limit: int = 20) -> list[dict[str, Any]]:
        return _newest(self.quality_evals.find({}), "created_at", limit)

    def insert_guardrail_eval(self, document: dict[str, Any]) -> str:
        result = self.guardrail_evals.insert_one(document)
        return str(result.inserted_id)

    def list_guardrail_evals(self, limit: int = 20) -> list[dict[str, Any]]:
        return _newest(self.guardrail_evals.find({}), "created_at", limit)

    def seed_lga_coverage(self, lga: str) -> None:
        self.lga_coverage.update_one(
            {"lga": lga},
            {"$setOnInsert": {"lga": lga, "last_discovered_at": None, "items_found": 0}},
            upsert=True,
        )

    def increment_lga_coverage(self, lga: str, *, discovered_at: datetime) -> None:
        self.lga_coverage.update_one(
            {"lga": lga},
            {"$set": {"last_discovered_at": discovered_at}, "$inc": {"items_found": 1}},
            upsert=True,
        )

    def insert_image_generation_cost(self, document: dict[str, Any]) -> str:
        result = self.image_generation_costs.insert_one(document)
        return str(result.inserted_id)

    def list_all_image_generation_costs(self) -> list[dict[str, Any]]:
        return [dict(document) for document in self.image_generation_costs.find({})]

    def list_image_generation_costs_between(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        rows = []
        for document in self.list_all_image_generation_costs():
            created = document.get("created_at")
            if not isinstance(created, datetime):
                continue
            moment = created if created.tzinfo else created.replace(tzinfo=timezone.utc)
            if start <= moment <= end:
                rows.append(document)
        return rows

    def list_lga_coverage(self) -> list[dict[str, Any]]:
        rows = [dict(doc) for doc in self.lga_coverage.find({})]
        return sorted(rows, key=lambda row: str(row.get("lga") or ""))


def _as_object_id(item_id: str) -> ObjectId | None:
    try:
        return ObjectId(item_id)
    except Exception:
        return None


def _newest(cursor, field: str, limit: int) -> list[dict[str, Any]]:
    rows = [dict(doc) for doc in cursor]
    rows.sort(key=lambda doc: _timestamp(doc.get(field)), reverse=True)
    return rows[:limit]


def _timestamp(value: object) -> float:
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return moment.timestamp()
    return 0.0


def _review_sort_key(document: dict[str, Any]) -> tuple[int, float]:
    flagged_first = 0 if document.get("status") == "flagged" else 1
    created = document.get("created_at")
    if isinstance(created, datetime):
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        timestamp = created.timestamp()
    else:
        timestamp = 0.0
    return (flagged_first, -timestamp)
