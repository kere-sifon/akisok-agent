from __future__ import annotations

import time
import urllib.error
import urllib.request
from typing import Any, Callable

FETCH_TIMEOUT_SECONDS = 5
RETRY_BACKOFF_SECONDS = 1
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

ExtractFn = Callable[[str], str | None]
OpenUrlFn = Callable[..., Any]
SleepFn = Callable[[float], None]


def check_source_link(
    url: str,
    *,
    timeout: int = FETCH_TIMEOUT_SECONDS,
    opener: OpenUrlFn | None = None,
    extract_text: ExtractFn | None = None,
    sleeper: SleepFn | None = None,
) -> dict[str, Any]:
    """GET the source URL once (plus one retry on transients). Shared with reproduction."""
    open_url = opener or urllib.request.urlopen
    sleep = sleeper or time.sleep
    result = _attempt(
        url,
        timeout=timeout,
        open_url=open_url,
        extract_text=extract_text or _extract_readable_text,
    )
    if result["ok"] or not _is_transient(result):
        return result
    sleep(RETRY_BACKOFF_SECONDS)
    return _attempt(
        url,
        timeout=timeout,
        open_url=open_url,
        extract_text=extract_text or _extract_readable_text,
    )


def _attempt(
    url: str,
    *,
    timeout: int,
    open_url: OpenUrlFn,
    extract_text: ExtractFn,
) -> dict[str, Any]:
    request = urllib.request.Request(url, method="GET", headers=BROWSER_HEADERS)
    try:
        with open_url(request, timeout=timeout) as response:
            status_code = int(getattr(response, "status", None) or response.getcode())
            raw = response.read()
    except urllib.error.HTTPError as exc:
        return _from_status(int(exc.code))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return _from_status(None)

    if status_code < 200 or status_code >= 300:
        return _from_status(status_code)

    html = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
    content = extract_text(html)
    return {
        "ok": True,
        "status_code": status_code,
        "content": content or None,
        "flag_broken": False,
        "likely_bot_blocked": False,
    }


def _from_status(status_code: int | None) -> dict[str, Any]:
    bot_blocked = status_code == 403
    return {
        "ok": False,
        "status_code": status_code,
        "content": None,
        "flag_broken": _should_flag(status_code),
        "likely_bot_blocked": bot_blocked,
    }


def _should_flag(status_code: int | None) -> bool:
    if status_code is None:
        return True
    if status_code == 403:
        return True
    if status_code == 404 or status_code >= 500:
        return True
    return False


def _is_transient(result: dict[str, Any]) -> bool:
    status = result.get("status_code")
    return status is None or status in {403, 429, 503}


def _extract_readable_text(html: str) -> str | None:
    import trafilatura

    extracted = trafilatura.extract(html, include_comments=False, include_tables=False)
    if extracted and extracted.strip():
        return extracted.strip()
    return None
