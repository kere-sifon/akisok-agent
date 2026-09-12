from __future__ import annotations

import os
from io import BytesIO

import cloudinary
import cloudinary.uploader

FOLDER = "akisok"


def upload_image(
    image_bytes: bytes,
    public_id: str,
    *,
    uploader: object | None = None,
) -> str:
    """
    Upload via Cloudinary's Upload API under folder `akisok`.
    Returns secure_url. Raises on failure.
    """
    cloudinary.config(
        cloud_name=(os.getenv("CLOUDINARY_CLOUD_NAME") or "").strip(),
        api_key=(os.getenv("CLOUDINARY_API_KEY") or "").strip(),
        api_secret=(os.getenv("CLOUDINARY_API_SECRET") or "").strip(),
    )
    client = uploader or cloudinary.uploader
    result = client.upload(
        BytesIO(image_bytes),
        folder=FOLDER,
        public_id=public_id,
        overwrite=False,
    )
    url = (result or {}).get("secure_url")
    if not url:
        raise RuntimeError("Cloudinary upload returned no secure_url")
    return str(url)
