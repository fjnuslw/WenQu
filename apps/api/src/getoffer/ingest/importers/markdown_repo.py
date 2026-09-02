"""通用 markdown 题库仓库导入器（spec §3 / F1）。

流程：clone（浅）→ 文件收集（globs + 目录排除）→ markdown AST 章节切分
→ LLM 结构化抽取（license 门禁生效）→ content-hash 幂等 upsert。
产出 ImportReport，不静默吞掉任何失败。
"""

import hashlib
import os
import subprocess
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from getoffer.config import Settings
from getoffer.errors import LicenseViolation, UpstreamError
from getoffer.ingest import markdown_ast
from getoffer.ingest.markdown_ast import Section
from getoffer.ingest.qa_extract import extract_from_sections
from getoffer.ingest.sources import AllowedUse, SourceSpec, get_source
from getoffer.llm.gateway import LLMGateway
from getoffer.models import Question, Source, SourceFile, Tag
from getoffer.search.meili import QUESTIONS_INDEX, MeiliIndexer

MIN_SECTION_CHARS = 60  # 少于该长度的小节不进抽取，避免标题党碎片


def normalize_text(text: str) -> str:
    """NFKC 规范化 + 空白折叠 + 小写。字符串操作，不用正则（spec §7）。"""
    normalized = unicodedata.normalize("NFKC", text)
    return " ".join(normalized.split()).lower()


def content_hash(stem: str) -> str:
    return hashlib.sha256(normalize_text(stem).encode("utf-8")).hexdigest()


@dataclass
class ImportReport:
    slug: str
    files_seen: int = 0
    files_remaining: int = 0
    sections_seen: int = 0
    extracted: int = 0
    inserted: int = 0
    duplicates: int = 0
    skipped_sources: list[str] = field(default_factory=list)


def ensure_clone(spec: SourceSpec, repos_dir: Path, *, git_proxy: str = "") -> Path:
    target = repos_dir / spec.slug
    if target.exists() and (target / ".git").exists():
        return target  # 已克隆则复用；更新走显式 refresh 流程，不在导入路径里隐式 pull
    repos_dir.mkdir(parents=True, exist_ok=True)
    env = None
    if git_proxy:
        # 显式网络拓扑配置（GETOFFER_GIT_PROXY），不是错误兜底
        env = {**os.environ, "HTTP_PROXY": git_proxy, "HTTPS_PROXY": git_proxy}
    proc = subprocess.run(
        ["git", "clone", "--depth", "1", spec.repo_url, str(target)],
        capture_output=True,
        text=True,
        env=env,
    )
    if proc.returncode != 0:
        raise UpstreamError(f"git clone 失败: {spec.repo_url}", details={"stderr": proc.stderr[-800:]})
    return target


def collect_markdown_files(root: Path, spec: SourceSpec, *, max_files: int | None = None) -> list[Path]:
    excluded = set(spec.exclude_dirs)
    collected: dict[str, Path] = {}
    for pattern in spec.md_globs:
        for path in root.glob(pattern):
            if not path.is_file():
                continue
            parts = path.relative_to(root).parts
            if any(part in excluded for part in parts[:-1]):
                continue
            collected[str(path).lower()] = path
    files = [collected[key] for key in sorted(collected)]
    return files[:max_files] if max_files is not None else files


def sections_from_file(path: Path) -> list[Section]:
    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raw = path.read_text(encoding="utf-8", errors="replace")
    tokens = markdown_ast.parse_markdown(raw)
    _, roots = markdown_ast.split_sections(tokens)
    return [
        section
        for section in markdown_ast.flatten_sections(roots)
        if len(section.text) >= MIN_SECTION_CHARS
    ]


async def _get_or_create_tag(session: AsyncSession, name: str) -> Tag:
    # canonical 归一（保留显示大小写）：修复历史上"统一小写"导致 RAG/Agent 筛选零命中的问题
    from getoffer.ingest.tag_vocab import canonical_tag_name

    canonical = canonical_tag_name(name)
    existing = await session.scalar(select(Tag).where(Tag.name == canonical))
    if existing is not None:
        return existing
    # 大小写漂移的存量标签（如 "rag"）视为同一标签，直接复用其 id 并改名为 canonical
    drifted = await session.scalar(
        select(Tag).where(func.lower(Tag.name) == canonical.lower())
    )
    if drifted is not None:
        drifted.name = canonical
        await session.flush()
        return drifted
    tag = Tag(name=canonical)
    session.add(tag)
    await session.flush()
    return tag


