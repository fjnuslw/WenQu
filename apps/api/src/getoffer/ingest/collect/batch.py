"""审核公开候选并分批复用现有面经入库；单次最多 30 条，断点可续。

跨 URL 搬运去重只作用于本批新候选，不删除/改写任何既有记录。
抽取题干须在输入原文中出现；无法证实的题目明确记入审核日志，不补全。
"""

import argparse
import asyncio
import json
import unicodedata
from collections import Counter
from dataclasses import asdict
from datetime import date
from pathlib import Path

from sqlalchemy import select

from getoffer.config import Settings
from getoffer.db import make_engine, make_sessionmaker
from getoffer.errors import ComplianceViolation, StructuredOutputError, UpstreamError
from getoffer.ingest.collect import get_channel
from getoffer.ingest.collect.base import PostPreview
from getoffer.ingest.collect.catalog import read_json, url_key, write_json
from getoffer.ingest.collect.manual import get_manual_channel
from getoffer.ingest.collect.nowcoder_public import canonical_post_url
from getoffer.ingest.collect.polite import PoliteClient
from getoffer.ingest.collect.runner import ingest_post_previews
from getoffer.ingest.experience_extract import ExperienceDraft, extract_experience_batch
from getoffer.llm.gateway import LLMGateway
from getoffer.models import Experience, LLMCall


