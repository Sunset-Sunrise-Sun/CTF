import json
import os
from typing import AsyncIterator, Literal, Protocol
import httpx
from pydantic import Field
from .models import Model


class Capabilities(Model):
    streaming: bool = False
    tool_calling: bool = False
    structured_output: bool = False


class ProviderConfig(Model):
    provider_id: str
    adapter: Literal["deepseek", "openai", "anthropic", "openai-compatible"]
    base_url: str
    model_id: str
    api_key_env: str
    timeout_seconds: float = Field(default=30, gt=0, le=300)
    capabilities: Capabilities = Field(default_factory=Capabilities)


class Message(Model):
    role: Literal["system", "user", "assistant"]
    content: str


class ToolDefinition(Model):
    name: str
    description: str
    parameters: dict


class ToolCall(Model):
    call_id: str
    name: str
    arguments: dict


class ModelRequest(Model):
    messages: list[Message]
    tools: list[ToolDefinition] = Field(default_factory=list)
    output_schema: dict | None = None
    # Explicit opt-in: omit unsupported features, never parse prose as tool calls.
    allow_degrade: bool = False


class ModelResponse(Model):
    provider_id: str
    model_id: str
    text: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    degraded_features: list[str] = Field(default_factory=list)
    usage: dict[str, int] | None = None
    audit_call_id: str | None = None


class StreamChunk(Model):
    text: str = ""
    response: ModelResponse | None = None


class ProviderError(Exception):
    def __init__(self, code: str, retry_after: str | None = None):
        self.code, self.retry_after = code, retry_after
        super().__init__(
            code
        )  # Never include upstream response/request bodies or keys.


class ModelProvider(Protocol):
    config: ProviderConfig

    async def complete(self, request: ModelRequest) -> ModelResponse: ...
    def stream(self, request: ModelRequest) -> AsyncIterator[StreamChunk]: ...


