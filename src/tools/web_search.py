from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Callable

SearchFn = Callable[[str], list[dict]]

TAVILY_ENDPOINT = "https://api.tavily.com/search"


def create_web_search(*, api_key: str, max_results: int = 5) -> SearchFn:
    """Return a `web_search(query) -> [{title, url, snippet}]` function.

    Backend is Tavily. Keep this signature stable so the provider can be swapped.
    """

    def web_search(query: str) -> list[dict]:
        payload = json.dumps(
            {
                "api_key": api_key,
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            TAVILY_ENDPOINT,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Tavily search failed ({exc.code}): {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Tavily search request failed: {exc}") from exc

        results = []
        for item in body.get("results") or []:
            url = str(item.get("url") or "").strip()
            title = str(item.get("title") or "").strip()
            if not url or not title:
                continue
            results.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": str(item.get("content") or item.get("snippet") or "").strip(),
                }
            )
        return results

    return web_search
