"""学习路径 API（F7）：目录只读 + 进度读写。

- 目录来自受版本控制的 JSON（`catalog.py`），改内容走 Git，本模块无写接口。
- 进度落 `learning_enrollments` / `learning_node_progress`，两处写入均幂等 upsert。
- 完成度分母剔除 `skipped`，避免「跳过刷进度」。
"""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from getoffer.api.deps import get_db_session
from getoffer.errors import NotFound, ValidationFailed
from getoffer.models import LearningEnrollment, LearningNodeProgress, ReviewItem
from getoffer.paths.catalog import (
    Catalog,
    load_catalog,
    node_out,
    path_nodes,
    resource_out,
    stage_out,
)

router = APIRouter(prefix="/api/paths", tags=["paths"])

VALID_STATUS = ("todo", "doing", "done", "skipped")


class EnrollIn(BaseModel):
    target_role: str = ""
    daily_minutes: int = Field(default=60, ge=10, le=960)
    target_on: date | None = None


class ProgressIn(BaseModel):
    status: str
    note: str = ""


def _require_status(status: str) -> str:
    if status not in VALID_STATUS:
        raise ValidationFailed(f"非法节点状态 {status!r}，可选: {', '.join(VALID_STATUS)}")
    return status


def _enrollment_out(row: LearningEnrollment | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "path_slug": row.path_slug,
        "target_role": row.target_role,
        "daily_minutes": row.daily_minutes,
        "started_on": row.started_on.isoformat(),
        "target_on": row.target_on.isoformat() if row.target_on else None,
    }


def _summarize(
    catalog: Catalog,
    slug: str,
    status_by_node: dict[str, str],
) -> dict[str, Any]:
    nodes = list(path_nodes(catalog, slug))
    done = sum(1 for n in nodes if status_by_node.get(n.id) == "done")
    skipped = sum(1 for n in nodes if status_by_node.get(n.id) == "skipped")
    total_hours = sum(n.hours for n in nodes)
    remaining_hours = sum(n.hours for n in nodes if status_by_node.get(n.id) not in ("done", "skipped"))
    current = next(
        (n for n in nodes if status_by_node.get(n.id) not in ("done", "skipped")),
        None,
    )
    denominator = len(nodes) - skipped
    return {
        "total_nodes": len(nodes),
        "done_nodes": done,
        "skipped_nodes": skipped,
        "percent": round(done / denominator * 100) if denominator > 0 else 0,
        "total_hours": total_hours,
        "remaining_hours": remaining_hours,
        "current_node": (
            {"id": current.id, "title": current.title, "kind": current.kind} if current else None
        ),
    }


