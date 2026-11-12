from __future__ import annotations

from src.ops.cost_report import format_summary, summarize_month
from src.ops.cost_tracking import RunCostTracker
from src.ops.pricing import estimate_cost


def test_token_usage_accumulates_per_model() -> None:
    tracker = RunCostTracker()
    tracker.record("model-a", 100, 20)
    tracker.record("model-a", 50, 10)
    tracker.record("model-b", 10, 5)

    usage = tracker.token_usage()
    assert usage["model-a"] == {"input_tokens": 150, "output_tokens": 30, "calls": 2}
    assert usage["model-b"] == {"input_tokens": 10, "output_tokens": 5, "calls": 1}


def test_estimate_cost_uses_pricing_table() -> None:
    usage = {
        "us.anthropic.claude-haiku-4-5-20251001-v1:0": {
            "input_tokens": 1000,
            "output_tokens": 1000,
            "calls": 1,
        },
        "amazon.titan-embed-text-v2:0": {
            "input_tokens": 1000,
            "output_tokens": 0,
            "calls": 1,
        },
    }
    # 1000/1000 * 0.0008 + 1000/1000 * 0.004 + 1000/1000 * 0.00002
    assert estimate_cost(usage) == 0.00482


def test_pricing_override_json(monkeypatch) -> None:
    monkeypatch.setenv(
        "PRICING_OVERRIDE_JSON",
        '{"us.anthropic.claude-haiku-4-5-20251001-v1:0": {"input": 1.0, "output": 2.0}}',
    )
    usage = {
        "us.anthropic.claude-haiku-4-5-20251001-v1:0": {
            "input_tokens": 1000,
            "output_tokens": 1000,
            "calls": 1,
        }
    }
    assert estimate_cost(usage) == 3.0


def test_record_image_adds_per_image_cost() -> None:
    tracker = RunCostTracker()
    tracker.record_image("image_generation", "stability.stable-image-core-v1:1")
    tracker.record_image("image_generation", "stability.stable-image-core-v1:1", count=2)
    assert tracker.cost_by_stage["image_generation"] == 0.09
    assert tracker.image_usage()["stability.stable-image-core-v1:1"] == 3


def test_summarize_month_adds_pipeline_and_image_costs() -> None:
    runs = [{"estimated_cost_usd": 0.10, "token_usage": {}, "items_discovered": 1, "items_queued": 1, "items_flagged": 0}]
    images = [{"estimated_cost_usd": 0.03, "images": 1}]
    stats = summarize_month(runs, images)
    assert stats["pipeline_cost_usd"] == 0.10
    assert stats["estimated_cost_usd"] == 0.13
    assert stats["image_cost_usd"] == 0.03
    assert stats["image_count"] == 1


def test_format_summary_includes_total_so_far() -> None:
    month = summarize_month(
        [{"estimated_cost_usd": 0.10, "token_usage": {}, "items_discovered": 0, "items_queued": 0, "items_flagged": 0}],
        [],
    )
    totals = summarize_month(
        [
            {"estimated_cost_usd": 0.10, "token_usage": {}, "items_discovered": 0, "items_queued": 0, "items_flagged": 0},
            {"estimated_cost_usd": 0.40, "token_usage": {}, "items_discovered": 0, "items_queued": 0, "items_flagged": 0},
        ],
        [{"estimated_cost_usd": 0.06, "images": 2}],
    )
    text = format_summary("2026-09", month, totals=totals)
    assert "This month:          $0.10" in text
    assert "Total so far:        $0.56" in text
