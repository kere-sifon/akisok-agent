from __future__ import annotations

from types import SimpleNamespace

import pytest
from bson import ObjectId

from src.config import Settings
from src.graph.state import SourceItem


class FakeReviewCollection:
    def __init__(self, existing: list[dict] | None = None) -> None:
        self.docs = list(existing or [])

    def create_index(self, *args, **kwargs) -> None:
        return None

    def find(self, query=None, projection=None):
        query = query or {}
        docs = [dict(doc) for doc in self.docs]
        source_filter = query.get("source_url")
        if isinstance(source_filter, dict) and "$in" in source_filter:
            wanted = set(source_filter["$in"])
            docs = [doc for doc in docs if doc.get("source_url") in wanted]
        status_filter = query.get("status")
        if isinstance(status_filter, dict) and "$in" in status_filter:
            wanted_status = set(status_filter["$in"])
            docs = [doc for doc in docs if doc.get("status") in wanted_status]
        elif status_filter:
            docs = [doc for doc in docs if doc.get("status") == status_filter]
        if "lga" in query:
            docs = [doc for doc in docs if doc.get("lga") == query["lga"]]
        return docs

    def count_documents(self, query=None):
        return len(self.find(query))

    def insert_one(self, document):
        copied = dict(document)
        copied.setdefault("_id", ObjectId())
        self.docs.append(copied)
        return SimpleNamespace(inserted_id=copied["_id"])

    def find_one(self, query):
        target = query.get("_id")
        for doc in self.docs:
            if doc.get("_id") == target or str(doc.get("_id")) == str(target):
                return dict(doc)
        return None

    def update_one(self, query, update, upsert=False):
        match = None
        for doc in self.docs:
            if self._matches(doc, query):
                match = doc
                break
        created = False
        if match is None:
            if not upsert:
                return SimpleNamespace(modified_count=0)
            match = dict(query)
            match.setdefault("_id", ObjectId())
            self.docs.append(match)
            created = True
        if created:
            match.update(update.get("$setOnInsert") or {})
        match.update(update.get("$set") or {})
        for key, amount in (update.get("$inc") or {}).items():
            match[key] = int(match.get(key) or 0) + int(amount)
        return SimpleNamespace(modified_count=1)

    def _matches(self, doc: dict, query: dict) -> bool:
        if not query:
            return True
        if "_id" in query and doc.get("_id") != query["_id"] and str(doc.get("_id")) != str(query["_id"]):
            return False
        if "lga" in query and doc.get("lga") != query["lga"]:
            return False
        return True

    def insert_many(self, documents):
        inserted = []
        for document in documents:
            copied = dict(document)
            copied.setdefault("_id", ObjectId())
            self.docs.append(copied)
            inserted.append(copied["_id"])
        return SimpleNamespace(inserted_ids=inserted)


class FakeDedupCollection:
    def __init__(self, matches: list[dict] | None = None) -> None:
        self.docs: list[dict] = []
        self.aggregate_calls: list[list] = []
        self.matches = list(matches or [])

    def aggregate(self, pipeline):
        self.aggregate_calls.append(pipeline)
        return list(self.matches)

    def insert_one(self, document):
        copied = dict(document)
        copied.setdefault("_id", ObjectId())
        self.docs.append(copied)
        return SimpleNamespace(inserted_id=copied["_id"])


class FakeMongoDatabase:
    def __init__(
        self,
        review_queue: FakeReviewCollection | None = None,
        dedup: FakeDedupCollection | None = None,
    ) -> None:
        self._collections = {
            "review_queue": review_queue or FakeReviewCollection(),
            "dedup_embeddings": dedup or FakeDedupCollection(),
            "pipeline_state": FakeReviewCollection(),
        }

    def __getitem__(self, name: str):
        if name not in self._collections:
            self._collections[name] = FakeReviewCollection()
        return self._collections[name]


