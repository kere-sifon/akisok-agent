from __future__ import annotations

import argparse
from calendar import monthrange
from datetime import datetime, timezone

from src.config import load_settings
from src.db.mongo_client import ReviewQueueStore


def summarize_month(runs: list[dict], image_costs: list[dict] | None = None) -> dict:
    input_tokens = 0
    output_tokens = 0
    for run in runs:
        for usage in (run.get("token_usage") or {}).values():
            input_tokens += int(usage.get("input_tokens") or 0)
            output_tokens += int(usage.get("output_tokens") or 0)
    return {
        "runs": len(runs),
        "items_discovered": sum(int(run.get("items_discovered") or 0) for run in runs),
        "items_queued": sum(int(run.get("items_queued") or 0) for run in runs),
        "items_flagged": sum(int(run.get("items_flagged") or 0) for run in runs),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "image_count": sum(int(row.get("images") or 0) for row in (image_costs or [])),
        "image_cost_usd": sum(float(row.get("estimated_cost_usd") or 0) for row in (image_costs or [])),
        "estimated_cost_usd": sum(float(run.get("estimated_cost_usd") or 0) for run in runs)
        + sum(float(row.get("estimated_cost_usd") or 0) for row in (image_costs or [])),
    }


def format_summary(month: str, stats: dict) -> str:
    return (
        f"Month:              {month}\n"
        f"Runs:                {stats['runs']}\n"
        f"Items discovered:    {stats['items_discovered']}\n"
        f"Items queued:        {stats['items_queued']}\n"
        f"Items flagged:       {stats['items_flagged']}\n"
        f"Total tokens (in):   {stats['input_tokens']:,}\n"
        f"Total tokens (out):  {stats['output_tokens']:,}\n"
        f"Images generated:    {stats.get('image_count', 0)}\n"
        f"Image cost:          ${float(stats.get('image_cost_usd') or 0):.2f}\n"
        f"Estimated cost:      ${stats['estimated_cost_usd']:.2f}\n"
    )


def parse_month(value: str | None) -> tuple[int, int, str]:
    if not value:
        now = datetime.now(timezone.utc)
        return now.year, now.month, now.strftime("%Y-%m")
    year_s, month_s = value.split("-", 1)
    year, month = int(year_s), int(month_s)
    return year, month, f"{year:04d}-{month:02d}"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Monthly Bedrock cost summary from pipeline_runs.")
    parser.add_argument("--month", help="YYYY-MM (defaults to the current UTC month)")
    args = parser.parse_args(argv)
    year, month, label = parse_month(args.month)
    settings = load_settings()
    store = ReviewQueueStore(uri=settings.mongodb_uri, db_name=settings.mongodb_db_name)
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    end_day = monthrange(year, month)[1]
    end = datetime(year, month, end_day, 23, 59, 59, tzinfo=timezone.utc)
    runs = store.list_pipeline_runs_between(start, end)
    images = store.list_image_generation_costs_between(start, end)
    print(format_summary(label, summarize_month(runs, images)), end="")


if __name__ == "__main__":
    main()
