"""项目拷打 API（G1，spec F4 / research/06）：备课触发与查询。"""

from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from getoffer.api.deps import get_db_session, get_gateway, get_settings
from getoffer.config import Settings
from getoffer.errors import NotFound, ValidationFailed
from getoffer.grill.prep import prepare_project
from getoffer.llm.gateway import LLMGateway
from getoffer.models import Project, RepoArtifact

router = APIRouter(prefix="/api/grill", tags=["grill"])

MAX_ZIP_BYTES = 50 * 1024 * 1024


@router.post("/projects")
async def create_project(
    file: UploadFile = File(..., description="项目源码 zip（不含 node_modules 等构建产物）"),
    name: str = Form(..., min_length=1, max_length=64),
    resume_id: int | None = Form(None),
    session: AsyncSession = Depends(get_db_session),
    gateway: LLMGateway = Depends(get_gateway),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """zip 上传 → 解压 → LLM 备课（模块/考点/拷打题）→（可选）简历声明对照。

    备课内联执行（与导入/采集一致）；大仓库 1-3 分钟，切 arq 队列时语义不变。
    """
    raw = await file.read()
    if len(raw) > MAX_ZIP_BYTES:
        raise ValidationFailed(f"zip 超过 {MAX_ZIP_BYTES // (1024 * 1024)}MB 上限")
    if not raw.startswith(b"PK"):
        raise ValidationFailed("仅支持 zip 包")
    if "/" in name or "\\" in name or name.startswith("."):
        raise ValidationFailed("项目名不能包含路径分隔符或以 . 开头")

    return await prepare_project(
        zip_bytes=raw,
        name=name,
        session=session,
        gateway=gateway,
        settings=settings,
        resume_id=resume_id,
    )


def _project_out(project: Project, artifacts: list[RepoArtifact]) -> dict[str, Any] | None:
    by_kind = {artifact.kind: artifact.meta for artifact in artifacts}
    if "briefing" not in by_kind:
        return None
    return {
        "project_id": project.id,
        "name": project.name,
        "file_count": len((by_kind.get("tree") or {}).get("files") or []),
        "language_mix": (by_kind.get("tree") or {}).get("language_mix") or {},
        "briefing": by_kind["briefing"],
        "claim_checks": by_kind.get("claims") or [],
    }


@router.get("/projects")
async def list_projects(session: AsyncSession = Depends(get_db_session)) -> dict[str, Any]:
    rows = (await session.scalars(select(Project).order_by(Project.id.desc()).limit(20))).all()
    return {"items": [{"id": row.id, "name": row.name} for row in rows]}


@router.get("/projects/{project_id}")
async def get_project(
    project_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    project = await session.get(Project, project_id)
    if project is None:
        raise NotFound(f"项目不存在: {project_id}")
    artifacts = (
        await session.scalars(select(RepoArtifact).where(RepoArtifact.project_id == project_id))
    ).all()
    payload = _project_out(project, list(artifacts))
    if payload is None:
        raise NotFound(f"项目 {project_id} 缺少备课产物（briefing）")
    return payload
