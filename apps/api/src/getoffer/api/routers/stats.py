"""全局统计 API（L1 · Dashboard 完整版的数据源）。"""

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from getoffer.api.deps import get_db_session
from getoffer.models import Experience, Question, ReviewItem

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("")
async def overview(session: AsyncSession = Depends(get_db_session)) -> dict[str, Any]:
    """Dashboard 概览：题库/面经/复习队列/今日到期。"""
    questions_total = await session.scalar(select(func.count()).select_from(Question)) or 0
    questions_by_track = dict(
        (await session.execute(select(Question.track, func.count()).group_by(Question.track))).all()
    )
    questions_by_track = {key or "未分类": value for key, value in questions_by_track.items()}
    experiences_total = await session.scalar(select(func.count()).select_from(Experience)) or 0
    review_total = await session.scalar(select(func.count()).select_from(ReviewItem)) or 0
    review_due = (
        await session.scalar(
            select(func.count()).select_from(ReviewItem).where(ReviewItem.due_on <= date.today())
        )
        or 0
    )
    review_mastered = (
        await session.scalar(
            select(func.count())
            .select_from(ReviewItem)
            .where(ReviewItem.repetitions >= 2, ReviewItem.last_grade >= 4)
        )
        or 0
    )
    answered_total = (
        await session.scalar(
            select(func.count()).select_from(Question).where(Question.answer.is_not(None))
        )
        or 0
    )
    return {
        "questions": {
            "total": questions_total,
            "with_answer": answered_total,
            "by_track": dict(sorted(questions_by_track.items(), key=lambda kv: -kv[1])),
        },
        "experiences": {"total": experiences_total},
        "review": {"total": review_total, "due": review_due, "mastered": review_mastered},
    }
