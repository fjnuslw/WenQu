"""LLM 网关：显式单供应商 + 结构化输出（spec §5.1）。

设计约束（spec §7）：
- 不做供应商间静默降级；换模型是部署决策。
- 结构化输出失败仅允许一次"带校验错误回传"的重试，仍失败抛 StructuredOutputError。
- 全部调用经 usage_sink 记账（llm_calls 表）。
"""

import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from getoffer.config import LLMProviderConfig
from getoffer.errors import NotConfigured, StructuredOutputError, UpstreamError

TModel = TypeVar("TModel", bound=BaseModel)

UsageSink = Callable[[dict[str, Any]], Awaitable[None]]


def strip_code_fence(text: str) -> str:
    """去掉 LLM 可能包裹的 markdown 代码栅栏。

    用字符串操作而非正则（spec §7）；仅处理首尾栅栏，不解析内容。
    """
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


@dataclass(frozen=True)
class LLMUsage:
    provider: str
    model: str
    purpose: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "purpose": self.purpose,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "latency_ms": self.latency_ms,
        }


def _usage_from_response(
    payload: dict[str, Any],
    *,
    provider: str,
    model: str,
    purpose: str,
    latency_ms: int,
) -> LLMUsage:
    usage = payload.get("usage") or {}
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    return LLMUsage(
        provider=provider,
        model=model,
        purpose=purpose,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        latency_ms=latency_ms,
    )


class LLMGateway:
    def __init__(self, config: LLMProviderConfig, *, usage_sink: UsageSink | None = None) -> None:
        self._config = config
        self._usage_sink = usage_sink
        self._client = httpx.AsyncClient(base_url=config.base_url, timeout=httpx.Timeout(180.0))

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _post(self, payload: dict[str, Any], *, purpose: str) -> dict[str, Any]:
        if not self._config.api_key:
            raise NotConfigured(
                "LLM api_key 未配置（GETOFFER_LLM__API_KEY）",
                details={"provider": self._config.name},
            )
        started = time.monotonic()
        try:
            response = await self._client.post(
                "/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {self._config.api_key}"},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise UpstreamError(
                f"LLM 上游返回 {exc.response.status_code}",
                details={"body": exc.response.text[:500]},
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamError(f"LLM 上游不可达: {exc}") from exc
        latency_ms = int((time.monotonic() - started) * 1000)
        data = response.json()
        usage = _usage_from_response(
            data, provider=self._config.name, model=self._config.model, purpose=purpose, latency_ms=latency_ms
        )
        if self._usage_sink is not None:
            await self._usage_sink(usage.as_dict())
        return data

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        purpose: str = "complete",
        thinking: bool | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self._config.model,
            "messages": ([{"role": "system", "content": system}] if system else []) + messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        # DeepSeek 思考开关（pi-ai thinkingFormat="deepseek" 同款协议）
        disable = self._config.disable_thinking if thinking is None else (not thinking)
        if disable:
            payload["thinking"] = {"type": "disabled"}
        data = await self._post(payload, purpose=purpose)
        try:
            choice = data["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise UpstreamError(
                "LLM 响应缺少 choices[0].message.content",
                details={"payload_keys": list(data)},
            ) from exc
        if not isinstance(content, str) or not content.strip():
            # 思考型模型可能把输出预算全部消耗在 reasoning_content 上：显式暴露 finish_reason 便于定位
            message = choice.get("message") or {}
            raise UpstreamError(
                "LLM 返回空 content（推理 token 可能挤占输出预算，请增大 max_tokens 或减小输入批次）",
                details={
                    "finish_reason": choice.get("finish_reason"),
                    "reasoning_content_len": len(message.get("reasoning_content") or ""),
                    "usage": data.get("usage"),
                },
            )
        return content

    async def complete_structured(
        self,
        messages: list[dict[str, str]],
        schema: type[TModel],
        *,
        system: str | None = None,
        purpose: str = "structured",
        max_tokens: int = 16384,
    ) -> TModel:
        """结构化输出：json_object 模式 + Pydantic 校验 + 单次错误回传重试。

        max_tokens 显式给足：思考型模型的 reasoning 与回答共享输出预算，默认值会被推理吃光。
        """
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        instruction = (
            "只输出一个符合以下 JSON Schema 的 JSON 对象，不要输出任何解释文字或代码栅栏。\n"
            f"Schema:\n{schema_json}"
        )
        base_messages = ([{"role": "system", "content": system}] if system else []) + list(messages)
        base_messages = base_messages + [{"role": "user", "content": instruction}]

        text = await self.complete(base_messages, temperature=0.0, purpose=purpose, max_tokens=max_tokens)
        try:
            return schema.model_validate_json(strip_code_fence(text))
        except (json.JSONDecodeError, ValidationError) as exc:
            first_error = exc

        # 单次重试：把校验错误回传给模型修正。仍失败则显式抛错，不静默兜底。
        repair_messages = base_messages + [
            {"role": "assistant", "content": text},
            {
                "role": "user",
                "content": f"上面的输出不符合 Schema，错误：{first_error}\n请重新输出正确的 JSON。",
            },
        ]
        retry_text = await self.complete(
            repair_messages, temperature=0.0, purpose=f"{purpose}:repair", max_tokens=max_tokens
        )
        try:
            return schema.model_validate_json(strip_code_fence(retry_text))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise StructuredOutputError(
                "LLM 结构化输出两次校验失败",
                details={"schema": schema.__name__, "first_error": str(first_error), "retry_error": str(exc)},
            ) from exc
