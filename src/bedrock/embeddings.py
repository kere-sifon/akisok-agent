from __future__ import annotations

import json
from typing import Any, Protocol

import boto3


class InvokeModelClient(Protocol):
    def invoke_model(self, **kwargs: Any) -> Any: ...


class EmbeddingClient:
    def __init__(
        self,
        *,
        region: str,
        model_id: str,
        runtime_client: InvokeModelClient | None = None,
    ) -> None:
        self.model_id = model_id
        self.last_usage = {"input_tokens": 0, "output_tokens": 0}
        self._client: InvokeModelClient = runtime_client or boto3.client(
            "bedrock-runtime",
            region_name=region,
        )

    def embed_text(self, text: str) -> list[float]:
        response = self._client.invoke_model(
            modelId=self.model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps({"inputText": text}),
        )
        body = response.get("body")
        payload = body.read() if hasattr(body, "read") else body
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8")
        parsed = json.loads(payload)
        embedding = parsed.get("embedding")
        if not isinstance(embedding, list):
            raise ValueError("Bedrock embedding response missing embedding list")
        self.last_usage = {
            "input_tokens": int(parsed.get("inputTextTokenCount") or 0),
            "output_tokens": 0,
        }
        return [float(value) for value in embedding]
