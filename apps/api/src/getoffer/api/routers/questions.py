"""题库读取 API（F2 查询侧；写入来自摄入管道）。

`q` 走 Meilisearch 全文检索取 id 列表，DB 仍是唯一事实源（渲染与关系数据均来自 DB）。
来源标记策略（用户要求）：GitHub 渠道只显示仓库名不渲染外链；其他渠道（小红书/知乎/
论坛/抖音等）通过 meta.source_url/meta.source_channel 输出可跳转链接。
"""

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from getoffer.api.deps import get_db_session, get_indexer
from getoffer.errors import NotFound
from getoffer.models import Company, Question, QuestionCompany, QuestionTag, Tag
from getoffer.search.meili import QUESTIONS_INDEX, MeiliIndexer

router = APIRouter(prefix="/api/questions", tags=["questions"])

_EAGER = (
    selectinload(Question.tags),
    selectinload(Question.followups),
    selectinload(Question.company_stats).selectinload(QuestionCompany.company),
    selectinload(Question.source),
)


def _source_out(question: Question) -> dict[str, Any]:
    """来源结构：kind ∈ github | official | external | None。"""
    meta = question.meta or {}
    if question.source is not None:
        return {
            "kind": "github",
            "repo": question.source.name,
            "ref": question.source_ref,
            "channel": None,
            "url": None,  # GitHub 渠道不渲染外链（用户要求）
        }
    if (question.source_ref or "").startswith("leetcode/"):
        return {"kind": "official", "repo": "LeetCode Hot100", "ref": question.source_ref,
                "channel": None, "url": None}
    if meta.get("source_url"):
        return {
            "kind": "external",
            "repo": None,
            "ref": question.source_ref,
            "channel": meta.get("source_channel"),
            "url": meta.get("source_url"),
        }
    return {"kind": None, "repo": None, "ref": question.source_ref, "channel": None, "url": None}


def _question_out(question: Question) -> dict[str, Any]:
    return {
        "id": question.id,
        "stem": question.stem,
        "kind": question.kind,
        "track": question.track,
        "difficulty": question.difficulty,
        "answer": question.answer,
        "answer_provenance": question.answer_provenance,
        "source": _source_out(question),
        "tags": [tag.name for tag in question.tags],
        "companies": [
            {"name": stat.company.name, "freq": stat.freq, "logo": stat.company.logo}
            for stat in question.company_stats
        ],
    }


@router.get("")
async def list_questions(
    tag: str | None = None,
    company: str | None = None,
    kind: str | None = None,
    track: str | None = None,
    q: str | None = None,
    limit: int = 20,
    offset: int = 0,
    session: AsyncSession = Depends(get_db_session),
    indexer: MeiliIndexer = Depends(get_indexer),
) -> dict[str, Any]:
    limit = min(max(limit, 1), 100)
    offset = max(offset, 0)

    conditions = []
    if tag:
        sub = select(QuestionTag.question_id).join(Tag, Tag.id == QuestionTag.tag_id).where(Tag.name == tag)
        conditions.append(Question.id.in_(sub))
    if company:
        sub = (
            select(QuestionCompany.question_id)
            .join(Company, Company.id == QuestionCompany.company_id)
            .where(Company.name == company)
        )
        conditions.append(Question.id.in_(sub))
    if kind:
        conditions.append(Question.kind == kind)
    if track:
        conditions.append(Question.track == track)

    if q:
        # 检索路径：Meili 决定命中与排序；DB 提供完整数据。track/company 筛选在 DB 侧二次过滤。
        ids, total = await _search_ids(indexer, q, limit)
        if not ids:
            return {"total": 0, "items": []}
        query = select(Question).where(Question.id.in_(ids), *conditions).options(*_EAGER)
        by_id = {row.id: row for row in (await session.scalars(query)).all()}
        items = [by_id[question_id] for question_id in ids if question_id in by_id]
        return {"total": len(items), "items": [_question_out(question) for question in items]}

    total = await session.scalar(select(func.count()).select_from(Question).where(*conditions))
    rows = (
        await session.scalars(
            select(Question).where(*conditions).order_by(Question.id).limit(limit).offset(offset).options(*_EAGER)
        )
    ).all()
    return {"total": total or 0, "items": [_question_out(question) for question in rows]}


async def _search_ids(indexer: MeiliIndexer, q: str, limit: int) -> tuple[list[int], int]:
    result = await indexer.search(QUESTIONS_INDEX, q=q, limit=limit)
    hits = result.get("hits", [])
    return [int(hit["id"]) for hit in hits], int(result.get("estimatedTotalHits") or len(hits))


@router.get("/stats")
async def question_stats(session: AsyncSession = Depends(get_db_session)) -> dict[str, Any]:
    """facet 计数：驱动题库页 track/kind/标签上的数量徽章。"""
    total = await session.scalar(select(func.count()).select_from(Question))
    by_track = (
        await session.execute(
            select(func.coalesce(Question.track, "未分类"), func.count()).group_by(Question.track)
        )
    ).all()
    by_kind = (
        await session.execute(select(Question.kind, func.count()).group_by(Question.kind))
    ).all()
    by_tag = (
        await session.execute(
            select(Tag.name, func.count(QuestionTag.question_id))
            .join(QuestionTag, QuestionTag.tag_id == Tag.id)
            .group_by(Tag.name)
            .order_by(func.count(QuestionTag.question_id).desc())
            .limit(24)
        )
    ).all()
    return {
        "total": total or 0,
        "by_track": {name: count for name, count in by_track},
        "by_kind": {name: count for name, count in by_kind},
        "by_tag": {name: count for name, count in by_tag},
    }


@router.get("/{question_id}")
async def get_question(
    question_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    question = (
        await session.scalars(select(Question).where(Question.id == question_id).options(*_EAGER))
    ).first()
    if question is None:
        raise NotFound(f"题目不存在: {question_id}")
    return _question_out(question)
