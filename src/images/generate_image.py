from __future__ import annotations

import base64
import json
import os
from typing import Any

import boto3

DEFAULT_IMAGE_MODEL_ID = "stability.stable-image-core-v1:1"
DEFAULT_IMAGE_REGION = "us-west-2"


def build_image_prompt(title: str, pillar: str, lga: str | None) -> str:
    """Abstract editorial prompt — not photorealistic, not a real person or landmark."""
    theme = (title or "Akwa Ibom").strip()
    pillar_label = (pillar or "news").strip()
    place = f" Motifs loosely associated with {lga.strip()} as texture only." if (lga or "").strip() else ""
    return (
        f"Abstract editorial illustration evoking the theme of '{theme}', "
        f"for a {pillar_label} feature.{place} "
        "In the style of geometric West African textile patterns, warm earth "
        "tones (forest green, cream, ochre), no text, no identifiable real "
        "people, no specific real landmarks — decorative and artistic only. "
        "Not photorealistic. Do not depict specific real people. "
        "Do not claim to depict a specific real place accurately."
    )


def generate_image(
    prompt: str,
    *,
    runtime_client: Any | None = None,
    model_id: str | None = None,
    region: str | None = None,
) -> bytes:
    """
    Calls Stability Stable Image Core on Bedrock (us-west-2 by default).
    Returns raw PNG bytes. Raises on failure or a non-null finish_reason.
    """
    resolved_model = (model_id or os.getenv("IMAGE_MODEL_ID") or DEFAULT_IMAGE_MODEL_ID).strip()
    resolved_region = (region or os.getenv("IMAGE_MODEL_REGION") or DEFAULT_IMAGE_REGION).strip()
    client = runtime_client or boto3.client("bedrock-runtime", region_name=resolved_region)
    body = {
        "prompt": prompt,
        "aspect_ratio": "1:1",
        "output_format": "png",
    }
    response = client.invoke_model(
        modelId=resolved_model,
        body=json.dumps(body),
    )
    result = _read_json_body(response)

    finish_reasons = result.get("finish_reasons") or []
    if any(reason is not None for reason in finish_reasons):
        raise RuntimeError(f"Stable Image Core filtered the request: {finish_reasons}")

    images = result.get("images") or []
    if not images:
        raise RuntimeError("Stable Image Core returned no images")

    return base64.b64decode(images[0])


def _read_json_body(response: dict[str, Any]) -> dict[str, Any]:
    raw = response.get("body")
    if hasattr(raw, "read"):
        raw = raw.read()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if isinstance(raw, str):
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    if isinstance(raw, dict):
        return raw
    raise RuntimeError("Stable Image Core returned an unreadable body")
