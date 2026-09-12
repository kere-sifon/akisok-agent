from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import subprocess

import pytest
from bson import ObjectId

from src.admin.publish import get_default_image_key, publish_item


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _init_content_repo(root: Path) -> Path:
    posts = root / "content" / "posts"
    posts.mkdir(parents=True)
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Akisok Tests")
    return root


@pytest.fixture(autouse=True)
def _no_live_images(monkeypatch) -> None:
    def _boom(_prompt: str) -> bytes:
        raise RuntimeError("image generation disabled in default publish tests")

    monkeypatch.setattr("src.admin.publish.generate_image", _boom)
    monkeypatch.setattr("src.admin.publish.upload_image", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("no upload")))


class _Store:
    def __init__(self) -> None:
        self.updates: list[tuple[str, dict]] = []
        self.image_costs: list[dict] = []

    def update_review_item(self, item_id: str, fields: dict) -> dict:
        self.updates.append((item_id, fields))
        return fields

    def insert_image_generation_cost(self, document: dict) -> str:
        self.image_costs.append(document)
        return "cost-1"


def _item(**overrides) -> dict:
    payload = {
        "title": "Ibom Air Expands Uyo Routes!",
        "pillar": "news",
        "lga": "Uyo",
        "source_url": "https://example.gov.ng/news/ibom-air",
        "draft_text": "From here the new routes feel like a bet on Uyo.",
        "created_at": datetime(2026, 9, 11, tzinfo=timezone.utc),
    }
    payload.update(overrides)
    return payload


def test_publish_writes_mdx_with_front_matter(tmp_path, monkeypatch) -> None:
    repo = _init_content_repo(tmp_path)
    monkeypatch.setenv("CONTENT_REPO_PATH", str(repo))

    result = publish_item(_item())

    assert result["published"] is True
    assert result["slug"] == "ibom-air-expands-uyo-routes"
    assert result["path"] == "content/posts/ibom-air-expands-uyo-routes.mdx"
    written = (repo / result["path"]).read_text(encoding="utf-8")
    assert written.startswith("---\n")
    assert 'title: Ibom Air Expands Uyo Routes!' in written or 'title: "Ibom Air Expands Uyo Routes!"' in written
    assert "pillar: news" in written
    assert "lga: Uyo" in written
    assert "date: '2026-09-11'" in written or "date: 2026-09-11" in written
    assert "image: pillar-news" in written
    assert "source_name: example.gov.ng" in written
    assert "source_url: https://example.gov.ng/news/ibom-air" in written
    assert "From here the new routes feel like a bet on Uyo." in written
    log = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Add post: Ibom Air Expands Uyo Routes!" in log.stdout


def test_slug_collision_appends_suffix(tmp_path, monkeypatch) -> None:
    repo = _init_content_repo(tmp_path)
    existing = repo / "content" / "posts" / "ibom-air-expands-uyo-routes.mdx"
    existing.write_text("---\ntitle: existing\n---\n", encoding="utf-8")
    monkeypatch.setenv("CONTENT_REPO_PATH", str(repo))

    result = publish_item(_item())

    assert result["published"] is True
    assert result["slug"] == "ibom-air-expands-uyo-routes-2"
    assert (repo / "content" / "posts" / "ibom-air-expands-uyo-routes-2.mdx").exists()


def test_unset_or_invalid_path_does_not_raise(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("CONTENT_REPO_PATH", raising=False)
    assert publish_item(_item()) == {"published": False, "reason": "content repo not configured"}

    monkeypatch.setenv("CONTENT_REPO_PATH", str(tmp_path / "missing"))
    assert publish_item(_item())["published"] is False
    assert publish_item(_item())["reason"] == "content repo not configured"

    not_git = tmp_path / "not-git"
    not_git.mkdir()
    monkeypatch.setenv("CONTENT_REPO_PATH", str(not_git))
    result = publish_item(_item())
    assert result == {"published": False, "reason": "content repo not configured"}


def test_failing_git_step_returns_reason(tmp_path, monkeypatch) -> None:
    repo = _init_content_repo(tmp_path)
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    monkeypatch.setenv("CONTENT_REPO_PATH", str(repo))

    result = publish_item(_item())

    assert result["published"] is False
    assert "git commit failed" in result["reason"]


def test_default_image_key_follows_pillar() -> None:
    assert get_default_image_key("history") == "pillar-history"
    assert get_default_image_key("places") == "pillar-places"


def test_publish_uses_generated_image_and_persists_key(tmp_path, monkeypatch) -> None:
    repo = _init_content_repo(tmp_path)
    monkeypatch.setenv("CONTENT_REPO_PATH", str(repo))
    generated: list[str] = []
    uploaded: list[str] = []
    store = _Store()
    item_id = ObjectId()
    item = _item(_id=item_id)

    def fake_generate(prompt: str) -> bytes:
        generated.append(prompt)
        return b"png-bytes"

    def fake_upload(image_bytes: bytes, public_id: str) -> str:
        uploaded.append(public_id)
        assert image_bytes == b"png-bytes"
        return "https://res.cloudinary.com/demo/image/upload/akisok/ibom-air-expands-uyo-routes.jpg"

    result = publish_item(item, store=store, generate_fn=fake_generate, upload_fn=fake_upload)

    assert result["published"] is True
    written = (repo / result["path"]).read_text(encoding="utf-8")
    assert "image: ibom-air-expands-uyo-routes" in written
    assert store.updates == [(str(item_id), {"image_key": "ibom-air-expands-uyo-routes"})]
    assert item["image_key"] == "ibom-air-expands-uyo-routes"
    assert generated and uploaded == ["ibom-air-expands-uyo-routes"]
    assert store.image_costs and store.image_costs[0]["stage"] == "image_generation"


def test_publish_falls_back_when_image_pipeline_fails(tmp_path, monkeypatch) -> None:
    repo = _init_content_repo(tmp_path)
    monkeypatch.setenv("CONTENT_REPO_PATH", str(repo))
    store = _Store()

    def boom(_prompt: str) -> bytes:
        raise RuntimeError("bedrock down")

    result = publish_item(_item(_id=ObjectId()), store=store, generate_fn=boom, upload_fn=lambda *_a, **_k: "")

    assert result["published"] is True
    written = (repo / result["path"]).read_text(encoding="utf-8")
    assert "image: pillar-news" in written
    assert store.updates == []
    assert store.image_costs == []


def test_publish_skips_generation_when_image_key_already_set(tmp_path, monkeypatch) -> None:
    repo = _init_content_repo(tmp_path)
    monkeypatch.setenv("CONTENT_REPO_PATH", str(repo))
    calls = {"generate": 0, "upload": 0}

    def fake_generate(_prompt: str) -> bytes:
        calls["generate"] += 1
        return b"png"

    def fake_upload(*_a, **_k) -> str:
        calls["upload"] += 1
        return "https://example.com/x.jpg"

    result = publish_item(
        _item(image_key="already-assigned"),
        store=_Store(),
        generate_fn=fake_generate,
        upload_fn=fake_upload,
    )

    assert result["published"] is True
    written = (repo / result["path"]).read_text(encoding="utf-8")
    assert "image: already-assigned" in written
    assert calls == {"generate": 0, "upload": 0}
