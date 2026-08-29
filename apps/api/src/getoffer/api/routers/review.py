"""失分点复习队列（F6 · L1 第一块）：SM-2 间隔重复。

评分报告的 weaknesses 自动回流为本队列条目（sessions.generate_report 内联）；
本路由负责到期清单与评分推进。SM-2 参数为经典 SuperMemo-2 算法：
q<3 重学（间隔归 1 天、repetitions 归零、lapses+1）；q>=3 按阶梯放大间隔并调整 ease。
"""

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from getoffer.api.deps import get_db_session
from getoffer.errors import NotFound
from getoffer.models import ReviewItem

router = APIRouter(prefix="/api/review", tags=["review"])

GRADE_MAP = {"forgot": 1, "fuzzy": 3, "mastered": 5}  # UI 三键 → SM-2 质量


def apply_sm2(item: ReviewItem, quality: int, *, today: date | None = None) -> None:
    """经典 SM-2：原地更新调度字段。quality ∈ [1,5]。"""
    today = today or date.today()
    if quality < 3:
        item.repetitions = 0
        item.interval_days = 1
        item.lapses += 1
    else:
        item.repetitions += 1
        if item.repetitions == 1:
            item.interval_days = 1
        elif item.repetitions == 2:
            item.interval_days = 6
        else:
            item.interval_days = max(1, round(item.interval_days * item.ease))
        item.ease = max(1.3, item.ease + 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    item.last_grade = quality
    item.due_on = today + timedelta(days=item.interval_days)


def _item_out(item: ReviewItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "source": item.source,
        "source_ref": item.source_ref,
        "question_text": item.question_text,
        "weakness": item.weakness,
        "tag": item.tag,
        "ease": round(item.ease, 2),
        "interval_days": item.interval_days,
        "repetitions": item.repetitions,
        "lapses": item.lapses,
        "due_on": item.due_on.isoformat(),
        "overdue": item.due_on <= date.today(),
    }


class GradeRequest(BaseModel):
    grade: str = Field(pattern="^(forgot|fuzzy|mastered)$")


@router.get("")
async def list_review(
    scope: str = "due",
    limit: int = 50,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """scope=due（含逾期与今日到期）| all。"""
    limit = min(max(limit, 1), 100)
    conditions = []
    if scope == "due":
        conditions.append(ReviewItem.due_on <= date.today())
    total = await session.scalar(select(func.count()).select_from(ReviewItem).where(*conditions))
    rows = (
        (
            await session.scalars(
                select(ReviewItem)
                .where(*conditions)
                .order_by(ReviewItem.due_on, ReviewItem.id)
                .limit(limit)
            )
        )
        .all()
    )
    return {"total": total or 0, "items": [_item_out(item) for item in rows]}


@router.post("/{item_id}/grade")
async def grade_review(
    item_id: int,
    request: GradeRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    item = await session.get(ReviewItem, item_id)
    if item is None:
        raise NotFound(f"复习条目不存在: {item_id}")
    apply_sm2(item, GRADE_MAP[request.grade])
    await session.commit()
    return _item_out(item)
