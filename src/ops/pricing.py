from __future__ import annotations

import json
import os
from typing import Any

# USD per 1K tokens. Confirm against the current AWS Bedrock pricing page for
# your region — these are placeholders and Bedrock pricing does change.
PRICING_USD_PER_1K_TOKENS: dict[str, dict[str, float]] = {
    "us.anthropic.claude-haiku-4-5-20251001-v1:0": {"input": 0.0008, "output": 0.004},
    "amazon.titan-embed-text-v2:0": {"input": 0.00002, "output": 0.0},
}

_FALLBACK = {"input": 0.003, "output": 0.015}

# USD per generated image (not per token). Confirm against the current AWS
# Bedrock on-demand page before relying on this long-term.
PRICING_USD_PER_IMAGE: dict[str, float] = {
    "stability.stable-image-core-v1:1": 0.03,
}

_IMAGE_FALLBACK = 0.03


def load_pricing() -> dict[str, dict[str, float]]:
    table = {key: dict(value) for key, value in PRICING_USD_PER_1K_TOKENS.items()}
    raw = (os.getenv("PRICING_OVERRIDE_JSON") or "").strip()
    if not raw:
        return table
    override = json.loads(raw)
    if not isinstance(override, dict):
        raise ValueError("PRICING_OVERRIDE_JSON must be a JSON object")
    for model_id, rates in override.items():
        if not isinstance(rates, dict):
            continue
        current = table.get(str(model_id), {})
        table[str(model_id)] = {
            "input": float(rates.get("input", current.get("input", _FALLBACK["input"]))),
            "output": float(rates.get("output", current.get("output", _FALLBACK["output"]))),
        }
    return table


def rates_for(model_id: str) -> dict[str, float]:
    table = load_pricing()
    if model_id in table:
        return table[model_id]
    lowered = (model_id or "").lower()
    for key, rates in table.items():
        if key.lower() in lowered or lowered in key.lower():
            return rates
    return dict(_FALLBACK)


def estimate_cost(token_usage: dict[str, Any]) -> float:
    """Sum USD cost from `{model_id: {input_tokens, output_tokens}}`."""
    total = 0.0
    for model_id, usage in (token_usage or {}).items():
        rates = rates_for(str(model_id))
        input_tokens = int((usage or {}).get("input_tokens") or 0)
        output_tokens = int((usage or {}).get("output_tokens") or 0)
        total += (input_tokens / 1000.0) * rates["input"]
        total += (output_tokens / 1000.0) * rates["output"]
    return round(total, 6)


def load_image_pricing() -> dict[str, float]:
    table = dict(PRICING_USD_PER_IMAGE)
    raw = (os.getenv("PRICING_OVERRIDE_JSON") or "").strip()
    if not raw:
        return table
    override = json.loads(raw)
    if not isinstance(override, dict):
        return table
    for model_id, rates in override.items():
        if isinstance(rates, dict) and "per_image" in rates:
            table[str(model_id)] = float(rates["per_image"])
        elif isinstance(rates, (int, float)):
            table[str(model_id)] = float(rates)
    return table


def image_rate_for(model_id: str) -> float:
    table = load_image_pricing()
    if model_id in table:
        return table[model_id]
    lowered = (model_id or "").lower()
    for key, rate in table.items():
        if key.lower() in lowered or lowered in key.lower():
            return rate
    return _IMAGE_FALLBACK


def estimate_image_cost(image_usage: dict[str, Any]) -> float:
    """Sum USD cost from `{model_id: count}` or `{model_id: {count: int}}`."""
    total = 0.0
    for model_id, usage in (image_usage or {}).items():
        if isinstance(usage, dict):
            count = int(usage.get("count") or usage.get("images") or 0)
        else:
            count = int(usage or 0)
        total += count * image_rate_for(str(model_id))
    return round(total, 6)
