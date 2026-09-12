from __future__ import annotations

import logging
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from collections.abc import Callable
from urllib.parse import urlparse

import yaml

from src.images.cloudinary_upload import upload_image
from src.images.generate_image import DEFAULT_IMAGE_MODEL_ID, build_image_prompt, generate_image
from src.ops.cost_tracking import record_approve_image_cost

logger = logging.getLogger(__name__)

GenerateFn = Callable[[str], bytes]
UploadFn = Callable[..., str]

POSTS_DIR = Path("content/posts")
NOT_CONFIGURED = "content repo not configured"


def get_default_image_key(pillar: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (pillar or "news").lower()).strip("-") or "news"
    return f"pillar-{slug}"


def slugify(title: str) -> str:
    text = (title or "").lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "post"


def unique_slug(posts_dir: Path, title: str) -> str:
    base = slugify(title)
    candidate = base
    suffix = 2
    while (posts_dir / f"{candidate}.mdx").exists():
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def publish_item(
    item: dict[str, Any],
    *,
    store: Any | None = None,
    generate_fn: GenerateFn | None = None,
    upload_fn: UploadFn | None = None,
) -> dict[str, Any]:
    """
    Writes item as an MDX file into the akisok-site repo (CONTENT_REPO_PATH),
    commits, and pushes. Never raises — always returns a result dict so an
    approval in Mongo succeeds even if publish fails; failures are logged
    and surfaced in the return value for the admin UI to display.
    """
    try:
        repo = _resolve_repo()
        if repo is None:
            return {"published": False, "reason": NOT_CONFIGURED}

        posts_dir = repo / POSTS_DIR
        posts_dir.mkdir(parents=True, exist_ok=True)
        slug = unique_slug(posts_dir, str(item.get("title") or "post"))
        image_key = _resolve_image_key(
            item,
            slug=slug,
            store=store,
            generate_fn=generate_fn,
            upload_fn=upload_fn,
        )
        relative_path = POSTS_DIR / f"{slug}.mdx"
        absolute_path = repo / relative_path
        absolute_path.write_text(_render_mdx(item, image_key=image_key), encoding="utf-8")

        added, add_error = _run_git(repo, "add", str(relative_path))
        if not added:
            return {"published": False, "reason": f"git add failed: {add_error}"}

        title = str(item.get("title") or slug)
        committed, commit_error = _run_git(repo, "commit", "-m", f"Add post: {title}")
        if not committed:
            return {"published": False, "reason": f"git commit failed: {commit_error}"}

        if _has_remote(repo):
            pulled, pull_error = _run_git(repo, "pull", "--rebase")
            if not pulled:
                return {"published": False, "reason": f"git pull --rebase failed: {pull_error}"}
            pushed, push_error = _run_git(repo, "push")
            if not pushed:
                return {"published": False, "reason": f"git push failed: {push_error}"}

        return {
            "published": True,
            "slug": slug,
            "path": str(relative_path).replace("\\", "/"),
        }
    except Exception as exc:
        logger.exception("publish_item failed; approval will still be stored.")
        return {"published": False, "reason": str(exc)}


def _resolve_repo() -> Path | None:
    raw = (os.getenv("CONTENT_REPO_PATH") or "").strip()
    if not raw:
        logger.warning("publish_item skipped: CONTENT_REPO_PATH is unset.")
        return None
    path = Path(raw).expanduser()
    if not path.exists() or not _is_git_repo(path):
        logger.warning(
            "publish_item skipped: CONTENT_REPO_PATH is missing or is not a git repo."
        )
        return None
    return path


def _is_git_repo(path: Path) -> bool:
    ok, output = _run_git(path, "rev-parse", "--is-inside-work-tree")
    return ok and output.strip() == "true"


def _has_remote(repo: Path) -> bool:
    ok, output = _run_git(repo, "remote")
    return ok and bool(output.strip())


def _run_git(repo: Path, *args: str) -> tuple[bool, str]:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or f"exit {result.returncode}").strip()
        logger.warning("git %s failed: %s", " ".join(args), detail)
        return False, detail
    return True, (result.stdout or "").strip()


def _resolve_image_key(
    item: dict[str, Any],
    *,
    slug: str,
    store: Any | None,
    generate_fn: GenerateFn | None,
    upload_fn: UploadFn | None,
) -> str:
    existing = str(item.get("image_key") or "").strip()
    if existing:
        return existing
    pillar = str(item.get("pillar") or "news")
    try:
        prompt = build_image_prompt(
            str(item.get("title") or ""),
            pillar,
            item.get("lga"),
        )
        raw = (generate_fn or generate_image)(prompt)
        (upload_fn or upload_image)(raw, public_id=slug)
        _persist_generated_image(item, slug, store)
        return slug
    except Exception:
        logger.warning(
            "Image generate/upload failed; falling back to %s",
            get_default_image_key(pillar),
            exc_info=True,
        )
        return get_default_image_key(pillar)


def _persist_generated_image(item: dict[str, Any], slug: str, store: Any | None) -> None:
    item["image_key"] = slug
    resolved = store if store is not None else _optional_store()
    if resolved is None:
        return
    item_id = str(item.get("_id") or item.get("id") or "")
    if item_id:
        resolved.update_review_item(item_id, {"image_key": slug})
    try:
        record_approve_image_cost(
            resolved,
            model_id=(os.getenv("IMAGE_MODEL_ID") or DEFAULT_IMAGE_MODEL_ID).strip(),
            public_id=slug,
            item_id=item_id or None,
        )
    except Exception:
        logger.warning("Could not record image_generation cost for %s", slug, exc_info=True)


def _optional_store() -> Any | None:
    try:
        from src.config import load_settings
        from src.db.mongo_client import ReviewQueueStore

        settings = load_settings()
        return ReviewQueueStore(uri=settings.mongodb_uri, db_name=settings.mongodb_db_name)
    except Exception:
        logger.warning("No Mongo store available to persist image_key")
        return None


def _render_mdx(item: dict[str, Any], *, image_key: str) -> str:
    front_matter = {
        "title": str(item.get("title") or ""),
        "pillar": item.get("pillar") or "news",
        "lga": item.get("lga"),
        "date": _post_date(item),
        "image": image_key,
        "source_name": _source_name(item),
        "source_url": str(item.get("source_url") or ""),
    }
    header = yaml.safe_dump(
        front_matter,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    ).strip()
    body = str(item.get("draft_text") or "").strip()
    return f"---\n{header}\n---\n\n{body}\n"


def _post_date(item: dict[str, Any]) -> str:
    for key in ("approved_at", "created_at"):
        value = item.get(key)
        if isinstance(value, datetime):
            moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            return moment.date().isoformat()
        if isinstance(value, str) and len(value) >= 10:
            return value[:10]
    return datetime.now(timezone.utc).date().isoformat()


def _source_name(item: dict[str, Any]) -> str:
    if item.get("source_name"):
        return str(item["source_name"])
    host = urlparse(str(item.get("source_url") or "")).netloc
    return host.removeprefix("www.") if host else "source"
