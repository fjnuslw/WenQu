"""面经读取 API（F1 查询侧）。"""

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from getoffer.api.deps import get_db_session
from getoffer.errors import NotFound
from getoffer.models import Company, Experience, ExperienceItem

router = APIRouter(prefix="/api/experiences", tags=["experiences"])

_EAGER = (
    selectinload(Experience.company),
    selectinload(Experience.items),
)


def _experience_out(experience: Experience) -> dict[str, Any]:
    return {
        "id": experience.id,
        "company": experience.company.name if experience.company else None,
        "role": experience.role,
        "round": experience.round,
        "occurred_on": experience.occurred_on.isoformat() if experience.occurred_on else None,
        "result": experience.result,
        "url": experience.url,
        "items": [_item_out(item) for item in experience.items],
    }


def _item_out(item: ExperienceItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "parent_id": item.parent_id,
        "order_no": item.order_no,
        "question_text": item.question_text,
        "note": item.note,
    }


@router.get("")
async def list_experiences(
    company: str | None = None,
    limit: int = 20,
    offset: int = 0,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    limit = min(max(limit, 1), 100)
    offset = max(offset, 0)
    conditions = []
    if company:
        sub = select(Company.id).where(Company.name == company)
        conditions.append(Experience.company_id.in_(sub))
    total = await session.scalar(select(func.count()).select_from(Experience).where(*conditions))
    rows = (
        await session.scalars(
            select(Experience).where(*conditions).order_by(Experience.id.desc()).limit(limit).offset(offset).options(*_EAGER)
        )
    ).all()
    return {"total": total or 0, "items": [_experience_out(experience) for experience in rows]}


@router.get("/{experience_id}")
async def get_experience(
    experience_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    experience = (
        await session.scalars(select(Experience).where(Experience.id == experience_id).options(*_EAGER))
    ).first()
    if experience is None:
        raise NotFound(f"面经不存在: {experience_id}")
    return _experience_out(experience)
