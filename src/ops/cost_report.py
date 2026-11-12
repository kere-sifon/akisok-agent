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
    pipeline_cost_usd = sum(float(run.get("estimated_cost_usd") or 0) for run in runs)
    image_cost_usd = sum(float(row.get("estimated_cost_usd") or 0) for row in (image_costs or []))
    return {
        "runs": len(runs),
        "items_discovered": sum(int(run.get("items_discovered") or 0) for run in runs),
        "items_queued": sum(int(run.get("items_queued") or 0) for run in runs),
        "items_flagged": sum(int(run.get("items_flagged") or 0) for run in runs),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "image_count": sum(int(row.get("images") or 0) for row in (image_costs or [])),
        "pipeline_cost_usd": pipeline_cost_usd,
        "image_cost_usd": image_cost_usd,
        "estimated_cost_usd": pipeline_cost_usd + image_cost_usd,
    }


def format_summary(month: str, stats: dict, *, totals: dict | None = None) -> str:
    lines = [
        f"Month:              {month}",
        f"Runs:                {stats['runs']}",
        f"Items discovered:    {stats['items_discovered']}",
        f"Items queued:        {stats['items_queued']}",
        f"Items flagged:       {stats['items_flagged']}",
        f"Total tokens (in):   {stats['input_tokens']:,}",
        f"Total tokens (out):  {stats['output_tokens']:,}",
        f"Images generated:    {stats.get('image_count', 0)}",
        f"Pipeline this month: ${float(stats.get('pipeline_cost_usd') or 0):.2f}",
        f"Image cost:          ${float(stats.get('image_cost_usd') or 0):.2f}",
        f"This month:          ${stats['estimated_cost_usd']:.2f}",
    ]
    if totals is not None:
        lines.append(
            f"Total so far:        ${totals['estimated_cost_usd']:.2f} "
            f"(pipeline ${float(totals.get('pipeline_cost_usd') or 0):.2f} + "
            f"images ${float(totals.get('image_cost_usd') or 0):.2f})"
        )
    return "\n".join(lines) + "\n"


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
    totals = summarize_month(
        store.list_all_pipeline_runs(),
        store.list_all_image_generation_costs(),
    )
    print(format_summary(label, summarize_month(runs, images), totals=totals), end="")


if __name__ == "__main__":
    main()