class OpenAICompatibleAdapter:
    max_buffered_response_bytes = 512 * 1024

    def __init__(self, config: ProviderConfig, transport=None, api_key: str | None = None):
        self.config, self.transport = config, transport
        # Inline secrets come from the OS-protected settings store.  They are
        # deliberately never placed in ProviderConfig (which is serialised into
        # docs/contracts/openapi) or in the environment.
        self._inline_api_key = api_key

    def api_key_present(self) -> bool:
        return bool(self._inline_api_key or os.environ.get(self.config.api_key_env))

    def prepare(self, request: ModelRequest) -> tuple[dict, list[str]]:
        missing = []
        body = {
            "model": self.config.model_id,
            "messages": [m.model_dump() for m in request.messages],
        }
        if request.tools:
            if self.config.capabilities.tool_calling:
                body["tools"] = [
                    {"type": "function", "function": t.model_dump()}
                    for t in request.tools
                ]
            else:
                missing.append("tool_calling")
        if request.output_schema is not None:
            if self.config.capabilities.structured_output:
                body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "output",
                        "strict": True,
                        "schema": request.output_schema,
                    },
                }
            else:
                missing.append("structured_output")
        if missing and not request.allow_degrade:
            raise ProviderError("unsupported_capability")
        return body, missing

    def key(self) -> str:
        key = self._inline_api_key or os.environ.get(self.config.api_key_env)
        if not key:
            raise ProviderError("missing_credentials")
        return key

    @staticmethod
    def status(response):
        if response.status_code == 429:
            raise ProviderError("rate_limited", response.headers.get("retry-after"))
        if not 200 <= response.status_code < 300:
            raise ProviderError(
                "authentication"
                if response.status_code in (401, 403)
                else "upstream_error"
            )

    def parse(self, message: dict, missing: list[str]) -> ModelResponse:
        calls = [
            ToolCall(
                call_id=t["id"],
                name=t["function"]["name"],
                arguments=json.loads(t["function"]["arguments"]),
            )
            for t in message.get("tool_calls", [])
        ]
        return ModelResponse(
            provider_id=self.config.provider_id,
            model_id=self.config.model_id,
            text=message.get("content") or "",
            tool_calls=calls,
            degraded_features=missing,
        )

    async def complete(self, request: ModelRequest) -> ModelResponse:
        body, missing = self.prepare(request)
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=self.config.timeout_seconds,
                follow_redirects=False,
            ) as client:
                async with client.stream(
                    "POST",
                    self.config.base_url.rstrip("/") + "/chat/completions",
                    json=body,
                    headers={"Authorization": "Bearer " + self.key()},
                ) as response:
                    self.status(response)
                    received = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(received) + len(chunk) > self.max_buffered_response_bytes:
                            raise ProviderError("response_limit_exceeded")
                        received.extend(chunk)
                payload = json.loads(received)
                result = self.parse(payload["choices"][0]["message"], missing)
                usage = payload.get("usage")
                if usage is not None:
                    if not isinstance(usage, dict):
                        raise ProviderError("invalid_response")
                    filtered = {k: v for k, v in usage.items() if k in {
                        "prompt_tokens", "completion_tokens", "total_tokens"
                    }}
                    if any(type(v) is not int or not 0 <= v <= 2**53-1 for v in filtered.values()):
                        raise ProviderError("invalid_response")
                    result.usage = filtered or None
                return result
        except httpx.TimeoutException:
            raise ProviderError("timeout") from None
        except httpx.HTTPError:
            raise ProviderError("transport_error") from None
        except (KeyError, ValueError, TypeError):
            raise ProviderError("invalid_response") from None

    async def stream(self, request: ModelRequest) -> AsyncIterator[StreamChunk]:
        body, missing = self.prepare(request)
        if not self.config.capabilities.streaming:
            if not request.allow_degrade:
                raise ProviderError("unsupported_capability")
            response = await self.complete(request)
            response.degraded_features.append("streaming")
            yield StreamChunk(response=response)
            return
        body["stream"] = True
        text, calls = "", {}
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=self.config.timeout_seconds,
                follow_redirects=False,
            ) as client:
                async with client.stream(
                    "POST",
                    self.config.base_url.rstrip("/") + "/chat/completions",
                    json=body,
                    headers={"Authorization": "Bearer " + self.key()},
                ) as response:
                    self.status(response)
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        choices = json.loads(data).get("choices", [])
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {})
                        token = delta.get("content") or ""
                        text += token
                        if token:
                            yield StreamChunk(text=token)
                        for part in delta.get("tool_calls", []):
                            item = calls.setdefault(
                                part["index"],
                                {"id": "", "function": {"name": "", "arguments": ""}},
                            )
                            item["id"] += part.get("id", "")
                            for field in ("name", "arguments"):
                                item["function"][field] += part.get("function", {}).get(
                                    field, ""
                                )
            yield StreamChunk(
                response=self.parse(
                    {"content": text, "tool_calls": list(calls.values())}, missing
                )
            )
        except httpx.TimeoutException:
            raise ProviderError("timeout") from None
        except httpx.HTTPError:
            raise ProviderError("transport_error") from None
        except (KeyError, ValueError, TypeError):
            raise ProviderError("invalid_response") from None


class DeepSeekAdapter(OpenAICompatibleAdapter):
    pass


class OpenAIAdapter(OpenAICompatibleAdapter):
    """Chat Completions wire adapter. Capabilities configured for the chosen model."""


class AnthropicAdapter(OpenAICompatibleAdapter):
    """Reserved native Messages adapter; deliberately fails closed until implemented."""

    async def complete(self, request: ModelRequest) -> ModelResponse:
        raise ProviderError("adapter_not_implemented")

    async def stream(self, request: ModelRequest) -> AsyncIterator[StreamChunk]:
        raise ProviderError("adapter_not_implemented")
        yield StreamChunk()  # pragma: no cover


class ProviderRegistry:
    @classmethod
    def from_file(cls, path):
        from pathlib import Path

        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            [ProviderConfig.model_validate(c) for c in data["providers"]],
            data["selected"],
        )

    adapters = {
        "deepseek": DeepSeekAdapter,
        "openai": OpenAIAdapter,
        "anthropic": AnthropicAdapter,
        "openai-compatible": OpenAICompatibleAdapter,
    }

    def __init__(self, configs: list[ProviderConfig], selected: str):
        self.configs = {c.provider_id: c for c in configs}
        if len(self.configs) != len(configs):
            raise ValueError("Duplicate provider ID")
        self.select(selected)

    def select(self, provider_id: str):
        if provider_id not in self.configs:
            raise ValueError("Unknown provider")
        self.selected = provider_id

    def get(self, transport=None, api_key: str | None = None) -> ModelProvider:
        config = self.configs[self.selected]
        return self.adapters[config.adapter](config, transport, api_key=api_key)