@router.get("")
async def list_paths(
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    catalog = load_catalog()
    status_rows = (await session.scalars(select(LearningNodeProgress))).all()
    status_by_node = {row.node_id: row.status for row in status_rows}
    enrollment_rows = (await session.scalars(select(LearningEnrollment))).all()
    enrollment_by_slug = {row.path_slug: row for row in enrollment_rows}

    items = []
    for path in sorted(catalog.paths, key=lambda p: p.order):
        stages = catalog.stages_by_path.get(path.slug, [])
        core_resources = 0
        for stage in stages:
            for node in catalog.nodes_by_stage.get(stage.id, []):
                core_resources += sum(
                    1 for rid in node.resources if catalog.resource_by_id[rid].priority == "core"
                )
        items.append(
            {
                **path.model_dump(),
                **_summarize(catalog, path.slug, status_by_node),
                "stage_count": len(stages),
                "core_resources": core_resources,
                "enrollment": _enrollment_out(enrollment_by_slug.get(path.slug)),
            }
        )

    return {
        "verified_at": catalog.verified_at,
        "resource_count": len(catalog.resources),
        "node_count": len(catalog.nodes),
        "items": items,
    }


@router.get("/plan/today")
async def today_plan(
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """今日计划：已订阅路径各自推进到哪个节点。

    只给「下一个」而不是一串 —— 学习路径的价值在于下一步明确，不在于清单更长。
    """
    catalog = load_catalog()
    enrollment_rows = (await session.scalars(select(LearningEnrollment))).all()
    status_rows = (await session.scalars(select(LearningNodeProgress))).all()
    status_by_node = {row.node_id: row.status for row in status_rows}

    items = []
    for row in sorted(enrollment_rows, key=lambda r: r.path_slug):
        path = catalog.path_by_slug.get(row.path_slug)
        if path is None:
            continue
        node = next(
            (
                n
                for n in path_nodes(catalog, row.path_slug)
                if status_by_node.get(n.id) not in ("done", "skipped")
            ),
            None,
        )
        if node is None:
            continue
        stage = next(
            (s for s in catalog.stages_by_path.get(row.path_slug, []) if s.id == node.stage),
            None,
        )
        items.append(
            {
                "path": {"slug": path.slug, "title": path.title, "accent": path.accent},
                "stage": {"id": stage.id, "title": stage.title} if stage else None,
                "node": node_out(node, catalog),
                "daily_minutes": row.daily_minutes,
                "estimated_days": max(1, round(node.hours * 60 / row.daily_minutes)) if node.hours else 1,
            }
        )
    return {"items": items}


@router.get("/{slug}")
async def get_path(
    slug: str,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    catalog = load_catalog()
    path = catalog.path_by_slug.get(slug)
    if path is None:
        raise NotFound(f"学习路径不存在: {slug}")

    status_rows = (await session.scalars(select(LearningNodeProgress))).all()
    status_by_node = {row.node_id: row.status for row in status_rows}
    note_by_node = {row.node_id: row.note for row in status_rows}
    enrollment = (
        await session.scalars(select(LearningEnrollment).where(LearningEnrollment.path_slug == slug))
    ).first()

    stages = []
    for stage in catalog.stages_by_path.get(slug, []):
        payload = stage_out(stage, catalog)
        for node_payload in payload["nodes"]:
            node_payload["status"] = status_by_node.get(node_payload["id"], "todo")
            node_payload["note"] = note_by_node.get(node_payload["id"], "")
        nodes = catalog.nodes_by_stage.get(stage.id, [])
        payload["node_count"] = len(nodes)
        payload["done_count"] = sum(1 for n in nodes if status_by_node.get(n.id) == "done")
        payload["hours"] = sum(n.hours for n in nodes)
        stages.append(payload)

    return {
        "path": path.model_dump(),
        "summary": _summarize(catalog, slug, status_by_node),
        "enrollment": _enrollment_out(enrollment),
        "verified_at": catalog.verified_at,
        "stages": stages,
    }


@router.put("/{slug}/enroll")
async def enroll_path(
    slug: str,
    body: EnrollIn,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    catalog = load_catalog()
    if slug not in catalog.path_by_slug:
        raise NotFound(f"学习路径不存在: {slug}")

    row = (
        await session.scalars(select(LearningEnrollment).where(LearningEnrollment.path_slug == slug))
    ).first()
    if row is None:
        row = LearningEnrollment(
            path_slug=slug,
            target_role=body.target_role,
            daily_minutes=body.daily_minutes,
            target_on=body.target_on,
        )
        session.add(row)
    else:
        row.target_role = body.target_role
        row.daily_minutes = body.daily_minutes
        row.target_on = body.target_on
    await session.commit()
    await session.refresh(row)
    return {"enrollment": _enrollment_out(row)}


@router.put("/nodes/{node_id}/progress")
async def set_node_progress(
    node_id: str,
    body: ProgressIn,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    catalog = load_catalog()
    node = catalog.node_by_id.get(node_id)
    if node is None:
        raise NotFound(f"学习节点不存在: {node_id}")
    status = _require_status(body.status)

    row = (
        await session.scalars(select(LearningNodeProgress).where(LearningNodeProgress.node_id == node_id))
    ).first()
    if row is None:
        row = LearningNodeProgress(node_id=node_id, status=status, note=body.note)
        session.add(row)
    else:
        row.status = status
        row.note = body.note
    await session.commit()
    await session.refresh(row)

    stage = next((s for s in catalog.stages if s.id == node.stage), None)
    return {
        "node_id": node_id,
        "status": row.status,
        "note": row.note,
        "path_slug": stage.path if stage else None,
        "resource_count": len(node.resources),
        "core_resource_ids": [
            rid for rid in node.resources if catalog.resource_by_id[rid].priority == "core"
        ],
    }


@router.post("/nodes/{node_id}/review")
async def node_to_review(
    node_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """把一个节点变成复习卡，接进 F6 的 SM-2 队列（source=path）。

    去重键沿用 F6 的思路：按**节点**去重而非文本哈希——改一次文案不该多出一张卡。
    """
    catalog = load_catalog()
    node = catalog.node_by_id.get(node_id)
    if node is None:
        raise NotFound(f"学习节点不存在: {node_id}")

    content_hash = hashlib.sha256(node_id.encode("utf-8")).hexdigest()
    existing = (
        await session.scalars(
            select(ReviewItem).where(
                ReviewItem.source == "path",
                ReviewItem.source_ref == node_id,
                ReviewItem.content_hash == content_hash,
            )
        )
    ).first()
    if existing is not None:
        return {"item_id": existing.id, "created": False}

    weakness_parts = [f"目标：{node.objective}"]
    if node.deliverable:
        weakness_parts.append(f"产出物：{node.deliverable}")
    if node.acceptance:
        weakness_parts.append("验收：" + "；".join(node.acceptance))

    item = ReviewItem(
        source="path",
        source_ref=node_id,
        content_hash=content_hash,
        question_text=node.title,
        weakness="\n".join(weakness_parts),
        tag=node.related.tags[0] if node.related.tags else None,
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return {"item_id": item.id, "created": True}


@router.get("/nodes/{node_id}/resources")
async def node_resources(node_id: str) -> dict[str, Any]:
    """节点资源单独取：详情接口已内嵌，此端点供链接分享与调试使用。"""
    catalog = load_catalog()
    node = catalog.node_by_id.get(node_id)
    if node is None:
        raise NotFound(f"学习节点不存在: {node_id}")
    return {
        "node_id": node_id,
        "items": [
            resource_out(catalog.resource_by_id[rid])
            for rid in node.resources
            if rid in catalog.resource_by_id
        ],
    }
