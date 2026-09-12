from __future__ import annotations

from typing import Any, Protocol

import boto3


class ConverseClient(Protocol):
    def converse(self, **kwargs: Any) -> dict[str, Any]: ...


class BedrockClient:
    """Thin Bedrock Runtime wrapper. Model ID comes from settings, never hardcoded."""

    def __init__(
        self,
        *,
        region: str,
        model_id: str,
        runtime_client: ConverseClient | None = None,
    ) -> None:
        self.model_id = model_id
        self.last_usage = {"input_tokens": 0, "output_tokens": 0}
        self._client: ConverseClient = runtime_client or boto3.client(
            "bedrock-runtime",
            region_name=region,
        )

    def converse(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        tool_config: dict[str, Any] = {"tools": [_as_tool_spec(tool) for tool in tools]}
        if tool_choice:
            tool_config["toolChoice"] = tool_choice
        response = self._client.converse(
            modelId=self.model_id,
            system=[{"text": system}],
            messages=messages,
            toolConfig=tool_config,
        )
        self.last_usage = _usage_from_response(response)
        return response

    def invoke_tool(
        self,
        *,
        system: str,
        user: str,
        tool_name: str,
        tool_description: str,
        input_schema: dict[str, Any],
    ) -> dict[str, Any]:
        response = self.converse(
            system=system,
            messages=[{"role": "user", "content": [{"text": user}]}],
            tools=[
                {
                    "name": tool_name,
                    "description": tool_description,
                    "inputSchema": {"json": input_schema},
                }
            ],
            tool_choice={"tool": {"name": tool_name}},
        )
        return _first_tool_input(response, tool_name)


def _usage_from_response(response: dict[str, Any]) -> dict[str, int]:
    usage = response.get("usage") or {}
    return {
        "input_tokens": int(usage.get("inputTokens") or usage.get("input_tokens") or 0),
        "output_tokens": int(usage.get("outputTokens") or usage.get("output_tokens") or 0),
    }


def _as_tool_spec(tool: dict[str, Any]) -> dict[str, Any]:
    if "toolSpec" in tool:
        return tool
    return {"toolSpec": tool}


def _first_tool_input(response: dict[str, Any], tool_name: str) -> dict[str, Any]:
    for block in tool_use_blocks(response):
        if block.get("name") == tool_name:
            raw = block.get("input") or {}
            if not isinstance(raw, dict):
                raise ValueError(f"Bedrock tool {tool_name} returned non-object input")
            return raw
    raise ValueError(f"Bedrock response missing toolUse for {tool_name}")


def tool_use_blocks(response: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = []
    for block in response.get("output", {}).get("message", {}).get("content", []):
        tool_use = block.get("toolUse")
        if tool_use:
            blocks.append(tool_use)
    return blocks