def normalized_text(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", text).lower() if c.isalnum())


def canonical_url(url: str | None) -> str:
    return canonical_post_url(url) or url or "" if url else ""


def unsegmented_compilation(text: str) -> bool:
    """明确编号为多份面经但未由渠道分段的文本，不能交给模型混成一场。"""
    headings = [
        line.strip().removeprefix("面经").strip()
        for line in text.splitlines()
        if line.strip().startswith("面经")
    ]
    return sum(heading.isdigit() for heading in headings) > 1


def generic_interview_label(text: str) -> bool:
    if text.startswith("【") and "】" in text:
        text = text.partition("】")[2]
    return normalized_text(text) in {
        "场景题",
        "手撕",
        "算法题",
        "反问",
        "反问环节",
        "项目拷打",
        "实习拷打",
        "简历拷打",
        "项目介绍",
        "介绍项目",
        "论文介绍",
        "介绍论文",
        "自我介绍",
        "项目深挖",
        "实习经历深挖",
        "简历项目",
        "交流环节",
    }


class ContentIndex:
    def __init__(self) -> None:
        self.entries: list[tuple[str, str, set[str]]] = []

    def add(self, key: str, text: str) -> None:
        normalized = normalized_text(text)
        self.entries.append((key, normalized, self.shingles(normalized)))

    @staticmethod
    def shingles(text: str) -> set[str]:
        return {text[i : i + 8] for i in range(max(0, len(text) - 7))}

    def duplicate_of(self, text: str) -> str | None:
        normalized = normalized_text(text)
        if len(normalized) < 100:
            return None
        shingles = self.shingles(normalized)
        for key, existing, existing_shingles in self.entries:
            if normalized in existing or (len(existing) >= 150 and existing in normalized):
                return key
            denominator = min(len(shingles), len(existing_shingles))
            # 高重叠片段通常是同帖预览/全文或换链接搬运，保守不重复计数。
            if denominator >= 140 and len(shingles & existing_shingles) / denominator >= 0.82:
                return key
        return None


def ground_draft(draft: ExperienceDraft, post: PostPreview) -> tuple[ExperienceDraft, list[str]]:
    evidence = normalized_text(post.as_text()[:6000])
    warnings = []
    items = []
    seen_questions = set()
    for item in draft.items if draft.is_interview_experience else []:
        quote = normalized_text(item.question_text)
        if generic_interview_label(item.question_text):
            warnings.append(f"只有泛化环节标签，没有具体题干，未入库：{item.question_text}")
            continue
        if item.question_text.rstrip().endswith(("...", "…")):
            warnings.append(f"题干在预览中截断，不能补全或按完整问题入库：{item.question_text}")
            continue
        if not quote or quote not in evidence:
            warnings.append(f"题干未逐字对应原文，未入库：{item.question_text}")
            continue
        if quote in seen_questions:
            warnings.append(f"同一面经重复题干，未重复入库：{item.question_text}")
            continue
        seen_questions.add(quote)
        followups = []
        for followup in item.followups:
            if normalized_text(followup) in evidence:
                followups.append(followup)
            else:
                warnings.append(f"追问未对应原文，未入库：{followup}")
        items.append(item.model_copy(update={"note": None, "followups": followups}))
    company = draft.company
    if company and normalized_text(company) not in evidence:
        warnings.append(f"公司名不在原文中，保留未知：{company}")
        company = None
    occurred_on = draft.occurred_on
    if occurred_on:
        try:
            date.fromisoformat(occurred_on)
        except ValueError as exc:
            raise StructuredOutputError("面经日期不是有效的日历日期", details={"date": occurred_on}) from exc
    rounds = draft.rounds
    if rounds and len(rounds) > 32:
        warnings.append(f"轮次超过数据库 32 字符限制，结构化值留空、原文保留：{rounds}")
        rounds = None
    return draft.model_copy(
        update={
            "company": company,
            "rounds": rounds,
            "is_interview_experience": bool(items),
            "items": items,
        }
    ), warnings


class _PreparedGateway:
    """将已校验的批量抽取结果交给未改动的单帖入库函数，不重复调用 LLM。"""

    def __init__(self, draft: ExperienceDraft) -> None:
        self.draft = draft

    async def complete_structured(self, messages, model, **kwargs):
        if model is not ExperienceDraft:
            raise TypeError("预抽取适配器仅支持 ExperienceDraft")
        return self.draft


async def import_candidates(
    root: Path,
    channel: str,
    max_posts: int,
    *,
    fetch: bool = False,
    batch_size: int = 5,
    manual_source: str | None = None,
    retry_failed: bool = False,
) -> dict:
    if not 1 <= max_posts <= 30 or not 1 <= batch_size <= 5:
        raise ValueError("单次审核须为 1–30 条，LLM 子批次须为 1–5 条")
    settings = Settings()
    spec = get_manual_channel(manual_source) if manual_source else get_channel(channel)
    if spec.slug != channel:
        raise ValueError("人工来源名称与 channel 不一致")
    if manual_source and fetch:
        raise ComplianceViolation("人工摘录审核不允许自动访问来源网站")
    ledger_path = root / f"audit-{channel}.json"
    ledger = read_json(ledger_path, {})
    if fetch:
        client = PoliteClient(proxy=settings.collect_proxy, min_interval=spec.min_interval)
        try:
            fetched = await spec.fetch_posts(client, max_posts)
        finally:
            await client.aclose()
        counts = Counter(post.url for post in fetched)
        source_candidates = {}
        for post in fetched:
            sectioned = counts[post.url] > 1
            key = f"{post.url}#excerpt-{url_key(post.content)[:16]}" if sectioned else post.url
            source_candidates[key] = {"channel": channel, "post": asdict(post), "sectioned": sectioned}
        write_json(root / f"candidates-{channel}.json", source_candidates)
    else:
        candidate_path = root / (
            "candidates.json" if channel == "nowcoder-public" else f"candidates-{channel}.json"
        )
        source_candidates = read_json(candidate_path, {})

    engine = make_engine(settings)
    sessions = make_sessionmaker(engine)

    async def usage_sink(usage: dict) -> None:
        async with sessions() as session:
            session.add(LLMCall(**usage))
            await session.commit()

    gateway = LLMGateway(settings.llm, usage_sink=usage_sink)
    summary = {
        "channel": channel,
        "considered": 0,
        "inserted": 0,
        "duplicates": 0,
        "rejected": 0,
        "failed": 0,
    }
    try:
        async with sessions() as session:
            rows = (await session.execute(select(Experience.id, Experience.url, Experience.raw_text))).all()
        known_urls = {canonical_url(row.url) for row in rows if row.url}
        index = ContentIndex()
        for row in rows:
            index.add(f"experience:{row.id}", row.raw_text or "")
        pending = []
        for url, candidate in source_candidates.items():
            if url in ledger and (ledger[url].get("status") != "failed" or not retry_failed):
                continue
            if summary["considered"] >= max_posts:
                break
            summary["considered"] += 1
            post_data = dict(candidate["post"])
            if post_data.get("occurred_on"):
                post_data["occurred_on"] = date.fromisoformat(post_data["occurred_on"])
            post = PostPreview(**post_data)
            if unsegmented_compilation(post.content):
                ledger[url] = {"status": "rejected", "reason": "未分段的多候选人面经汇总，不按一场入库"}
                summary["rejected"] += 1
                continue
            duplicate = (
                "same_source_url"
                if not candidate.get("sectioned") and canonical_url(post.url) in known_urls
                else index.duplicate_of(post.content)
            )
            if duplicate:
                ledger[url] = {"status": "duplicate", "duplicate_of": duplicate}
                summary["duplicates"] += 1
            else:
                pending.append((url, post))
                index.add(url, post.content)
        write_json(ledger_path, ledger)

        for offset in range(0, len(pending), batch_size):
            group = pending[offset : offset + batch_size]
            try:
                batch = await extract_experience_batch(
                    {str(i): post.as_text() for i, (_, post) in enumerate(group)},
                    gateway,
                    source_name=spec.name,
                )
            except (StructuredOutputError, UpstreamError) as exc:
                error = f"{exc} [{type(exc.__cause__).__name__}]" if exc.__cause__ else str(exc)
                details = getattr(exc, "details", None)
                for url, _ in group:
                    ledger[url] = {
                        "status": "failed",
                        "error": error,
                        "type": type(exc).__name__,
                        "details": details,
                    }
                summary["failed"] += len(group)
                write_json(ledger_path, ledger)
                print(
                    json.dumps(
                        {"batch_failed": error, "urls": [url for url, _ in group]}, ensure_ascii=False
                    ),
                    flush=True,
                )
                continue
            by_id = {entry.post_id: entry.draft for entry in batch.entries}
            for i, (url, post) in enumerate(group):
                try:
                    draft, warnings = ground_draft(by_id[str(i)], post)
                except StructuredOutputError as exc:
                    ledger[url] = {"status": "failed", "error": str(exc), "details": exc.details}
                    summary["failed"] += 1
                    write_json(ledger_path, ledger)
                    print(json.dumps({"url": url, "failed": str(exc)}, ensure_ascii=False), flush=True)
                    continue
                async with sessions() as session:
                    report = await ingest_post_previews(
                        spec,
                        [post],
                        session=session,
                        gateway=_PreparedGateway(draft),
                    )
                status = "inserted" if report.inserted else "duplicate" if report.duplicates else "rejected"
                ledger[url] = {
                    "status": status,
                    "report": asdict(report),
                    "warnings": warnings,
                    "draft": draft.model_dump(),
                    "source_text": post.as_text(),
                }
                summary["inserted"] += report.inserted
                summary["duplicates"] += report.duplicates
                summary["rejected"] += report.skipped_non_experience
                write_json(ledger_path, ledger)
                print(
                    json.dumps(
                        {
                            "url": url,
                            "status": status,
                            "questions": len(draft.items),
                            "warnings": len(warnings),
                            "summary": summary,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
    finally:
        await gateway.aclose()
        await engine.dispose()
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Settings().data_dir / "experience-catalog")
    parser.add_argument("--channel", default="nowcoder-public")
    parser.add_argument("--max-posts", type=int, choices=range(1, 31), default=30)
    parser.add_argument("--batch-size", type=int, choices=range(1, 6), default=5)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--manual-source", help="只审核已人工读取的本地候选；不得与 --fetch 合用")
    parser.add_argument(
        "--retry-failed", action="store_true", help="显式重试上次失败项；默认保留失败日志而不循环重试"
    )
    args = parser.parse_args()
    result = asyncio.run(
        import_candidates(
            args.root,
            args.channel,
            args.max_posts,
            fetch=args.fetch,
            batch_size=args.batch_size,
            manual_source=args.manual_source,
            retry_failed=args.retry_failed,
        )
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
