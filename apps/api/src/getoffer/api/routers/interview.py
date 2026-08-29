"""模拟面试组卷 API（F3 · I1）：按公司/岗位大类/题型从题库抽题生成面试题单。

有公司筛选时按该公司出题频率降序（CodeTop 范式），否则随机；题单含参考答案要点，
供面试官 agent 判断回答质量（不直接展示给候选人）。
"""

from random import sample
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from getoffer.api.deps import get_db_session
from getoffer.errors import NotFound
from getoffer.models import Company, Question, QuestionCompany

router = APIRouter(prefix="/api/interview", tags=["interview"])

_EAGER = (
    selectinload(Question.tags),
    selectinload(Question.company_stats).selectinload(QuestionCompany.company),
)

DEFAULT_KINDS = ["knowledge", "handwritten_code", "algorithm", "scenario"]


class InterviewPlanRequest(BaseModel):
    company: str | None = None
    track: str | None = None
    kinds: list[str] = Field(default_factory=lambda: list(DEFAULT_KINDS), max_length=5)
    size: int = Field(default=8, ge=3, le=20)


class PlanQuestion(BaseModel):
    id: int
    stem: str
    kind: str
    track: str | None
    difficulty: int
    answer: str | None
    tags: list[str]
    companies: list[str]


class InterviewPlan(BaseModel):
    total_pool: int
    questions: list[PlanQuestion]


@router.post("/plan")
async def create_plan(
    request: InterviewPlanRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    conditions = []
    if request.kinds:
        conditions.append(Question.kind.in_(request.kinds))
    if request.track:
        conditions.append(Question.track == request.track)

    company: Company | None = None
    if request.company:
        company = await session.scalar(select(Company).where(Company.name == request.company))
        if company is None:
            raise NotFound(f"未知公司: {request.company}")
        conditions.append(
            Question.id.in_(
                select(QuestionCompany.question_id).where(QuestionCompany.company_id == company.id)
            )
        )

    stmt = select(Question).where(*conditions).options(*_EAGER)
    if company is not None:
        # 该公司频率降序（CodeTop 范式），随机打散并列
        stmt = (
            stmt.join(
                QuestionCompany,
                (QuestionCompany.question_id == Question.id)
                & (QuestionCompany.company_id == company.id),
            )
            .order_by(QuestionCompany.freq.desc(), func.random())
        )
    else:
        stmt = stmt.order_by(func.random())

    pool_total = await session.scalar(select(func.count()).select_from(Question).where(*conditions))
    limit = min(request.size * 3, 120)  # 先取候选池，再随机抽样到目标题数
    rows = (await session.scalars(stmt.limit(limit))).unique().all()
    picked = sample(rows, min(request.size, len(rows))) if rows else []

    return {
        "total_pool": pool_total or 0,
        "questions": [
            {
                "id": q.id,
                "stem": q.stem,
                "kind": q.kind,
                "track": q.track,
                "difficulty": q.difficulty,
                "answer": q.answer,
                "tags": [t.name for t in q.tags],
                "companies": [c.company.name for c in q.company_stats],
            }
            for q in picked
        ],
    }
