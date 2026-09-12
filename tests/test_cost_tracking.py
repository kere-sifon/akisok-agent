from __future__ import annotations

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
