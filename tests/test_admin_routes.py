from __future__ import annotations

from datetime import datetime, timezone

from bson import ObjectId
from fastapi.testclient import TestClient

from src.admin.main import create_app
from src.admin.publish import publish_item
from src.admin.routes import get_publish, get_store
from src.db.mongo_client import ReviewQueueStore
from tests.conftest import FakeMongoClient, FakeReviewCollection


def _store(docs: list[dict]) -> ReviewQueueStore:
    return ReviewQueueStore(
        uri="mongodb://localhost:27017",
        db_name="akisok_test",
        client=FakeMongoClient(FakeReviewCollection(docs)),
    )


def _client(store: ReviewQueueStore, publish=None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_store] = lambda: store
    if publish is not None:
        app.dependency_overrides[get_publish] = lambda: publish
    return TestClient(app)


def _item(*, title: str, status: str, created_at: datetime, draft_text: str = "Draft body") -> dict:
    return {
        "_id": ObjectId(),
        "title": title,
        "source_url": f"https://example.com/{title.replace(' ', '-').lower()}",
        "pillar": "news",
        "lga": "Uyo",
        "relevance_score": 0.8,
        "draft_text": draft_text,
        "status": status,
        "created_at": created_at,
        "guardrail_flags": ["sensitive_topic"] if status == "flagged" else [],
        "guardrail_details": {
            "sensitive_topic": {
                "sensitive": status == "flagged",
                "reason": "Needs scrutiny" if status == "flagged" else None,
            }
        },
    }


def test_queue_lists_flagged_items_before_pending() -> None:
    pending_old = _item(
        title="Older pending",
        status="pending",
        created_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    flagged = _item(
        title="Flagged first",
        status="flagged",
        created_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
    )
    pending_new = _item(
        title="Newer pending",
        status="pending",
        created_at=datetime(2026, 9, 3, tzinfo=timezone.utc),
    )
    client = _client(_store([pending_old, pending_new, flagged]))

    response = client.get("/queue")

    assert response.status_code == 200
    body = response.text
    assert body.index("Flagged first") < body.index("Newer pending") < body.index("Older pending")
    assert "sensitive_topic" in body


def test_shared_nav_and_tab_routes() -> None:
    client = _client(_store([]))
    status = client.get("/")
    queue = client.get("/queue")
    evals = client.get("/eval-scores")
    cost = client.get("/cost")
    assert status.status_code == 200
    assert queue.status_code == 200
    assert evals.status_code == 200
    assert cost.status_code == 200
    assert 'href="/queue"' in status.text
    assert "Review queue" in status.text
    assert "Status" in status.text
    assert "No items in" in queue.text


def test_item_detail_renders_draft_and_guardrail_details() -> None:
    item = _item(
        title="Bridge work",
        status="flagged",
        created_at=datetime(2026, 9, 11, tzinfo=timezone.utc),
        draft_text="The Ikot Ekpene bridge story is about getting home.",
    )
    client = _client(_store([item]))

    response = client.get(f"/items/{item['_id']}")

    assert response.status_code == 200
    assert "The Ikot Ekpene bridge story is about getting home." in response.text
    assert "Needs scrutiny" in response.text
    assert "sensitive_topic" in response.text


def test_approve_sets_status_and_calls_publish() -> None:
    item = _item(
        title="Approve me",
        status="pending",
        created_at=datetime(2026, 9, 11, tzinfo=timezone.utc),
    )
    store = _store([item])
    called: list[dict] = []

    def fake_publish(document: dict) -> dict:
        called.append(document)
        return {"published": False, "reason": "content repo not configured"}

    client = _client(store, publish=fake_publish)
    response = client.post(f"/items/{item['_id']}/approve", follow_redirects=False)

    assert response.status_code == 303
    updated = store.get_review_item(str(item["_id"]))
    assert updated is not None
    assert updated["status"] == "approved"
    assert updated["approved_at"]
    assert called
    assert called[0]["status"] == "approved"


def test_reject_stores_reason() -> None:
    item = _item(
        title="Reject me",
        status="flagged",
        created_at=datetime(2026, 9, 11, tzinfo=timezone.utc),
    )
    store = _store([item])
    client = _client(store)

    response = client.post(
        f"/items/{item['_id']}/reject",
        data={"reason": "Too thin on sources"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    updated = store.get_review_item(str(item["_id"]))
    assert updated is not None
    assert updated["status"] == "rejected"
    assert updated["rejection_reason"] == "Too thin on sources"
    assert updated["rejected_at"]


def test_edit_updates_draft_and_leaves_status() -> None:
    item = _item(
        title="Edit me",
        status="flagged",
        created_at=datetime(2026, 9, 11, tzinfo=timezone.utc),
        draft_text="Original draft",
    )
    store = _store([item])
    client = _client(store)

    response = client.post(
        f"/items/{item['_id']}/edit",
        data={"draft_text": "Edited diaspora framing."},
        follow_redirects=False,
    )

    assert response.status_code == 303
    updated = store.get_review_item(str(item["_id"]))
    assert updated is not None
    assert updated["draft_text"] == "Edited diaspora framing."
    assert updated["status"] == "flagged"
    assert updated["edited_at"]


def test_publish_item_unset_path_still_graceful(monkeypatch) -> None:
    monkeypatch.delenv("CONTENT_REPO_PATH", raising=False)
    result = publish_item({"title": "Anything"})
    assert result == {"published": False, "reason": "content repo not configured"}
