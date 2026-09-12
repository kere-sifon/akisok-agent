from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

FRESH_WINDOW_DAYS = 14


def seed_lga_coverage(mongo, lga_names: list[str]) -> None:
    for name in lga_names:
        if name:
            mongo.seed_lga_coverage(name)


def record_queued_lgas(
    mongo,
    items: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    lga_names: list[str] | None = None,
) -> None:
    if lga_names:
        seed_lga_coverage(mongo, lga_names)
    moment = now or datetime.now(timezone.utc)
    for item in items:
        lga = (item.get("lga") or "").strip()
        if lga:
            mongo.increment_lga_coverage(lga, discovered_at=moment)


def classify_freshness(
    last_discovered_at: datetime | None,
    *,
    now: datetime | None = None,
    window_days: int = FRESH_WINDOW_DAYS,
) -> str:
    if last_discovered_at is None:
        return "never"
    moment = now or datetime.now(timezone.utc)
    discovered = last_discovered_at
    if discovered.tzinfo is None:
        discovered = discovered.replace(tzinfo=timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    if discovered >= moment - timedelta(days=window_days):
        return "fresh"
    return "due soon"


def relative_discovered(last_discovered_at: datetime | None, *, now: datetime | None = None) -> str:
    if last_discovered_at is None:
        return "never"
    moment = now or datetime.now(timezone.utc)
    discovered = last_discovered_at
    if discovered.tzinfo is None:
        discovered = discovered.replace(tzinfo=timezone.utc)
    days = max(0, (moment - discovered).days)
    if days == 0:
        return "today"
    if days == 1:
        return "1 day ago"
    return f"{days} days ago"
