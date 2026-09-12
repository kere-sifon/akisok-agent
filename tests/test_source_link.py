from __future__ import annotations

from io import BytesIO
import urllib.error
import urllib.request

from src.guardrails.source_link import BROWSER_HEADERS, check_source_link


class FakeResponse:
    def __init__(self, status: int, body: bytes = b"<html><p>Akwa Ibom</p></html>") -> None:
        self.status = status
        self._body = body

    def getcode(self) -> int:
        return self.status

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args) -> bool:
        return False


class ScriptedOpener:
    def __init__(self, outcomes: list) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[urllib.request.Request] = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(*outcome)


def _http_error(url: str, code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, "error", None, BytesIO(b""))


def test_403_flags_and_tags_bot_block() -> None:
    opener = ScriptedOpener(
        [
            _http_error("https://en.wikipedia.org/wiki/Uyo", 403),
            _http_error("https://en.wikipedia.org/wiki/Uyo", 403),
        ]
    )
    slept: list[float] = []
    result = check_source_link(
        "https://en.wikipedia.org/wiki/Uyo",
        opener=opener,
        extract_text=lambda html: html,
        sleeper=slept.append,
    )

    assert result["ok"] is False
    assert result["status_code"] == 403
    assert result["flag_broken"] is True
    assert result["likely_bot_blocked"] is True
    assert opener.requests[0].get_header("User-agent") == BROWSER_HEADERS["User-Agent"]
    assert slept == [1]


def test_404_flags_without_bot_block_tag() -> None:
    opener = ScriptedOpener([_http_error("https://example.com/missing", 404)])
    result = check_source_link(
        "https://example.com/missing",
        opener=opener,
        extract_text=lambda html: html,
        sleeper=lambda _: None,
    )

    assert result["flag_broken"] is True
    assert result["status_code"] == 404
    assert result["likely_bot_blocked"] is False
    assert len(opener.requests) == 1


def test_timeout_after_retry_flags() -> None:
    opener = ScriptedOpener([TimeoutError("timed out"), TimeoutError("timed out")])
    slept: list[float] = []
    result = check_source_link(
        "https://example.com/slow",
        opener=opener,
        extract_text=lambda html: html,
        sleeper=slept.append,
    )

    assert result["ok"] is False
    assert result["status_code"] is None
    assert result["flag_broken"] is True
    assert result["likely_bot_blocked"] is False
    assert slept == [1]
    assert len(opener.requests) == 2


def test_retry_after_transient_503_succeeds() -> None:
    opener = ScriptedOpener(
        [_http_error("https://en.wikipedia.org/wiki/Uyo", 503), (200, b"<html>ok</html>")]
    )
    result = check_source_link(
        "https://en.wikipedia.org/wiki/Uyo",
        opener=opener,
        extract_text=lambda html: "ok",
        sleeper=lambda _: None,
    )

    assert result["ok"] is True
    assert result["flag_broken"] is False
    assert result["status_code"] == 200
    assert result["content"] == "ok"
    assert len(opener.requests) == 2
