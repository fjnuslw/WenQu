"""Meilisearch 异步薄客户端（httpx 直连 REST API）。

只实现管道需要的操作面；任务为异步队列，wait=True 时轮询 task 状态直到成功，
超时抛 UpstreamError —— 不静默吞掉索引失败（spec §7）。
"""

import asyncio
import time
from typing import Any

import httpx

from getoffer.config import Settings
from getoffer.errors import UpstreamError

QUESTIONS_INDEX = "questions"


class MeiliIndexer:
    def __init__(self, settings: Settings) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.meilisearch_url,
            headers=(
                {"Authorization": f"Bearer {settings.meilisearch_key}"}
                if settings.meilisearch_key
                else {}
            ),
            timeout=httpx.Timeout(60.0),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, *, json_body: Any = None) -> dict[str, Any]:
        try:
            response = await self._client.request(method, path, json=json_body)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise UpstreamError(
                f"Meilisearch 返回 {exc.response.status_code}（{method} {path}）",
                details={"status": exc.response.status_code, "body": exc.response.text[:400]},
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamError(f"Meilisearch 不可达（{method} {path}）: {exc}") from exc
        if response.status_code == 204:
            return {}
        return response.json()

    async def ensure_index(self, uid: str, *, primary_key: str = "id") -> None:
        """存在则跳过，不存在则创建（含检索配置）。404 用结构化 status 判断，不做字符串匹配。"""
        try:
            await self._request("GET", f"/indexes/{uid}")
            return
        except UpstreamError as exc:
            if exc.details.get("status") != 404:
                raise
        await self._request("POST", "/indexes", json_body={"uid": uid, "primaryKey": primary_key})
        await self._request(
            "PUT",
            f"/indexes/{uid}/settings",
            json_body={
                "searchableAttributes": ["stem", "answer", "tags", "companies.name"],
                "filterableAttributes": ["kind", "tags", "companies.name", "difficulty"],
                "sortableAttributes": ["difficulty"],
            },
        )

    async def upsert_documents(
        self,
        uid: str,
        documents: list[dict[str, Any]],
        *,
        wait: bool = False,
    ) -> None:
        if not documents:
            return
        task = await self._request("POST", f"/indexes/{uid}/documents", json_body=documents)
        if wait:
            await self.wait_task(int(task["taskUid"]))

    async def wait_task(self, task_uid: int, *, timeout_sec: float = 60.0) -> None:
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            payload = await self._request("GET", f"/tasks/{task_uid}")
            status = payload.get("status")
            if status == "succeeded":
                return
            if status in ("failed", "canceled"):
                raise UpstreamError(
                    f"Meilisearch 任务 {task_uid} {status}",
                    details={"error": payload.get("error")},
                )
            await asyncio.sleep(0.3)
        raise UpstreamError(f"Meilisearch 任务 {task_uid} 等待超时（{timeout_sec}s）")

    async def search(
        self,
        uid: str,
        *,
        q: str,
        limit: int = 20,
        offset: int = 0,
        filter_expr: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"q": q, "limit": limit, "offset": offset}
        if filter_expr:
            body["filter"] = filter_expr
        return await self._request("POST", f"/indexes/{uid}/search", json_body=body)

    async def delete_all_documents(self, uid: str) -> None:
        task = await self._request("DELETE", f"/indexes/{uid}/documents")
        await self.wait_task(int(task["taskUid"]))


def question_document(row: Any) -> dict[str, Any]:
    """SQLAlchemy Question → Meili 文档。DB 是唯一事实源，索引只是派生物。"""
    return {
        "id": row.id,
        "stem": row.stem,
        "answer": row.answer or "",
        "kind": row.kind,
        "difficulty": row.difficulty,
        "tags": [tag.name for tag in row.tags],
        "companies": [{"name": stat.company.name, "freq": stat.freq} for stat in row.company_stats],
    }
