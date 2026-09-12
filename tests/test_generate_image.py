from __future__ import annotations

import base64
import json
from types import SimpleNamespace

import pytest

from src.images.generate_image import DEFAULT_IMAGE_MODEL_ID, build_image_prompt, generate_image


def test_build_image_prompt_is_abstract_and_includes_theme() -> None:
    prompt = build_image_prompt("Uyo market morning", "culture", "Uyo")
    lowered = prompt.lower()
    assert "Uyo market morning" in prompt
    assert "culture" in lowered
    assert "not photorealistic" in lowered
    assert "no identifiable real people" in lowered
    assert "no specific real landmarks" in lowered
    assert "do not depict specific real people" in lowered
    assert "do not claim to depict a specific real place accurately" in lowered


def test_generate_image_uses_stability_request_shape(monkeypatch) -> None:
    png = b"\x89PNG-test"
    captured: dict = {}

    class FakeRuntime:
        def invoke_model(self, **kwargs):
            captured["invoke"] = kwargs
            return {
                "body": SimpleNamespace(
                    read=lambda: json.dumps(
                        {
                            "images": [base64.b64encode(png).decode("ascii")],
                            "finish_reasons": [None],
                        }
                    ).encode()
                )
            }

    def fake_client(service, region_name=None):
        captured["service"] = service
        captured["region"] = region_name
        return FakeRuntime()

    monkeypatch.setattr("src.images.generate_image.boto3.client", fake_client)

    result = generate_image("abstract prompt")

    assert result == png
    assert captured["service"] == "bedrock-runtime"
    assert captured["region"] == "us-west-2"
    assert captured["invoke"]["modelId"] == DEFAULT_IMAGE_MODEL_ID
    body = json.loads(captured["invoke"]["body"])
    assert body == {
        "prompt": "abstract prompt",
        "aspect_ratio": "1:1",
        "output_format": "png",
    }
    assert "taskType" not in body
    assert "textToImageParams" not in body


def test_generate_image_raises_when_filtered() -> None:
    runtime = SimpleNamespace(
        invoke_model=lambda **kwargs: {
            "body": SimpleNamespace(
                read=lambda: json.dumps(
                    {"images": [], "finish_reasons": ["FILTERED"]}
                ).encode()
            )
        }
    )
    with pytest.raises(RuntimeError, match="filtered"):
        generate_image("abstract prompt", runtime_client=runtime)


def test_generate_image_decodes_images_payload() -> None:
    png = b"\x89PNG-ok"
    runtime = SimpleNamespace(
        invoke_model=lambda **kwargs: {
            "body": SimpleNamespace(
                read=lambda: json.dumps(
                    {
                        "images": [base64.b64encode(png).decode("ascii")],
                        "finish_reasons": [None],
                    }
                ).encode()
            )
        }
    )
    assert generate_image("abstract prompt", runtime_client=runtime) == png


def test_generate_image_raises_when_no_images() -> None:
    runtime = SimpleNamespace(
        invoke_model=lambda **kwargs: {
            "body": SimpleNamespace(read=lambda: json.dumps({"images": [], "finish_reasons": [None]}).encode())
        }
    )
    with pytest.raises(RuntimeError, match="no images"):
        generate_image("abstract prompt", runtime_client=runtime)
