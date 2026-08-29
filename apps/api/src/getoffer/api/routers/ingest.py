"""摄入管道 API：源注册表与导入触发。

导入在 P0 阶段内联执行（dev 友好）；进入 K1 的批量采集时切换为 arq 队列任务，
端点语义不变（提交即返回任务号）。"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from getoffer.api.deps import get_db_session, get_gateway, get_indexer, get_settings
from getoffer.ingest.importers.markdown_repo import import_markdown_repo
from getoffer.ingest.sources import SOURCES
from getoffer.models import Question, QuestionCompany
from getoffer.search.meili import QUESTIONS_INDEX, MeiliIndexer, question_document

router = APIRouter(prefix="/api/ingest", tags=["ingest"])


class SourceOut(BaseModel):
    slug: str
    name: str
    license: str
    allowed_use: str
    repo_url: str
    notes: str


@router.get("/sources", response_model=list[SourceOut])
async def list_sources() -> list[SourceOut]:
    return [
        SourceOut(
            slug=spec.slug,
            name=spec.name,
            license=spec.license,
            allowed_use=spec.allowed_use.value,
            repo_url=spec.repo_url,
            notes=spec.notes,
        )
        for spec in SOURCES.values()
    ]


@router.post("/sources/{slug}/run")
async def run_import(
    slug: str,
    max_files: int | None = None,
    session: AsyncSession = Depends(get_db_session),
    gateway=Depends(get_gateway),
    settings=Depends(get_settings),
    indexer: MeiliIndexer = Depends(get_indexer),
) -> dict:
    # AppError（NotFound/LicenseViolation/UpstreamError 等）由全局 handler 转换为 problem 响应。
    # max_files 用于大仓库分批增量导入（推理模型单批较慢，避免长事务被客户端超时切断）。
    bounded = max(1, min(max_files, 200)) if max_files else None
    report = await import_markdown_repo(
        slug,
        session=session,
        gateway=gateway,
        settings=settings,
        indexer=indexer,
        max_files=bounded,
    )
    return {
        "slug": report.slug,
        "files_seen": report.files_seen,
        "files_remaining": report.files_remaining,
        "sections_seen": report.sections_seen,
        "extracted": report.extracted,
        "inserted": report.inserted,
        "duplicates": report.duplicates,
    }


@router.post("/reindex")
async def reindex(
    session: AsyncSession = Depends(get_db_session),
    indexer: MeiliIndexer = Depends(get_indexer),
) -> dict:
    """全量重建题目检索索引（DB → Meili，幂等）。"""
    rows = (
        await session.scalars(
            select(Question).options(
                selectinload(Question.tags),
                selectinload(Question.company_stats).selectinload(QuestionCompany.company),
            )
        )
    ).all()
    documents = [question_document(row) for row in rows]
    await indexer.ensure_index(QUESTIONS_INDEX)
    await indexer.upsert_documents(QUESTIONS_INDEX, documents, wait=True)
    return {"indexed": len(documents)}


@router.post("/seed-companies")
async def seed_companies_endpoint(
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    from getoffer.ingest.company_tagging import seed_companies

    seeded = await seed_companies(session)
    await session.commit()
    return {"seeded": seeded}


@router.post("/classify-companies")
async def classify_companies(
    limit: int = 20,
    session: AsyncSession = Depends(get_db_session),
    gateway=Depends(get_gateway),
) -> dict:
    """为无公司标注的题目做一轮厂商推断（批量收敛由调用方控制）。"""
    from getoffer.ingest.company_tagging import classify_unclassified_questions

    return await classify_unclassified_questions(session, gateway, limit=min(max(limit, 1), 40))
