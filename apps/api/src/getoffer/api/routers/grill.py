"""项目拷打 API（G1）：备课触发与查询。"""

import os
from pathlib import Path, PurePosixPath
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from getoffer.api.deps import get_db_session, get_embedding_gateway, get_settings
from getoffer.config import Settings
from getoffer.errors import NotFound, ValidationFailed
from getoffer.grill.embeddings import EmbeddingGateway
from getoffer.grill.retrieval import semantic_search
from getoffer.grill.source import derive_repository_name, validate_public_git_url
from getoffer.models import Embedding, Project, RepoArtifact, RepoChunk

router = APIRouter(prefix="/api/grill", tags=["grill"])

MAX_ZIP_BYTES = 50 * 1024 * 1024


class SemanticSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=6, ge=1, le=12)


@router.post("/projects")
async def create_project(
    file: UploadFile | None = File(None, description="项目源码 zip（与 local_path/git_url 三选一）"),
    name: str = Form(""),
    local_path: str = Form("", description="本地项目目录绝对路径（本地部署推荐方式，原位读取零拷贝）"),
    git_url: str = Form("", description="公共 HTTPS Git URL（与 file/local_path 三选一）"),
    resume_id: int | None = Form(None),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """备课（异步）：立即返回 project_id，后台执行，前端轮询 GET /projects/{id} 的 status。

    大仓库备课分钟级（weixin 实测 3-4 分钟），同步阻塞会让页面像卡死——异步化 + 分步进度。
    """
    from getoffer.grill.prep import prepare_project_async

    local_value = local_path.strip()
    git_value = git_url.strip()
    has_upload = file is not None and bool(file.filename)
    if sum((has_upload, bool(local_value), bool(git_value))) != 1:
        raise ValidationFailed("file、local_path、git_url 必须且只能提供一个")
    if git_value:
        git_value = validate_public_git_url(git_value)
    upload_name = Path(file.filename or "").stem if has_upload else ""
    resolved_name = (
        name.strip()
        or (Path(local_value).name if local_value else "")
        or (derive_repository_name(git_value) if git_value else "")
        or upload_name
    )
    if not resolved_name:
        raise ValidationFailed("需要项目名，或提供 local_path（自动取目录名）")
    if "/" in resolved_name or "\\" in resolved_name or resolved_name.startswith("."):
        raise ValidationFailed("项目名不能包含路径分隔符或以 . 开头")

    zip_bytes: bytes | None = None
    if has_upload and file is not None:
        raw = await file.read()
        if len(raw) > MAX_ZIP_BYTES:
            raise ValidationFailed(f"zip 超过 {MAX_ZIP_BYTES // (1024 * 1024)}MB 上限")
        if not raw.startswith(b"PK"):
            raise ValidationFailed("仅支持 zip 包")
        zip_bytes = raw
    project_id = await prepare_project_async(
        zip_bytes=zip_bytes,
        local_path=local_value or None,
        git_url=git_value or None,
        name=resolved_name,
        settings=settings,
        resume_id=resume_id,
    )
    return {"project_id": project_id, "status": "preparing"}


def _project_out(project: Project, artifacts: list[RepoArtifact]) -> dict[str, Any] | None:
    by_kind = {artifact.kind: artifact.meta for artifact in artifacts}
    if "briefing" not in by_kind:
        return None
    repomap = by_kind.get("repomap") or {}
    semantic = by_kind.get("semantic_index") or {"status": "missing"}
    ownership = by_kind.get("ownership") or {"available": False, "reason": "missing"}
    return {
        "project_id": project.id,
        "name": project.name,
        "repo_root": project.repo_path,
        "resume_used": bool(by_kind.get("claims")),
        "file_count": len((by_kind.get("tree") or {}).get("files") or []),
        "language_mix": (by_kind.get("tree") or {}).get("language_mix") or {},
        "briefing": by_kind["briefing"],
        "claim_checks": by_kind.get("claims") or [],
        "source": (project.meta or {}).get("source") or {"kind": "legacy"},
        "capabilities": by_kind.get("capabilities")
        or {"repo_map": False, "semantic_search": False, "git_ownership": False},
        "repomap_summary": {
            "parsed_files": repomap.get("parsed_files", 0),
            "supported_files": repomap.get("supported_files", 0),
            "coverage": repomap.get("coverage", 0),
            "edge_count": repomap.get("edge_count", 0),
            "failure_count": len(repomap.get("failures") or {}),
        },
        "semantic_index": semantic,
        "ownership_summary": _ownership_summary(ownership),
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
                "source_kind": str((meta.get("source") or {}).get("kind") or "legacy"),
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
    project = await session.get(Project, project_id)
    if project is None:
        raise NotFound(f"项目不存在: {project_id}")
    chunk_ids = select(RepoChunk.id).where(RepoChunk.project_id == project_id)
    await session.execute(
        delete(Embedding).where(Embedding.kind == "repo_chunk", Embedding.ref_id.in_(chunk_ids))
    )
    await session.execute(delete(RepoChunk).where(RepoChunk.project_id == project_id))
    await session.execute(delete(RepoArtifact).where(RepoArtifact.project_id == project_id))
    await session.delete(project)
    await session.commit()
    removed_dir = False
    repo_path = Path(project.repo_path)
    if repo_path.is_dir() and settings_projects_dir() in repo_path.parents:
        # 复用 Source 的已校验清理边界，并处理 Windows Git 对象的只读位。
        from getoffer.grill.source import remove_owned_repository

        remove_owned_repository(repo_path, settings_projects_dir())
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


@router.get("/projects/{project_id}/map")
async def project_repo_map(
    project_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    if await session.get(Project, project_id) is None:
        raise NotFound(f"项目不存在: {project_id}")
    artifact = await session.scalar(
        select(RepoArtifact).where(
            RepoArtifact.project_id == project_id,
            RepoArtifact.kind == "repomap",
        )
    )
    if artifact is None:
        raise NotFound(f"项目还没有 repo map: {project_id}")
    return artifact.meta


@router.post("/projects/{project_id}/search")
async def project_semantic_search(
    project_id: int,
    body: SemanticSearchRequest,
    session: AsyncSession = Depends(get_db_session),
    gateway: EmbeddingGateway = Depends(get_embedding_gateway),
) -> dict[str, Any]:
    if await session.get(Project, project_id) is None:
        raise NotFound(f"项目不存在: {project_id}")
    return await semantic_search(
        session,
        gateway,
        project_id=project_id,
        query=body.query,
        limit=body.limit,
    )


@router.get("/projects/{project_id}/ownership")
async def project_ownership(
    project_id: int,
    path: str = "",
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    if await session.get(Project, project_id) is None:
        raise NotFound(f"项目不存在: {project_id}")
    artifact = await session.scalar(
        select(RepoArtifact).where(
            RepoArtifact.project_id == project_id,
            RepoArtifact.kind == "ownership",
        )
    )
    if artifact is None:
        raise NotFound(f"项目还没有 Git 归属产物: {project_id}")
    ownership = artifact.meta or {}
    if not ownership.get("available"):
        return _ownership_summary(ownership)
    normalized_path = path.strip().replace("\\", "/")
    if normalized_path:
        pure = PurePosixPath(normalized_path)
        if pure.is_absolute() or ".." in pure.parts:
            raise ValidationFailed("ownership path 必须是项目内相对路径")
        match = next(
            (item for item in ownership.get("files") or [] if item.get("path") == normalized_path),
            None,
        )
        if match is None:
            raise NotFound(f"Git 历史中没有该文件: {normalized_path}")
        return {"available": True, "path": normalized_path, "file": match}
    return _ownership_summary(ownership)


def _ownership_summary(ownership: dict[str, Any]) -> dict[str, Any]:
    if not ownership.get("available"):
        return {"available": False, "reason": ownership.get("reason", "unknown")}
    return {
        "available": True,
        "head_commit": ownership.get("head_commit"),
        "history_scope": ownership.get("history_scope") or {},
        "contributors": [
            {
                "name": item.get("name"),
                "commits": item.get("commits", 0),
                "commit_share": item.get("commit_share", 0),
            }
            for item in (ownership.get("contributors") or [])[:10]
        ],
        "candidate": ownership.get("candidate"),
    }


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
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__",
    "dist", "build", "out", "target", ".next", ".turbo", "coverage",
    ".idea", ".vscode", ".tmp", ".ruff_cache", ".workbuddy", ".zcode",
    "miniprogram_npm", "uni_modules", "unpackage", "vendor", "Pods",
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
            is_junction = getattr(entry, "is_junction", None)
            try:
                if entry.is_symlink() or bool(is_junction and is_junction()):
                    continue
            except OSError:
                continue
            rel = f"{prefix}{entry.name}"
            if entry.is_dir():
                if entry.name in _TREE_EXCLUDE_DIRS:
                    continue
                out.append(f"{rel}/")
                queue.append((entry, f"{rel}/"))
            else:
                out.append(rel)
    return out
