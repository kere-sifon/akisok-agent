from __future__ import annotations

import re
from typing import Any

SHINGLE_SIZE = 8
_WORD_RE = re.compile(r"[a-z0-9]+")


def check_reproduction(
    draft_text: str,
    source_content: str | None,
    *,
    overlap_threshold: float,
) -> dict[str, Any]:
    """Shingled n-gram overlap. Skip (do not flag) when the source was not fetched."""
    if source_content is None or not source_content.strip():
        return {"overlap_ratio": 0.0, "flagged": False, "skipped": True}

    ratio = overlap_ratio(draft_text, source_content)
    return {"overlap_ratio": ratio, "flagged": ratio > overlap_threshold, "skipped": False}


def overlap_ratio(draft_text: str, source_content: str, *, n: int = SHINGLE_SIZE) -> float:
    draft_shingles = _shingles(draft_text, n)
    source_shingles = _shingles(source_content, n)
    if not draft_shingles or not source_shingles:
        return 0.0
    return len(draft_shingles & source_shingles) / len(draft_shingles)


def _shingles(text: str, n: int) -> set[str]:
    words = _WORD_RE.findall(text.lower())
    if len(words) < n:
        return set()
    return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}
