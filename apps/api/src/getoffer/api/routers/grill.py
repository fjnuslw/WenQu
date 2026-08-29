"""项目拷打 API（G1，spec F4 / research/06）：备课触发与查询。"""

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from getoffer.api.deps import get_db_session, get_settings
from getoffer.config import Settings
from getoffer.errors import NotFound, ValidationFailed
from getoffer.models import Project, RepoArtifact

router = APIRouter(prefix="/api/grill", tags=["grill"])

MAX_ZIP_BYTES = 50 * 1024 * 1024


@router.post("/projects")
async def create_project(
    file: UploadFile | None = File(None, description="项目源码 zip（与 local_path 二选一）"),
    name: str = Form(""),
    local_path: str = Form("", description="本地项目目录绝对路径（本地部署推荐方式，原位读取零拷贝）"),
    resume_id: int | None = Form(None),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """备课（异步）：立即返回 project_id，后台执行，前端轮询 GET /projects/{id} 的 status。

    大仓库备课分钟级（weixin 实测 3-4 分钟），同步阻塞会让页面像卡死——异步化 + 分步进度。
    """
    from getoffer.grill.prep import prepare_project_async

    resolved_name = name.strip() or (Path(local_path.strip()).name if local_path.strip() else "")
    if not resolved_name:
        raise ValidationFailed("需要项目名，或提供 local_path（自动取目录名）")
    if "/" in resolved_name or "\\" in resolved_name or resolved_name.startswith("."):
        raise ValidationFailed("项目名不能包含路径分隔符或以 . 开头")

    zip_bytes: bytes | None = None
    if file is not None and file.filename:
        raw = await file.read()
        if len(raw) > MAX_ZIP_BYTES:
            raise ValidationFailed(f"zip 超过 {MAX_ZIP_BYTES // (1024 * 1024)}MB 上限")
        if not raw.startswith(b"PK"):
            raise ValidationFailed("仅支持 zip 包")
        zip_bytes = raw
    if zip_bytes is None and not local_path.strip():
        raise ValidationFailed("需要 zip 文件或 local_path 目录路径之一")

    project_id = await prepare_project_async(
        zip_bytes=zip_bytes,
        local_path=local_path.strip() or None,
        name=resolved_name,
        settings=settings,
        resume_id=resume_id,
    )
    return {"project_id": project_id, "status": "preparing"}


def _project_out(project: Project, artifacts: list[RepoArtifact]) -> dict[str, Any] | None:
    by_kind = {artifact.kind: artifact.meta for artifact in artifacts}
    if "briefing" not in by_kind:
        return None
    return {
        "project_id": project.id,
        "name": project.name,
        "repo_root": project.repo_path,
        "resume_used": bool(by_kind.get("claims")),
        "file_count": len((by_kind.get("tree") or {}).get("files") or []),
        "language_mix": (by_kind.get("tree") or {}).get("language_mix") or {},
        "briefing": by_kind["briefing"],
        "claim_checks": by_kind.get("claims") or [],
    }


@router.get("/projects")
async def list_projects(session: AsyncSession = Depends(get_db_session)) -> dict[str, Any]:
    """项目列表（管理板块）：状态/规模/时间/备课摘要——归位到 /grilling 页的项目卡片。"""
    rows = (await session.scalars(select(Project).order_by(Project.id.desc()).limit(20))).all()
    items: list[dict[str, Any]] = []
    for row in rows:
        meta = row.meta or {}
        briefing_meta = await session.scalar(
            select(RepoArtifact.meta).where(
                RepoArtifact.project_id == row.id, RepoArtifact.kind == "briefing"
            )
        )
        tree_meta = await session.scalar(
            select(RepoArtifact.meta).where(
                RepoArtifact.project_id == row.id, RepoArtifact.kind == "tree"
            )
        )
        status = str(meta.get("status") or ("ready" if briefing_meta else "preparing"))
        overview = ""
        module_count = 0
        if isinstance(briefing_meta, dict):
            overview = str(briefing_meta.get("overview") or "")[:160]
            module_count = len(briefing_meta.get("modules") or [])
        items.append(
            {
                "id": row.id,
                "name": row.name,
                "status": status,
                "error": meta.get("error"),
                "file_count": len((tree_meta or {}).get("files") or []) if isinstance(tree_meta, dict) else 0,
                "module_count": module_count,
                "overview": overview,
                "in_projects_dir": settings_projects_dir() in Path(row.repo_path).parents,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )
    return {"items": items}


def settings_projects_dir() -> Path:
    from getoffer.config import load_settings

    return load_settings().projects_dir


@router.delete("/projects/{project_id}")
async def delete_project(
    project_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """删除项目：库行 + 备课产物 + zip 解压目录（local_path 原位项目只删库记录不动源目录）。"""
    import shutil

    project = await session.get(Project, project_id)
    if project is None:
        raise NotFound(f"项目不存在: {project_id}")
    await session.execute(delete(RepoArtifact).where(RepoArtifact.project_id == project_id))
    await session.delete(project)
    await session.commit()
    removed_dir = False
    repo_path = Path(project.repo_path)
    if repo_path.is_dir() and settings_projects_dir() in repo_path.parents:
        shutil.rmtree(repo_path, ignore_errors=True)
        removed_dir = True
    return {"deleted": project_id, "dir_removed": removed_dir}


@router.get("/projects/{project_id}")
async def get_project(
    project_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """详情：备课未完成时返回 status/step/progress（供前端轮询），而非 404。"""
    project = await session.get(Project, project_id)
    if project is None:
        raise NotFound(f"项目不存在: {project_id}")
    artifacts = (
        await session.scalars(select(RepoArtifact).where(RepoArtifact.project_id == project_id))
    ).all()
    payload = _project_out(project, list(artifacts))
    if payload is None:
        meta = project.meta or {}
        return {
            "project_id": project_id,
            "name": project.name,
            "status": str(meta.get("status") or "preparing"),
            "step": str(meta.get("step") or ""),
            "progress": int(meta.get("progress") or 0),
            "error": meta.get("error"),
        }
    payload["status"] = "ready"
    return payload


@router.get("/projects/{project_id}/tree")
async def project_tree(
    project_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """拷打侧栏的文件树（与 agents 工具面同源的排除规则）。"""
    project = await session.get(Project, project_id)
    if project is None:
        raise NotFound(f"项目不存在: {project_id}")
    files = list_files_tree(Path(project.repo_path))
    return {"repo_root": project.repo_path, "files": files}


@router.get("/projects/{project_id}/file")
async def project_file(
    project_id: int,
    path: str,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """读项目内单个文件（路径监狱 + 128KB 截断），带行号返回。"""
    project = await session.get(Project, project_id)
    if project is None:
        raise NotFound(f"项目不存在: {project_id}")
    root = Path(project.repo_path).resolve()
    target = (root / path).resolve()
    if target != root and not str(target).startswith(str(root) + os.sep):
        raise ValidationFailed(f"路径越界: {path}")
    if not target.is_file():
        raise NotFound(f"文件不存在: {path}")
    text = target.read_text(encoding="utf-8", errors="replace")[: (128 * 1024)]
    lines = text.split("\n")
    return {"path": path, "total_lines": len(lines), "lines": lines}


# 与 agents 工具面（grill-repo.ts）同源的排除规则，避免侧栏出现工具看不到的文件
_TREE_EXCLUDE_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", "out", ".next",
    "miniprogram_npm", "uni_modules", "unpackage", "coverage", ".idea", ".vscode",
}
_TREE_MAX_ENTRIES = 600


def list_files_tree(root: Path) -> list[str]:
    """BFS 收集相对路径（目录以 / 结尾），封顶防超大仓库。"""
    out: list[str] = []
    queue: list[tuple[Path, str]] = [(root, "")]
    while queue and len(out) < _TREE_MAX_ENTRIES:
        current, prefix = queue.pop(0)
        try:
            entries = sorted(current.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except OSError:
            continue
        for entry in entries:
            if len(out) >= _TREE_MAX_ENTRIES:
                break
            rel = f"{prefix}{entry.name}"
            if entry.is_dir():
                if entry.name in _TREE_EXCLUDE_DIRS:
                    continue
                out.append(f"{rel}/")
                queue.append((entry, f"{rel}/"))
            else:
                out.append(rel)
    return out
