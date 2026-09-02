"""OpenAI-compatible embedding gateway with strict response validation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import httpx

from getoffer.config import EmbeddingProviderConfig
from getoffer.errors import NotConfigured, UpstreamError


@dataclass(frozen=True)
class EmbeddingBatch:
    vectors: list[list[float]]
    model: str
    dimension: int


class EmbeddingGateway:
    def __init__(
        self,
        config: EmbeddingProviderConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config
        self._client: httpx.AsyncClient | None = None
        if config.provider != "disabled" and config.base_url.strip():
            self._client = httpx.AsyncClient(
                base_url=config.base_url.rstrip("/"),
                timeout=httpx.Timeout(config.timeout_seconds),
                transport=transport,
            )

    @property
    def configured(self) -> bool:
        return not self._missing_fields()

    @property
    def model(self) -> str:
        return self._config.model

    def capabilities(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "provider": self._config.provider,
            "model": self._config.model if self.configured else None,
            "dimension": self._config.dimension or None,
        }

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def embed(self, texts: list[str]) -> EmbeddingBatch:
        if not texts:
            return EmbeddingBatch([], self._config.model, self._config.dimension)
        missing = self._missing_fields()
        if missing or self._client is None:
            raise NotConfigured(
                "代码语义 embedding 未配置",
                details={"provider": self._config.provider, "missing": missing},
            )

        vectors: list[list[float]] = []
        dimension = self._config.dimension
        for offset in range(0, len(texts), self._config.batch_size):
            payload = await self._request(texts[offset : offset + self._config.batch_size])
            batch = self._vectors_from_response(payload)
            for vector in batch:
                if dimension == 0:
                    dimension = len(vector)
                if len(vector) != dimension:
                    raise UpstreamError(
                        "embedding 维度不一致",
                        details={"expected": dimension, "actual": len(vector)},
                    )
                vectors.append(vector)
        if len(vectors) != len(texts):
            raise UpstreamError(
                "embedding 数量与输入不一致",
                details={"expected": len(texts), "actual": len(vectors)},
            )
        return EmbeddingBatch(vectors=vectors, model=self._config.model, dimension=dimension)

    async def _request(self, texts: list[str]) -> dict[str, Any]:
        assert self._client is not None
        headers = (
            {"Authorization": f"Bearer {self._config.api_key}"}
            if self._config.api_key.strip()
            else None
        )
        try:
            response = await self._client.post(
                "/embeddings",
                json={"model": self._config.model, "input": texts, "encoding_format": "float"},
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            raise UpstreamError(
                f"embedding 上游返回 {exc.response.status_code}",
                details={"status": exc.response.status_code},
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise UpstreamError(f"embedding 上游不可达或响应非 JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise UpstreamError("embedding 响应不是 JSON 对象")
        return data

    def _vectors_from_response(self, payload: dict[str, Any]) -> list[list[float]]:
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise UpstreamError("embedding 响应缺少 data 数组")
        ordered: list[tuple[int, list[float]]] = []
        for position, row in enumerate(rows):
            if not isinstance(row, dict) or not isinstance(row.get("embedding"), list):
                raise UpstreamError("embedding data 项结构非法", details={"position": position})
            raw_vector = row["embedding"]
            try:
                vector = [float(value) for value in raw_vector]
            except (TypeError, ValueError, OverflowError) as exc:
                raise UpstreamError(
                    "embedding 向量包含非数值",
                    details={"position": position},
                ) from exc
            if not vector or any(not math.isfinite(value) for value in vector):
                raise UpstreamError("embedding 向量为空或含非有限数", details={"position": position})
            index = row.get("index", position)
            if not isinstance(index, int):
                raise UpstreamError("embedding index 不是整数", details={"position": position})
            ordered.append((index, vector))
        ordered.sort(key=lambda item: item[0])
        expected = list(range(len(ordered)))
        if [index for index, _vector in ordered] != expected:
            raise UpstreamError("embedding index 不连续或重复")
        return [vector for _index, vector in ordered]

    def _missing_fields(self) -> list[str]:
        if self._config.provider == "disabled":
            return ["provider"]
        missing: list[str] = []
        if not self._config.base_url.strip():
            missing.append("base_url")
        if not self._config.model.strip():
            missing.append("model")
        return missing
