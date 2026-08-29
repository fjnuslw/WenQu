"""G1 项目拷打：备课流水线（research/06 §3）。

zip 上传 → 解压（Zip Slip 防护）→ 噪声过滤 → 文件树+重要度 → LLM 分批备课
（模块/职责/技术点/三类拷打题）→（可选）简历声明对照 → 注水疑点清单。
产物落 Project + RepoArtifact（分步 checkpoint，spec §7）。
"""

import io
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from getoffer.config import Settings
from getoffer.errors import ValidationFailed
from getoffer.llm.gateway import LLMGateway
from getoffer.models import Project, RepoArtifact, Resume, ResumeClaim

# 噪声过滤（gitingest/repomix 思路，research/03 §3.1）：目录名/扩展名/大小三道闸
EXCLUDE_DIRS = {
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__",
    "dist", "build", "out", "target", ".next", ".turbo", "coverage",
    ".idea", ".vscode", "assets", "img", "images", "fonts",
}
TEXT_SUFFIXES = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts",
    ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini",
    ".sql", ".sh", ".ps1", ".bat", ".html", ".css", ".scss", ".vue", ".svelte",
    ".go", ".rs", ".java", ".kt", ".c", ".h", ".cpp", ".hpp", ".cs", ".rb", ".php", ".swift",
    "Dockerfile", ".dockerignore", ".gitignore", ".env.example",
}
MAX_FILE_BYTES = 256 * 1024  # 单文件读入上限（大文件多为生成物/数据）
MAX_FILES = 400
MAX_TOTAL_CHARS = 400_000  # 备课输入预算（分批后仍然封顶）


@dataclass
class CollectedFile:
    rel_path: str
    text: str
    lines: int
    importance: int  # 越大越先被备课


@dataclass
class RepoSnapshot:
    files: list[CollectedFile] = field(default_factory=list)
    skipped_dirs: list[str] = field(default_factory=list)
    total_files_on_disk: int = 0

    def tree_text(self, limit: int = 120) -> str:
        lines = [f"{f.rel_path} ({f.lines} 行)" for f in self.files[:limit]]
        if len(self.files) > limit:
            lines.append(f"… 共 {len(self.files)} 个文件")
        return "\n".join(lines)

    def language_mix(self) -> dict[str, int]:
        mix: dict[str, int] = {}
        for f in self.files:
            suffix = PurePosixPath(f.rel_path).suffix.lstrip(".") or "other"
            mix[suffix] = mix.get(suffix, 0) + f.lines
        return dict(sorted(mix.items(), key=lambda kv: -kv[1])[:8])


def extract_zip_safely(data: bytes, target: Path) -> tuple[int, list[str]]:
    """解压 + Zip Slip 防护 + 噪声过滤（解压阶段就不落噪声文件）。返回 (落盘文件数, 跳过目录)。"""
    target.mkdir(parents=True, exist_ok=True)
    skipped: set[str] = set()
    written = 0
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValidationFailed(f"zip 包损坏: {exc}") from exc
    for info in archive.infolist():
        if info.is_dir():
            continue
        name = info.filename
        # 绝对路径 / 盘符 / .. 一律拒绝（Zip Slip）
        pure = PurePosixPath(name.replace("\\", "/"))
        if pure.is_absolute() or ".." in pure.parts or name.startswith(("/", "\\")) or ":" in name.split("/")[0]:
            raise ValidationFailed(f"zip 内含非法路径（疑似 Zip Slip）: {name}")
        parts = pure.parts
        if any(part in EXCLUDE_DIRS for part in parts[:-1]):
            skipped.add(parts[next(i for i, p in enumerate(parts) if p in EXCLUDE_DIRS)])
            continue
        dest = target.joinpath(*parts)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(archive.read(info))
        written += 1
    return written, sorted(skipped)


