"""厂商列表 API：题库页公司 logo 横条的数据源。"""

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from getoffer.api.deps import get_db_session
from getoffer.models import Company, QuestionCompany

router = APIRouter(prefix="/api/companies", tags=["companies"])


@router.get("")
async def list_companies(session: AsyncSession = Depends(get_db_session)) -> dict[str, Any]:
    counts = dict(
        (await session.execute(
            select(QuestionCompany.company_id, func.count()).group_by(QuestionCompany.company_id)
        )).all()
    )
    rows = (await session.scalars(select(Company).order_by(Company.id))).all()
    items = [
        {
            "id": company.id,
            "name": company.name,
            "logo": company.logo,
            "question_count": counts.get(company.id, 0),
        }
        for company in rows
    ]
    # 有题的厂商排前面，便于 logo 横条优先展示有效项
    items.sort(key=lambda item: (-item["question_count"], item["id"]))
    return {"total": len(items), "items": items}