async def _upsert_source_row(session: AsyncSession, spec: SourceSpec) -> Source:
    row = await session.scalar(select(Source).where(Source.slug == spec.slug))
    if row is None:
        row = Source(
            slug=spec.slug,
            name=spec.name,
            repo_url=spec.repo_url,
            license=spec.license,
            allowed_use=spec.allowed_use.value,
            notes=spec.notes,
        )
        session.add(row)
        await session.flush()
    return row


async def import_markdown_repo(
    slug: str,
    *,
    session: AsyncSession,
    gateway: LLMGateway,
    settings: Settings,
    indexer: MeiliIndexer | None = None,
    batch_size: int = 4,
    max_files: int | None = None,
) -> ImportReport:
    spec = get_source(slug)
    if spec.allowed_use is AllowedUse.REFERENCE_ONLY:
        raise LicenseViolation(
            f"{spec.slug} 的 license 为 {spec.license}，禁止入库；只能站外引用（spec §10）",
            details={"license": spec.license},
        )

    report = ImportReport(slug=slug)
    source_row = await _upsert_source_row(session, spec)
    repo_path = ensure_clone(spec, settings.repos_dir, git_proxy=settings.git_proxy)
    files = collect_markdown_files(repo_path, spec, max_files=None)
    indexed_documents: list[dict] = []

    # 增量导入：以 source_files 处理记录为准（无论是否抽出题目都算 done，保证收敛）
    processed = set(
        (
            await session.scalars(select(SourceFile.path).where(SourceFile.source_id == source_row.id))
        ).all()
    )
    pending = [path for path in files if path.relative_to(repo_path).as_posix() not in processed]
    report.files_remaining = len(pending)
    if max_files is not None:
        pending = pending[:max_files]

    for path in pending:
        report.files_seen += 1
        rel_path = path.relative_to(repo_path).as_posix()
        sections = sections_from_file(path)
        report.sections_seen += len(sections)
        file_inserted = 0
        if sections:
            items = await extract_from_sections(
                sections,
                gateway,
                source_name=spec.name,
                allow_answers=(spec.allowed_use is AllowedUse.ANSWERS),
                batch_size=batch_size,
            )
            report.extracted += len(items)
            seen_in_file: set[str] = set()
            for item in items:
                digest = content_hash(item.stem)
                if digest in seen_in_file:
                    report.duplicates += 1
                    continue
                seen_in_file.add(digest)
                exists = await session.scalar(select(Question).where(Question.content_hash == digest))
                if exists is not None:
                    report.duplicates += 1
                    continue
                if spec.allowed_use is AllowedUse.ANSWERS and item.answer:
                    provenance = "source"
                    answer: str | None = item.answer
                else:
                    provenance = "pending"
                    answer = None
                question = Question(
                    stem=item.stem,
                    kind=item.kind,
                    difficulty=item.difficulty,
                    answer=answer,
                    answer_provenance=provenance,
                    source_id=source_row.id,
                    # 统一 posix 风格：增量跳过逻辑按 as_posix() 匹配，Windows 反斜杠会导致永远匹配不上
                    source_ref=rel_path,
                    content_hash=digest,
                    track=item.track,
                )
                question_tags: list[Tag] = []
                for tag_name in item.tags:
                    tag = await _get_or_create_tag(session, tag_name)
                    if all(existing.id != tag.id for existing in question_tags):
                        question_tags.append(tag)
                question.tags = question_tags  # flush 前显式赋值，避免 async 懒加载（MissingGreenlet）
                # savepoint 内插入：并发/批内竞态导致的唯一键冲突按重复计数回退，不炸整批事务
                nested = await session.begin_nested()
                try:
                    session.add(question)
                    await session.flush()
                except IntegrityError:
                    await nested.rollback()
                    report.duplicates += 1
                    continue
                await nested.commit()
                indexed_documents.append(
                    {
                        "id": question.id,
                        "stem": question.stem,
                        "answer": question.answer or "",
                        "kind": question.kind,
                        "difficulty": question.difficulty,
                        "tags": [tag.name for tag in question_tags],
                        "companies": [],
                    }
                )
                report.inserted += 1
                file_inserted += 1
        # 处理记录：无论是否抽出题目都记 done，保证增量导入收敛（不重烧已处理文件）
        session.add(SourceFile(source_id=source_row.id, path=rel_path, questions_extracted=file_inserted))

    await session.commit()

    # DB 已提交后再写检索索引；索引失败显式上抛（重跑导入或 /api/ingest/reindex 可修复）
    if indexer is not None and indexed_documents:
        await indexer.ensure_index(QUESTIONS_INDEX)
        await indexer.upsert_documents(QUESTIONS_INDEX, indexed_documents)
    return report
