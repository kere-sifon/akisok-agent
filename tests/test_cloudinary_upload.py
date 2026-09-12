from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.images.cloudinary_upload import upload_image


def test_upload_image_returns_secure_url() -> None:
    seen: dict = {}

    def fake_upload(stream, **kwargs):
        seen["kwargs"] = kwargs
        seen["stream"] = stream
        return {"secure_url": "https://res.cloudinary.com/demo/image/upload/akisok/demo.jpg"}

    url = upload_image(b"png-bytes", "demo", uploader=SimpleNamespace(upload=fake_upload))
    assert url.endswith("akisok/demo.jpg")
    assert seen["kwargs"]["folder"] == "akisok"
    assert seen["kwargs"]["public_id"] == "demo"


def test_upload_image_raises_without_secure_url() -> None:
    def fake_upload(*_a, **_k):
        return {}

    with pytest.raises(RuntimeError, match="secure_url"):
        upload_image(b"png-bytes", "demo", uploader=SimpleNamespace(upload=fake_upload))