class FakeMongoClient:
    def __init__(
        self,
        collection: FakeReviewCollection | None = None,
        *,
        review_queue: FakeReviewCollection | None = None,
        dedup: FakeDedupCollection | None = None,
    ) -> None:
        self.review_queue = review_queue or collection or FakeReviewCollection()
        self.dedup = dedup or FakeDedupCollection()
        self.database = FakeMongoDatabase(self.review_queue, self.dedup)

    def __getitem__(self, name: str) -> FakeMongoDatabase:
        return self.database


class FakeEmbeddings:
    def __init__(self, vector: list[float] | None = None) -> None:
        self.vector = vector or [0.1, 0.2, 0.3]
        self.calls: list[str] = []

    def embed_text(self, text: str) -> list[float]:
        self.calls.append(text)
        return list(self.vector)


def tool_use_content(name: str, payload: dict, tool_use_id: str | None = None) -> list[dict]:
    return [
        {
            "toolUse": {
                "toolUseId": tool_use_id or name,
                "name": name,
                "input": payload,
            }
        }
    ]


class ScriptedBedrockRuntime:
    def __init__(
        self,
        payloads_by_tool: dict[str, list[dict]] | None = None,
        converse_script: list[list[dict]] | None = None,
    ) -> None:
        self.payloads_by_tool = {name: list(items) for name, items in (payloads_by_tool or {}).items()}
        self.converse_script = list(converse_script or [])
        self.calls: list[dict] = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        forced = (
            kwargs.get("toolConfig", {})
            .get("toolChoice", {})
            .get("tool", {})
            .get("name")
        )
        if forced and self.payloads_by_tool.get(forced):
            payload = self.payloads_by_tool[forced].pop(0)
            return {"output": {"message": {"content": tool_use_content(forced, payload)}}}
        if self.converse_script:
            return {"output": {"message": {"content": self.converse_script.pop(0)}}}
        raise AssertionError("No scripted Bedrock response remaining")


@pytest.fixture
def settings() -> Settings:
    return Settings(
        aws_region="us-east-1",
        bedrock_model_id="test.model-id",
        mongodb_uri="mongodb://localhost:27017",
        mongodb_db_name="akisok_test",
        search_api_key="test-search-key",
        embedding_model_id="test.embedding-id",
        max_search_calls_per_run=10,
        relevance_threshold=0.6,
        reproduction_overlap_threshold=0.15,
        dedup_similarity_threshold=0.92,
        dedup_lookback_days=14,
        seed_queries=["Akwa Ibom news this week"],
        evergreen_queries=[
            "Akwa Ibom news this week",
            "Uyo Nigeria culture",
            "Akwa Ibom state history",
        ],
        lga_names=["Uyo", "Ikot Ekpene", "Oron", "Eket"],
        seed_lga_rotation_size=3,
    )


@pytest.fixture
def sample_item() -> SourceItem:
    return {
        "title": "Ibom Air expands Uyo routes",
        "url": "https://example.gov.ng/news/ibom-air",
        "snippet": "The state-owned carrier announced additional flights from Uyo.",
        "discovered_at": "2026-09-11T10:00:00+00:00",
    }


def recording_web_search(results: list[dict] | None = None):
    seen: list[str] = []

    def web_search(query: str) -> list[dict]:
        seen.append(query)
        return list(results or [])

    web_search.calls = seen
    return web_search


def fake_fetch(
    ok: bool = True,
    status_code: int | None = 200,
    content: str | None = "Unrelated source page.",
    flag_broken: bool | None = None,
    likely_bot_blocked: bool = False,
):
    def fetch_source(_url: str) -> dict:
        broken = (not ok) if flag_broken is None else flag_broken
        return {
            "ok": ok,
            "status_code": status_code,
            "content": content if ok else None,
            "flag_broken": broken,
            "likely_bot_blocked": likely_bot_blocked,
        }

    return fetch_source