def collect_files(root: Path) -> RepoSnapshot:
    """收集文本文件并按重要度排序：README > 入口/配置 > 更大的源码文件。"""
    snapshot = RepoSnapshot()
    all_paths = [p for p in root.rglob("*") if p.is_file()]
    snapshot.total_files_on_disk = len(all_paths)
    candidates: list[tuple[int, Path]] = []
    for path in all_paths:
        rel = path.relative_to(root).as_posix()
        parts = PurePosixPath(rel).parts
        if any(part in EXCLUDE_DIRS for part in parts[:-1]):
            continue
        suffix = path.suffix.lower()
        base = path.name.lower()
        is_text = suffix in TEXT_SUFFIXES or base in {"dockerfile", "makefile", "license"} or base.startswith(".env")
        if not is_text:
            continue
        if path.stat().st_size > MAX_FILE_BYTES:
            continue
        name = path.name.lower()
        if name == "readme.md" or name.startswith("readme"):
            importance = 1000
        elif name in {"main.py", "app.py", "server.ts", "index.ts", "main.ts", "__init__.py", "package.json", "pyproject.toml"} or "main" in name:
            importance = 800
        elif parts[0] in {"src", "apps", "lib", "server", "api"} :
            importance = 500 + min(path.stat().st_size // 2000, 300)
        else:
            importance = 100 + min(path.stat().st_size // 2000, 300)
        candidates.append((importance, path))
    candidates.sort(key=lambda pair: (-pair[0], pair[1].as_posix()))
    total_chars = 0
    for importance, path in candidates:
        if len(snapshot.files) >= MAX_FILES:
            break
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if total_chars + len(text) > MAX_TOTAL_CHARS:
            text = text[: max(0, MAX_TOTAL_CHARS - total_chars)]
            if len(text) < 200:
                break
        total_chars += len(text)
        snapshot.files.append(
            CollectedFile(
                rel_path=path.relative_to(root).as_posix(),
                text=text,
                lines=text.count("\n") + 1,
                importance=importance,
            )
        )
        if total_chars >= MAX_TOTAL_CHARS:
            break
    return snapshot


class ModuleBriefing(BaseModel):
    files: list[str] = Field(default_factory=list, max_length=8)
    purpose: str = Field(max_length=300)
    tech_points: list[str] = Field(default_factory=list, max_length=8)
    exam_tags: list[str] = Field(default_factory=list, max_length=4)
    detail_questions: list[str] = Field(default_factory=list, max_length=4)
    alternative_question: str | None = Field(default=None, max_length=300)
    missing_question: str | None = Field(default=None, max_length=300)


class RepoBriefing(BaseModel):
    overview: str = Field(max_length=900)
    stack_summary: str = Field(max_length=400)
    modules: list[ModuleBriefing] = Field(default_factory=list, max_length=16)
    not_understood: list[str] = Field(default_factory=list, max_length=8)


BRIEFING_SYSTEM = """你是资深工程师，正在给一个代码仓库"备课"——目标是你之后要扮演面试官，针对候选人在这个仓库里的实现做深挖拷打。
输入是仓库的文件树（含行数）与若干文件内容（按重要度排序，可能截断）。
任务：
1. overview：项目是什么、解决什么问题、整体架构 3-6 句。
2. stack_summary：技术栈一句话清单。
3. modules：模块清单（4-12 个）。每个模块：
   - files：涉及的文件（相对路径）
   - purpose：职责一句话
   - tech_points：值得考的技术点（具体到库/模式/算法，如 "Hono SSE 流式"、"SQLAlchemy async session"）
   - exam_tags：从词表选 0-4 个：{TAGS}
   - detail_questions：2-4 个"实现细节拷打题"（答案必须能从代码里找到，如 "X 的 Y 是怎么实现的？"）
   - alternative_question：1 个"方案对比题"（"为什么用 A 而不用 <合理替代>？"——替代方案要真实合理）
   - missing_question：1 个"缺失质询题"（常见工程缺口：错误处理/并发/测试/降级/安全，只问代码里确实没做的）
4. not_understood：内容不足无法判断的文件/区域。

规则：忠于代码，不编造不存在的东西；missing_question 必须先确认代码里真的没做。"""


class ClaimCheck(BaseModel):
    """简历声明 × 代码证据 的对照结论。"""

    claim: str = Field(max_length=400)
    status: str = Field(pattern="^(supported|suspicious|not_found)$")
    evidence: str | None = Field(default=None, max_length=400)
    probe_question: str = Field(max_length=300)


class ClaimCheckBatch(BaseModel):
    checks: list[ClaimCheck] = Field(default_factory=list, max_length=12)


CLAIM_SYSTEM = """你是代码审查员。输入：候选人简历中的项目"声明"列表 + 仓库备课简报。
对每条声明判定：
- supported：备课简报/代码树中能找到对应实现的痕迹（evidence 引用模块/文件）
- suspicious：声明了量化指标或复杂机制，但代码痕迹与声明的规模不匹配（evidence 说明差距）
- not_found：简报中找不到任何对应实现
并给 probe_question：一个面试官当场的质证问题（如果 supported，问实现细节；否则问"你说的 X 在哪？"）。
宁缺毋滥，不确定时用 supported 并在 probe_question 里问细节。"""


async def run_briefing(
    snapshot: RepoSnapshot, gateway: LLMGateway, *, tag_families: list[str]
) -> RepoBriefing:
    from getoffer.ingest.qa_extract import TAG_FAMILIES as _default_tags

    tags = tag_families or _default_tags
    # 分批：每批 3 个文件的内容（控制单次输入），文件树总是全量给
    batches: list[str] = []
    current: list[str] = []
    current_len = 0
    for f in snapshot.files:
        block = f"### 文件 {f.rel_path}（{f.lines} 行）\n```\n{f.text[:6000]}\n```"
        if current_len + len(block) > 24000 and current:
            batches.append("\n\n".join(current))
            current, current_len = [], 0
        current.append(block)
        current_len += len(block)
    if current:
        batches.append("\n\n".join(current))
    batches = batches[:6]  # 备课预算封顶（超大仓库只备最重要的部分，not_understood 里说明）

    briefings: list[RepoBriefing] = []
    for batch in batches:
        content = (
            f"## 文件树（按重要度）\n{snapshot.tree_text()}\n\n"
            f"## 语言构成（后缀: 行数）\n{snapshot.language_mix()}\n\n"
            f"## 文件内容（本批 {len(batch)} 字符）\n{batch}"
        )
        system = BRIEFING_SYSTEM.replace("{TAGS}", "、".join(tags))
        briefings.append(
            await gateway.complete_structured(
                [{"role": "user", "content": content}],
                RepoBriefing,
                system=system,
                purpose="grill.briefing",
                max_tokens=8192,
            )
        )
    if not briefings:
        raise ValidationFailed("仓库为空或没有可读的文本文件，无法备课")
    # 聚合：overview/stack 用第一批（最重要文件），modules 合并去重
    merged_modules: list[ModuleBriefing] = []
    seen_files: set[str] = set()
    for briefing in briefings:
        for module in briefing.modules:
            key = ",".join(module.files)
            if key and key not in seen_files:
                seen_files.add(key)
                merged_modules.append(module)
    return RepoBriefing(
        overview=briefings[0].overview,
        stack_summary=briefings[0].stack_summary,
        modules=merged_modules[:16],
        not_understood=[n for b in briefings for n in b.not_understood][:8],
    )


async def check_claims(
    claims: list[str], briefing: RepoBriefing, gateway: LLMGateway
) -> list[ClaimCheck]:
    if not claims:
        return []
    batch = await gateway.complete_structured(
        [
            {
                "role": "user",
                "content": (
                    "## 候选人简历声明\n"
                    + "\n".join(f"{i+1}. {c}" for i, c in enumerate(claims[:12]))
                    + "\n\n## 仓库备课简报\n"
                    + briefing.model_dump_json()
                ),
            }
        ],
        ClaimCheckBatch,
        system=CLAIM_SYSTEM,
        purpose="grill.claim_check",
    )
    return batch.checks


async def prepare_project(
    *,
    zip_bytes: bytes,
    name: str,
    session: AsyncSession,
    gateway: LLMGateway,
    settings: Settings,
    resume_id: int | None = None,
) -> dict[str, Any]:
    """zip → 解压 → 收集 → 备课 →（可选）声明对照 → 落库。返回给前端/agents 的完整备课包。"""
    project_root = settings.projects_dir / name.replace("/", "_")
    if project_root.exists():
        raise ValidationFailed(f"项目目录已存在: {name}（请换名或先删除）")
    written, skipped = extract_zip_safely(zip_bytes, project_root)
    if written == 0:
        raise ValidationFailed("zip 内没有有效文件（全部被噪声过滤或为空包）")
    snapshot = collect_files(project_root)

    briefing = await run_briefing(snapshot, gateway, tag_families=[])

    claims: list[str] = []
    resume_used = False
    if resume_id is not None:
        resume = await session.get(Resume, resume_id)
        if resume is None:
            raise ValidationFailed(f"简历不存在: {resume_id}")
        claim_rows = (
            (await session.scalars(select(ResumeClaim).where(ResumeClaim.resume_id == resume_id))).all()
        )
        claims = [row.claim_text for row in claim_rows][:12]
        resume_used = True
    claim_checks: list[ClaimCheck] = []
    if claims:
        claim_checks = await check_claims(claims, briefing, gateway)

    project = Project(name=name, repo_path=str(project_root), meta={"skipped_dirs": skipped})
    session.add(project)
    await session.flush()
    for kind, payload in (
        ("tree", {"files": [f.rel_path for f in snapshot.files], "language_mix": snapshot.language_mix()}),
        ("briefing", briefing.model_dump()),
        ("claims", [c.model_dump() for c in claim_checks]),
    ):
        session.add(RepoArtifact(project_id=project.id, kind=kind, meta=payload))
    await session.commit()

    return {
        "project_id": project.id,
        "name": name,
        "repo_root": str(project_root),
        "resume_used": resume_used,
        "file_count": len(snapshot.files),
        "language_mix": snapshot.language_mix(),
        "briefing": briefing.model_dump(),
        "claim_checks": [c.model_dump() for c in claim_checks],
    }
