from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from src.bedrock.client import BedrockClient, tool_use_blocks
from src.config import Settings, next_run_seed_queries
from src.db.mongo_client import ReviewQueueStore
from src.graph.state import PipelineState, SourceItem
from src.ops.cost_tracking import RunCostTracker, record_last_usage
from src.tools.web_search import SearchFn

WEB_SEARCH_TOOL = "web_search"
SUBMIT_TOOL = "submit_candidates"

WEB_SEARCH_SPEC = {
    "name": WEB_SEARCH_TOOL,
    "description": "Search the public web for Akwa Ibom-related pages. Use a seed query or a close variant.",
    "inputSchema": {
        "json": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query to run.",
                }
            },
            "required": ["query"],
            "additionalProperties": False,
        }
    },
}

SUBMIT_SPEC = {
    "name": SUBMIT_TOOL,
    "description": "Submit the genuinely new, relevant candidate items you found. Call this once you are done searching.",
    "inputSchema": {
        "json": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "url": {"type": "string"},
                            "snippet": {"type": "string"},
                        },
                        "required": ["title", "url", "snippet"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["items"],
            "additionalProperties": False,
        }
    },
}

_SYSTEM = (
    "You discover source items for Akisok, a curated Akwa Ibom (Nigeria) site. "
    "Use the web_search tool to run queries from the provided seed list (or close variants). "
    "Do not invent URLs. "
    "Only submit candidate URLs that point to a specific article, post, or page about a "
    "particular topic, event, or story — never a site's homepage, category index, tag "
    "archive, or generic landing page. If a search result's URL is just a domain root "
    "(e.g. https://example.com/ with no further path) or looks like a general index "
    "rather than one specific piece of content, skip it even if the domain itself seems "
    "relevant. Prefer URLs with a specific slug or article path over bare domains. "
    "Stay within the search-call budget. When finished, call submit_candidates with "
    "distinct items that look relevant to an Akwa Ibom-focused audience."
)


def discover(
    state: PipelineState,
    *,
    bedrock: BedrockClient,
    mongo: ReviewQueueStore,
    web_search: SearchFn,
    seed_queries: list[str] | None = None,
    settings: Settings | None = None,
    max_search_calls: int,
    tracker: RunCostTracker | None = None,
    now: datetime | None = None,
) -> dict[str, list[SourceItem]]:
    del state
    discovered_at = (now or datetime.now(timezone.utc)).isoformat()
    queries = seed_queries
    if queries is None:
        if settings is None:
            queries = []
        else:
            queries = next_run_seed_queries(
                mongo,
                evergreen=settings.evergreen_queries,
                lga_names=settings.lga_names,
                rotation_size=settings.seed_lga_rotation_size,
            )
    submitted = _run_discovery(
        bedrock=bedrock,
        web_search=web_search,
        seed_queries=queries,
        max_search_calls=max_search_calls,
        tracker=tracker,
    )
    candidates = _normalize_items(submitted, discovered_at=discovered_at)
    already_queued = mongo.existing_urls([item["url"] for item in candidates])
    after_dedup = [item for item in candidates if item["url"] not in already_queued]
    discovered: list[SourceItem] = []
    dropped_homepages = 0
    for item in after_dedup:
        if is_likely_homepage(item["url"]):
            dropped_homepages += 1
            continue
        discovered.append(item)
    print(f"discover: dropped {dropped_homepages} homepage/root URL(s)")
    return {"discovered_items": discovered}


def is_likely_homepage(url: str) -> bool:
    """True when the URL is a site root (no path beyond `/`).

    Category, tag, and other index paths are not filtered here — those are a
    known follow-up. Title-based heuristics are intentionally omitted.
    """
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    return path == ""


def _run_discovery(
    *,
    bedrock: BedrockClient,
    web_search: SearchFn,
    seed_queries: list[str],
    max_search_calls: int,
    tracker: RunCostTracker | None = None,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": [{"text": _user_prompt(seed_queries, max_search_calls)}]}
    ]
    search_calls = 0
    max_turns = max_search_calls + 2

    for _ in range(max_turns):
        force_submit = search_calls >= max_search_calls
        response = bedrock.converse(
            system=_SYSTEM,
            messages=messages,
            tools=[WEB_SEARCH_SPEC, SUBMIT_SPEC],
            tool_choice={"tool": {"name": SUBMIT_TOOL}} if force_submit else {"any": {}},
        )
        record_last_usage(tracker, "discover", bedrock)
        assistant_content = response.get("output", {}).get("message", {}).get("content") or []
        uses = tool_use_blocks(response)
        if not uses:
            break

        messages.append({"role": "assistant", "content": assistant_content})
        tool_results: list[dict[str, Any]] = []
        submitted: list[dict[str, Any]] | None = None

        for tool_use in uses:
            name = tool_use.get("name")
            tool_use_id = str(tool_use.get("toolUseId") or name)
            payload = tool_use.get("input") or {}
            if name == SUBMIT_TOOL:
                submitted = list(payload.get("items") or [])
                tool_results.append(_tool_result(tool_use_id, {"status": "accepted"}))
            elif name == WEB_SEARCH_TOOL:
                if search_calls >= max_search_calls:
                    tool_results.append(
                        _tool_result(
                            tool_use_id,
                            {"error": "Search budget exhausted. Submit candidates now."},
                        )
                    )
                    continue
                query = str(payload.get("query") or "").strip()
                results = web_search(query) if query else []
                search_calls += 1
                tool_results.append(
                    _tool_result(
                        tool_use_id,
                        {
                            "query": query,
                            "remaining_calls": max_search_calls - search_calls,
                            "results": results,
                        },
                    )
                )
            else:
                tool_results.append(_tool_result(tool_use_id, {"error": f"Unknown tool: {name}"}))

        if submitted is not None:
            return submitted
        messages.append({"role": "user", "content": tool_results})

    return []


def _normalize_items(raw_items: list[dict[str, Any]], *, discovered_at: str) -> list[SourceItem]:
    items: list[SourceItem] = []
    seen: set[str] = set()
    for raw in raw_items:
        url = _valid_http_url(raw.get("url"))
        title = str(raw.get("title") or "").strip()
        if not url or not title or url in seen:
            continue
        seen.add(url)
        items.append(
            {
                "title": title,
                "url": url,
                "snippet": str(raw.get("snippet") or "").strip(),
                "discovered_at": discovered_at,
            }
        )
    return items


def _valid_http_url(value: object) -> str | None:
    raw = str(value or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return raw


def _user_prompt(seed_queries: list[str], max_search_calls: int) -> str:
    listed = "\n".join(f"- {query}" for query in seed_queries)
    return (
        f"You may call web_search at most {max_search_calls} times this run.\n"
        "Choose the most useful seed queries from this list:\n"
        f"{listed}\n\n"
        "After searching, call submit_candidates with new, relevant article URLs only — "
        "never homepage or index URLs."
    )


def _tool_result(tool_use_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "toolResult": {
            "toolUseId": tool_use_id,
            "content": [{"json": payload}],
        }
    }
